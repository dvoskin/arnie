#!/usr/bin/env python3
"""Reproduce + verify the imperative-add phantom rescue.

Danny 2026-07-21: "add a happy wolf" → "Second Happy Wolf logged" with ZERO tools
fired — a phantom. It only became real after he typed "Not logged or adjusted". The
phantom detector was blind to imperative adds; now it fires and the rescue forces the
real log_food. Run: python scripts/repro_phantom_add.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import simulate_logging_discipline as S
import core.conversation as C
from core.chat_service import run_chat_turn
from db.queries import reload_user

_calls = {"n": 0}


async def _fake_chat(messages, system, tools=True, max_tokens=4096, **kw):
    """1st tools=True call = pass-1 PHANTOM (claims logged, fires nothing).
    2nd = the phantom rescue → actually fire log_food."""
    sh = kw.get("stream_handler")
    if sh:
        await sh("")
    if not tools:
        return {"text": "", "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
    _calls["n"] += 1
    if _calls["n"] == 1:
        # PHANTOM: past-tense success claim, NO tool call.
        return {"text": "Second Happy Wolf logged. You're at 1706 / 2165 calories.",
                "raw_content": [{"type": "text", "text": "Second Happy Wolf logged."}],
                "tool_calls": [], "stop_reason": "end_turn"}
    # Rescue pass: actually log it.
    return {"text": "", "raw_content": [{"type": "text", "text": ""}],
            "tool_calls": [{"name": "log_food", "input": {
                "food_name": "Happy Wolf chocolate chip", "quantity": "1 bar",
                "calories": 110, "protein": 6, "carbs": 12, "fats": 5,
                "confidence": 0.9, "meal_type": "snack", "processing_level": "processed"}}],
            "stop_reason": "tool_use"}


async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512, stream_handler=None):
    t = "Happy Wolf's in, 110 cal. What's next?"
    if stream_handler:
        await stream_handler(t)
    return t


async def main():
    C.chat = _fake_chat
    C.chat_follow_up = _fake_follow_up
    H = S.Harness(); await H.setup(); uid = await H.new_user()
    async with await H.session() as db:
        u = await reload_user(db, uid)
        await run_chat_turn(db, u, "Ok cool and add a happy wolf",
                            platform="ios", schedule_background=False)
        await db.commit()
    rows = await S.db_food_rows(H, uid)
    names = [r.parsed_food_name for r in rows]
    print("=" * 66)
    print('"Ok cool and add a happy wolf" — pass-1 claimed "logged", fired NOTHING')
    print(f"  pass-1 + rescue chat calls: {_calls['n']}  (2 = phantom + rescue)")
    print(f"  DB now: {len(rows)} row(s) = {names}")
    ok = any("happy wolf" in (n or "").lower() for n in names)
    print(f"  VERDICT: {'✅ PASS — rescue forced the real log' if ok else '❌ FAIL — phantom shipped, nothing logged'}")
    print("=" * 66)


if __name__ == "__main__":
    asyncio.run(main())
