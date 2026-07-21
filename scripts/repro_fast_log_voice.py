"""Proof: the fast clean log voice — one reply, sub-second, no ~ / no em dash.

Runs the three screenshot scenarios (Twix, corn+chips, Quest chips) through
core.log_voice.voice_log against the real model and prints output + latency.
"""
import asyncio
import time
from types import SimpleNamespace

from core.log_voice import voice_log, build_log_facts


def _user(cal_t=2165, pro_t=180, goal="recomp", tz="America/New_York"):
    return SimpleNamespace(
        preferences=SimpleNamespace(calorie_target=cal_t, protein_target=pro_t),
        primary_goal=goal, timezone=tz)


SCENARIOS = [
    ("Twix bar",
     [{"name": "log_food", "input": {"food_name": "Twix bar"}}],
     {"log_food": "Logged: Twix bar, 250 cal, 2g protein"},
     SimpleNamespace(total_calories=1527, total_protein=91)),
    ("corn on the cob and corn chips",
     [{"name": "log_food", "input": {"food_name": "corn on the cob"}},
      {"name": "log_food", "input": {"food_name": "corn chips"}}],
     {"log_food": "Logged: corn on the cob 100 cal 3g protein; corn chips 140 cal 2g protein"},
     SimpleNamespace(total_calories=240, total_protein=5)),
    ("Quest chips full bag",
     [{"name": "log_food", "input": {"food_name": "Quest Tortilla Chips, Spicy Sweet Chili"}}],
     {"log_food": "Logged: Quest Tortilla Chips Spicy Sweet Chili, 140 cal, 19g protein"},
     SimpleNamespace(total_calories=1667, total_protein=110)),
]


async def main():
    for label, tcs, trs, log in SCENARIOS:
        user = _user()
        t0 = time.monotonic()
        out = await voice_log(tcs, trs, log, user)
        dt = time.monotonic() - t0
        bubbles = (out or "").split("|||")
        print(f"\n=== {label!r}   ({dt:.2f}s · {len(bubbles)} bubble(s)) ===")
        for b in bubbles:
            print("   •", b)
        assert out, "EMPTY reply"
        assert "~" not in out, "tilde leaked"
        assert "—" not in out and "–" not in out, "em/en dash leaked"
        assert len(bubbles) <= 2, "more than 2 bubbles"
    print("\nALL PASS: one reply, <=2 bubbles, no ~ / no em dash.")


if __name__ == "__main__":
    asyncio.run(main())
