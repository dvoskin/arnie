"""Hole-hunt (LIVE, needs ANTHROPIC_API_KEY) — does the REAL interpreter+path
drop a co-mentioned food?

The offline sweep proved the PATH drops a settled food left in `items` during an
ask (3/7 shapes). This checks the interpreter side: on messages where one item is
ask-worthy (branded/ambiguous) and the other is simple, does the simple one
survive? Strict mode, to make the clarification fire. Invariant I1:

    every food in the message is committed or asked — never silently dropped.

Lightweight user (no DB), so this exercises the interpreter + turn plan without
the async-session lazy-load traps. Key read from env only, never written.

    ANTHROPIC_API_KEY=... python scripts/hole_hunt_live.py
"""
from __future__ import annotations
import asyncio, os, sys, pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# (message, {expected food keywords}) — one ask-worthy item + one simple co-item.
CASES = [
    ("a Quest bar and an apple", {"quest", "apple"}),
    ("a Barebells bar and a banana", {"barebells", "banana"}),
    ("some trail mix and an orange", {"trail", "orange"}),
    ("a protein shake and 2 eggs", {"shake", "egg"}),
    ("grilled chicken breast and a banana", {"chicken", "banana"}),  # control: no ask
    ("8 oz sirloin steak and a corn", {"sirloin", "corn"}),
]


def _user(mode="strict"):
    return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=mode))


async def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("needs ANTHROPIC_API_KEY in the environment."); return 2
    import core.food_turn as FT

    dropped_cases = []
    print("\nLIVE leave-no-food-behind (real interpreter, strict mode)\n")
    for msg, expected in CASES:
        try:
            out = await FT.run(msg, _user())
        except Exception as e:
            print(f"[{msg}] ERROR {type(e).__name__}: {str(e)[:70]}"); continue
        action = (out or {}).get("action")
        committed = [str(c["input"].get("food_name", "")).lower()
                     for c in (out.get("tool_calls") or [])]
        text = (out.get("text") or "").lower()
        blob = " ".join(committed) + " " + text
        dropped = sorted(f for f in expected if f not in blob)
        if dropped:
            dropped_cases.append((msg, dropped))
        print(f"[{msg}]\n   action={action} committed={committed} "
              f"dropped={dropped or 'none'}")

    print(f"\n=== I1 leave-no-food-behind: {len(dropped_cases)} case(s) dropped a food ===")
    for msg, d in dropped_cases:
        print(f"  DROP  {msg}  ->  {d}")
    return 1 if dropped_cases else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
