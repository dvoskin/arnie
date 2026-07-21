#!/usr/bin/env python3
"""Reproduce + verify the 2-item reference-drop end to end.

Turkey+rice incident (user 26, 2026-07-20): a stated plan "gonna have 150g turkey
and 100g rice" (not logged — correct), then "Just had that" logged ONLY turkey and
dropped rice. The gate saw no items in "just had that", so no completeness guard
fired.

This seeds the plan turn, sends "Just had that", and mocks pass-1 to log ONLY the
turkey (the bug). With reference resolution + the undercount self-heal, the retry
must log the rice too. Asserts BOTH land. Run: python scripts/repro_reference_drop.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import simulate_logging_discipline as S
import core.conversation as C
from core.chat_service import run_chat_turn
from db.queries import reload_user, log_conversation

_TURKEY = {"name": "log_food", "input": {
    "food_name": "Ground turkey, 96% lean", "quantity": "150g", "calories": 213,
    "protein": 29, "carbs": 0, "fats": 11, "confidence": 0.9,
    "meal_type": "dinner", "processing_level": "whole"}}
_RICE = {"name": "log_food", "input": {
    "food_name": "White rice, cooked", "quantity": "100g", "calories": 130,
    "protein": 3, "carbs": 28, "fats": 0, "confidence": 0.9,
    "meal_type": "dinner", "processing_level": "whole"}}

_calls = {"n": 0}


async def _fake_chat(messages, system, tools=True, max_tokens=4096, **kw):
    """1st tools=True call = pass-1 (BUG: logs turkey only). 2nd = the undercount
    self-heal retry (logs turkey + rice — the real extraction). tools=False = a
    correction call, return empty (no correction needed here)."""
    sh = kw.get("stream_handler")
    if sh:
        await sh("")
    if not tools:
        return {"text": "", "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
    _calls["n"] += 1
    if _calls["n"] == 1:
        calls = [_TURKEY]                 # pass-1 drops the rice
    else:
        calls = [_TURKEY, _RICE]          # self-heal finishes the list
    return {"text": "", "raw_content": [{"type": "text", "text": ""}],
            "tool_calls": calls, "stop_reason": "tool_use"}


async def _fake_follow_up(messages, raw, tool_calls, tool_results, system,
                          max_tokens=512, stream_handler=None):
    txt = "Turkey and rice are in, 343 calories total. What's next?"
    if stream_handler:
        await stream_handler(txt)
    return txt


async def main():
    C.chat = _fake_chat
    C.chat_follow_up = _fake_follow_up
    H = S.Harness(); await H.setup(); uid = await H.new_user()

    # Seed the PLAN turn (assistant did NOT log it — "ping me when it's on the plate").
    async with await H.session() as db:
        await log_conversation(
            db, uid, "Gonna have like 150g turkey and 100g of rice for dinner",
            "Solid plan. Ping me when it's on the plate and I'll log it.",
            source_type="ios", skills_fired=None, platform="ios")
        await db.commit()

    async with await H.session() as db:
        u = await reload_user(db, uid)
        await run_chat_turn(db, u, "Just had that", platform="ios",
                            schedule_background=False)
        await db.commit()

    rows = await S.db_food_rows(H, uid)
    names = [r.parsed_food_name for r in rows]
    total = round(sum(float(r.calories or 0) for r in rows))
    print("=" * 68)
    print(f'"Just had that" (ref to 150g turkey + 100g rice plan):')
    print(f"  pass-1 chat calls: {_calls['n']}  (1 pass-1 + 1 self-heal retry expected)")
    print(f"  DB now: {len(rows)} rows = {names}  ({total} cal)")
    has_turkey = any("turkey" in n.lower() for n in names)
    has_rice = any("rice" in n.lower() for n in names)
    ok = has_turkey and has_rice
    print(f"  turkey logged: {has_turkey}  rice logged: {has_rice}")
    print(f"  VERDICT: {'✅ PASS — reference resolved, rice no longer dropped' if ok else '❌ FAIL — rice dropped'}")
    print("=" * 68)


if __name__ == "__main__":
    asyncio.run(main())
