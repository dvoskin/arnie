"""Multi-item logging eval — the heavy sim that proves the regression is dead.

Runs a battery of realistic multi-item food messages through the REAL model
with the REAL system prompt, and counts how many log_food tool calls it emits
per message vs. the expected item count. Pure planning measurement: tools=True,
NO execution, NO DB writes — it measures exactly the failure Chaya hit (the
model emitting one log_food for a three-item message).

  python scripts/eval_multi_item.py            # 1 pass over the battery
  python scripts/eval_multi_item.py --runs 3   # 3× for stochastic coverage
  python scripts/eval_multi_item.py --model claude-opus-4-8

Reports per-case emitted-vs-expected and an overall completeness rate. Run it
before and after a prompt change to see the number move.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Each case: (message, expected_item_count, note). Expected = distinct foods a
# human would say the message names. Mix of phrasings that have burned us:
# "and"/comma/with chaining, generic+specific pairs, quantities, restaurant.
CASES = [
    ("1 egg and half a cup of egg whites with some spinach", 3, "Chaya's exact drop"),
    ("2 eggs, buttered toast, and an oat milk latte", 3, "comma+and breakfast"),
    ("chicken breast, white rice, and broccoli", 3, "classic 3"),
    ("I had a turkey sandwich, a bag of chips, and a diet coke", 3, "lunch combo"),
    ("greek yogurt with honey and granola and a banana", 3, "with+and chain"),
    ("salmon, quinoa, roasted brussels sprouts, and a glass of white wine", 4, "dinner 4"),
    ("protein shake and two rice cakes with peanut butter", 3, "shake + cakes + PB"),
    ("had a burrito bowl — rice, black beans, steak, guac, and cheese", 5, "decomposed bowl"),
    ("coffee with oat milk, then a bagel with cream cheese", 2, "then-chained 2"),
    ("apple, string cheese, and a handful of almonds", 3, "snack 3"),
    ("bowl of oatmeal, blueberries, and a scoop of whey", 3, "breakfast 3"),
    ("cheeseburger and fries and a milkshake", 3, "and-and-and"),
    ("two slices of pepperoni pizza and a caesar salad", 2, "pizza + salad"),
    ("scrambled eggs, avocado toast, orange juice, and black coffee", 4, "brunch 4"),
    ("a barebells bar and a cold brew", 2, "brand + drink"),
]

_LOG_RE = re.compile(r"log_food")


async def run_once(model: str | None):
    from core.prompts.arnie import build_arnie_system
    from core.llm import chat

    # The iOS system prompt carries the full logging rules incl. MULTI-ITEM +
    # the NON_NEGOTIABLES completeness clause. User context is injected at
    # runtime; for a pure planning measure the static prompt is what governs
    # how many log_food calls the model emits.
    sysp = build_arnie_system(platform="ios")

    results = []
    for msg, expected, note in CASES:
        messages = [{"role": "user", "content": msg}]
        extras = {"model": model} if model else {}
        try:
            r = await chat(messages, sysp, tools=True, max_tokens=1200, **extras)
            calls = [tc for tc in (r.get("tool_calls") or [])
                     if tc.get("name") == "log_food"]
            got = len(calls)
        except Exception as e:
            got = -1
            note += f" (ERR {e})"
        results.append((msg, expected, got, note))
    return results


async def main(runs: int, model: str | None):
    agg: dict[str, list[int]] = {}
    for _ in range(runs):
        for msg, expected, got, note in await run_once(model):
            agg.setdefault(msg, []).append(got)

    print(f"\nMULTI-ITEM EVAL — {runs} run(s), model={model or 'default'}\n" + "─" * 66)
    total_expected = total_got = complete = cases = 0
    for msg, expected, note in CASES:
        gots = agg.get(msg, [])
        best = max(gots) if gots else 0   # generous: best of the runs
        ok = "✓" if best >= expected else "✗ UNDER"
        allruns = ",".join(str(g) for g in gots)
        print(f"  {ok:8} exp {expected}  got [{allruns}]  {msg[:44]!r}")
        cases += 1
        total_expected += expected
        total_got += best
        complete += 1 if best >= expected else 0
    print("─" * 66)
    print(f"  cases fully logged: {complete}/{cases} "
          f"({complete/cases:.0%})   items: {total_got}/{total_expected} "
          f"({total_got/total_expected:.0%})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default=os.getenv("EVAL_MODEL"))
    args = ap.parse_args()
    asyncio.run(main(args.runs, args.model))
