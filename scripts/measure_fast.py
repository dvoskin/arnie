"""FAST per-cut regression gate for prompt trimming (2026-07-22).

A 12-case subset run end-to-end (pass-1 + scribe reconcile) so each prompt cut
can be checked in ~2-3 min. ANY prompt change can shift logging behaviour (it's
total attention load), so we re-measure complete% + over-split% after every cut.

Baseline to beat: complete ~94%, over-split ~4%. A cut that pushes over-split up
or complete down is a REGRESSION — revert it.
"""
import asyncio

from core.prompts.arnie import build_arnie_system
from core.llm import chat, DEFAULT_MODEL
from core.scribe import extract_food_items, unlogged_items

RUNS = 3
CONC = 6

CASES = [
    ("175g turkey and 100g rice", 2), ("eggs bacon toast", 3),
    ("a burger and fries", 2), ("chicken, rice, and broccoli", 3),
    ("2 chunks of parmesan and a small caesar salad", 2),
    ("melon, watermelon and mango", 3),
    # composites — the over-split canaries
    ("a poke bowl with salmon, tuna, rice, edamame, avocado", 1),
    ("a chipotle bowl with chicken, white rice, black beans, guac", 1),
    ("a greek yogurt parfait with granola, berries, honey", 1),
    ("a mediterranean chicken platter with rice, pita, hummus", 1),
    # singles — must not get padded
    ("a banana", 1), ("a large iced coffee", 1),
]


async def _pass1(sem, system, msg):
    async with sem:
        r = await chat([{"role": "user", "content": msg}], system,
                       tools=True, max_tokens=2048, model=DEFAULT_MODEL())
    return [(tc.get("input") or {}).get("food_name") or ""
            for tc in (r.get("tool_calls") or []) if tc.get("name") == "log_food"]


async def _scribe(sem, msg):
    async with sem:
        return await extract_food_items(msg)


async def one(sem, system, msg, exp):
    logged, extracted = await asyncio.gather(_pass1(sem, system, msg), _scribe(sem, msg))
    final = len(logged) + len(unlogged_items(extracted, logged))
    return final, exp


async def main():
    system = build_arnie_system("imessage")
    sem = asyncio.Semaphore(CONC)
    tasks = [asyncio.create_task(one(sem, system, msg, exp))
             for msg, exp in CASES for _ in range(RUNS)]
    complete = drop = oversplit = 0
    for t in tasks:
        final, exp = await t
        if final == exp:
            complete += 1
        elif final < exp:
            drop += 1
        else:
            oversplit += 1
    tot = len(tasks)
    print(f"chars={len(system)}  runs={tot}  "
          f"COMPLETE {100*complete/tot:.0f}%  DROP {100*drop/tot:.0f}%  "
          f"OVERSPLIT {100*oversplit/tot:.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
