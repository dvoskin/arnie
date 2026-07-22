"""END-TO-END logging outcome with the DETERMINISTIC scribe (2026-07-22).

For each of ~35 meal variations it runs the REAL pipeline the user gets:
  pass-1 (opus + tools)  →  logged items
  scribe (Haiku)         →  full item list
  unlogged_items()       →  what the deterministic reconcile ADDS
  FINAL = logged + added

and scores the FINAL result (what actually lands on the board), not raw pass-1:
  • COMPLETE  — final count == expected  (the win)
  • DROP      — final < expected  (scribe missed it too)
  • OVERSPLIT — final > expected  (pass-1 fanned a composite; scribe can't undo)

This is the true outcome. RUNS repeats each (drops are stochastic).
"""
import asyncio

from core.prompts.arnie import build_arnie_system
from core.llm import chat, DEFAULT_MODEL
from core.scribe import extract_food_items, unlogged_items

RUNS = 2
CONC = 6

# (message, expected human log-entry count). Composites = 1.
CASES = [
    # distinct 2-item
    ("175g turkey and 100g rice", 2), ("eggs and toast", 2),
    ("a burger and fries", 2), ("salmon and asparagus", 2),
    ("greek yogurt and a banana", 2), ("a protein shake and a bagel", 2),
    ("a turkey sandwich and an apple", 2), ("shrimp and white rice", 2),
    ("cottage cheese and blueberries", 2), ("2 slices of pizza and a coke", 2),
    ("2 chunks of parmesan and a small caesar salad", 2),
    ("a bagel with cream cheese and a latte", 2),
    # distinct 3-item
    ("eggs bacon toast", 3), ("chicken, rice, and broccoli", 3),
    ("steak, baked potato, and a side salad", 3),
    ("oatmeal, a banana, and a scoop of whey", 3),
    ("a california roll, a spicy tuna roll, and miso soup", 3),
    ("pizza, garlic knots, and tiramisu", 3),
    # composites (expect 1)
    ("a poke bowl with salmon, tuna, rice, edamame, avocado", 1),
    ("a chipotle burrito with chicken, rice, beans, cheese", 1),
    ("a chipotle bowl with chicken, white rice, black beans, guac", 1),
    ("a chicken caesar wrap with croutons and parmesan", 1),
    ("a cobb salad with chicken, egg, bacon, avocado", 1),
    ("a greek yogurt parfait with granola, berries, honey", 1),
    ("a turkey club with bacon, lettuce, tomato, mayo", 1),
    ("a breakfast sandwich with egg, cheese, sausage", 1),
    # category != dedup
    ("melon, watermelon and mango", 3), ("fish, salmon, and rice", 3),
    ("berry, strawberry, and yogurt", 3),
    # real-world / harder
    ("a mediterranean chicken platter with rice, pita, and hummus", 1),
    ("a big mac and a large fries", 2),
    ("3 eggs, 2 turkey sausage patties, sourdough toast, and avocado", 4),
    ("a fairlife core power, a quest bar, and a banana", 3),
    # single items (must NOT get padded)
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
    added = unlogged_items(extracted, logged)
    final = len(logged) + len(added)
    return {"logged": len(logged), "added": len(added), "final": final, "exp": exp,
            "scribe": len(extracted)}


async def main():
    system = build_arnie_system("imessage")
    sem = asyncio.Semaphore(CONC)
    print(f"model={DEFAULT_MODEL()}  cases={len(CASES)}  runs={RUNS}\n")
    tasks = [(msg, exp, asyncio.create_task(one(sem, system, msg, exp)))
             for msg, exp in CASES for _ in range(RUNS)]
    complete = drop = oversplit = 0
    raw_drop = 0
    fails = []
    for msg, exp, t in tasks:
        r = await t
        if r["logged"] < exp:
            raw_drop += 1
        if r["final"] == exp:
            complete += 1
        elif r["final"] < exp:
            drop += 1
            fails.append(f"  DROP  {msg[:44]:44} pass1={r['logged']} +scribe={r['added']} final={r['final']}/{exp}")
        else:
            oversplit += 1
            fails.append(f"  SPLIT {msg[:44]:44} pass1={r['logged']} +scribe={r['added']} final={r['final']}/{exp}")
    tot = len(tasks)
    for f in fails:
        print(f)
    print(f"\n==== {tot} runs ====")
    print(f"  raw pass-1 drops:        {raw_drop}/{tot} ({100*raw_drop/tot:.0f}%)")
    print(f"  FINAL complete:          {complete}/{tot} ({100*complete/tot:.0f}%)")
    print(f"  FINAL drops (scribe missed): {drop}/{tot} ({100*drop/tot:.0f}%)")
    print(f"  FINAL over-splits:       {oversplit}/{tot} ({100*oversplit/tot:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
