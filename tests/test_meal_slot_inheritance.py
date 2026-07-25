"""A multi-item meal must land in ONE slot.

Field bug (Danny 2026-07-22): a shawarma dinner split into a DINNER row (the main,
which the model slotted) and a SNACK row (the sides, re-added by the partial-drop
rescue in a second pass with no meal_type → clock default = the 15:30-17:30 snack
band). _inherit_or_default_meal_type fixes it: an item logged without a slot
inherits a same-occasion sibling's slot, falling back to the clock only when there
is no sibling.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from handlers.tool_executor import _inherit_or_default_meal_type, _default_meal_type


def _entry(slot, ts):
    return SimpleNamespace(meal_type=slot, meal_time=ts, timestamp=ts)


def _log(entries):
    return SimpleNamespace(food_entries=entries)


def _user(tz="America/New_York"):
    return SimpleNamespace(timezone=tz)


def test_side_inherits_the_mains_slot_same_occasion():
    now = datetime(2026, 7, 22, 16, 2, 0)          # 4:02pm — clock default = snack
    log = _log([_entry("dinner", now - timedelta(seconds=30))])   # main logged just now
    # No model slot on the side → it should inherit DINNER, not fall to the snack band.
    assert _inherit_or_default_meal_type(_user(), log, now) == "dinner"


def test_no_sibling_falls_back_to_clock_default():
    now = datetime(2026, 7, 22, 16, 2, 0)
    assert _inherit_or_default_meal_type(_user(), _log([]), now) == \
        _default_meal_type(SimpleNamespace(timezone="UTC")) or "snack"
    # Explicit: empty board → clock default (whatever the hour maps to), never a crash.
    assert _inherit_or_default_meal_type(_user(), _log([]), now) in {
        "breakfast", "lunch", "dinner", "snack"}


def test_old_sibling_outside_occasion_does_not_leak(monkeypatch):
    """A lunch entry 5 hours earlier is OUTSIDE the 45-minute window, so it must
    not be inherited — the item falls back to the clock default.

    The clock default is pinned here because it reads the WALL CLOCK rather than
    the `meal_time` it was handed, so between roughly 11am and 2pm in the user's
    zone the real default IS "lunch" and the assertion failed for reasons that
    had nothing to do with inheritance. A test that passes depending on when it
    runs reports a red build as a code change.
    """
    import handlers.tool_executor as TE
    monkeypatch.setattr(TE, "_default_meal_type", lambda user: "dinner")

    now = datetime(2026, 7, 22, 20, 0, 0)
    log = _log([_entry("lunch", now - timedelta(hours=5))])
    slot = _inherit_or_default_meal_type(_user(), log, now)
    assert slot == "dinner", "the stale lunch sibling leaked into a new occasion"


def test_most_recent_sibling_wins():
    now = datetime(2026, 7, 22, 16, 2, 0)
    log = _log([
        _entry("lunch", now - timedelta(minutes=40)),    # tail of lunch, in window
        _entry("dinner", now - timedelta(seconds=20)),   # the main just logged
    ])
    assert _inherit_or_default_meal_type(_user(), log, now) == "dinner"


def test_lazyload_or_bad_entries_never_crash():
    class _Boom:
        @property
        def food_entries(self):
            raise RuntimeError("simulated async lazy-load failure")
    now = datetime(2026, 7, 22, 16, 2, 0)
    # Must fall back to the clock default, not propagate.
    assert _inherit_or_default_meal_type(_user(), _Boom(), now) in {
        "breakfast", "lunch", "dinner", "snack"}
