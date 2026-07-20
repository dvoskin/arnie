"""Full logging regression net — the guardrail the prompt diet rides on.

Beyond single-message multi-item (scripts/eval_multi_item.py), this exercises
the MULTI-TURN classes that actually regressed: a repeat ("another one"), a
clarify-then-answer ("chicken wrap" → "regular size"), and component
decomposition. Each scenario is a real conversation replayed through the model
(tools=True, NO execution, NO DB writes); we assert the model FIRES the log
tool with the right item count on the final turn.

  set -a; source ../arnie/.env; set +a
  python scripts/eval_logging_full.py            # 1 pass
  python scripts/eval_logging_full.py --runs 3   # stochastic coverage

The number this prints is the gate: run before a prompt cut, run after, it
must not drop. "We can only move forward."
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Each scenario: (label, [prior turns as (role, content)], final_user_msg,
#                 min_log_calls, note). The model sees the priors as history.
SCENARIOS = [
    ("repeat-another",
     [("user", "I had a barebells salty peanut bar"),
      ("assistant", "Barebells logged, 200 cal, 20g protein. You're at 200/2,165.")],
     "I just had another one of those", 1,
     "repeat must FIRE log_food, not narrate 'second logged' (#7119)"),
    ("clarify-wrap",
     [("user", "grilled chicken wrap from the bodega"),
      ("assistant", "Grilled chicken wrap — regular size or large, and how much oil?")],
     "Regular size minimal oil", 1,
     "clarify-answer must FIRE log_food for the wrap (#7125)"),
    ("clarify-flavor",
     [("user", "had a barebells cookies and caramel bar"),
      ("assistant", "Cookies and caramel Barebells, same 55g bar as usual?")],
     "Yes the full one", 1,
     "a 'yes' answering the clarifier must FIRE the log"),
    ("multi-3",
     [], "chicken breast, white rice, and a side of broccoli", 3,
     "3-item single message → 3 log_food"),
    ("decompose-plate",
     [], "salmon plate — 6oz salmon, half cup rice, and grilled asparagus", 3,
     "a composed PLATE decomposes into its parts (salmon/rice/asparagus)"),
    ("add-on-mid",
     [("user", "logged my lunch, chicken and rice"),
      ("assistant", "Logged. You're at 1,200/2,165.")],
     "oh and I also had a greek yogurt after", 1,
     "mid-conversation add must FIRE log_food for the yogurt"),
    ("simple-single",
     [], "just had a cup of oatmeal", 1, "the base case must never regress"),
    ("voice-multi",
     [], "[Voice note]: for breakfast I had two eggs, some spinach, and coffee", 3,
     "voice multi-item → 3 log_food"),
]


async def run_once(model):
    from core.prompts.arnie import build_arnie_system
    from core.llm import chat
    sysp = build_arnie_system(platform="ios")
    out = []
    for label, priors, final, minlog, note in SCENARIOS:
        messages = [{"role": r, "content": c} for r, c in priors]
        messages.append({"role": "user", "content": final})
        try:
            r = await chat(messages, sysp, tools=True, max_tokens=1200,
                           **({"model": model} if model else {}))
            n = len([tc for tc in (r.get("tool_calls") or [])
                     if tc.get("name") in ("log_food", "log_exercise")])
        except Exception as e:
            n = -1
            note += f" (ERR {e})"
        out.append((label, minlog, n, note))
    return out


async def main(runs, model):
    from collections import defaultdict
    agg = defaultdict(list)
    for _ in range(runs):
        for label, minlog, n, note in await run_once(model):
            agg[label].append(n)

    print(f"\nFULL LOGGING EVAL — {runs} run(s), model={model or 'default'}\n" + "─" * 68)
    passed = 0
    for label, priors, final, minlog, note in SCENARIOS:
        gots = agg[label]
        best = max(gots) if gots else 0
        ok = best >= minlog
        passed += 1 if ok else 0
        print(f"  {'✓' if ok else '✗ FAIL':7} need≥{minlog} got{gots}  {label:16} {note[:38]}")
    print("─" * 68)
    print(f"  scenarios passed: {passed}/{len(SCENARIOS)} ({passed/len(SCENARIOS):.0%})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default=os.getenv("EVAL_MODEL"))
    args = ap.parse_args()
    asyncio.run(main(args.runs, args.model))
