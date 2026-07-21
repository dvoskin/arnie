"""Consistency probe — run each of the 25 meal cases N times and measure how
stable the LOGGING DECISION is run-to-run (Danny 2026-07-21: "how consistent
was logging against the 25?").

For each case it reports the item-count across runs (e.g. "2,2,0" = a flaky drop)
and the calorie spread. This is the RAW pass-1 decision with NO enrichment and
NO self-heal — production is MORE stable because run_turn's self-heal retries a
stall. So a 0 here that's non-zero on other runs is exactly the stall class that
self-heal catches live.
"""
import asyncio

from core.prompts.arnie import build_arnie_system
from core.llm import chat, DEFAULT_MODEL
from scripts.eval_meals import CASES

RUNS = 3


async def _log_calls(message: str):
    system = build_arnie_system("imessage")
    res = await chat([{"role": "user", "content": message}], system,
                     tools=True, max_tokens=4096, model=DEFAULT_MODEL())
    return [tc for tc in (res.get("tool_calls") or []) if tc.get("name") == "log_food"]


async def main():
    print(f"model={DEFAULT_MODEL()}  cases={len(CASES)}  runs_each={RUNS}\n")
    stable_items = 0     # cases whose item-count never varied AND never dropped below imin
    never_dropped = 0    # cases that logged >=imin on ALL runs
    for cid, msg, exp_cal, exp_pro, (imin, imax) in CASES:
        counts, cals = [], []
        for _ in range(RUNS):
            try:
                foods = await _log_calls(msg)
            except Exception as e:
                counts.append(-1); cals.append(0); continue
            counts.append(len(foods))
            cals.append(sum((f.get("input") or {}).get("calories") or 0 for f in foods))
        item_stable = len(set(counts)) == 1
        no_drop = all(c >= imin for c in counts)
        stable_items += item_stable
        never_dropped += no_drop
        cal_lo, cal_hi = min(cals), max(cals)
        spread = f"{cal_lo}-{cal_hi}" if cal_lo != cal_hi else f"{cal_lo}"
        flag = "" if (item_stable and no_drop) else "  <-- VARIES"
        print(f"[{cid:>2}] items={counts} (exp {imin}-{imax})  cal={spread} (exp {exp_cal}){flag}")
    print(f"\n==== item-count identical across {RUNS} runs: {stable_items}/{len(CASES)} ====")
    print(f"==== never dropped below expected on any run: {never_dropped}/{len(CASES)} ====")


if __name__ == "__main__":
    asyncio.run(main())
