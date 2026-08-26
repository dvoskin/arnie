"""Acceptance gate for food logging — Danny's 25 real-meal cases (2026-07-21).

For each meal message it runs the REAL pass-1 logging decision (the arnie system
prompt + tools, same as run_turn) and reports:
  • how many log_food calls fired (completeness vs over-split)
  • the model's summed calories/protein vs the expected label
  • PASS/FAIL flags: DROP (fewer items than expected), OVERSPLIT (a composite fanned
    into many), CAL off by >25%.

This tests the LOGGING DECISION (does it write every distinct item, and treat a
composite as one) — the exact thing that's broken. Run before/after a change.
"""
import asyncio
import json

from core.prompts.arnie import build_arnie_system
from core.llm import chat, DEFAULT_MODEL

# (id, message, exp_cal, exp_protein, exp_items)  — exp_items = distinct log entries a
# human would expect (a composite = 1; distinct dishes/sides = N). Ranges where fair.
CASES = [
    (1,  "Subway Footlong Turkey on Italian Herbs & Cheese, provolone, veggies, mayo", 980, 54, (1, 1)),
    (2,  "Five Guys Little Cheeseburger and a small fries", 1060, 39, (2, 2)),
    (3,  "Panda Express Bigger Plate: Orange Chicken, Teriyaki Chicken, and Super Greens", 1080, 69, (2, 3)),
    (4,  "Chick-fil-A 12-count nuggets, medium fries, and Polynesian sauce", 840, 43, (2, 3)),
    (5,  "Jersey Mike's Regular #7 Turkey and Provolone, Mike's Way", 760, 42, (1, 1)),
    (6,  "Taco Bell Crunchwrap Supreme, a Beefy 5-Layer, and a Baja Blast Zero", 980, 35, (2, 3)),
    (7,  "Wendy's Dave's Single and a small fries", 860, 35, (2, 2)),
    (8,  "Popeyes 3-piece tenders, Cajun fries, and a Blackened Ranch", 990, 48, (2, 3)),
    (9,  "CAVA Greens and Grains bowl with steak, hummus, feta, and tzatziki", 1020, 52, (1, 1)),
    (10, "Sweetgreen Chicken Pesto Parm bowl", 720, 44, (1, 1)),
    (11, "Chipotle burrito with chicken, white rice, black beans, cheese, and sour cream", 1270, 61, (1, 1)),
    (12, "Panera Bacon Turkey Bravo and a bag of chips", 920, 41, (2, 2)),
    (13, "Starbucks Double-Smoked Bacon sandwich and a Venti Caramel Macchiato", 810, 29, (2, 2)),
    (14, "Shake Shack SmokeShack and fries", 1180, 41, (2, 2)),
    (15, "A California roll, a spicy tuna roll, and miso soup", 820, 35, (3, 3)),
    (16, "8 oz sirloin, a loaded baked potato, and a Caesar salad", 1060, 67, (3, 3)),
    (17, "A chicken Caesar wrap and an apple", 760, 45, (2, 2)),
    (18, "A Mediterranean chicken platter with rice, pita, and hummus", 1420, 66, (1, 4)),
    (19, "2 Costco pepperoni pizza slices", 1420, 68, (1, 1)),
    (20, "Trader Joe's Butter Chicken and a Garlic Naan", 930, 35, (2, 2)),
    (21, "A Fairlife Core Power Elite, a Quest Bar, and a banana", 570, 68, (3, 3)),
    (22, "3 eggs, 2 turkey sausage patties, sourdough toast, and avocado", 760, 41, (4, 4)),
    (23, "A Greek yogurt parfait with granola, berries, honey, and almonds", 620, 33, (1, 1)),
    (24, "A homemade turkey burger on a brioche bun with sweet potato fries", 910, 47, (2, 2)),
    (25, "A large poke bowl with salmon, tuna, rice, edamame, avocado, and spicy mayo", 1120, 59, (1, 1)),
]


