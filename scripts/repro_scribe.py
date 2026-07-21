#!/usr/bin/env python3
"""Reproduce + verify the scribe end-to-end: pass-1 drops an item, the scribe names it,
the self-heal logs it — regardless of what pass-1 emitted.

Chaya 2026-07-21: "1 egg plus 3/4 cup of egg whites" → only the egg logged. Here pass-1
(mocked) logs ONLY the egg; the scribe's parallel Haiku extraction finds 'egg whites'
missing and the self-heal retry logs it. The extraction is a REAL Haiku call (core.llm),
only pass-1/self-heal are mocked (core.conversation.chat).

Run: python scripts/repro_scribe.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import simulate_logging_discipline as S
import core.conversation as C
from core.chat_service import run_chat_turn
from db.queries import reload_user

_EGG = {"name": "log_food", "input": {"food_name": "Egg (whole)", "quantity": "1 egg",
        "calories": 70, "protein": 6, "carbs": 0, "fats": 5, "confidence": 0.9,
        "meal_type": "breakfast", "processing_level": "whole"}}
_WHITES = {"name": "log_food", "input": {"food_name": "Egg whites", "quantity": "3/4 cup",
        "calories": 94, "protein": 20, "carbs": 1, "fats": 0, "confidence": 0.9,
        "meal_type": "breakfast", "processing_level": "whole"}}
_n = {"i": 0}


async def _fake_chat(messages, system, tools=True, max_tokens=4096, **kw):
    """pass-1 (1st tools call): logs ONLY the egg (drops the whites).
    self-heal (2nd): logs BOTH — the model, told exactly what's missing, complies."""
    sh = kw.get("stream_handler")
    if sh:
        await sh("")
    if not tools:
        return {"text": "", "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
    _n["i"] += 1
    calls = [_EGG] if _n["i"] == 1 else [_EGG, _WHITES]
    return {"text": "", "raw_content": [{"type": "text", "text": ""}],
            "tool_calls": calls, "stop_reason": "tool_use"}


async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512, stream_handler=None):
    t = "Egg and egg whites in. Solid protein start."
    if stream_handler:
        await stream_handler(t)
    return t


async def main():
    C.chat = _fake_chat
    C.chat_follow_up = _fake_follow_up   # scribe uses core.llm.chat (real Haiku), untouched
    H = S.Harness(); await H.setup(); uid = await H.new_user()
    async with await H.session() as db:
        u = await reload_user(db, uid)
        await run_chat_turn(db, u, "1 egg plus 3/4 cup of egg whites",
                            platform="ios", schedule_background=False)
        await db.commit()
    rows = await S.db_food_rows(H, uid)
    names = [r.parsed_food_name for r in rows]
    print("=" * 66)
    print('"1 egg plus 3/4 cup of egg whites" — pass-1 logged ONLY the egg')
    print(f"  pass-1 + self-heal chat calls: {_n['i']}  (2 = drop + scribe self-heal)")
    print(f"  DB now: {names}")
    has_egg = any("egg" in (n or "").lower() and "white" not in (n or "").lower() for n in names)
    has_whites = any("white" in (n or "").lower() for n in names)
    ok = has_egg and has_whites
    print(f"  egg logged: {has_egg}  egg whites logged: {has_whites}")
    print(f"  VERDICT: {'✅ PASS — scribe caught the dropped item' if ok else '❌ FAIL — item still dropped'}")
    print("=" * 66)


if __name__ == "__main__":
    asyncio.run(main())
