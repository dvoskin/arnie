"""
SESSION STATE — structured awareness of where the user is in TODAY's workout.

Phase 3 of the live-coaching reinforcements. Solves the "Arnie says 'what's
next?' instead of suggesting an exercise" failure: with [SESSION STATE]
injected into context, the model can give a concrete answer to mid-session
open questions ("any suggestions?") instead of bouncing the question back.

Distinct from [COACHING STATE] (which lives in core/coaching_state.py and
represents day-level readiness from wearables). SESSION STATE is workout-
local: what's been hit this session vs. what's still planned for this day
of the user's program rotation.

Data sources (all already in context):
  - today_log.exercise_entries  : what's been logged this session
  - WorkoutProgram.program_json : the user's split + day-level exercise lists

Matching program-day exercises to logged entries uses the Phase 2 catalog —
both sides canonicalize first, then exact OR program-as-substring matches.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional


def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").lower().split())


def matches_program_exercise(program_name: str, entry_name: str) -> bool:
    """Does a logged entry fulfill a program day's planned exercise?

    Both names canonicalize first. Accept exact match OR program name as
    a substring of entry name — so a program slot "Cable Curl" gets
    credited when the user logged the more specific "Straight Bar Cable
    Curl". Reverse direction is NOT accepted (a program "Straight Bar
    Cable Curl" does not get credited by a generic "Cable Curl" entry)
    because the user picking a less-specific variant could mean a
    different movement.
    """
    from skills.fitness.exercise_catalog import canonicalize

    if not program_name or not entry_name:
        return False
    p_canon, _ = canonicalize(program_name)
    e_canon, _ = canonicalize(entry_name)
    if not p_canon or not e_canon:
        return False
    p = _norm(p_canon)
    e = _norm(e_canon)
    if p == e:
        return True
    # Program slot is a substring of entry — user did a more specific variant
    if p and p in e:
        return True
    return False


def _format_entry_brief(e) -> str:
    """One-liner for a logged entry — sets/reps/weight if strength, duration
    if cardio. Used inside the [SESSION STATE] block."""
    weight = getattr(e, "weight", None)
    sets = getattr(e, "sets", None)
    reps = getattr(e, "reps", None) or ""
    dur = getattr(e, "duration_minutes", None)
    if weight and reps:
        # Show weight in lb (user-facing units) without forcing prefs lookup
        wlb = weight * 2.20462
        return f"{wlb:.0f}lb × {reps}"
    if reps:
        return f"× {reps}"
    if dur:
        return f"{dur:.0f}min"
    return ""


def _catalog_meta_for(entry_name: str) -> Optional[dict]:
    """Look up Phase 2 catalog metadata for an entry's exercise_name.
    Returns None when the name isn't in the catalog (off-catalog movements
    still render, they just lose the muscle/rest annotations).

    Returns the canonicalized catalog entry — so even an old raw name
    like 'Crunches (Cable/Machine)' resolves to the Cable Crunch entry.
    """
    from skills.fitness.exercise_catalog import canonicalize
    _, entry = canonicalize(entry_name or "")
    return entry


def _decorate_movement_with_meta(entry_name: str) -> str:
    """Format 'Cable Pushdown (triceps · cable)' when catalog has metadata,
    or just 'Cable Pushdown' when it doesn't. Helps the model see muscle
    coverage at a glance for movement-order coaching."""
    meta = _catalog_meta_for(entry_name)
    if meta:
        return f"{entry_name} ({meta.get('primary', '?')} · {meta.get('equipment', '?')})"
    return entry_name


def _muscle_coverage(entries: list) -> dict[str, int]:
    """Tally sets per primary muscle group based on catalog metadata.
    Falls back to a single 'other' bucket for off-catalog movements."""
    counts: dict[str, int] = {}
    for e in entries:
        meta = _catalog_meta_for(getattr(e, "exercise_name", ""))
        muscle = meta.get("primary", "other") if meta else "other"
        sets_count = getattr(e, "sets", None) or 1
        counts[muscle] = counts.get(muscle, 0) + int(sets_count)
    return counts


def _last_set_info(entries: list, now_dt: datetime) -> tuple[Optional[int], Optional[dict], Optional[str]]:
    """Find the most recent entry and return (seconds_since, catalog_meta,
    exercise_name). Used to surface rest-window timing to the model."""
    if not entries:
        return None, None, None
    latest = max(entries, key=lambda e: getattr(e, "timestamp", datetime.min))
    ts = getattr(latest, "timestamp", None)
    if ts is None:
        return None, None, None
    sec_since = max(0, int((now_dt - ts).total_seconds()))
    name = getattr(latest, "exercise_name", "")
    meta = _catalog_meta_for(name)
    return sec_since, meta, name


def pick_program_day(program_json: Optional[dict], entries: Iterable) -> Optional[str]:
    """Auto-discover which day of the user's rotation TODAY's exercises map
    to, based on overlap between logged entries and each day's planned slots.

    Returns the name of the best-matching day, or None when there's no
    meaningful overlap (e.g. user is doing free-form work outside the
    program, or has no logged entries yet).

    Used by build_session_state when the caller doesn't already know the
    day — saves us from having to add a program_day_name field to DailyLog
    or ask the user "which day is this?" mid-session.
    """
    if not program_json:
        return None
    entry_names = [getattr(e, "exercise_name", None) for e in entries]
    entry_names = [n for n in entry_names if n]
    if not entry_names:
        return None
    best_day = None
    best_count = 0
    for d in program_json.get("days", []) or []:
        day_name = d.get("name")
        if not day_name:
            continue
        count = 0
        for ex in (d.get("exercises") or []):
            slot_name = ex.get("name") or ""
            if any(matches_program_exercise(slot_name, en) for en in entry_names):
                count += 1
        if count > best_count:
            best_count = count
            best_day = day_name
    return best_day if best_count > 0 else None


def build_session_state(
    today_log,
    program_json: Optional[dict],
    now_dt: datetime,
    todays_program_day_name: Optional[str] = None,
) -> str:
    """Render the [SESSION STATE] block for the system prompt.

    Returns "" when there's nothing meaningful to show:
      - no today_log or no exercise_entries → not in session yet
      - no program_json → no structured plan to compare against. Still
        return a minimal "in-session" block so the model knows time
        elapsed and what's been done — that beats silence.

    todays_program_day_name: pass the rotation day label if the caller
      knows which day of the user's split this is (e.g. "Day 4 — Arms").
      When None, the block omits the day label gracefully.

    The block is intentionally short. Long blocks dilute the prompt and
    the model tends to under-weight any single section in a verbose
    context window.
    """
    entries: list = list(getattr(today_log, "exercise_entries", None) or [])
    if not entries:
        return ""

    # Auto-pick the program day when caller didn't supply one — we don't
    # store which rotation day the user picked, so derive it from the
    # exercises that have been logged.
    if todays_program_day_name is None and program_json:
        # A user-declared day ("today is leg day") beats overlap inference.
        _ov = program_json.get("today_override") or {}
        try:
            # Same pre-dawn grace as the stamp side (see tool_executor):
            # before 4am local, "today" is still the previous day.
            _d = now_dt.date()
            if getattr(now_dt, "hour", 12) < 4:
                from datetime import timedelta as _td
                _d = _d - _td(days=1)
            _today_iso = _d.isoformat()
        except Exception:
            _today_iso = None
        if _ov.get("day") and _ov.get("date") == _today_iso:
            todays_program_day_name = (
                None if _ov["day"] == "__rest__" else _ov.get("day"))
    if todays_program_day_name is None:
        todays_program_day_name = pick_program_day(program_json, entries)

    # Time-in-session: earliest entry timestamp to now.
    timestamps = [getattr(e, "timestamp", None) for e in entries]
    timestamps = [t for t in timestamps if t is not None]
    if timestamps:
        first_ts = min(timestamps)
        elapsed_min = max(0, int((now_dt - first_ts).total_seconds() // 60))
    else:
        elapsed_min = 0

    total_sets = sum((getattr(e, "sets", None) or 1) for e in entries)
    distinct_movements = len({getattr(e, "exercise_name", "") for e in entries})

    lines = ["[SESSION STATE]"]
    if todays_program_day_name:
        lines.append(
            f"Today: {todays_program_day_name} — {elapsed_min} min in · "
            f"{total_sets} sets across {distinct_movements} movements"
        )
    else:
        lines.append(
            f"In session: {elapsed_min} min · "
            f"{total_sets} sets across {distinct_movements} movements"
        )

    # ── On-the-board reconciliation line (logging-accuracy guard) ──────────
    # Explicit per-movement SET COUNT already logged today, so the model can
    # diff a newly reported set/roll-up against what's saved BEFORE calling
    # log_exercise — instead of logging a message behind (re-logging a closed
    # movement, or dropping a set). Compact + scannable; the prompt's
    # RECONCILE BEFORE LOGGING rule keys off this exact line.
    _board_counts: dict[str, int] = {}
    _board_order: list[str] = []
    for e in entries:
        nm = getattr(e, "exercise_name", None) or "exercise"
        if nm not in _board_counts:
            _board_order.append(nm)
        _board_counts[nm] = _board_counts.get(nm, 0) + (getattr(e, "sets", None) or 1)
    if _board_order:
        board = ", ".join(f"{nm} {_board_counts[nm]}" for nm in _board_order)
        lines.append(f"On the board (reconcile before adding — log only NEW sets): {board}")

    # Last-set timing + rest window from catalog. This is the single most
    # actionable piece for live coaching — tells the model whether the user
    # is mid-rest, ready to push, or stalling.
    sec_since, last_meta, last_name = _last_set_info(entries, now_dt)
    if sec_since is not None and last_name:
        rest_part = ""
        if last_meta:
            r_lo, r_hi = last_meta.get("rest_seconds", (0, 0))
            if r_lo or r_hi:
                rest_part = f" · typical rest for {last_name} is {r_lo}-{r_hi}s"
        # Human-readable elapsed
        if sec_since < 60:
            since_part = f"{sec_since}s ago"
        else:
            since_part = f"{sec_since // 60} min ago"
        lines.append(f"Last set: {since_part}{rest_part}")

    # Group entries by exercise name so each movement shows a single roll-up
    # (sets are recorded as separate rows in the DB — Phase 1 dedup made
    # this safe to summarize).
    grouped: dict[str, list] = {}
    order: list[str] = []  # preserve first-seen order for stable rendering
    for e in entries:
        name = getattr(e, "exercise_name", None) or "exercise"
        if name not in grouped:
            order.append(name)
            grouped[name] = []
        grouped[name].append(e)

    # Match grouped entries to program day exercises (if program supplied).
    program_exercises: list[dict] = []
    if program_json and todays_program_day_name:
        for d in program_json.get("days", []):
            if _norm(d.get("name")) == _norm(todays_program_day_name):
                program_exercises = list(d.get("exercises") or [])
                break

    # If program supplied, render done/not-done against it.
    if program_exercises:
        done_lines = []
        notdone_lines = []
        matched_entry_names: set[str] = set()
        for ex in program_exercises:
            ex_name = ex.get("name") or ""
            category = ex.get("category") or ""
            # Find any logged entry that matches this program slot
            matched = []
            for entry_name in order:
                if matches_program_exercise(ex_name, entry_name):
                    matched.append((entry_name, grouped[entry_name]))
                    matched_entry_names.add(entry_name)
            if matched:
                # Roll up all matched entries for this slot
                roll = " / ".join(
                    f"{_decorate_movement_with_meta(en)} — " + ", ".join(
                        _format_entry_brief(e) for e in es if _format_entry_brief(e)
                    )
                    for en, es in matched
                )
                done_lines.append(f"  ✓ {ex_name} [{category}] · {roll}")
            else:
                notdone_lines.append(f"  ▢ {ex_name} [{category}]")

        if done_lines:
            lines.append("Done on program:")
            lines.extend(done_lines)
        if notdone_lines:
            lines.append("Still on program:")
            lines.extend(notdone_lines)

        # Off-program entries (user did something not in today's program slots)
        off_program = [n for n in order if n not in matched_entry_names]
        if off_program:
            off_lines = []
            for en in off_program:
                roll = ", ".join(
                    _format_entry_brief(e) for e in grouped[en]
                    if _format_entry_brief(e)
                )
                off_lines.append(
                    f"  • {_decorate_movement_with_meta(en)}"
                    + (f" — {roll}" if roll else "")
                )
            lines.append("Off-program done:")
            lines.extend(off_lines)

        # Suggested next: first not-done exercise from program, prioritized
        # by category (main → accessory → core).
        def _priority(ex):
            cat = (ex.get("category") or "").lower()
            return {"main": 0, "accessory": 1, "core": 2}.get(cat, 3)
        notdone_sorted = sorted(
            [ex for ex in program_exercises
             if not any(matches_program_exercise(ex.get("name", ""), en)
                        for en in order)],
            key=_priority,
        )
        if notdone_sorted:
            nxt = notdone_sorted[0]
            lines.append(
                f"Suggested next: {nxt.get('name')} "
                f"({nxt.get('category', 'accessory')}) — "
                f"first on-program slot you haven't hit."
            )
        else:
            lines.append(
                "Suggested next: wrap or pick an accessory — every on-program "
                "slot is covered."
            )
    else:
        # No program (or no day): summarize what's been done with catalog
        # decorations so the model still has primary-muscle + equipment data
        # to coach against. This is the FREEFORM path — most useful when
        # the user hasn't set up a program yet or is doing ad-hoc work.
        lines.append("Done this session (in order):")
        for en in order:
            roll = ", ".join(
                _format_entry_brief(e) for e in grouped[en]
                if _format_entry_brief(e)
            )
            lines.append(
                f"  • {_decorate_movement_with_meta(en)}"
                + (f" — {roll}" if roll else "")
            )
        lines.append(
            "Suggested next: use EXERCISE ORDER rules to pick — "
            "antagonist pair, complete the muscle group, or wrap if "
            "session is long enough."
        )

    # Muscle coverage rollup — always render. Gives the model an at-a-glance
    # picture of what's been worked, useful for both program-driven and
    # freeform coaching.
    coverage = _muscle_coverage(entries)
    if coverage:
        # Sort by set count desc, then name for stable rendering
        items = sorted(coverage.items(), key=lambda kv: (-kv[1], kv[0]))
        roll = ", ".join(f"{m} ({n})" for m, n in items)
        lines.append(f"Muscle coverage so far: {roll}")

    return "\n".join(lines)
