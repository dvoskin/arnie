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

    DATA ONLY — no model-facing directives and no internal markers like
    [TRAINING PROGRAM]. This string can be echoed verbatim to a user (Danny
    2026-06-27 saw raw "YOUR REPLY: ..." / "[#1314]" leak), so it carries facts
    only; the "acknowledge briefly, never announce a skip" behavior lives in the
    SYSTEM PROMPT (core/prompts/arnie.py).

    Starts with 'Already on the board:' (NOT 'Skipped' or 'Error') so the
    deterministic_confirmation recovery-message path doesn't false-positive it
    as a tool failure — the prefix MUST stay stable. The entry id is carried as
    a bare '#id' (NOT the bracketed '[#id]' marker that leaked) so the model can
    reference the row without echoing the internal-looking token.
    """
    weight_part = ""
    if getattr(dup, "weight", None):
        weight_part = f" @ {dup.weight * 2.20462:.0f}lb"
    age_sec = max(0, int((now_utc - dup.timestamp).total_seconds()))
    age_part = f"{age_sec}s ago" if age_sec < 90 else f"{age_sec // 60} min ago"
    return (
        f"Already on the board: {dup.exercise_name} "
        f"({dup.sets}×{dup.reps}{weight_part}), logged {age_part} #{dup.id}."
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
        f"Updated the running set on #{entry.id}: {entry.exercise_name} "
        f"now {entry.sets}x{entry.reps}{weight_part} — one entry grew, no new row."
    )


def _weights_tokens(weights) -> list:
    """Split a per-set weights CSV into float tokens. '93,102.1' -> [93.0, 102.1].
    None/'' or any unparseable token -> []."""
    if not weights:
        return []
    out = []
    for t in str(weights).split(","):
        t = t.strip()
        if not t:
            continue
        try:
            out.append(float(t))
        except ValueError:
            return []
    return out


def _fmt_kg(w: float) -> str:
    """Compact kg for the weights CSV — 2dp with trailing zeros trimmed."""
    s = f"{w:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def find_incremental_append(
    *,
    exercise_name: Optional[str],
    sets: Optional[int],
    reps: Optional[str],
    weight_kg: Optional[float],
    existing_entries: Iterable,
    now_utc: datetime,
    window_sec: int = 5400,
    refire_guard_sec: int = 120,
    allow_identical: bool = False,
):
    """INCREMENTAL set report → grow the movement's session row, don't insert a
    parallel one-set row.

    The live failure mode behind Danny's fragmentation (83% of strength entries
    one-row-per-set): reporting sets one message at a time ("205x15 first set" →
    "fell to 10" → "another set of 15") writes N overlapping rows because the
    rollup upsert only catches a FULL-list re-state. This is its strict
    complement: a pure single-set report of a movement already in this session
    APPENDS to that row (reps CSV +1 token, weights CSV when loads differ —
    pyramids/drop sets are one movement, that's what the column is for).

    Phantom protection: a single set whose (weight, reps) pair was ALREADY
    performed this session is refire-shaped (the model re-emitting an earlier
    set on a topic pivot / double-fire). Without `allow_identical` (the turn
    gate — "another set", "one more"):
      • movement touched within `refire_guard_sec` → ("refire", row): report
        already-on-the-board (kills the double-fire double-append);
      • older → None: fall through to the legacy dedup/superseded/insert paths.

    Returns one of:
      ("append", entry, new_sets, new_reps, new_weights_csv_or_None)
      ("refire", entry)
      None — nothing appendable; caller runs the legacy paths unchanged.
    """
    if not exercise_name:
        return None
    in_tokens = _reps_tokens(reps)
    eff_sets = int(sets) if sets is not None else (len(in_tokens) or None)
    if eff_sets != 1 or len(in_tokens) != 1:
        return None                       # only pure single-set reports append
    if weight_kg is None or weight_kg <= 0:
        return None                       # unloaded/bodyweight: legacy paths
    key_name = normalize_exercise_name(exercise_name)
    cutoff = now_utc - timedelta(seconds=window_sec)

    session_rows = []
    for e in existing_entries:
        ts = getattr(e, "timestamp", None)
        if ts is None or ts < cutoff:
            continue
        if getattr(e, "cardio_type", None):
            continue
        if normalize_exercise_name(getattr(e, "exercise_name", "")) != key_name:
            continue
        session_rows.append((ts, e))
    if not session_rows:
        return None
    session_rows.sort(key=lambda p: p[0], reverse=True)
    newest_ts, newest = session_rows[0]
    in_rep = in_tokens[0]

    if not allow_identical:
        for _ts, e in session_rows:
            e_tokens = _reps_tokens(getattr(e, "reps", ""))
            e_wtokens = _weights_tokens(getattr(e, "weights", None))
            e_weight = getattr(e, "weight", None)
            for i, tok in enumerate(e_tokens):
                w_i = e_wtokens[i] if i < len(e_wtokens) else e_weight
                if tok == in_rep and _close(w_i, weight_kg):
                    if (now_utc - newest_ts).total_seconds() <= refire_guard_sec:
                        # Cite the row that actually holds the re-fired pair —
                        # the truthful "already on the board" reference.
                        return ("refire", e)
                    return None           # ambiguous beyond the guard → legacy

    e_tokens = _reps_tokens(getattr(newest, "reps", ""))
    if not e_tokens:
        return None                       # opaque row — can't align a CSV
    e_sets = getattr(newest, "sets", None)
    try:
        e_sets = int(e_sets) if e_sets is not None else len(e_tokens)
    except (TypeError, ValueError):
        e_sets = len(e_tokens)
    if e_sets != len(e_tokens):
        # Constant-rep block stored compact (sets=3, reps='12') — expand so the
        # appended CSV stays aligned per set.
        if len(e_tokens) == 1 and e_sets and e_sets > 1:
            e_tokens = e_tokens * e_sets
        else:
            return None
    e_weight = getattr(newest, "weight", None)
    e_wtokens = _weights_tokens(getattr(newest, "weights", None))

    new_sets = len(e_tokens) + 1
    new_reps = ",".join(e_tokens + [in_rep])
    new_weights = None
    if e_wtokens:
        if len(e_wtokens) < len(e_tokens):
            base = e_weight if e_weight is not None else e_wtokens[-1]
            e_wtokens = e_wtokens + [base] * (len(e_tokens) - len(e_wtokens))
        new_weights = ",".join(_fmt_kg(w) for w in (e_wtokens + [weight_kg]))
    elif e_weight is not None and not _close(e_weight, weight_kg):
        new_weights = ",".join(
            _fmt_kg(w) for w in ([e_weight] * len(e_tokens) + [weight_kg]))
    # else: same load throughout → scalar weight stands, no CSV needed.
    return ("append", newest, new_sets, new_reps, new_weights)


def format_append_result(entry, now_utc: datetime) -> str:
    """Tool-result string when an incremental set grew the session row.

    Non-error prefix (same contract as format_rollup_result) + the row's full
    running state so the model confirms from DB truth, not its own memory."""
    wtokens = _weights_tokens(getattr(entry, "weights", None))
    if wtokens:
        load = "/".join(f"{w * 2.20462:.0f}" for w in wtokens) + "lb"
    elif getattr(entry, "weight", None):
        load = f"{entry.weight * 2.20462:.0f}lb"
    else:
        load = ""
    load_part = f" @ {load}" if load else ""
    return (
        f"Appended the set to #{entry.id}: {entry.exercise_name} "
        f"now {entry.sets}x{entry.reps}{load_part} — one entry grew by a set, no "
        f"new row. Confirm JUST the set you logged (this set's weight × reps), "
        f"not the whole list."
    )
