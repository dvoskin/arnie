"""HIGH-VOLUME completeness stress test (2026-07-21).

Proves the scribe-reconcile net at volume: for a large, diverse meal set it runs
the REAL pass-1 logging decision (opus + tools), the REAL scribe extraction, and
the REAL reconcile — then measures the two things that matter:

  • CATCH RATE   — when pass-1 DROPS a distinct item, does the reconcile flag it?
                   (this is the whole point of the net; must be ~100%)
  • FALSE-POS    — when a COMPOSITE logged correctly as one, does the reconcile
                   wrongly flag it? (the over-split risk; must be ~0%)

Each case runs RUNS times (drops are stochastic ~1/3, so we need repeats to see
them). Concurrency-bounded so we don't hammer the API.
"""
import asyncio
import os

from core.prompts.arnie import build_arnie_system
from core.llm import chat, DEFAULT_MODEL
from core.scribe import extract_food_items, distinct_missing_items

RUNS = 3
CONCURRENCY = 6

# DISTINCT: genuinely separate foods/sides/drinks. exp = the count a human logs.
DISTINCT = [
    ("175g turkey and 100g rice", 2),
    ("eggs bacon toast", 3),
    ("a burger and fries", 2),
    ("salmon and asparagus", 2),
    ("3 eggs and oatmeal", 2),
    ("greek yogurt and a banana", 2),
    ("a protein shake and a bagel", 2),
    ("chicken, rice, and broccoli", 3),
    ("steak, baked potato, and a side salad", 3),
    ("2 slices of pizza and a coke", 2),
    ("a bowl of cereal with milk and a coffee", 2),
    ("pancakes and 2 sausage links", 2),
    ("a turkey sandwich and an apple", 2),
    ("tuna salad and crackers", 2),
    ("a quest bar and a fairlife", 2),
    ("cottage cheese and blueberries", 2),
    ("grilled chicken and sweet potato", 2),
    ("shrimp and white rice", 2),
    ("a bagel with cream cheese and a latte", 2),
    ("oatmeal, a banana, and a scoop of whey", 3),
    ("chicken thighs and green beans", 2),
    ("a ribeye and mashed potatoes", 2),
    ("egg whites and turkey bacon", 2),
    ("a smoothie and a rice cake", 2),
    ("lentil soup and a roll", 2),
]

# COMPOSITES: ONE named dish whose fillings are listed (no per-item amounts).
COMPOSITE = [
    "a poke bowl with salmon, tuna, rice, edamame, and avocado",
    "a chicken caesar wrap with croutons and parmesan",
    "a Chipotle burrito with chicken, rice, beans, cheese, and salsa",
    "a Chipotle bowl with chicken, white rice, black beans, and guac",
    "a greek yogurt parfait with granola, berries, and honey",
    "a cobb salad with chicken, egg, bacon, avocado, and blue cheese",
    "an acai bowl with granola, banana, and peanut butter",
    "a turkey club with bacon, lettuce, tomato, and mayo",
    "a burrito bowl with steak, rice, corn, and cheese",
    "a Mediterranean grain bowl with chicken, hummus, feta, and tzatziki",
    "a breakfast sandwich with egg, cheese, and sausage",
    "a smoothie with banana, spinach, protein powder, and almond milk",
    "a California roll",
    "a bahn mi with pork, pickled veggies, and cilantro",
    "a chicken quesadilla with cheese and pico",
]


async def _pass1(sem, system, message):
    async with sem:
        res = await chat([{"role": "user", "content": message}], system,
                         tools=True, max_tokens=4096, model=DEFAULT_MODEL())
    return [(tc.get("input") or {}).get("food_name") or ""
            for tc in (res.get("tool_calls") or []) if tc.get("name") == "log_food"]


async def _scribe(sem, message):
    async with sem:
        return await extract_food_items(message)


async def one_run(sem, system, message, is_composite):
    logged = await _pass1(sem, system, message)
    extracted = await _scribe(sem, message)
    missing = distinct_missing_items(extracted, logged)
    return {"logged": logged, "n_logged": len(logged),
            "scribe_n": len(extracted), "missing": missing}


async def main():
    system = build_arnie_system("imessage")
    sem = asyncio.Semaphore(CONCURRENCY)
    print(f"model={DEFAULT_MODEL()}  distinct={len(DISTINCT)} composite={len(COMPOSITE)}  runs={RUNS}\n")

    # DISTINCT: measure drop rate + catch rate
    drops = caught = distinct_runs = 0
    tasks = []
    for msg, exp in DISTINCT:
        for _ in range(RUNS):
            tasks.append((msg, exp, asyncio.create_task(one_run(sem, system, msg, False))))
    print("=== DISTINCT (drop → must be caught) ===")
    for msg, exp, t in tasks:
        r = await t
        distinct_runs += 1
        dropped = r["n_logged"] < exp
        if dropped:
            drops += 1
            # caught if reconcile flags at least one missing item
            if r["missing"]:
                caught += 1
            else:
                print(f"  MISSED  {msg[:44]:44} logged={r['n_logged']}/{exp} scribe={r['scribe_n']} missing={r['missing']}")
    print(f"  drops seen: {drops}/{distinct_runs} runs;  CAUGHT by reconcile: {caught}/{drops}")

    # COMPOSITE: measure false-positive rate (reconcile must stay empty)
    print("\n=== COMPOSITE (must NEVER be flagged) ===")
    ctasks = []
    for msg in COMPOSITE:
        for _ in range(RUNS):
            ctasks.append((msg, asyncio.create_task(one_run(sem, system, msg, True))))
    false_pos = comp_runs = 0
    for msg, t in ctasks:
        r = await t
        comp_runs += 1
        if r["missing"]:
            false_pos += 1
            print(f"  FALSE-FLAG  {msg[:44]:44} logged={r['n_logged']} scribe={r['scribe_n']} missing={r['missing']}")
    print(f"  false-flags: {false_pos}/{comp_runs} runs (want 0)")

    print("\n==== SUMMARY ====")
    print(f"  DISTINCT: {drops} drops across {distinct_runs} runs, {caught} caught "
          f"({100*caught/drops if drops else 100:.0f}% catch rate)")
    print(f"  COMPOSITE: {false_pos}/{comp_runs} false-flags "
          f"({100*false_pos/comp_runs if comp_runs else 0:.1f}%)")
    print(f"  VERDICT: {'PASS' if (drops==0 or caught==drops) and false_pos==0 else 'NEEDS REVIEW'}")


if __name__ == "__main__":
    asyncio.run(main())
