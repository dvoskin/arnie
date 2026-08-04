"""The first mutation-critical migration, in shadow: writes unchanged.

`_undeferred`'s fuzzy claim loop is the top of the consequence audit — 8
mutation-targeting hits, and its own neighbouring comment says a wrong match
across turns is "DELETING a row the user reported". So it is migrated first,
and it is migrated in shadow: an id-based reconciliation runs BESIDE the live
name match, the disagreement is logged, and the live answer is what gets
returned.

Every test here asserts the live behaviour is untouched. That is the property
that makes this reversible.
"""
import logging

import pytest

from core.food_turn import (_calls_for_ready, _item_id_of, _orphan_calls,
                            _undeferred)


def _c(name):
    return {"name": "log_food", "input": {"food_name": name}}


def _names(calls):
    return [c["input"]["food_name"] for c in calls]


# ── ids are assigned once, where the item is built ───────────────────────────

def test_held_calls_carry_a_stable_id():
    calls = _calls_for_ready([
        {"food": "Rice", "calories": 200, "amount": 1, "unit": "cup"},
        {"food": "Corn", "calories": 90, "amount": 1, "unit": "ear"}])
    assert [_item_id_of(c) for c in calls] == ["ready:0", "ready:1"]


def test_orphans_get_their_own_namespace():
    """Orphans come from `items` minus ready/points, so they are DIFFERENT
    foods from the ready ones by construction. Reusing "ready:N" would give two
    distinct foods the same id, which is worse than giving them none — and
    `_orphan_calls` delegates to `_calls_for_ready`, so it very nearly did."""
    ready = _calls_for_ready([
        {"food": "Rice", "calories": 200, "amount": 1, "unit": "cup"}])
    orphan = _orphan_calls({"items": [
        {"food": "Mayo", "calories": 90, "amount": 1, "unit": "tbsp"}],
        "ready": [], "points": []})
    ids = [_item_id_of(c) for c in ready + orphan]
    assert ids == ["ready:0", "orphan:0"]
    assert len(ids) == len(set(ids)), "two foods must never share an id"


def test_an_id_is_never_minted_downstream():
    """`_item_id_of` READS. The failure being measured is identity re-derived
    downstream from a string; a shadow that invents the id it is testing tests
    itself."""
    assert _item_id_of({"name": "log_food", "input": {"food_name": "Rice"}}) == ""
    assert _item_id_of(None) == ""
    assert _item_id_of("not a dict") == ""


# ── the live answer is unchanged ─────────────────────────────────────────────

@pytest.mark.parametrize("held,plan,expected", [
    ([_c("Turkey"), _c("Corn")], [_c("Turkey")], ["Corn"]),
    ([_c("White rice")], [_c("White rice, cooked")], []),
    ([_c("Orange"), _c("Orange juice")], [_c("Orange juice")], ["Orange"]),
    ([_c("Rice"), _c("Rice cakes")], [], ["Rice", "Rice cakes"]),
    ([_c("Corn"), _c("Corn")], [], ["Corn"]),
])
def test_the_shadow_changes_no_outcome(held, plan, expected):
    """The whole point of a shadow. Every reconciliation the live path made
    before, it still makes."""
    assert _names(_undeferred(held, plan)) == expected


def test_labelled_held_items_still_reconcile_by_name():
    """Ids being present must not change the live answer either — they are
    carried, not consulted, by the path that decides."""
    held = _calls_for_ready([
        {"food": "White rice", "calories": 200, "amount": 1, "unit": "cup"},
        {"food": "Corn", "calories": 90, "amount": 1, "unit": "ear"}])
    kept = _undeferred(held, [_c("White rice, cooked")])
    assert _names(kept) == ["Corn"]


# ── and it reports what it saw ───────────────────────────────────────────────

def _log_of(caplog, outcome):
    return [r for r in caplog.records
            if "event=identity_shadow" in r.getMessage()
            and f"outcome={outcome}" in r.getMessage()]


def test_it_reports_when_nothing_is_labelled(caplog):
    with caplog.at_level(logging.INFO, logger="core.food_turn"):
        _undeferred([_c("Rice")], [])
    assert _log_of(caplog, "no_ids"), "an unmeasurable turn must say so"


def test_it_counts_the_collapses_the_name_match_made(caplog):
    """THE NUMBER THIS PHASE EXISTS TO PRODUCE. Held items are labelled and the
    answer turn's re-parse is not, which is the expected state until a
    cross-turn id can name the FOOD rather than the parse. So the measurable
    quantity is how many held foods the name match dropped — each one a
    candidate row deletion."""
    held = _calls_for_ready([
        {"food": "Rice", "calories": 200, "amount": 1, "unit": "cup"},
        {"food": "Corn", "calories": 90, "amount": 1, "unit": "ear"}])
    with caplog.at_level(logging.INFO, logger="core.food_turn"):
        _undeferred(held, [_c("White rice")])
    rec = _log_of(caplog, "plan_unlabelled")
    assert rec and "collapsed=1" in rec[0].getMessage()


def test_a_real_comparison_when_both_sides_carry_ids(caplog):
    """Reachable once the answer turn can carry the original ids. Pinned now so
    the path is exercised before anything depends on it."""
    import copy
    held = _calls_for_ready([
        {"food": "Rice", "calories": 200, "amount": 1, "unit": "cup"}])
    with caplog.at_level(logging.INFO, logger="core.food_turn"):
        _undeferred(held, copy.deepcopy(held))
    assert _log_of(caplog, "agree")


def test_the_shadow_never_costs_the_turn(monkeypatch, caplog):
    """A measurement may not break what it measures."""
    import core.food_turn as FT
    monkeypatch.setattr(FT, "_item_id_of",
                        lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
    assert _names(_undeferred([_c("Turkey"), _c("Corn")], [_c("Turkey")])) \
        == ["Corn"]


def test_it_can_be_switched_off(monkeypatch, caplog):
    """A shadow that cannot be disabled gets reverted instead."""
    monkeypatch.setenv("FOOD_IDENTITY_SHADOW", "false")
    with caplog.at_level(logging.INFO, logger="core.food_turn"):
        _undeferred([_c("Rice")], [])
    assert not [r for r in caplog.records
                if "event=identity_shadow" in r.getMessage()]
