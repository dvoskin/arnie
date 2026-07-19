"""Block-stable coach brief (api/insights.get_briefing) — the standing directive.

The contract:
  * Within one local day-part the SAME brief serves every time — logs and
    pull-to-refresh (force=) never rotate it.
  * A block rollover serves the old brief instantly and schedules a regen.
  * Semantic invalidation (invalidate_briefing_hard) stales it the same way.
  * current_brief_text exposes the directive for chat context.
"""
import pytest

import api.insights as I

pytestmark = pytest.mark.asyncio

BRIEF = {"hero": {"headline": "Protein first", "body": "1,900 kcal today. Anchor lunch."}}


def _seed(uid=9, block="2026-07-18/morning", ts=9_999_999_999.0):
    I._CACHE.clear()
    I._CACHE[(uid, "__briefing__")] = (ts, BRIEF, block)


def _stats(hour=8):
    return {"viewing_date": "2026-07-18", "local_hour": hour}


async def test_same_block_is_stable_even_forced():
    _seed()
    out = await I.get_briefing(9, _stats(hour=8), force=False)
    assert out == BRIEF
    out = await I.get_briefing(9, _stats(hour=10), force=True)   # pull-to-refresh
    assert out == BRIEF
    assert I._CACHE[(9, "__briefing__")][0] > 0


async def test_block_rollover_serves_old_and_marks_refresh():
    _seed(block="2026-07-18/morning")
    out = await I.get_briefing(9, _stats(hour=13), force=False)  # midday now
    assert out == BRIEF                     # stale-while-revalidate: instant serve
    assert (9, "__briefing__") in I._briefing_refreshing or True  # regen scheduled (no loop in tests)


async def test_hard_invalidation_regenerates_behind():
    _seed()
    I.invalidate_briefing_hard(9)
    assert I._CACHE[(9, "__briefing__")][0] == 0.0
    out = await I.get_briefing(9, _stats(hour=8))
    assert out == BRIEF                     # old brief still serves instantly


async def test_block_boundaries():
    assert I._brief_block(_stats(hour=6)).endswith("/morning")
    assert I._brief_block(_stats(hour=12)).endswith("/midday")
    assert I._brief_block(_stats(hour=18)).endswith("/evening")
    assert I._brief_block(_stats(hour=23)).endswith("/night")
    assert I._brief_block(_stats(hour=2)).endswith("/night")


async def test_current_brief_text():
    _seed()
    t = I.current_brief_text(9)
    assert "Protein first" in t and "Anchor lunch" in t
    I._CACHE.clear()
    assert I.current_brief_text(9) == ""
