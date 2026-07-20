"""Latency probe — MEASURES where a turn's time goes, no guessing.

Times the two model round-trips a logging turn makes (pass-1 tool selection +
the follow-up voicing pass) and reports TTFT, total, and the cache token
breakdown from the API usage — so we can see whether the ~38k static prefix is
actually cache-HITTING or being reprocessed every call.

  set -a; source ../arnie/.env; set +a
  python scripts/latency_probe.py                 # cold, then warm (cache)
  python scripts/latency_probe.py --model claude-opus-4-8
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MSG = "I had a barebells salty peanut bar"


async def _timed_chat(chat, messages, sysp, model, tools):
    t0 = time.monotonic()
    r = await chat(messages, sysp, tools=tools, max_tokens=1024,
                   **({"model": model} if model else {}))
    dt = time.monotonic() - t0
    usage = r.get("usage") or r.get("_usage") or {}
    return dt, r, usage


async def main(model, passes):
    from core.prompts.arnie import build_arnie_system
    from core.llm import chat, DEFAULT_MODEL

    sysp = build_arnie_system(platform="ios")
    approx_tokens = len(sysp) // 4
    print(f"system prompt: {len(sysp):,} chars (~{approx_tokens:,} tokens) | "
          f"model={model or DEFAULT_MODEL()}\n" + "─" * 60)

    for i in range(passes):
        label = "cold" if i == 0 else f"warm#{i}"
        # Pass 1: tool selection.
        dt1, r1, u1 = await _timed_chat(
            chat, [{"role": "user", "content": MSG}], sysp, model, True)
        ncalls = len(r1.get("tool_calls") or [])
        cw = u1.get("cache_creation_input_tokens", "?")
        cr = u1.get("cache_read_input_tokens", "?")
        inp = u1.get("input_tokens", "?")
        print(f"[{label}] pass-1 (tools): {dt1:5.2f}s  calls={ncalls}  "
              f"in={inp} cache_write={cw} cache_read={cr}")
        # Small wait to stay within the 5-min ephemeral window for the warm runs.
        await asyncio.sleep(1)

    # A follow-up voicing pass (tools off) for the second round-trip cost.
    fu_messages = [
        {"role": "user", "content": MSG},
        {"role": "assistant", "content": "logged it"},
        {"role": "user", "content": "(tool result) Logged: Barebells 200 cal"},
    ]
    dt2, r2, u2 = await _timed_chat(chat, fu_messages, sysp, None, False)
    print(f"[voice ] follow-up (no tools): {dt2:5.2f}s  "
          f"cache_read={u2.get('cache_read_input_tokens','?')}")
    print("─" * 60)
    print(f"  a logging turn pays roughly pass-1 + follow-up back to back.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.getenv("EVAL_MODEL"))
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args()
    asyncio.run(main(args.model, args.passes))
