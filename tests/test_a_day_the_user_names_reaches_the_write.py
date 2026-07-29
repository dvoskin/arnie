"""Food reported for another day is written to that day.

Every piece of this existed except one. `update_food_entry` has taken a `date`
since move-to-date landed, `_update_call` carries it, `log_food`'s executor
resolves it through `_resolve_log` — which gets-or-creates that day's log
before the write — and the receipt already renders "Moved the entry to another
day". Only `_log_call` dropped it.

So the lane could RE-DATE a row it had already written and could not WRITE one
to the day the user named. Reporting yesterday's dinner had exactly one
available outcome: today's board.

Production, 2026-07-29 11:05, u=3 — "Вареная индейка была вчера и в салате
курица" (the boiled turkey was yesterday). The turn wrote rice and a Caesar
salad to TODAY, said in its own reply that the turkey was excluded "так как она
была вчера" — so the day had been understood — and on the next turn deleted
both rows rather than moving them. 07-28 ended with no Caesar and no turkey;
07-29 ended with zero entries. The food exists on no day.

A delete stood in for a re-parent the vocabulary already contained.
"""
import core.food_turn as FT


def _inp(call):
    """The builders return {name, input}; the write reads `input`."""
    return (call or {}).get("input") or {}


def _item(**kw):
    base = {"food": "Caesar salad", "amount": 1, "unit": "порция"}
    base.update(kw)
    return base


# ── the day reaches the write ────────────────────────────────────────────────

def test_a_logged_item_carries_the_day_it_was_eaten():
    call = _inp(FT._log_call(_item(date="yesterday")))
    assert call["date"] == "yesterday"


def test_an_explicit_date_is_carried_verbatim():
    call = _inp(FT._log_call(_item(date="2026-07-28")))
    assert call["date"] == "2026-07-28"


def test_an_item_with_no_day_carries_none():
    """Absent, not empty — the executor reads presence to pick the target log,
    and an empty string would send every ordinary log through date parsing."""
    assert "date" not in _inp(FT._log_call(_item()))


def test_a_blank_day_is_not_a_day():
    assert "date" not in _inp(FT._log_call(_item(date="   ")))


# ── one message may span days ────────────────────────────────────────────────

def test_two_items_from_two_days_keep_their_own_days():
    """The production message reported yesterday's turkey alongside food from
    today. A day is a property of the item, not of the turn."""
    yesterday = _inp(FT._log_call(_item(food="Boiled turkey", date="yesterday")))
    today = _inp(FT._log_call(_item(food="Rice")))
    assert yesterday["date"] == "yesterday"
    assert "date" not in today


# ── the correction path keeps working ────────────────────────────────────────

def test_a_correction_can_still_move_an_existing_row():
    board = {7: {"cal": 420.0, "name": "Boiled turkey"}}
    call = _inp(FT._update_call({"entry_id": 7, "date": "yesterday"}, board))
    assert call["date"] == "yesterday"
    assert call["entry_id"] == 7
