"""
Social "circle" leaderboard — aggregates each member's recent activity into a
ranked board that friends can see.

Visibility (decided 2026-06-25): friends see each other's RAW numbers — today's
calories + protein and this week's workouts — plus a current streak. This is a
deliberate product choice; raw intake isn't comparable across cut/bulk/maintain
goals, so it does NOT drive the ranking. The board is ORDERED by effort
(workouts this week, then streak, then days logged) — a clean "more is better"
axis — while DISPLAYING the raw stats next to each name.

Everything keys off the canonical user (callers pass resolve_user output and
friend rows, which are already canonical). Stats come straight from DailyLog so
a member's board number matches what they see on their own Today tab.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DailyLog, User
from db.queries import _user_today, get_friends

# A day "counts" toward streaks / logged-days if the user put real food or a
# workout against it. An empty auto-materialized DailyLog (created on app launch
# with zeros) must NOT count, or every user would show a fake streak.
def _is_logged(log: DailyLog | None) -> bool:
    if log is None:
        return False
    return bool((log.total_calories or 0) > 0 or log.workout_completed)


async def _member_stats(db: AsyncSession, user: User) -> dict:
    """Compute one member's board row from the last 7 days of DailyLogs."""
    today = _user_today(user.timezone or "UTC")
    week_start = today - timedelta(days=6)

    rows = (
        await db.execute(
            select(DailyLog).where(
                and_(
                    DailyLog.user_id == user.id,
                    DailyLog.date >= week_start - timedelta(days=53),  # streak look-back
                    DailyLog.date <= today,
                )
            )
        )
    ).scalars().all()
    by_date = {r.date: r for r in rows}

    today_log = by_date.get(today)
    calories_today = int(round(today_log.total_calories or 0)) if today_log else 0
    protein_today = int(round(today_log.total_protein or 0)) if today_log else 0

    # Workouts logged in the trailing 7 days (today inclusive).
    workouts_week = sum(
        1 for d, r in by_date.items() if d >= week_start and r.workout_completed
    )
    days_logged_week = sum(
        1 for d, r in by_date.items() if d >= week_start and _is_logged(r)
    )

    # Streak: consecutive logged days ending today, OR ending yesterday if today
    # isn't logged yet (so the streak doesn't visibly "drop" first thing in the
    # morning before the day's first log).
    anchor = today if _is_logged(by_date.get(today)) else today - timedelta(days=1)
    streak = 0
    cursor = anchor
    while _is_logged(by_date.get(cursor)):
        streak += 1
        cursor -= timedelta(days=1)

    score = workouts_week * 100 + streak * 10 + days_logged_week
    return {
        "user_id": user.id,
        "name": (user.name or "Athlete").split()[0],
        "calories_today": calories_today,
        "protein_today": protein_today,
        "workouts_week": workouts_week,
        "streak": streak,
        "days_logged_week": days_logged_week,
        "logged_today": _is_logged(today_log),
        "score": score,
    }


async def build_circle(db: AsyncSession, user: User) -> dict:
    """
    Assemble the ranked circle board for `user` (canonical), including the user.

    Returns {rows, friend_count, has_code}. `rows` is sorted best-first with a
    1-based `rank` and an `is_me` flag stamped on each. With no friends yet the
    board is just the user (rank 1) — the empty state the client renders with an
    invite CTA.
    """
    friends = await get_friends(db, user)
    members = [user] + friends
    rows = [await _member_stats(db, m) for m in members]

    rows.sort(key=lambda r: (r["score"], r["workouts_week"], r["streak"]), reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["is_me"] = r["user_id"] == user.id

    return {
        "rows": rows,
        "friend_count": len(friends),
        "has_code": bool(user.friend_code),
    }


def render_circle_text(circle: dict) -> str:
    """Render the board as a plain-text leaderboard for Telegram/iMessage."""
    rows: List[dict] = circle["rows"]
    if circle["friend_count"] == 0:
        return (
            "🏆 <b>Your Circle</b>\n\n"
            "You're flexing in an empty gym — no friends yet.\n\n"
            "Run /invite to get your friend code, share it, and add a buddy "
            "with /addfriend &lt;code&gt;. Then you'll see each other's calories, "
            "workouts, and streaks here."
        )

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 <b>Your Circle</b> — this week\n"]
    for r in rows:
        tag = medals.get(r["rank"], f"{r['rank']}.")
        name = "<b>You</b>" if r["is_me"] else r["name"]
        cals = f"{r['calories_today']:,} cal" if r["logged_today"] else "—"
        lines.append(
            f"{tag} {name}  ·  💪{r['workouts_week']}  ·  🔥{r['streak']}  ·  {cals} today"
        )
    lines.append("\n<i>Ranked by workouts + streak this week.</i>")
    return "\n".join(lines)
