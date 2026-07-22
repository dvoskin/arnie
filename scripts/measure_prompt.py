"""Score the CURRENT build_arnie_system prompt on the three logging failure axes,
so a prompt trim can be judged on all of them at once (a trim that cuts drops but
raises over-splits is not a win). Prints DROPS / OVERSPLIT / CATEGORY percentages.

Runs the REAL pass-1 decision (opus + tools). RUNS repeats per case (drops are
stochastic). Concurrency-bounded.
"""
import asyncio

from core.prompts.arnie import build_arnie_system
from core.llm import chat, DEFAULT_MODEL

RUNS = 3
CONC = 8

# (message, expected log_food count). DROPS = logged < expected on a multi-item.
DROPS = [
    ("175g turkey and 100g rice", 2), ("eggs bacon toast", 3),
    ("a burger and fries", 2), ("chicken, rice, and broccoli", 3),
    ("2 slices of pizza and a coke", 2), ("salmon and asparagus", 2),
    ("2 chunks of parmesan and a small caesar salad", 2),
    ("oatmeal, a banana, and a scoop of whey", 3),
    ("a turkey sandwich and an apple", 2), ("shrimp and white rice", 2),
]
# Composites: must log as ONE (over-split = logged > 1).
COMPOSITE = [
    "a poke bowl with salmon, tuna, rice, edamame, avocado",
    "a chipotle burrito with chicken, rice, beans, cheese",
    "a chicken caesar wrap with croutons and parmesan",
    "a cobb salad with chicken, egg, bacon, avocado",
]
# Category ≠ dedup: a generic + specific in the list are distinct.
CATEGORY = [
    ("melon, watermelon and mango", 3), ("fish, salmon, and rice", 3),
    ("berry, strawberry, and yogurt", 3),
]


async def _n(sem, system, msg):
    async with sem:
        r = await chat([{"role": "user", "content": msg}], system,
                       tools=True, max_tokens=2048, model=DEFAULT_MODEL())
    return len([tc for tc in (r.get("tool_calls") or []) if tc.get("name") == "log_food"])


async def main():
    system = build_arnie_system("imessage")
    sem = asyncio.Semaphore(CONC)
    print(f"model={DEFAULT_MODEL()}  runs={RUNS}  prompt_chars={len(system)}")

    async def rate(cases, is_composite):
        tasks = [(exp, asyncio.create_task(_n(sem, system, msg)))
                 for msg, exp in cases for _ in range(RUNS)]
        bad = 0
        for exp, t in tasks:
            n = await t
            if is_composite:
                if n > 1:
                    bad += 1            # over-split
            elif n < exp:
                bad += 1                # drop / collapse
        return bad, len(tasks)

    d_bad, d_tot = await rate(DROPS, False)
    o_bad, o_tot = await rate([(m, 1) for m in COMPOSITE], True)
    c_bad, c_tot = await rate(CATEGORY, False)
    print(f"DROPS:    {d_bad}/{d_tot} ({100*d_bad/d_tot:.0f}%)")
    print(f"OVERSPLIT:{o_bad}/{o_tot} ({100*o_bad/o_tot:.0f}%)")
    print(f"CATEGORY: {c_bad}/{c_tot} ({100*c_bad/c_tot:.0f}%)")
    print(f"SCORE (lower=better): drops={100*d_bad/d_tot:.0f} oversplit={100*o_bad/o_tot:.0f} category={100*c_bad/c_tot:.0f}")


if __name__ == "__main__":
    asyncio.run(main())
