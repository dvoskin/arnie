"""Rotation position — the SCALABLE answer to "what day is it in my program?"

Derived, never stored: the last program day the user actually COMPLETED
(inferred from their logged exercises, the same containment matching the iOS
card uses) advances the rotation pointer; the next non-rest day in the
rotation is today's expected day. Overrides for the current day still win at
render time — this is the default underneath them.

One pure function, served to BOTH the program card (today_day in the API
payload) and the model's [PROGRAM] context — so chat and card cannot
disagree about what's next. (The back-day incident, 2026-07-20: chat said
"back day tomorrow" from history-reading; the card's fallback was
first-primary-day, with no rotation state anywhere.)
"""
from __future__ import annotations

from typing import Optional


def _norm(s: str) -> str:
    return (s or "").lower().strip()


def _day_matches(day: dict, logged_names: set[str]) -> int:
    """How many of a program day's exercises appear in a set of logged
    exercise names (containment either way — 'lat pulldown' matches
    'Lat Pulldown (wide grip)')."""
    hits = 0
    for ex in day.get("exercises") or []:
        n = _norm(ex.get("name") if isinstance(ex, dict) else str(ex))
        if not n:
            continue
        if any(n in ln or ln in n for ln in logged_names):
            hits += 1
    return hits


def infer_next_day(program: dict,
                   entries_by_day: list[tuple[str, set[str]]]) -> Optional[str]:
    """The rotation's NEXT expected day name, or None when underivable.

    program        — the unified rich shape: {rotation: [names], days: [{name,
                     exercises: [{name}]}]}.
    entries_by_day — the user's recent training history, NEWEST FIRST:
                     [(iso_date, {normalized exercise names logged that day})].
                     Rest days simply don't appear; they don't advance anything.

    Walks the history for the most recent day that clearly matches a program
    day (≥2 exercise overlaps, or ≥1 when the day has a single exercise), then
    returns the next entry in the rotation list that maps to a real training
    day (skipping literal rest slots). No match anywhere → the first day.
    """
    days = [d for d in (program.get("days") or []) if isinstance(d, dict)]
    if not days:
        return None
    day_names = [_norm(d.get("name", "")) for d in days]
    rotation = [r for r in (program.get("rotation") or []) if r] or \
               [d.get("name", "") for d in days]

    last_done: Optional[str] = None
    for _date, logged in entries_by_day:
        if not logged:
            continue
        scored = [(d.get("name", ""), _day_matches(d, logged)) for d in days]
        name, hits = max(scored, key=lambda t: t[1])
        needed = 1 if len(next((d for d in days if d.get("name") == name),
                               {}).get("exercises", []) or []) <= 1 else 2
        if hits >= needed:
            last_done = name
            break

    if last_done is None:
        return days[0].get("name")

    # Advance from the completed day's rotation slot to the next TRAINING day.
    try:
        idx = next(i for i, r in enumerate(rotation) if _norm(r) == _norm(last_done))
    except StopIteration:
        return days[0].get("name")
    n = len(rotation)
    for step in range(1, n + 1):
        cand = rotation[(idx + step) % n]
        cn = _norm(cand)
        if "rest" in cn and cn not in day_names:
            continue   # a literal rest slot in the rotation — skip past it
        if any(cn == dn for dn in day_names):
            return next(d.get("name") for d in days if _norm(d.get("name", "")) == cn)
    return days[0].get("name")


async def recent_entries_by_day(db, user_id: int, days: int = 14):
    """The user's recent training history for the rotation inference —
    [(iso_date, {normalized exercise names})], NEWEST FIRST. One indexed query."""
    from datetime import datetime, timedelta
    from sqlalchemy import select
    from db.models import DailyLog, ExerciseEntry

    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(DailyLog.date, ExerciseEntry.exercise_name)
        .join(ExerciseEntry, ExerciseEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id, ExerciseEntry.timestamp >= since)
    )).all()
    by_day: dict = {}
    for d, name in rows:
        n = _norm(name or "")
        if n:
            by_day.setdefault(str(d), set()).add(n)
    return sorted(by_day.items(), key=lambda t: t[0], reverse=True)
