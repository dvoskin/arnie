"""STAGING: the whole food turn, on a real profile, writing nothing.

sim_clarify exercises the interpreter and the composer. This runs the thing a
user actually hits — `core.food_turn.run()` — with the real pre-gate, the real
staged pipeline, the real clarification policy and the real composer, for a
profile loaded from production.

It is safe to point at production because the pipeline decides and does not
execute: `run()` RETURNS `tool_calls` and the caller is what runs them. Nothing
here calls the executor, so no row is written, no ledger event is appended and
no day total moves. The harness prints the calls that WOULD have run, which is
the point — seeing what commits behind a question is the thing that was wrong.

Two turns, because one turn never showed the bug: the meal is described, then
answered, and it is the ANSWER turn that used to commit four invented portions.

    .venv/bin/python scripts/stage_clarify_e2e.py
    .venv/bin/python scripts/stage_clarify_e2e.py --user 26 --modes strict
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env() -> None:
    candidates = []
    if os.environ.get("ARNIE_ENV"):
        candidates.append(os.environ["ARNIE_ENV"])
    directory = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidates.append(os.path.join(directory, ".env"))
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            for line in open(candidate):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return


_load_env()

import logging                                                 # noqa: E402
logging.basicConfig(level=logging.INFO,
                    format='      %(levelname)s %(name)s: %(message)s')
import core.food_turn as FT                                    # noqa: E402
from core.food_turn import _daily_targets                      # noqa: E402

B, DIM, X = "\033[1m", "\033[2m", "\033[0m"
RED, GRN, YEL, CYN = "\033[31m", "\033[32m", "\033[33m", "\033[36m"

ASK_TURN = ("Had some pasta some yellowtail crudo some ceased salad "
            "and some beef tartare")
ANSWER_TURN = "Some like cheesy big rigatoni in a red sauce"


async def load_user(user_id: int):
    """A real profile, read-only. Targets come from it, so the materiality
    scoring is the user's own rather than a fixture's."""
    from sqlalchemy import select
    from db.database import AsyncSessionLocal
    from db.models import User, UserPreferences
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.id == user_id))
        if user is None:
            return None
        prefs = await db.scalar(
            select(UserPreferences).where(UserPreferences.user_id == user_id))
        try:
            user.preferences = prefs
        except Exception:
            pass
        return user


def show(tag: str, out) -> None:
    if out is None:
        print(f"    {DIM}{tag}{X} run() returned None — legacy path handles it")
        return
    action = out.get("action")
    print(f"    {DIM}{tag}{X} action={action!r}")
    text = (out.get("text") or "").replace("|||", "\n              ")
    if text:
        print(f"    {GRN}SAYS   {X} {text}")
    calls = out.get("tool_calls") or []
    if calls:
        print(f"    {RED}WOULD WRITE{X} {len(calls)} row(s) — not executed here:")
        for c in calls:
            inp = c.get("input") or {}
            print(f"             - {c.get('name')} {inp.get('food_name')!r} "
                  f"qty={inp.get('quantity')!r} cal={inp.get('calories')} "
                  f"estimated={inp.get('estimated')}")
    else:
        print(f"    {CYN}WRITES NOTHING{X} — held behind the question")


async def one_mode(user, mode: str) -> None:
    print(f"\n  {B}{mode.upper():9}{X} targets={_daily_targets(user)}")
    FT._mode = lambda _u, _m=mode: _m       # exercise each mode on one profile

    print(f"    {B}turn 1{X} {ASK_TURN!r}")
    first = await FT.run(ASK_TURN, user)
    show("turn 1", first)

    # The prior EXACTLY as conversation.py stashes it — including the
    # concatenated original, which is what lets the answer turn re-derive the
    # whole meal, and ask_count, which the re-ask policy reads. A thinner prior
    # makes the answer turn look like a fresh meal and it asks again.
    prior = None
    if first and first.get("action") == "ask":
        prior = {"original": f"{ASK_TURN}\nThen: {ANSWER_TURN}",
                 "question": first.get("text") or "",
                 "kind": first.get("kind") or "clarify",
                 "ask_count": 1,
                 "items": first.get("items") or None}
    print(f"    {B}turn 2{X} {ANSWER_TURN!r}   (the commit turn)")
    second = await FT.run(ANSWER_TURN, user, prior=prior)
    show("turn 2", second)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=26)
    ap.add_argument("--modes", default="quick,moderate,strict")
    args = ap.parse_args()

    user = await load_user(args.user)
    if user is None:
        print(f"user {args.user} not found")
        return
    print(f"{B}STAGING — real turn, real profile, no writes{X}")
    print(f"user={user.id} ({user.name}) tz={getattr(user, 'timezone', None)}")
    original_mode = FT._mode
    try:
        for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
            try:
                await one_mode(user, mode)
            except Exception as e:
                print(f"\n  {mode.upper():9} {RED}failed{X}: {type(e).__name__}: {e}")
    finally:
        FT._mode = original_mode


if __name__ == "__main__":
    asyncio.run(main())
