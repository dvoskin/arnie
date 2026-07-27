"""FULL TURNS: the whole exchange, five composite meals, every mode.

    user   describes a composite meal with vague portions
    arnie  logs it, or asks
    user   answers
    arnie  replies, and the board is shown as the user would see it

Everything is the real thing — interpreter, staged pipeline, materiality,
composer, cards. Nothing is executed: `run()` returns tool calls and this
prints what WOULD be written, so it is safe against production.

    .venv/bin/python scripts/conversation_sim.py
    .venv/bin/python scripts/conversation_sim.py --modes quick --meal 2
"""
import argparse
import asyncio
import os
import sys
import time

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
logging.basicConfig(level=logging.CRITICAL)

import core.food_turn as FT                                     # noqa: E402
from core.conversation import _logged_entry_card                # noqa: E402
from core.food_ledger import build_snapshot                     # noqa: E402
from core.food_response import (CARD_FACTS, FoodItemSummary,    # noqa: E402
                                FoodResponseIntent,
                                FoodResponsePlan, apply_policy,
                                compose_async, composer_enabled, fallback)
from core.food_response import with_context as _ctx             # noqa: E402
from core import deadline                                       # noqa: E402


async def run_turn(*a, **kw):
    """A turn under its OWN budget, exactly as the request path runs it.

    Without this the harness leaks one expired deadline across every later
    call, `deadline.wait_for` raises inside the interpreter, and `run()`
    returns None — which prints as a legacy fall-through and looks like the
    pipeline giving up on the user's answer. It was the harness.
    """
    with deadline.budget():
        return await FT.run(*a, **kw)

#: (the meal, what the user says when asked)
CONVERSATIONS = [
    ("a bowl of ramen with an egg and some chashu",
     "it was a big bowl, two slices of chashu, and the egg was soft boiled"),
    ("some chicken curry with rice and a piece of naan",
     "about a cup of curry, a cup of rice, and one whole naan"),
    ("a plate of nachos with everything on them",
     "it was a shared plate, I had maybe a third of it"),
    ("a big salad with grilled chicken and a couple scoops of quinoa",
     "the chicken was one breast, two scoops of quinoa, and ranch dressing"),
    ("some leftover lasagna and a handful of garlic bread",
     "one big square of lasagna and two slices of bread"),
]
MODES = ("quick", "moderate", "strict")

B, D, X = "\033[1m", "\033[2m", "\033[0m"
GRN, CYN, YEL, MAG, RED = ("\033[32m", "\033[36m", "\033[33m",
                           "\033[35m", "\033[31m")


async def load_user(uid):
    from sqlalchemy import select
    from db.database import AsyncSessionLocal
    from db.models import User, UserPreferences
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.id == uid))
        if user is not None:
            user.preferences = await db.scalar(
                select(UserPreferences).where(UserPreferences.user_id == uid))
        return user


async def voice(out, user, targets, day):
    """Snapshot -> plan -> composer, as conversation.py assembles a log turn."""
    ok = []
    for i, c in enumerate(out.get("tool_calls") or []):
        inp = dict(c.get("input") or {})
        inp["_entry_id"] = 9000 + i
        ok.append({"name": c.get("name"), "input": inp})
    bc = sum(int(c["input"].get("calories") or 0) for c in ok)
    bp = sum(int(c["input"].get("protein") or 0) for c in ok)
    snap = build_snapshot(ok, bc, bp, day["cal"] + bc, day["protein"] + bp,
                          int(targets.get("calories") or 2000),
                          int(targets.get("protein") or 150))
    assumed = []
    for c in ok:
        nm = str(c["input"].get("food_name") or "").strip()
        for a in (c["input"].get("assumptions") or []):
            if isinstance(a, dict) and str(a.get("text") or "").strip():
                assumed.append(f"{nm}: {str(a['text']).strip()}")
    cards = [x for x in (_logged_entry_card(c["name"], c["input"])
                         for c in ok) if x]
    act = (out.get("action") or "").strip()
    intent = (FoodResponseIntent.CORRECT if act == "update"
              else FoodResponseIntent.COMMIT)
    # Before -> after, exactly as conversation.py builds it. Without this the
    # composer is asked to name the change and can only see the result.
    changed = []
    for c in ok:
        if c["name"] != "update_food_entry":
            continue
        was = str(c["input"].get("food_hint") or "").strip()
        now = str(c["input"].get("food_name") or "").strip()
        qty = str(c["input"].get("quantity") or "").strip()
        if now and was and now.lower() != was.lower():
            changed.append(f"{was} is now {now}")
        elif qty:
            changed.append(f"{was or now} is now {qty}")
    plan = apply_policy(FoodResponsePlan(
        intent=intent,
        committed_items=tuple(FoodItemSummary(
            name=str(c["input"].get("food_name")
                     or c["input"].get("food_hint") or "")) for c in ok),
        committed_snapshot=snap, assumptions=tuple(dict.fromkeys(assumed)),
        corrections=tuple(changed),
        model_say=out.get("say") or "", card_will_render=bool(cards),
        facts_visible_in_card=(CARD_FACTS if cards else frozenset())))
    plan = _ctx(plan, user=user)
    text = ""
    if composer_enabled():
        text, why = await compose_async(plan)
        if why != "ok":
            text = fallback(plan)
    else:
        text = fallback(plan)
    return text, ok, cards


