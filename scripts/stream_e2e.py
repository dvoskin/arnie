"""THE FULL STREAM — what the user actually sees, end to end, writing nothing.

`stage_clarify_e2e` stops at `food_turn.run()`, which is why a log turn showed
its rows and no reply: for a commit the sentence is composed downstream in
`conversation.py`, from the committed snapshot. This carries a turn the rest of
the way — snapshot, plan, composer, cards — using the SAME functions the live
path calls, so what prints is what ships.

Nothing is executed. The writes are simulated in memory (ids, batch and day
totals) purely so the snapshot the composer reads has real numbers in it; no
row is created, no ledger event appended, no day total moved.

    .venv/bin/python scripts/stream_e2e.py --user 26
    .venv/bin/python scripts/stream_e2e.py --user 26 --modes strict
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env() -> None:
    directory = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidate = os.path.join(directory, ".env")
        if os.path.exists(candidate):
            for line in open(candidate):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return
        parent = os.path.dirname(directory)
        if parent == directory:
            return
        directory = parent


_load_env()
os.environ.setdefault("FOOD_COMPOSER", "true")

import logging                                                  # noqa: E402
logging.basicConfig(level=logging.WARNING)

import core.food_turn as FT                                     # noqa: E402
from core.conversation import _logged_entry_card                # noqa: E402
from core.food_ledger import build_snapshot                     # noqa: E402
from core.food_response import (CARD_FACTS, FoodItemSummary,    # noqa: E402
                                FoodResponseIntent,
                                FoodResponsePlan, apply_policy,
                                compose_async, composer_enabled, fallback)
from core.food_response import with_context as _ctx             # noqa: E402

B, D, X = "\033[1m", "\033[2m", "\033[0m"
GRN, CYN, YEL, MAG, RED = ("\033[32m", "\033[36m", "\033[33m",
                           "\033[35m", "\033[31m")

MEAL = ("had some rice with a piece of grilled chicken, plus a barebells bar "
        "and a fairlife shake")
REPLY = ("about a cup of rice, the chicken was a small breast, the bar was "
         "cookies and cream, and the shake was core power vanilla")


async def load_user(uid: int):
    from sqlalchemy import select
    from db.database import AsyncSessionLocal
    from db.models import User, UserPreferences
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.id == uid))
        if user is not None:
            user.preferences = await db.scalar(
                select(UserPreferences).where(UserPreferences.user_id == uid))
        return user


async def voice(out, user, day) -> tuple:
    """Snapshot -> plan -> composer, exactly as conversation.py assembles it.

    Returns `(reply_text, cards, assumptions)`.
    """
    calls = out.get("tool_calls") or []
    ok = []
    for i, c in enumerate(calls):
        inp = dict(c.get("input") or {})
        inp["_entry_id"] = 9000 + i               # simulated, never written
        ok.append({"name": c.get("name"), "input": inp})

    batch_c = sum(int((c["input"].get("calories") or 0)) for c in ok)
    batch_p = sum(int((c["input"].get("protein") or 0)) for c in ok)
    snap = build_snapshot(ok, batch_c, batch_p,
                          day["cal"] + batch_c, day["protein"] + batch_p,
                          int(day["cal_target"]), int(day["protein_target"]))

    # Named, exactly as conversation.py builds it — an unattributed list gets
    # misattributed, and the pairing is not the composer's to infer.
    assumed = []
    for c in ok:
        nm = str(c["input"].get("food_name") or "").strip()
        for a in (c["input"].get("assumptions") or []):
            if isinstance(a, dict) and str(a.get("text") or "").strip():
                txt = str(a["text"]).strip()
                assumed.append(f"{nm}: {txt}" if nm else txt)
    assumed = tuple(dict.fromkeys(assumed))

    cards = [_logged_entry_card(c["name"], c["input"]) for c in ok]
    cards = [c for c in cards if c]
    renders = bool(cards)

    act = (out.get("action") or "").strip()
    intent = (FoodResponseIntent.UNDO if act == "delete" else
              FoodResponseIntent.CORRECT if act == "update" else
              FoodResponseIntent.COMMIT)
    plan = apply_policy(FoodResponsePlan(
        intent=intent,
        committed_items=tuple(
            FoodItemSummary(name=str(c["input"].get("food_name")
                                     or c["input"].get("food_hint") or ""))
            for c in ok),
        committed_snapshot=snap,
        assumptions=assumed,
        model_say=out.get("say") or "",
        note=out.get("note") or "",
        card_will_render=renders,
        facts_visible_in_card=(CARD_FACTS if renders else frozenset())))
    plan = _ctx(plan, user=user)

    text, why = "", "composer-off"
    if composer_enabled():
        text, why = await compose_async(plan)
        if why != "ok":
            text = fallback(plan)
    else:
        text = fallback(plan)
    return text, cards, assumed, why


def show_turn(n, msg, out, text, cards, assumed, why=""):
    print(f"\n  {B}USER{X}   {msg}")
    if out is None:
        print(f"  {D}(pass — the food lane declined this turn){X}")
        return
    act = out.get("action")
    if act == "ask":
        print(f"\n  {GRN}ARNIE{X}  {out.get('text') or ''}")
        print(f"  {CYN}       [nothing written — held behind the question]{X}")
        return
    print(f"\n  {GRN}ARNIE{X}  {text or '(no sentence — the card carries it)'}"
          + (f"   {RED}[composer: {why}]{X}" if why not in ("ok", "") else ""))
    for c in cards:
        p = c.get("payload") or {}
        print(f"  {MAG}  ┌ CARD{X} {p.get('name')}  {p.get('quantity')}  "
              f"{p.get('calories')} cal  "
              f"P{p.get('protein_g')} C{p.get('carbs_g')} F{p.get('fats_g')}")
        for a in (p.get("assumptions") or []):
            print(f"  {MAG}  └{X} {YEL}assumed{X} ({a.get('field')}) "
                  f"{a.get('text')}  {D}[tap to correct]{X}")


async def one_mode(user, mode, day):
    FT._mode = lambda _u, _m=mode: _m
    print(f"\n{B}{'='*74}{X}\n{B} {mode.upper()}{X}   "
          f"targets {int(day['cal_target'])} cal / "
          f"{int(day['protein_target'])}g protein\n{B}{'='*74}{X}")

    first = await FT.run(MEAL, user)
    t1, c1, a1, w1 = (await voice(first, user, day)) if first else ("", [], (), "")
    show_turn(1, MEAL, first, t1, c1, a1, w1)

    # Whatever turn one did decides what turn two is answering: a held question
    # carries `prior`, a commit leaves rows on the board instead.
    prior, board = None, None
    if first and first.get("action") == "ask":
        prior = {"original": f"{MEAL}\nThen: {REPLY}",
                 "question": first.get("text") or "", "kind": "clarify",
                 "ask_count": 1, "items": first.get("items") or None}
    elif first:
        board = [{"id": 9000 + i,
                  "food": (c.get("input") or {}).get("food_name"),
                  "qty": (c.get("input") or {}).get("quantity"),
                  "cal": (c.get("input") or {}).get("calories") or 0,
                  "mins_ago": 1}
                 for i, c in enumerate(first.get("tool_calls") or [])]

    second = await FT.run(REPLY, user, prior=prior, board=board)
    t2, c2, a2, w2 = (await voice(second, user, day)) if second else ("", [], (), "")
    show_turn(2, REPLY, second, t2, c2, a2, w2)

    if second:
        news = [c for c in (second.get("tool_calls") or [])
                if c.get("name") == "log_food"]
        if board and news:
            print(f"\n  {RED}!! {len(news)} NEW row(s) on the follow-up "
                  f"— duplicate{X}")
        elif board:
            print(f"\n  {CYN}   follow-up corrected the existing rows "
                  f"— no duplicates{X}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=26)
    ap.add_argument("--modes", default="quick,moderate,strict")
    args = ap.parse_args()

    user = await load_user(args.user)
    if user is None:
        print(f"no user {args.user}")
        return
    targets = FT._daily_targets(user) or {}
    day = {"cal": 0, "protein": 0,
           "cal_target": targets.get("calories") or 2000,
           "protein_target": targets.get("protein") or 150}

    print(f"{B}FULL STREAM{X} — real interpreter, real composer, real cards, "
          f"no writes\nuser={args.user} ({getattr(user, 'name', '?')})")
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        await one_mode(user, mode, day)


asyncio.run(main())
