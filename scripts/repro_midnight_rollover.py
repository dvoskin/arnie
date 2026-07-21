#!/usr/bin/env python3
"""Reproduce + verify the midnight-rollover clobber (the 12:15am pops-cereal incident).

At the pre-dawn boundary a log lands on YESTERDAY's log (user-tz grace) while a
UTC-resolved path hands the turn a fresh EMPTY new-day log. The day-total guard read
that empty log and "corrected" a real reply ("2146 / 2165") down to "0 / 2165" — a
full day zeroed on screen. A logging tool FIRED but today_log is empty → the guard
must SKIP, not clobber.

Run: python scripts/repro_midnight_rollover.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import simulate_logging_discipline as S
import core.conversation as C
from db.queries import reload_user, get_today_log


async def _fake_chat(messages, system, tools=True, max_tokens=4096, **kw):
    sh = kw.get("stream_handler")
    if not tools:
        # The day-total guard's correction call — if it fires, it CLOBBERS to 0.
        clob = "Pops cereal logged. You're at 0 / 2165 calories today. Protein's at 0 / 180g."
        if sh:
            await sh(clob)
        return {"text": clob, "raw_content": [], "tool_calls": [], "stop_reason": "end_turn"}
    # pass-1: fire log_food (the write lands on YESTERDAY's log — simulated by the
    # mock executor writing nothing to today_log, so today_log stays empty).
    return {"text": "", "raw_content": [{"type": "text", "text": ""}],
            "tool_calls": [{"name": "log_food", "id": "t1", "input": {
                "food_name": "Pops cereal (dry)", "quantity": "2 handfuls",
                "calories": 150, "protein": 2, "carbs": 34, "fats": 1,
                "confidence": 0.7, "meal_type": "snack", "processing_level": "ultra_processed"}}],
            "stop_reason": "tool_use"}


async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512, stream_handler=None):
    # The correct voicing — reads yesterday's log where the write landed.
    t = "Pops cereal logged.|||You're at 2146 / 2165 calories, 189g protein, right at the line."
    if stream_handler:
        await stream_handler(t)
    return t


async def _fake_exec(tool_calls, user, log, db, source_type, **_kw):
    # Simulate the write landing on YESTERDAY's log: return success but DON'T touch
    # today_log (it stays empty — the day-boundary condition).
    return {tc["name"]: "Logged ✅" for tc in (tool_calls or [])}


async def main():
    C.chat = _fake_chat
    C.chat_follow_up = _fake_follow_up
    C.execute_tool_calls = _fake_exec
    H = S.Harness(); await H.setup(); uid = await H.new_user()
    seen = []
    async with await H.session() as db:
        u = await reload_user(db, uid)
        tl = await get_today_log(db, uid, u.timezone)   # fresh, EMPTY today_log
        turn = await C.run_turn(
            u, db, messages=[{"role": "user", "content": "Had 2 handfuls of pops cereal"}],
            system="SYS", platform="ios", in_onboarding=False, was_onboarding=False,
            today_log=tl, on_text_bubble=lambda b: (seen.append(b), asyncio.sleep(0))[1])
        await db.commit()
    reply = " ".join(seen) if seen else " ".join(turn.response.bubbles)
    print("=" * 66)
    print("12:15am log: fired log_food, today_log EMPTY (write landed on yesterday)")
    print(f"  reply bubbles: {seen}")
    zeroed = "0 / 2165" in reply or "0/2165" in reply
    kept = "2146" in reply
    ok = kept and not zeroed
    print(f"  states real total (2146): {kept}  |  zeroed to 0/2165: {zeroed}")
    print(f"  VERDICT: {'✅ PASS — guard did not clobber a real day to 0' if ok else '❌ FAIL — day zeroed'}")
    print("=" * 66)


if __name__ == "__main__":
    asyncio.run(main())
