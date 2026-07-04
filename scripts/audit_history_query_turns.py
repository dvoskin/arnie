"""READ-ONLY audit: find turns where Danny (a) queried history AND logged in the
same turn, or (b) asked about a previously-logged food and Arnie then "got caught
up" (re-logged / double-counted / lost the thread).

Writes nothing. Pulls Danny's linked-account conversation_logs + food_entries from
whatever DATABASE_URL points at (production Postgres via arnie/.env), flags candidate
turns heuristically, and prints them with enough surrounding context to eyeball.
"""
import asyncio
import os
import re
from datetime import datetime

from sqlalchemy import select, or_, func
from db.database import AsyncSessionLocal
from db.models import User, ConversationLog, DailyLog, FoodEntry


# --- intent heuristics -------------------------------------------------------

# "What have I had / how many calories so far / show my log" — asking to READ state.
HISTORY_Q = re.compile(
    r"\b(how many|how much|what did i|what have i|what'?s my|whats my|show me|"
    r"remind me|so far|total|left|remaining|already (had|eaten|logged)|"
    r"where am i|how'?m i doing|calories today|protein today|macros?)\b",
    re.I,
)

# A new logging action in the same message.
LOG_ACTION = re.compile(
    r"\b(add|log|ate|had|just ate|just had|drank|put down|throw in|plus|also had|"
    r"and (a|an|some|my)|had a|grabbed|ate a)\b",
    re.I,
)

# "that / the X I logged" — referring back to an existing entry.
REFERS_BACK = re.compile(
    r"\b(that|the one|earlier|before|previous|last (meal|one|time)|"
    r"the .* i (had|logged|ate)|my breakfast|my lunch|my dinner)\b",
    re.I,
)


async def resolve_danny(db):
    res = await db.execute(
        select(User).where(or_(User.name.ilike("%danny%"), User.name.ilike("%daniel%")))
    )
    users = res.scalars().all()
    ids = set()
    for u in users:
        ids.add(u.id)
        if getattr(u, "linked_to_user_id", None):
            ids.add(u.linked_to_user_id)
    # also pull anyone linking INTO these
    if ids:
        res2 = await db.execute(select(User).where(User.linked_to_user_id.in_(ids)))
        for u in res2.scalars().all():
            ids.add(u.id)
    return sorted(ids), {u.id: u for u in users}


async def main():
    async with AsyncSessionLocal() as db:
        ids, umap = await resolve_danny(db)
        print(f"Danny linked user ids: {ids}")
        for uid in ids:
            cnt = await db.scalar(
                select(func.count(ConversationLog.id)).where(ConversationLog.user_id == uid)
            )
            u = umap.get(uid)
            print(f"  id={uid} name={u.name if u else '?'} convs={cnt}")

        # Pull all turns for the group, ordered by time.
        res = await db.execute(
            select(ConversationLog)
            .where(ConversationLog.user_id.in_(ids))
            .order_by(ConversationLog.timestamp.asc())
        )
        turns = res.scalars().all()
        # Cross-linked accounts (2 & 26) mirror the same turn. Dedupe on
        # (timestamp, raw_message) so each real turn is counted once; keep the
        # row whose user actually has skills_fired populated (iOS/user 26).
        seen = {}
        for t in turns:
            key = (t.timestamp, (t.raw_message or "")[:120])
            if key not in seen or (t.skills_fired and not seen[key].skills_fired):
                seen[key] = t
        turns = sorted(seen.values(), key=lambda x: x.timestamp or datetime.min)
        print(f"\nTotal turns across group (deduped): {len(turns)}\n")

        # Food entries (for double-count detection) keyed by daily_log -> user.
        # Map daily_log_id -> user_id + date.
        res = await db.execute(select(DailyLog).where(DailyLog.user_id.in_(ids)))
        dlogs = {d.id: d for d in res.scalars().all()}
        res = await db.execute(
            select(FoodEntry)
            .where(FoodEntry.daily_log_id.in_(list(dlogs.keys())))
            .order_by(FoodEntry.timestamp.asc())
        )
        foods = res.scalars().all()

        pat_a = []   # query-history + log in one turn
        pat_b = []   # asks about prior food -> possible re-log

        for t in turns:
            msg = (t.raw_message or "").strip()
            resp = (t.response or "").strip()
            if not msg:
                continue
            fired = (t.skills_fired or "")

            is_hist_q = bool(HISTORY_Q.search(msg))
            is_log = bool(LOG_ACTION.search(msg)) or "log_food" in fired
            refers_back = bool(REFERS_BACK.search(msg))

            # Pattern A: single message asks to read state AND logs something new.
            if is_hist_q and is_log:
                pat_a.append(t)

            # Pattern B: a READ-only question (asks about state / a prior food, no
            # new eating verb) that nonetheless fired log_food — candidate re-log.
            asks_only = (is_hist_q or refers_back)
            no_new_food = not bool(LOG_ACTION.search(msg))
            if asks_only and no_new_food and "log_food" in fired:
                pat_b.append(t)

        def dump(t, tag):
            ts = t.timestamp
            print(f"[{tag}] turn#{t.id} {ts} plat={t.platform} skills=[{t.skills_fired}]")
            print(f"   USER: {(t.raw_message or '')[:280]}")
            print(f"   ARNIE: {(t.response or '')[:400]}")
            print(f"   cards: {(t.cards_json or '')[:160]}")
            print()

        print("=" * 80)
        print(f"PATTERN A — query history + log in ONE turn: {len(pat_a)} candidates")
        print("=" * 80)
        for t in pat_a:
            dump(t, "A")

        print("=" * 80)
        print(f"PATTERN B — asks about prior food + log_food fired (re-log risk): {len(pat_b)} candidates")
        print("=" * 80)
        for t in pat_b:
            dump(t, "B")

        # Double-count detection: same parsed_food_name logged twice within 15 min
        # on the same daily_log — a hard signal that a "how many cals was that X?"
        # question got re-logged.
        print("=" * 80)
        print("DOUBLE-LOG SCAN — same food name within 15min on same day")
        print("=" * 80)
        by_day = {}
        for f in foods:
            by_day.setdefault(f.daily_log_id, []).append(f)
        dupes = 0
        for dlid, items in by_day.items():
            items.sort(key=lambda x: x.timestamp or datetime.min)
            for i in range(1, len(items)):
                a, b = items[i - 1], items[i]
                if not a.parsed_food_name or not b.parsed_food_name:
                    continue
                if a.parsed_food_name.strip().lower() == b.parsed_food_name.strip().lower():
                    dt = None
                    if a.timestamp and b.timestamp:
                        dt = (b.timestamp - a.timestamp).total_seconds()
                    if dt is not None and 0 <= dt <= 900:
                        d = dlogs.get(dlid)
                        dupes += 1
                        print(f"  {d.date if d else '?'} '{b.parsed_food_name}' "
                              f"x2 within {int(dt)}s  (ids {a.id},{b.id}, {b.calories}kcal)")
        if not dupes:
            print("  none found")


if __name__ == "__main__":
    asyncio.run(main())
