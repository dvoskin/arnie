"""Ironclad evaluation: live behavioral matrix for the structured food turn.

Every case is a real production failure we fixed (or a behavior Danny locked
in) — this is the regression battery for the WHOLE food-logging brain, run
against the real FOOD_LOGGER_MODEL. Each case states the message, the state
(mode / board / regulars / last_assistant), and the EXPECTED action (+ shape
checks). Output: PASS/FAIL per case + score.

Run:  PYTHONPATH=<repo> python eval_food_matrix.py
"""
import asyncio
import os
import sys
import json
from types import SimpleNamespace

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from core import food_turn as FT


def U(mode="strict"):
    return SimpleNamespace(
        id=999, first_name="Eval",
        preferences=SimpleNamespace(food_logging_mode=mode,
                                    calorie_target=2165, protein_target=180))


BOARD = [
    {"id": 501, "food": "Birria Taco", "qty": "1 taco", "cal": 180},
    {"id": 502, "food": "Quest Chips, Sour Cream & Onion", "qty": "1 bag", "cal": 140},
]

REG_COFFEE_ONE = [{"name": "Coffee with oat milk splash", "qty": "1 cup",
                   "calories": 25, "protein": 1, "carbs": 3, "fats": 1, "count": 9}]
# True ambiguity: neither is literally named "coffee" — an exact-name match
# (like "Coffee with oat milk splash") legitimately WINS the pointer instead.
REG_COFFEE_TWO = [
    {"name": "Iced Americano", "qty": "1 grande", "calories": 15,
     "protein": 0, "carbs": 2, "fats": 0, "count": 5},
    {"name": "Oat Milk Latte", "qty": "1 grande", "calories": 120,
     "protein": 4, "carbs": 12, "fats": 6, "count": 7},
]
REG_BAREBELLS = [{"name": "Barebells Caramel Cashew", "qty": "1 bar",
                  "calories": 200, "protein": 20, "carbs": 20, "fats": 7, "count": 12}]

CASES = [
    # ── action routing ────────────────────────────────────────────────────
    dict(name="multi-item split logs each component",
         msg="Had a caesar salad and a grilled chicken breast",
         mode="quick", expect="log", min_items=2),
    dict(name="quick mode logs small-swing vagueness (some strawberries < 300)",
         msg="had some strawberries", mode="quick", expect="log"),
    dict(name="strict asks on big-swing vagueness (some chicken, prep unknown)",
         msg="had some chicken", mode="strict", expect="ask"),
    dict(name="stated count logs without asking (strict)",
         msg="ate 12 strawberries", mode="strict", expect="log"),
    dict(name="plan/future is pass",
         msg="thinking about getting a burrito later", mode="strict", expect=None),
    dict(name="question is never food",
         msg="how much protein is in a barebells bar?", mode="strict", expect=None),
    dict(name="destructive routes to legacy",
         msg="remove the birria taco", mode="strict", expect=None),
    dict(name="workout routes to legacy",
         msg="did 3 sets of bench at 185", mode="strict", expect=None),

    # ── strict brand discipline (Barebells saga) ──────────────────────────
    dict(name="strict + branded + no flavor ALWAYS asks",
         msg="just had a barebells bar", mode="strict", expect="ask"),
    dict(name="strict + branded + flavor stated logs",
         msg="had a barebells caramel cashew bar", mode="strict", expect="log"),
    dict(name="branded + regular match logs THEIR numbers",
         msg="just had a barebell", mode="strict", regulars=REG_BAREBELLS,
         expect="log", want_cal=(180, 220)),

    # ── regulars pointer (my usual X) ─────────────────────────────────────
    dict(name="usual + one regular logs it verbatim",
         msg="having my usual coffee", mode="moderate", regulars=REG_COFFEE_ONE,
         expect="log", want_cal=(20, 30)),
    dict(name="usual + two matches asks which",
         msg="having my usual coffee", mode="moderate", regulars=REG_COFFEE_TWO,
         expect="ask"),
    dict(name="usual + no regular asks once (never generic)",
         msg="having my usual coffee", mode="moderate", regulars=[], expect="ask"),

    # ── counts anchor portions (truffle fries saga) ───────────────────────
    dict(name="5-6 fries prices per piece, never a menu side",
         msg="I had some parmesan truffle fries from Bobby Flay, like 5-6 fries",
         mode="strict", expect="log", max_cal=220),
    dict(name="stated mass is kept as the unit",
         msg="200g of grilled chicken breast", mode="strict", expect="log",
         want_unit_sub="g"),

    # ── corrections own the board ─────────────────────────────────────────
    dict(name="correction scales the board entry",
         msg="actually I had 2 of those birria tacos", mode="strict",
         board=BOARD, expect="update", want_cal=(340, 380)),
    dict(name="correction target off-board is pass",
         msg="actually make the ramen 2 bowls", mode="strict", board=BOARD,
         expect=None),
    dict(name="keep-as-is after a proposed bump writes NOTHING",
         msg="Leave it like this", mode="strict", board=BOARD,
         last_assistant="Those fries realistically run 350-400, I'll bump it up to be safe.",
         expect=None, gate_only=True),

    # ── say contract ──────────────────────────────────────────────────────
    dict(name="say never carries model-invented totals",
         msg="had a bowl of white rice and two fried eggs", mode="moderate",
         expect="log", say_contract=True),
]


