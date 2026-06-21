"""
Server-side guard against the re-log-on-context-shift bug.

The failure mode: the model occasionally re-fires log_exercise for already-logged
sets when the user pivots to a new exercise ("now doing pushdowns") or asks an
open mid-session question ("any suggestions?"). Catching this in the prompt is
brittle — even with explicit rules, the model occasionally drifts. A
deterministic guard at the executor layer makes the dup structurally impossible
regardless of what the prompt says.

The dedup is intentionally narrow: it only blocks an EXACT-PAYLOAD match within
a tight time window. A real second set at the same weight, far enough apart, is
allowed through unchanged. This file is a pure function — no DB access — so it's
trivially unit-testable. The caller passes the already-loaded exercise_entries
from today's daily_log (eagerly loaded via selectinload in get_today_log).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional


def normalize_exercise_name(name: Optional[str]) -> str:
    """Lowercase, strip, collapse whitespace. Used as the dedup key so 'Cable
    Pushdown' and 'cable  pushdown' match. Aliasing across distinct canonical
    names (e.g. 'Crunches (Cable/Machine)' → 'Cable Crunch') is Phase 2's job —
    this helper intentionally only normalizes whitespace + case."""
    if not name:
        return ""
    return " ".join(name.lower().split())


def _close(a: Optional[float], b: Optional[float], tol_kg: float = 0.5) -> bool:
    """Both None → match. Either-None → no match. Otherwise within tol_kg.

    tol_kg=0.5 absorbs rounding noise on lb↔kg conversions (a 1 lb difference
    is 0.45 kg). Tighter would false-negative on '135.5 lb' vs '135 lb' echoes.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol_kg


def is_duplicate_of_recent(
    *,
    exercise_name: Optional[str],
    sets: Optional[int],
    reps: Optional[str],
    weight_kg: Optional[float],
    existing_entries: Iterable,
    now_utc: datetime,
    window_sec: int = 120,
    superseded_window_sec: Optional[int] = None,
):
    """
    Return the most-recent matching existing entry that should block a write,
    or None.

    Match key: normalized exercise_name + sets + reps (string-compared) + close
    weight (±0.5 kg). All four must agree. A match blocks the write in one of
    two ways:

    1. Tight re-fire — the match is within ``window_sec`` (default 120s). Catches
       the "Logged 4 exercises" burst (several log_exercise calls in one turn,
       plus a re-log a few seconds/minutes later).

    2. Superseded backward re-log — only when ``superseded_window_sec`` is set.
       An exact match OLDER than ``window_sec`` still blocks IF a LATER entry of
       the SAME exercise at a DIFFERENT load/reps already exists: the session
       has moved this movement on, so re-emitting an earlier identical set is a
       phantom (Danny 2026-06-15 back session — 170×10 re-fired after 175×7 was
       logged; a straight-arm set re-emitted 37 min later during a food turn).
       Deliberately conservative so legit patterns keep writing:
         • straight sets — the later same-exercise set is IDENTICAL, not
           different, so it does not supersede;
         • supersets/circuits — the set that intervened is a DIFFERENT movement,
           so the matched set is still its exercise's frontier;
         • a genuine next single at the same load — nothing logged after it.

    The caller passes today's daily_log.exercise_entries iterable. Entries are
    sorted in-function by timestamp DESC and scanning stops at the widest window
    boundary, so this is O(entries-in-window).
    """
    if not exercise_name:
        return None
    key_name = normalize_exercise_name(exercise_name)
    key_reps = str(reps or "").strip()
    key_sets = int(sets) if sets is not None else None

    candidates = []
    for e in existing_entries:
        ts = getattr(e, "timestamp", None)
        if ts is None:
            continue
        candidates.append((ts, e))
    # Most recent first so the returned dup is the nearest neighbor.
    candidates.sort(key=lambda pair: pair[0], reverse=True)

    # Same-exercise entries, used for the "superseded" check below.
    same_exercise = [
        (ts, e) for ts, e in candidates
        if normalize_exercise_name(getattr(e, "exercise_name", "")) == key_name
    ]

    tight_cutoff = now_utc - timedelta(seconds=window_sec)
    outer_cutoff = (
        now_utc - timedelta(seconds=superseded_window_sec)
        if superseded_window_sec is not None else tight_cutoff
    )

    for ts, e in candidates:
        if ts < outer_cutoff:
            break  # older than the widest window we consider
        if normalize_exercise_name(getattr(e, "exercise_name", "")) != key_name:
            continue
        e_sets = getattr(e, "sets", None)
        e_sets = int(e_sets) if e_sets is not None else None
        if e_sets != key_sets:
            continue
        e_reps = str(getattr(e, "reps", "") or "").strip()
        if e_reps != key_reps:
            continue
        if not _close(getattr(e, "weight", None), weight_kg):
            continue
        # Exact payload match.
        if ts >= tight_cutoff:
            return e  # rapid re-fire within the tight window
        if superseded_window_sec is None:
            continue
        # Older than the tight window: a phantom only if a LATER same-exercise
        # set at a DIFFERENT payload exists (the movement progressed past this
        # set). Identical later sets / different movements do not supersede.
        for ts2, e2 in same_exercise:
            if ts2 <= ts:
                continue
            e2_reps = str(getattr(e2, "reps", "") or "").strip()
            if e2_reps != key_reps or not _close(getattr(e2, "weight", None), weight_kg):
                return e
    return None


