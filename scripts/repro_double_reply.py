#!/usr/bin/env python3
"""Reproduce the double-reply / phantom-total leak deterministically.

The turkey+rice incident (user 26, 2026-07-20): the follow-up voiced a total that
counted an unlogged item ("1698"), it streamed live, and a correction ("1566")
shipped on top — TWO replies. The stored reply was the correct one; the phantom
leaked because streaming can't be un-sent.

This mocks pass-1 (fires log_food for ONE item) and chat_follow_up (streams a
PHANTOM higher total), then captures EVERY on_text_bubble the user would see.
No network, no real model. Run: python scripts/repro_double_reply.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import simulate_logging_discipline as S
import core.conversation as C
from core.chat_service import run_chat_turn
from db.queries import reload_user


# The phantom the follow-up voices: a total (1698) HIGHER than the DB will hold
# after only the turkey (≈213) logs. Bubbles are ||| delimited, as the model emits.
PHANTOM_FOLLOWUP = (
    "Turkey and rice are in, 150g turkey and 100g rice, about 345 calories.|||"
    "That puts you at 1698 / 2165 calories, 167g protein, 467 left.|||"
    "One Barebells closes it. Cardio done today?"
)


async def _fake_chat(messages, system, tools=True, max_tokens=4096, **kw):
    """tools=True  → pass-1: fire log_food for the turkey ONLY (forces a follow-up).
    tools=False → the day-total guard's correction call: voice the REAL total."""
    sh = kw.get("stream_handler")
    if not tools:
        # The day-total truth guard regenerates a corrected reply (tools=False).
        # It must voice the DB total (213), not the phantom. Emulate a good fix.
        corrected = "Turkey's in. You're at 213 / 2165 calories today, plenty left."
        if sh:
            await sh(corrected)
        return {"text": corrected, "raw_content": [], "tool_calls": [],
                "stop_reason": "end_turn"}
    if sh:
        await sh("")  # nothing streamed in pass-1
    return {
        "text": "",
        "raw_content": [{"type": "text", "text": ""}],
        "tool_calls": [{
            "name": "log_food",
            "input": {"food_name": "Ground turkey, 96% lean, pan-cooked",
                      "quantity": "150g", "calories": 213, "protein": 29,
                      "carbs": 0, "fats": 11, "confidence": 0.9,
                      "meal_type": "dinner", "processing_level": "whole"},
        }],
        "stop_reason": "tool_use",
    }


# A follow-up with the CORRECT total — the happy path must still ship ONCE, clean.
CORRECT_FOLLOWUP = (
    "Turkey's in, 150g at about 213 calories.|||"
    "You're at 213 / 2165 calories today, plenty of room left.|||"
    "Protein anchor's down. What's next?"
)


def _mk_follow_up(text):
    async def _f(messages, raw, tool_calls, tool_results, system,
                 max_tokens=512, stream_handler=None):
        if stream_handler:
            await stream_handler(text)
        return text
    return _f


async def _run_case(label, followup_text):
    C.chat = _fake_chat
    C.chat_follow_up = _mk_follow_up(followup_text)
    H = S.Harness(); await H.setup(); uid = await H.new_user()
    seen = []
    async with await H.session() as db:
        u = await reload_user(db, uid)
        tr = await run_chat_turn(
            db, u, "Just had 150g of turkey",
            platform="ios", schedule_background=False,
            on_text_bubble=lambda b: (seen.append(b), asyncio.sleep(0))[1],
        )
        await db.commit()
    rows = await S.db_food_rows(H, uid)
    db_total = round(sum(float(r.calories or 0) for r in rows))
    print("=" * 70)
    print(f"CASE: {label}   (DB real total = {db_total} cal)")
    print(f"BUBBLES the user SAW ({len(seen)}):")
    for i, b in enumerate(seen, 1):
        print(f"   {i}. {b!r}")
    import re as _re
    phantom = any("1698" in b for b in seen)
    correct = any(str(db_total) in b for b in seen)
    # Double-REPLY signature = the running DAY TOTAL ("N / 2165") stated more than
    # once (a phantom voicing + a correction). One coherent reply states it once.
    day_totals = [m.group(0) for b in seen for m in _re.finditer(r"\d[\d,]*\s*/\s*2165", b)]
    dupe = len(day_totals) > 1
    ok = (not phantom) and correct and not dupe
    print(f"  phantom shown: {phantom} (want False) | correct total shown: {correct} (want True) "
          f"| day-total voicings: {len(day_totals)} (want 1, >1 = double-reply)")
    print(f"  VERDICT: {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


async def main():
    r1 = await _run_case("PHANTOM total (1698 vs DB) — must correct to ONE reply", PHANTOM_FOLLOWUP)
    r2 = await _run_case("CORRECT total — happy path must ship ONCE, no dupe", CORRECT_FOLLOWUP)
    print("=" * 70)
    print(f"OVERALL: {'✅ ALL PASS' if r1 and r2 else '❌ FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