async def run_case(c):
    if c.get("gate_only"):
        ok = (not FT.applies(c["msg"])) and (not FT.thread_routes(c["msg"]))
        return ok, "gate excluded ✓" if ok else "GATE LET IT THROUGH"
    res = await FT.run(c["msg"], U(c.get("mode", "strict")),
                       day_line="Today: 320 cal, 21g protein so far.",
                       board=c.get("board", []),
                       last_assistant=c.get("last_assistant", ""),
                       regulars=c.get("regulars", []))
    got = res["action"] if res else None
    if c["expect"] is None:
        return got is None, f"got={got}"
    if got != c["expect"]:
        detail = ""
        if res and res.get("action") == "ask":
            detail = f" ask={res.get('text', '')[:90]}"
        return False, f"got={got} want={c['expect']}{detail}"
    if got in ("log", "update"):
        calls = res.get("tool_calls", [])
        if "min_items" in c and len(calls) < c["min_items"]:
            return False, f"items={len(calls)} < {c['min_items']}"
        total = sum((tc.get("input") or {}).get("calories") or 0 for tc in calls)
        if "want_cal" in c:
            lo, hi = c["want_cal"]
            if not (lo <= total <= hi):
                return False, f"cal={total} not in [{lo},{hi}]"
        if "max_cal" in c and total > c["max_cal"]:
            return False, f"cal={total} > max {c['max_cal']}"
        if "want_unit_sub" in c:
            units = " ".join(str((tc.get("input") or {}).get("quantity") or "") +
                             str((tc.get("input") or {}).get("unit") or "")
                             for tc in calls)
            if c["want_unit_sub"] not in units:
                return False, f"unit missing '{c['want_unit_sub']}' in {units!r}"
        if c.get("say_contract"):
            say = res.get("say", "")
            cleaned = FT.enforce_say_contract(say, calls)
            if cleaned != say:
                return False, f"say violated contract: {say[:90]}"
    return True, f"got={got} ✓"


async def main():
    passed = failed = 0
    lines = []
    for c in CASES:
        try:
            ok, detail = await run_case(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"EXC {type(e).__name__}: {e}"
        mark = "PASS" if ok else "FAIL"
        passed += ok
        failed += (not ok)
        line = f"[{mark}] {c['name']}  ({detail})"
        print(line, flush=True)
        lines.append(line)
    print(f"\n{passed}/{passed + failed} passed", flush=True)
    out = "/tmp/eval_matrix_results.txt"
    with open(out, "w") as f:
        f.write("\n".join(lines) + f"\n\n{passed}/{passed + failed} passed\n")


if __name__ == "__main__":
    asyncio.run(main())
