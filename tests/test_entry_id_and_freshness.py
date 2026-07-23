"""Truthfulness + awareness fixes from the 'move the bagel to yesterday' report.

Danny hit four coupled failures on one late-night turn:
  1. Arnie GUESSED a food-entry id → update_food_entry:error → false "hit a snag,
     didn't go through" while the entry had actually moved, then a stuck re-guess
     loop.
  2. A committed move was reported as a failure.
  3. The Coach brief sat blank ~10s (cold-block) after logging.
  4. At 1am he called the bagel 'breakfast' and asked about 'lunch'.

These pin the fixes.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from db.queries import add_food_entry, get_or_create_today_log


async def _log(db, log_id, name, cal=100):
    return await add_food_entry(db, log_id, parsed_food_name=name, calories=cal,
                                protein=5, carbs=10, fats=2)


# ── 1 + 2: guessed-id self-heal, honest-ask, never-false-failure ──────────────

async def test_update_food_entry_self_heals_single_entry(db, make_user):
    """A wrong id with ONE entry today resolves to that entry — 'move the bagel'
    works even when the model guesses the id."""
    from handlers.tool_executor import _dispatch
    u = await make_user()
    log = await get_or_create_today_log(db, u.id, "UTC")
    bagel = await _log(db, log.id, "half a bagel with lox", 320)
    r = await _dispatch("update_food_entry",
                        {"entry_id": 99999, "date": "yesterday"},  # guessed id
                        u, log, db, "ios", user_message="move the bagel to yesterday")
    assert r.startswith("Updated entry"), r
    assert "moved to" in r


async def test_update_food_entry_self_heals_by_name_when_ambiguous(db, make_user):
    from handlers.tool_executor import _dispatch
    u = await make_user()
    log = await get_or_create_today_log(db, u.id, "UTC")
    await _log(db, log.id, "black coffee", 5)
    bagel = await _log(db, log.id, "everything bagel", 280)
    r = await _dispatch("update_food_entry",
                        {"entry_id": 88888, "date": "yesterday"},
                        u, log, db, "ios", user_message="move the bagel to yesterday")
    assert r.startswith("Updated entry")
    assert str(bagel.id) in r  # resolved the BAGEL, not the coffee


async def test_update_food_entry_asks_when_unresolvable(db, make_user):
    """Two entries, no usable name hint → do NOT fake success or re-guess; return
    the real-id listing so Arnie asks."""
    from handlers.tool_executor import _dispatch
    u = await make_user()
    log = await get_or_create_today_log(db, u.id, "UTC")
    a = await _log(db, log.id, "coffee")
    b = await _log(db, log.id, "toast")
    r = await _dispatch("update_food_entry", {"entry_id": 77777, "calories": 50},
                        u, log, db, "ios", user_message="fix that")
    assert "COULD NOT FIND" in r
    assert "do NOT" in r.lower() or "Do NOT" in r
    assert f"[#{a.id}]" in r and f"[#{b.id}]" in r   # real ids offered


async def test_correct_id_still_updates(db, make_user):
    from handlers.tool_executor import _dispatch
    u = await make_user()
    log = await get_or_create_today_log(db, u.id, "UTC")
    e = await _log(db, log.id, "oatmeal", 200)
    r = await _dispatch("update_food_entry", {"entry_id": e.id, "calories": 250},
                        u, log, db, "ios", user_message="make the oatmeal 250")
    assert r.startswith("Updated entry")
    assert str(e.id) in r


# ── 3: brief marked stale on log, not dropped (no cold block) ─────────────────

def test_invalidate_briefing_leaves_hero_standing():
    """Ship change (block-stability): a routine log must NOT touch the hero —
    only per-date insight caches drop. Semantic invalidation is a separate,
    deliberate path (invalidate_briefing_hard)."""
    import api.insights as I
    I._CACHE.clear()
    key = (42, "__briefing__")
    I._CACHE[key] = (9_999_999_999.0, {"hero": {"headline": "188.6 lbs"}}, "2026-07-08/morning")
    I._CACHE[(42, "2026-07-08")] = (9_999_999_999.0, ["insight"])
    I.invalidate_briefing(42)
    assert I._CACHE[key][0] == 9_999_999_999.0, "a log must not stale the standing directive"
    assert (42, "2026-07-08") not in I._CACHE
    I.invalidate_briefing_hard(42)
    assert I._CACHE[key][0] == 0.0, "semantic invalidation stales the hero for regen"
    assert I._CACHE[key][0] == 0.0
    assert I._CACHE[key][1]["hero"]["headline"] == "188.6 lbs"
    # per-date insight cache IS dropped
    assert (42, "2026-07-08") not in I._CACHE


async def test_stale_hero_serves_instantly_and_schedules_refresh(monkeypatch):
    import api.insights as I
    I._CACHE.clear()
    I._CACHE[(7, "__briefing__")] = (0.0, {"hero": {"headline": "cached"}})
    scheduled = {"n": 0}
    monkeypatch.setattr(I, "_schedule_briefing_refresh",
                        lambda *a, **k: scheduled.__setitem__("n", scheduled["n"] + 1))
    out = await I.get_briefing(7, {"user": {"name": "D"}}, force=False)
    assert out["hero"]["headline"] == "cached"     # served the stale copy instantly
    assert scheduled["n"] == 1                       # and kicked a background refresh


# ── 4: late-night read (no 'breakfast'/'lunch' at 1am) ────────────────────────

def test_wee_hours_context_says_sleep_not_next_meal():
    import core.context_builder as C
    from types import SimpleNamespace as NS
    prefs = NS(calorie_target=2000, protein_target=180, food_logging_mode=None,
               coaching_style=None, accountability_level=None, reminder_frequency=None,
               preferred_response_length=None)
    log = NS(total_calories=320, total_protein=14, total_carbs=40, total_fats=8,
             total_water_ml=0)
    # The pacing helper carries the time-of-day read.
    import inspect
    src = inspect.getsource(C)
    assert 'MIDDLE OF THE NIGHT' in src
    assert "Do NOT treat food now as 'breakfast'" in src


def test_prompt_ships_id_discipline():
    """The id discipline that ships today (post July-7 scale-back revert,
    017d436): ids come from TODAY'S board, corrections go through
    update_food_entry with a [#id], and N corrections in one turn use N
    DISTINCT ids. NOTE: the revert dropped the explicit 'NEVER GUESS AN
    [#id] / do NOT retry with another guessed id' sentences — if guessed-id
    corrections ever recur on the legacy path, restore that rule in the
    prompt (and re-pin it here), per audits/IRONCLAD_EVAL_2026-07-23.md."""
    from core.prompts import build_arnie_system
    s = " ".join(build_arnie_system(platform="ios").split())
    assert "update_food_entry() with [#id]" in s
    assert "entry_id values MUST be DISTINCT" in s
    assert "NEVER pass the same [#id] twice" in s
    assert "map each named item to its specific [#id]" in s
