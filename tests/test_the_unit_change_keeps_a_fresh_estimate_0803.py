"""A unit correction may invalidate a stale figure. It may not destroy a fresh one.

`_revalidate_after_answer` dropped `calories`/`protein`/`carbs`/`fats`/`grams`
from the op the moment a unit changed, above every branch that follows. Its
comment promised the gap would be filled: "the enrichment path recomputes from
the corrected unit, and a missing key is a recompute where a stale one is a
wrong answer that looks settled."

Nothing recomputes. `_log_call` omits absent keys, `analyze` receives
`llm_cal=None` and produces 0, the zero-calorie refusal sets `source="estimate"`
— which is the gate that OPENS the web enrich lane — and a fabricated total
commits with the macros then force-fit to match it.

Prod 2026-08-03, the Cali Roll:

    interpreter_output  ... "Cali Roll", amount 8, unit "piece", calories 283
    unit_correction     'Cali Roll' roll (6-8 pieces)->piece
    zero-calorie read for 'Cali Roll' and no mass to price it
    web meal enrich: 'Cali Roll' 0->400 cal (conf=high)
    macro_reconcile     carbs 30.0->37.6, fat 15.0->18.8 to match the calories

Three of the four exits from that loop COMMIT. On those paths the drop was not
invalidating a stale number, it was deleting the only reasoned one — and the 283
it deleted was closer to the truth than the 400 that replaced it.

So the drop is now conditional: a STALE estimate (the interpreter handing back
the figure it already gave) is still worthless and still goes; a FRESH one is the
best figure anyone has for the corrected unit and survives. On the ASK path it
still always goes — the op rides the question rather than committing.
"""
import pytest

import core.food_turn as FT


def _prior(food, unit, calories):
    """The pending-question payload as `core/conversation.py` stashes it — the
    prior INTERPRETATION, which is what the correction is compared against."""
    return {"items": [{"food": food, "unit": unit, "calories": calories}]}


def _op(food, unit, amount, calories, **kw):
    return {"food": food, "unit": unit, "amount": amount,
            "calories": calories, "protein": 8, "carbs": 54, "fats": 4, **kw}


def _revalidate(ops, prior, mode="moderate", message="actually they were pieces"):
    return FT._revalidate_after_answer(ops, prior, message, mode=mode)


# ── the defect ────────────────────────────────────────────────────────────────

def test_a_fresh_estimate_survives_a_compatible_unit_change():
    """The Cali Roll. "roll (6-8 pieces)" -> "piece" is compatible, and 283 is a
    NEW figure for the new unit — the interpreter's own reasoning about what 8
    pieces cost."""
    op = _op("Cali Roll", "piece", 8, 283)
    out = _revalidate([("log", op)], _prior("Cali Roll", "roll (6-8 pieces)", 460))
    assert out is None, "a compatible change with a fresh estimate should commit"
    assert op.get("calories") == 283, (
        "the interpreter's reasoned figure for the corrected unit was destroyed; "
        "downstream sees no calories, prices 0, and the web lane invents a total")


def test_a_repeated_figure_is_still_invalidated():
    """The case the drop exists for: the interpreter hands back the number it
    already gave, unrevised, across a change that means a different amount of
    food. That figure is worthless and must not be committed."""
    op = _op("Cali Roll", "piece", 8, 460)
    _revalidate([("log", op)], _prior("Cali Roll", "roll (6-8 pieces)", 460))
    assert op.get("calories") is None, (
        "a repeated estimate across a unit change is the previous answer, "
        "not a re-estimate")


def test_the_ask_path_still_invalidates():
    """When the correction cannot be settled and becomes a question, the op
    rides the question. A figure derived from the OLD unit surviving onto that
    item is exactly the wrong-answer-that-looks-settled the drop was for."""
    op = _op("Chicken", "piece", 3, 300)
    out = _revalidate([("log", op)], _prior("Chicken", "kg", 300), mode="strict")
    if out is not None and out.get("action") == "ask":
        assert op.get("calories") is None, "the asked item kept a stale figure"
    else:                                   # settled another way; not this test
        pytest.skip("this pair did not reach the ask path")


# ── it must not change anything else ──────────────────────────────────────────

def test_an_unchanged_unit_is_left_entirely_alone():
    op = _op("Cali Roll", "piece", 8, 283)
    out = _revalidate([("log", op)], _prior("Cali Roll", "piece", 283))
    assert out is None
    assert op["calories"] == 283 and op["protein"] == 8


def test_a_food_with_no_prior_is_left_alone():
    op = _op("Miso soup", "cup", 1, 40)
    out = _revalidate([("log", op)], _prior("Cali Roll", "piece", 283))
    assert out is None
    assert op["calories"] == 40
