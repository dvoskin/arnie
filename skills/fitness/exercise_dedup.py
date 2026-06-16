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
