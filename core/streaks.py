"""
Streaks — forgiving consistency chains over the daily log.

Three chains, one rule-set:

  logging   → a day counts if ANYTHING was logged (food or a workout).
              The flagship habit streak, shown as the flame in the top bar.
  full_day  → a day counts once ≥1000 kcal are logged (same qualifying rule
              as the Coach activation gate, so "a real logged day" means one
              thing everywhere in the product).
  training  → a day counts if a non-cardio session was completed. Free: the
              flag is already on the rows every caller passes in.

A chain is nothing but a predicate over a row plus the shared walk, so the
fourth and fifth cost a line each — see `CHAINS`.

FORGIVENESS (the core design decision): momentum.py exists because fragile
day-streaks backfire — one busy Tuesday nukes a 20-day chain and the user's
motivation with it. So these streaks absorb ONE missed day per rolling 7:
a single gap is bridged (the chain continues, the gap contributes nothing);
a second miss inside the same 7 days breaks it. Rest days are part of
training — the streak should model that, not punish it.

Today is always PENDING, never a miss: an empty today doesn't consume the
rest day or break the chain until the day is actually over.

Pure functions over (date → qualified) sets — all DB I/O stays in callers.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Iterable, Set

from core.activation import QUALIFYING_DAY_KCAL

# How far back we look. 90 days bounds the query and the walk; a `best` beyond
# this window ages out, which is fine for a motivational number.
WINDOW_DAYS = 90

# Streak lengths the clients celebrate. Server-side only as documentation —
# milestone detection is a client concern (it knows what it already showed).
#
# Extended past 100 (2026-07): the ladder used to end there, so the users least
# worth losing — the ones a year deep — had nothing ahead of them. 365 is the
# one worth building a moment around.
MILESTONES = (3, 7, 14, 30, 50, 100, 150, 200, 365)

FORGIVE_SPAN = 7   # rolling window (days) ...
FORGIVE_MAX = 1    # ... that absorbs at most this many missed days


def _walk(qualified: Set[date], anchor: date, today: date) -> int:
    """Length of the chain ending at `anchor`, walking backward with forgiveness."""
    streak = 0
    forgiven: list[date] = []
    cur = anchor
    while True:
        if cur in qualified:
            streak += 1
        elif cur == today:
            pass  # today is pending, not a miss
        else:
            recent = [f for f in forgiven if (f - cur).days < FORGIVE_SPAN]
            if len(recent) >= FORGIVE_MAX:
                break
            forgiven.append(cur)
        cur -= timedelta(days=1)
        if (anchor - cur).days > WINDOW_DAYS:
            break
    return streak


def _rest_day_banked(qualified: Set[date], today: date) -> bool:
    """Is the forgiveness still available, i.e. would ONE missed day survive?

    The engine has always absorbed a miss per rolling 7 — but silently, so
    users assume a single slip kills the chain and the mechanic buys no
    confidence. This exposes the state so the client can say it out loud.

    True when no day inside the trailing FORGIVE_SPAN has already been spent
    bridging a gap. Today is excluded: it's pending, never a miss.
    """
    spent = 0
    cur = today - timedelta(days=1)
    for _ in range(FORGIVE_SPAN - 1):
        if cur not in qualified:
            spent += 1
        cur -= timedelta(days=1)
    return spent < FORGIVE_MAX


def _chain(qualified: Set[date], today: date) -> dict:
    current = _walk(qualified, today, today)
    # Best within the window: the walk from each qualified day as anchor.
    # n ≤ WINDOW_DAYS keeps this trivial.
    best = max((_walk(qualified, d, today) for d in qualified), default=0)
    best = max(best, current)
    today_done = today in qualified
    return {
        "current": current,
        "best": best,
        "today_done": today_done,
        # Worth nudging about: an established chain the user hasn't fed today.
        "at_risk": (not today_done) and current >= 3,
        # The safety net, made legible. Only meaningful on a live chain —
        # there's nothing to protect at zero.
        "rest_day_banked": current > 0 and _rest_day_banked(qualified, today),
    }


def _qualifies_logging(row) -> bool:
    return (row.total_calories or 0) > 0 or bool(getattr(row, "workout_completed", False))


def _qualifies_full_day(row) -> bool:
    return (row.total_calories or 0) >= QUALIFYING_DAY_KCAL


def _qualifies_training(row) -> bool:
    """A real session. Cardio is deliberately excluded: `workout_completed`
    already means non-cardio (db.queries._is_cardio splits them on write), and
    a training streak that a walk satisfies isn't a training streak."""
    return bool(getattr(row, "workout_completed", False))


#: chain name → does this day count. Adding a chain is one entry; the walk,
#: the forgiveness and the `best` search are shared and know nothing about
#: what any of them mean.
CHAINS: dict[str, Callable[[object], bool]] = {
    "logging": _qualifies_logging,
    "full_day": _qualifies_full_day,
    "training": _qualifies_training,
}


def compute_streaks(daily_logs: Iterable, today: date, *,
                    chains: dict[str, Callable[[object], bool]] | None = None) -> dict:
    """The wire `streaks` block. `daily_logs` are DailyLog-shaped rows
    (date / total_calories / workout_completed); `today` is the USER-LOCAL
    logging day (_user_today) — never date.today(), which runs a day ahead
    for US-evening users (the Chaya incident class).

    One pass over the rows regardless of how many chains are asked for, so
    `training` rides along for free on data every caller already passes.
    """
    active = CHAINS if chains is None else chains
    qualified: dict[str, Set[date]] = {name: set() for name in active}

    for row in daily_logs:
        d = row.date
        if d > today:  # future-dated rows from old LLM date bugs — never count
            continue
        for name, qualifies in active.items():
            if qualifies(row):
                qualified[name].add(d)

    out = {name: _chain(days, today) for name, days in qualified.items()}
    # full_day carries its threshold so the client can name the rule it's under.
    if "full_day" in out:
        out["full_day"]["kcal"] = QUALIFYING_DAY_KCAL
    return out


def streaks_context_line(streaks: dict) -> str | None:
    """Compact context for Arnie: celebrate real chains, flag risk. Null when
    there's nothing worth a token."""
    log = streaks.get("logging") or {}
    cur, at_risk = log.get("current", 0), log.get("at_risk")
    if cur < 3 and not at_risk:
        return None
    # No "best" here — the context window may be shorter than the API's, and
    # Arnie must never state a personal best the app contradicts.
    bits = [f"logging streak {cur}d"]
    if at_risk:
        bits.append("AT RISK — nothing logged yet today; a natural nudge protects it")
    elif log.get("today_done") and cur in MILESTONES:
        bits.append(f"today hit the {cur}-day milestone — worth celebrating")
    return "[STREAK] " + "; ".join(bits)
