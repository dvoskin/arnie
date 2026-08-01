"""Hole-hunt (offline, no key) — the ask/log PATH's leave-no-food-behind invariant.

The corn bug: a food the user reported was silently dropped when a co-item
triggered a clarification. This feeds the real turn (`core.food_turn.run`) every
realistic shape of interpreter output and asserts ONE invariant:

    every food the interpreter parsed is either COMMITTED or ASKED-ABOUT —
    never silently dropped.

It tests the PATH's robustness to how the model distributes foods across
items / ready / points (interpreter-side drops need the real-model battery, which
needs the ANTHROPIC key). A food is "accounted" if it appears in tool_calls
(committed) OR by name in the rendered question. Anything parsed but unaccounted
is a DROP — silent data loss.

    NUTRITION_ACCURACY_V2=1 python scripts/invariant_sweep.py   # or flag off (prod)
"""
from __future__ import annotations
import asyncio, json, os, sys, pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc

def _user(mode="moderate"):
    return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=mode))

def _item(food, **kw):
    return {"food": food, "amount": kw.get("amount", 1), "unit": kw.get("unit", ""),
            "calories": kw.get("calories", 100), "protein": kw.get("protein", 5),
            "carbs": kw.get("carbs", 10), "fats": kw.get("fats", 3)}

# Each case: a message + the interpreter payload it stands in for. The foods are
# given distinct, findable names so a drop is unambiguous.
CASES = [
    ("log one",            {"action": "log", "items": [_item("Alpha")]}),
    ("log three",          {"action": "log", "items": [_item("Alpha"), _item("Bravo"), _item("Charlie")]}),
    ("ask: asked in points+items, settled in ready",
        {"action": "ask", "points": [{"label": "Alpha", "qs": ["how much?"]}],
         "items": [_item("Alpha")], "ready": [_item("Bravo")]}),
    ("ask: settled left in ITEMS (not ready)",   # <-- the corn shape
        {"action": "ask", "points": [{"label": "Alpha", "qs": ["how much?"]}],
         "items": [_item("Alpha"), _item("Bravo")]}),
    ("ask: settled only in items, asked has no item row",
        {"action": "ask", "points": [{"label": "Alpha", "qs": ["how much?"]}],
         "items": [_item("Bravo")]}),
    ("ask: two settled in ready, one asked",
        {"action": "ask", "points": [{"label": "Alpha", "qs": ["how much?"]}],
         "items": [_item("Alpha")], "ready": [_item("Bravo"), _item("Charlie")]}),
    ("ask: settled in ready + a THIRD only in items",
        {"action": "ask", "points": [{"label": "Alpha", "qs": ["how much?"]}],
         "items": [_item("Alpha"), _item("Charlie")], "ready": [_item("Bravo")]}),
]


def _names(payload):
    out = set()
    for key in ("items", "ready"):
        for it in payload.get(key, []) or []:
            n = str(it.get("food") or "").strip()
            if n:
                out.add(n)
    for p in payload.get("points", []) or []:
        n = str(p.get("label") or "").strip()
        if n:
            out.add(n)
    return out


async def main():
    import core.food_turn as FT
    flag = os.getenv("NUTRITION_ACCURACY_V2", "").lower() in ("1", "true", "yes")
    print(f"\nleave-no-food-behind sweep (flag {'ON' if flag else 'OFF — prod behaviour'})\n")
    print(f"{'case':<48} {'parsed':<7} {'kept':<6} {'dropped'}")
    print("-" * 78)
    total_drops = 0
    dropping_cases = 0
    for label, payload in CASES:
        FT.chat = _chat(payload)
        try:
            out = await FT.run("sweep", _user())
        except Exception as e:
            print(f"{label:<48} ERROR {type(e).__name__}: {str(e)[:30]}")
            continue
        parsed = _names(payload)
        committed = {str(c["input"]["food_name"]).strip()
                     for c in (out.get("tool_calls") or [])}
        text = (out.get("text") or "").lower()
        asked = {n for n in parsed if n.lower() in text}
        accounted = committed | asked
        dropped = parsed - accounted
        total_drops += len(dropped)
        if dropped:
            dropping_cases += 1
        flag_str = ("DROPPED: " + ", ".join(sorted(dropped))) if dropped else "ok"
        print(f"{label:<48} {len(parsed):<7} {len(accounted):<6} {flag_str}")

    print(f"\n{dropping_cases}/{len(CASES)} shapes drop a food; "
          f"{total_drops} foods silently lost across the sweep.")
    print("Invariant violated: a parsed food must be committed or asked, never dropped.")
    return 1 if total_drops else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