async def _turn(message: str):
    """`(log_food calls, reply text, every tool name)`.

    ⛔⛔ THE OLD VERSION RETURNED ONLY `log_food` AND THREW THE REPLY AWAY, so
    a turn that ASKED a material clarification was indistinguishable from one
    that silently did nothing — both scored `DROP(0<n)`. Case 18 measured
    2026-08-26: "A Mediterranean chicken platter with rice, pita, and hummus"
    answered *"What went into it and how big a plate we talking?"* and was
    counted a failure. **An ask is progression; silence is not.**
    """
    system = build_arnie_system("imessage")
    res = await chat([{"role": "user", "content": message}], system,
                     tools=True, max_tokens=4096, model=DEFAULT_MODEL())
    calls = res.get("tool_calls") or []
    foods = [tc for tc in calls if tc.get("name") == "log_food"]
    return foods, (res.get("text") or "").strip(), [c.get("name") for c in calls]


async def main():
    """⛔ EVERY CASE IS SCORED, AND THE SCRIPT PROVES IT.

    The old loop `continue`d on an exception, leaving the case out of
    `n_pass` while it stayed in the denominator — an outage read as a product
    failure. Now an error is its own terminal outcome and the assertion below
    refuses to publish a rate over a partial set.
    """
    print(f"model={DEFAULT_MODEL()}  cases={len(CASES)}\n")
    outcomes: dict = {}
    for cid, msg, exp_cal, exp_pro, (imin, imax) in CASES:
        try:
            foods, text, names = await _turn(msg)
        except Exception as e:                              # noqa: BLE001
            outcomes[cid] = ("ERROR", f"{type(e).__name__}: {e}")
            print(f"[{cid:>2}] ERROR      {type(e).__name__}: {e}")
            continue
        n = len(foods)
        cal = sum((f.get("input") or {}).get("calories") or 0 for f in foods)
        pro = sum((f.get("input") or {}).get("protein") or 0 for f in foods)

        if n == 0:
            # ⭐ ASK != DROP. A question is the lane making progress on a fact
            # it cannot settle; silence is the lane doing nothing at all.
            kind = "ASK" if ("?" in text) else "NO_ACTION"
            outcomes[cid] = (kind, text[:70])
            print(f"[{cid:>2}] {kind:<10} {text[:66]!r}")
            continue

        flags = []
        if n < imin:
            flags.append(f"DROP({n}<{imin})")
        if n > imax:
            flags.append(f"OVERSPLIT({n}>{imax})")
        if exp_cal and abs(cal - exp_cal) / exp_cal > 0.25:
            flags.append(f"CAL {cal}vs{exp_cal}")
        kind = "LOG_COMPLETE" if not flags else (
            "WRONG_COMPONENTS" if any(f.startswith(("DROP", "OVERSPLIT"))
                                      for f in flags) else "WRONG_NUTRITION")
        outcomes[cid] = (kind, " ".join(flags))
        label = ", ".join(((f.get("input") or {}).get("food_name") or "?")[:22]
                          for f in foods)
        print(f"[{cid:>2}] {kind:<16} items={n}(exp {imin}-{imax}) "
              f"cal={cal}(exp {exp_cal}) pro={pro}(exp {exp_pro})  "
              f"{' '.join(flags)}")
        print(f"     logged: {label}")

    # ⛔⛔ NO RATE OVER A PARTIAL SET. A silently dropped case makes every
    # percentage below a measurement of the survivors.
    assert len(outcomes) == len(CASES), (
        f"{len(outcomes)} of {len(CASES)} cases scored — refusing to publish "
        f"a rate over a partial set; missing "
        f"{sorted({c[0] for c in CASES} - set(outcomes))}")

    tally: dict = {}
    for kind, _ in outcomes.values():
        tally[kind] = tally.get(kind, 0) + 1
    print("\n==== OUTCOMES ====")
    for kind in sorted(tally):
        print(f"  {kind:<18} {tally[kind]}")

    n = len(CASES)
    progressed = tally.get("LOG_COMPLETE", 0) + tally.get("ASK", 0)
    print(f"\n  scored              {len(outcomes)}/{n}  (all cases)")
    print(f"  LOG_COMPLETE        {tally.get('LOG_COMPLETE', 0)}/{n} = "
          f"{100*tally.get('LOG_COMPLETE', 0)/n:.0f}%")
    print(f"  + ASK (progression) {progressed}/{n} = {100*progressed/n:.0f}%")
    print(f"\n  ⚠ ASK is reported SEPARATELY and always: a lane that asked "
          f"everything\n    would score 100% progression and log nothing.\n")


if __name__ == "__main__":
    asyncio.run(main())
