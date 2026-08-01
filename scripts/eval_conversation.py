"""CONVERSATIONAL accuracy — the clarification FLOW, not the resolver.

The sibling of eval_resolver.py, deliberately separate (Danny 2026-08-01). The
resolver eval asks "given everything stated, is the number right?"; this asks the
questions the resolver cannot answer:

    detect        an under-specified, MATERIAL log becomes a question
    right question the question is about the dimension actually in doubt
    no over-ask   a specified or immaterial log commits, no question
    apply         answering re-resolves and commits the corrected number
    corrected     that committed number is right

The butter-steak case lives HERE, not in the resolver eval: a steak whose butter
was never stated is not a resolver miss (it cannot invent the fat) — it is a
conversation that must ELICIT the fat, then apply it. Scoring it in the resolver
eval would pressure the resolver to guess; scoring it here judges the right system.

HOW. Each case supplies the interpreter's output (an overconfident `log`) and
drives the REAL turn (`core.food_turn.run`) with it mocked in — the same harness
as tests/test_food_turn_resolve_then_ask_e2e.py — then reads whether the turn
asked, and about what. No network, no DB writes (the turn returns the PLAN).

    NUTRITION_ACCURACY_V2=1 python scripts/eval_conversation.py

Scored BY CATEGORY. The apply/corrected dimensions need the two-turn answer
harness (the follow-up turn that re-parses and commits); they are declared here
and marked NEEDS HARNESS rather than faked — the same discipline as the resolver
eval's empty categories.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ── The conversational-corpus taxonomy ───────────────────────────────────────
# Declared in full so the coverage report names the gaps. detect / right-question
# / no-over-ask are scored now; apply / corrected need the answer-turn harness and
# are marked, not faked.
CONVERSATION_CATEGORIES = [
    "vague_portion_unstated",   # "a spoon of X" — how much?
    "cooking_fat_unstated",     # a steak whose oil/butter was never said
    "sauce_unstated",           # a salad with no dressing mentioned
    "over_ask_explicit",        # a stated mass must NOT be questioned
    "over_ask_immaterial",      # a tiny-calorie doubt must NOT be questioned
    "partial_consumption",      # "I only ate half" — NEEDS HARNESS
    "correction",               # "actually it was..." — NEEDS HARNESS
    "apply_corrected",          # answer → re-resolve → correct commit — NEEDS HARNESS
]


def _log(items):
    return {"action": "log", "items": items}


# Case = id, category, msg, interp (model output), mode, expect ('ask'|'log'),
#        dimension (a word the question must contain, when expect=='ask').
CASES: list[dict] = [
    dict(id="spoon-peanut-butter", category="vague_portion_unstated",
         msg="a spoon of peanut butter", mode="moderate", expect="ask",
         dimension="how much",
         interp=_log([{"food": "Peanut butter", "amount": 1, "unit": "spoon",
                       "calories": 350, "protein": 14, "carbs": 12, "fats": 28}])),
    dict(id="steak-unstated-fat", category="cooking_fat_unstated",
         msg="sirloin steak for dinner", mode="strict", expect="ask",
         dimension="butter",   # "any oil, butter, or dressing?"
         interp=_log([{"food": "Sirloin steak", "amount": 8, "unit": "oz",
                       "calories": 440, "protein": 46, "carbs": 0, "fats": 28}])),
    dict(id="salad-unstated-dressing", category="sauce_unstated",
         # A DEFINITE portion (2 cups), so the only doubt is the dressing — a
         # "bowl" would also (correctly) raise a portion question and muddy which
         # dimension this case is testing.
         msg="2 cups of green salad", mode="strict", expect="ask",
         dimension="dressing",
         interp=_log([{"food": "Green salad", "amount": 2, "unit": "cup",
                       "calories": 60, "protein": 3, "carbs": 8, "fats": 2}])),
    dict(id="steak-moderate-no-overask", category="over_ask_explicit",
         msg="8 oz sirloin steak", mode="moderate", expect="log", dimension=None,
         interp=_log([{"food": "Sirloin steak", "amount": 8, "unit": "oz",
                       "calories": 440, "protein": 46, "carbs": 0, "fats": 28}])),
    dict(id="peanut-butter-weighed", category="over_ask_explicit",
         msg="16 g of peanut butter", mode="moderate", expect="log", dimension=None,
         interp=_log([{"food": "Peanut butter", "amount": 16, "unit": "g",
                       "calories": 94, "protein": 4, "carbs": 3, "fats": 8}])),
    dict(id="spinach-handful", category="over_ask_immaterial",
         msg="a handful of spinach", mode="moderate", expect="log", dimension=None,
         interp=_log([{"food": "Spinach", "amount": 1, "unit": "handful",
                       "calories": 7, "protein": 1, "carbs": 1, "fats": 0}])),
]


def _fake_chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc


def _user(mode):
    return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=mode))


async def _run_case(FT, c: dict) -> dict:
    FT.chat = _fake_chat(c["interp"])
    try:
        out = await FT.run(c["msg"], _user(c["mode"]))
    except Exception as e:
        return {**c, "got": "error", "detail": f"{type(e).__name__}: {e}", "ok": False}
    action = (out or {}).get("action")
    text = (out or {}).get("text", "") or ""
    ok = action == c["expect"]
    dim_ok = True
    if c["expect"] == "ask" and c["dimension"]:
        dim_ok = c["dimension"].lower() in text.lower()
        ok = ok and dim_ok
    return {**c, "got": action, "text": text, "dim_ok": dim_ok, "ok": ok}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category",
                    choices=sorted({c["category"] for c in CASES}))
    args = ap.parse_args()

    if os.getenv("NUTRITION_ACCURACY_V2", "").lower() not in ("1", "true", "yes"):
        print("note: NUTRITION_ACCURACY_V2 is OFF — the promotion is dark, so every "
              "case will 'log'. Set NUTRITION_ACCURACY_V2=1 to exercise the flow.\n")

    import core.food_turn as FT
    from db.database import engine, Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    cases = [c for c in CASES if not args.category or c["category"] == args.category]
    rows = [await _run_case(FT, c) for c in cases]

    print(f"\nCONVERSATIONAL accuracy — {len(rows)} cases "
          f"(detect / right-question / no-over-ask)\n")
    print(f"{'id':<24} {'category':<24} {'expect':<6} {'got':<6} result")
    print("-" * 76)
    by_cat: dict = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["ok"])
        note = "" if r["ok"] else (
            f"  <- dimension {r['dimension']!r} not in question" if r.get("expect") == "ask"
            and r.get("got") == "ask" and not r.get("dim_ok")
            else f"  <- {r.get('detail', 'wrong action')}")
        print(f"{r['id']:<24} {r['category']:<24} {r['expect']:<6} "
              f"{str(r['got']):<6} {'PASS' if r['ok'] else 'FAIL'}{note}")

    print("\nby category:")
    for cat in sorted(by_cat):
        res = by_cat[cat]
        print(f"  {cat:<24} {sum(res)}/{len(res)}")
    total = [p for res in by_cat.values() for p in res]
    print(f"  {'TOTAL':<24} {sum(total)}/{len(total)}")

    print("\nconversational coverage:")
    counts: dict = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    scored_dims = {"vague_portion_unstated", "cooking_fat_unstated", "sauce_unstated",
                   "over_ask_explicit", "over_ask_immaterial"}
    for cat in CONVERSATION_CATEGORIES:
        n = counts.get(cat, 0)
        if cat not in scored_dims:
            print(f"  {cat:<24} NEEDS HARNESS — two-turn answer→apply not yet scored")
        else:
            print(f"  {cat:<24} {n} case(s)" if n else f"  {cat:<24} NEEDS CORPUS")

    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