def show_cards(cards, indent="        "):
    for c in cards:
        p = c.get("payload") or {}
        cal = p.get("calories")
        macros = (f"P{p.get('protein_g')} C{p.get('carbs_g')} "
                  f"F{p.get('fats_g')}" if cal is not None else "re-resolving")
        tag = f" {D}(corrected){X}" if p.get("corrected") else ""
        print(f"{indent}{MAG}▸{X} {str(p.get('name'))[:36]:36} "
              f"{str(p.get('quantity') or '')[:14]:14} "
              f"{'' if cal is None else str(cal) + ' cal'} {macros}{tag}")
        for a in (p.get("assumptions") or []):
            print(f"{indent}  {YEL}assumed{X} ({a.get('field')}) "
                  f"{a.get('text')}  {D}[tap to correct]{X}")


async def conversation(user, targets, meal, reply, mode):
    FT._mode = lambda _u, _m=mode: _m
    day = {"cal": 0, "protein": 0}
    print(f"\n  {B}── {mode.upper()} {'─' * (60 - len(mode))}{X}")

    t0 = time.monotonic()
    first = await run_turn(meal, user)
    ms1 = (time.monotonic() - t0) * 1000
    print(f"    {B}USER{X}   {meal}")

    prior, board = None, None
    if first is None:
        print(f"    {D}(legacy fall-through){X}")
        return
    if first.get("action") == "ask":
        print(f"    {GRN}ARNIE{X}  {(first.get('text') or '').strip()}"
              f"   {D}{ms1:.0f} ms{X}")
        held = first.get("tool_calls") or []
        if held:
            print(f"    {CYN}       committed while asking "
                  f"({len(held)} row(s)):{X}")
            show_cards([x for x in (_logged_entry_card(c.get("name"),
                                                       dict((c.get("input")
                                                             or {}),
                                                            _entry_id=8000 + i))
                                    for i, c in enumerate(held)) if x])
        else:
            print(f"    {CYN}       nothing written — the meal waits{X}")
        prior = {"original": f"{meal}\nThen: {reply}",
                 "question": first.get("text") or "", "kind": "clarify",
                 "ask_count": 1, "items": first.get("items") or None}
    else:
        text, ok, cards = await voice(first, user, targets, day)
        print(f"    {GRN}ARNIE{X}  {text or '(card only)'}   {D}{ms1:.0f} ms{X}")
        show_cards(cards)
        board = [{"id": 9000 + i,
                  "food": (c.get("input") or {}).get("food_name"),
                  "qty": (c.get("input") or {}).get("quantity"),
                  "cal": (c.get("input") or {}).get("calories") or 0,
                  "mins_ago": 1}
                 for i, c in enumerate(first.get("tool_calls") or [])]

    t1 = time.monotonic()
    second = await run_turn(reply, user, prior=prior, board=board)
    ms2 = (time.monotonic() - t1) * 1000
    print(f"    {B}USER{X}   {reply}")
    if second is None:
        print(f"    {D}(legacy fall-through){X}")
        return
    text, ok, cards = await voice(second, user, targets, day)
    print(f"    {GRN}ARNIE{X}  {text or '(card only)'}   {D}{ms2:.0f} ms{X}")
    show_cards(cards)
    if board:
        fresh = [c for c in ok if c["name"] == "log_food"]
        if fresh:
            print(f"    {RED}   !! {len(fresh)} NEW row(s) on the answer "
                  f"— duplicate{X}")
        else:
            print(f"    {CYN}   corrected in place — no duplicates{X}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=26)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--meal", type=int, default=0,
                    help="1-based; 0 runs all")
    args = ap.parse_args()

    user = await load_user(args.user)
    if user is None:
        print(f"no user {args.user}")
        return
    targets = FT._daily_targets(user) or {}
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    picked = (CONVERSATIONS if not args.meal
              else [CONVERSATIONS[args.meal - 1]])

    print(f"{B}FULL TURNS{X} — real interpreter, pipeline, composer and cards; "
          f"no writes\nuser={args.user}  targets={targets}")
    base = 1 if not args.meal else args.meal
    for n, (meal, reply) in enumerate(picked, start=base):
        print(f"\n{B}{'=' * 72}{X}\n{B}  MEAL {n}{X}")
        for mode in modes:
            await conversation(user, targets, meal, reply, mode)


asyncio.run(main())
