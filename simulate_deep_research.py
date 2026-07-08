"""
Behavioral routing sim for deep-research turns — the go/no-go gate before deploy.

Drives PASS-1 of the real pipeline (live LLM, production system prompt, real
tool list with SEARCH_ENABLED=true) and checks WHICH tools the model reaches
for. Routing is a pass-1 decision, so one LLM call per scenario is enough —
no DB, no Tavily, no tool execution.

The two invariants Danny cares about:
  1. SIMPLE PROMPTS STAY INSTANT — logging, quick questions, casual chat must
     NEVER route to deep_research (which would add ~20s of latency).
  2. PLAN-GRADE ASKS ESCALATE — a real-world, current-facts plan request must
     fire deep_research (with a heads-up bubble and a populated key_context),
     not a lone web_search and not a hand-wave.

Run from the repo root:
    .venv/bin/python simulate_deep_research.py

Requires ANTHROPIC_API_KEY in .env.
"""
import asyncio
import os
import sys

# Must be set BEFORE core.tools / prompts are imported.
os.environ["SEARCH_ENABLED"] = "true"

from dotenv import load_dotenv
load_dotenv(override=True)
os.environ["SEARCH_ENABLED"] = "true"   # reassert — .env may not carry it

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

_pass = 0
_fail = 0


def check(label, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  {G}PASS{X} {label}")
    else:
        _fail += 1
        print(f"  {R}FAIL{X} {label}  {D}{detail}{X}")


_CONTEXT = """
[USER PROFILE]
Name: Danny | Goal: lose weight (internal: cut) | 188.8 lb, target 178
Daily targets: 2,100 cal / 180g protein
Trains 4x/week (upper/lower), home city: New York

[TODAY]
1,240 / 2,100 cal · 96g protein · no workout logged yet
"""


# (message, must_fire, must_not_fire, label)
SCENARIOS = [
    # ── invariant 1: simple prompts stay instant ─────────────────────────────
    ("log a coke",
     {"log_food"}, {"deep_research", "web_search"}, "simple log routes to log_food only"),
    ("weighed in at 188.2 this morning",
     {"log_body_weight"}, {"deep_research"}, "weigh-in stays on log_body_weight"),
    ("what's my protein at today?",
     set(), {"deep_research", "web_search"}, "own-data question needs no tools"),
    ("should i train today or rest? feeling a little beat up",
     set(), {"deep_research"}, "coaching judgment stays instant"),
    ("macros for a chipotle chicken bowl?",
     set(), {"deep_research"}, "single fact = at most web_search, never deep"),
    # ── invariant 2: plan-grade asks escalate ────────────────────────────────
    ("flying to Miami tomorrow through Sunday, staying near South Beach. "
     "build me an eating strategy for the trip, restaurants and all",
     {"deep_research"}, set(), "trip eating strategy escalates"),
    ("I'm in Austin all next week for work, hotel has no gym. find me real "
     "gym options near downtown and where I'm getting protein lunches",
     {"deep_research"}, set(), "travel gym+food plan escalates"),
]


async def run():
    from core.llm import chat
    from core.prompts import build_arnie_system

    system = build_arnie_system(platform="ios") + "\n\n" + _CONTEXT
    print(f"\n{B}Deep-research routing sim{X} — live pass-1, {len(SCENARIOS)} scenarios\n")

    for msg, must, must_not, label in SCENARIOS:
        print(f"{C}» {msg[:74]}{X}")
        try:
            result = await chat(
                [{"role": "user", "content": msg}], system,
                tools=True, max_tokens=1200,
            )
        except Exception as e:
            check(label, False, f"chat() raised: {e}")
            continue
        fired = {tc["name"] for tc in (result.get("tool_calls") or [])}
        print(f"  {D}fired: {sorted(fired) or '(none)'}{X}")
        ok = must.issubset(fired) and not (must_not & fired)
        detail = f"needed {sorted(must) or 'none'}, forbidden {sorted(must_not)}, got {sorted(fired)}"
        check(label, ok, detail)

        # Deep calls must carry a heads-up + a real key_context.
        for tc in (result.get("tool_calls") or []):
            if tc["name"] == "deep_research":
                text = (result.get("text") or "").strip()
                check(f"{label} — heads-up bubble present", bool(text),
                      "model emitted deep_research with no lead-in text")
                kc = (tc.get("input") or {}).get("key_context", "")
                check(f"{label} — key_context carries personal facts",
                      any(t in kc for t in ("2,100", "2100", "180", "cut", "weight")),
                      f"key_context too thin: {kc[:120]!r}")
        print()

    print(f"\n{B}{'='*56}{X}")
    color = G if _fail == 0 else R
    print(f"{color}{B}{_pass} passed, {_fail} failed{X}\n")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