def format_dedup_result(dup, now_utc: datetime) -> str:
    """Build the tool-result string the executor returns when a dup is caught.

    Starts with 'Already on the board:' (NOT 'Skipped' or 'Error') so the
    deterministic_confirmation recovery-message path doesn't false-positive
    it as a tool failure. The body tells the model what was found and what
    NOT to do (no log line, no "I skipped it" disclosure).
    """
    weight_part = ""
    if getattr(dup, "weight", None):
        weight_part = f" @ {dup.weight * 2.20462:.0f}lb"
    age_sec = max(0, int((now_utc - dup.timestamp).total_seconds()))
    return (
        f"Already on the board: {dup.exercise_name} "
        f"({dup.sets}×{dup.reps}{weight_part}). "
        f"Logged as [#{dup.id}] {age_sec}s ago. "
        f"YOUR REPLY: do NOT emit a fresh log line for this set — it's already saved. "
        f"Acknowledge briefly and move to the next cue (e.g. 'next set?' or the next "
        f"exercise from [TRAINING PROGRAM]). Never tell the user a log was skipped — "
        f"just continue coaching naturally."
    )


def _reps_tokens(reps) -> list:
    """Split a reps CSV into normalized tokens. '12, 12 ,10' -> ['12','12','10'].
    None/'' -> []."""
    if not reps:
        return []
    return [t.strip() for t in str(reps).split(",") if t.strip()]


def find_rollup_supersede(
    *,
    exercise_name: Optional[str],
    sets: Optional[int],
    reps: Optional[str],
    weight_kg: Optional[float],
    existing_entries: Iterable,
    now_utc: datetime,
    window_sec: int = 3600,
):
    """Detect a CUMULATIVE ROLL-UP and return the existing session entry the
    caller should UPDATE in place (instead of inserting a new overlapping row).

    The live failure mode (Danny 2026-06-21 Lat Pulldown): the model re-fires
    log_exercise with the full running set list on every set report, so one
    exercise becomes several overlapping rows —
        set 1 -> sets=1 reps='12'
        set 2 -> sets=2 reps='12,12'      (re-states set 1)
        set 3 -> sets=3 reps='12,12,10'   (re-states sets 1-2)
    = 6 sets stored for 3 performed. is_duplicate_of_recent can't catch it (each
    payload is genuinely different), so dedup-by-equality is the wrong tool; the
    right one is upsert-by-(session, exercise) — the same idea add_body_metric
    already uses to fold repeat weigh-ins into one row.

    Returns the entry to update (the most-complete prior partial — the longest
    matching prefix), or None. Conservative: only fires when the incoming log
    SUBSUMES an existing same-exercise + same-weight entry within window_sec, so
    straight sets at different loads/reps keep writing as separate rows:
      • Case A (per-set CSV): existing reps is a strict prefix of incoming reps
        (existing '12,12' -> incoming '12,12,10').
      • Case B (constant reps): same single rep value, incoming has strictly more
        sets (existing 2x'12' -> incoming 3x'12').
    """
    if not exercise_name:
        return None
    key_name = normalize_exercise_name(exercise_name)
    in_tokens = _reps_tokens(reps)
    in_sets = int(sets) if sets is not None else None
    cutoff = now_utc - timedelta(seconds=window_sec)

    best = None  # (completeness, ts, entry) — prefer longest prefix, then newest
    for e in existing_entries:
        ts = getattr(e, "timestamp", None)
        if ts is None or ts < cutoff:
            continue
        if normalize_exercise_name(getattr(e, "exercise_name", "")) != key_name:
            continue
        if not _close(getattr(e, "weight", None), weight_kg):
            continue
        e_tokens = _reps_tokens(getattr(e, "reps", ""))
        e_sets = getattr(e, "sets", None)
        e_sets = int(e_sets) if e_sets is not None else None

        subsumed = False
        completeness = 0
        # Case A — per-set CSV roll-up: existing reps a strict prefix of incoming.
        if (len(in_tokens) >= 2 and 0 < len(e_tokens) < len(in_tokens)
                and in_tokens[:len(e_tokens)] == e_tokens):
            subsumed, completeness = True, len(e_tokens)
        # Case B — constant single-rep roll-up: same rep value, more sets.
        elif (len(in_tokens) <= 1 and len(e_tokens) <= 1 and e_tokens
              and e_tokens == in_tokens and in_sets is not None
              and e_sets is not None and in_sets > e_sets):
            subsumed, completeness = True, e_sets

        if subsumed:
            cand = (completeness, ts, e)
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand
    return best[2] if best else None


def format_rollup_result(entry, now_utc: datetime) -> str:
    """Tool-result string when a roll-up updated an existing row in place.

    Like format_dedup_result, starts with a non-error prefix so the
    deterministic_confirmation path doesn't read it as a failure, and tells the
    model it was an UPDATE (one row), not a new log line."""
    weight_part = ""
    if getattr(entry, "weight", None):
        weight_part = f" @ {entry.weight * 2.20462:.0f}lb"
    return (
        f"Updated the running set on [#{entry.id}]: {entry.exercise_name} "
        f"now {entry.sets}x{entry.reps}{weight_part} — one entry grew, no new row. "
        f"YOUR REPLY: confirm the latest set naturally and give the running count "
        f"(e.g. '3 sets in'); do NOT imply a separate or duplicate log was created."
    )
