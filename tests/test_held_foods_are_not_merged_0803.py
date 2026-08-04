"""Two held foods are two foods, even when one name contains the other.

`_undeferred` decides which of the ask's held writes the ANSWER turn has not
already covered. It collapses "White rice" against a re-read "White rice,
cooked" — that duplicate is real and is why `_same_food` exists, since both
calls land in ONE batch where the executor's dedup deliberately cannot see them.

But `_same_food` is a token-subset test in either direction, and it was applied
to the held list against ITSELF. Held entries come from different parsed items
by construction (`_calls_for_ready` walks `ready`, `_orphan_calls` walks `items`
minus ready/points), so that deleted real food:

    held=[Rice, Rice cakes, Coffee, Coffee cake]  ->  ['Rice', 'Coffee']

silently, with no tombstone and no log line naming the loss. Orange/orange
juice, egg/egg roll, milk/milk chocolate, coffee/coffee cake all do it.

Order mattered too. Walking once, the plain "Orange" reached a plan of
[Orange juice], matched it fuzzily, consumed the slot and dropped ITSELF —
writing the juice and vanishing the orange. Exact claims are now resolved in
their own pass first.

This is the branch's headline invariant (leave no food behind) failing inside
the mechanism added to guarantee it, and nothing in tests/ touched `_undeferred`
or `_same_food` before this file.
"""
import pytest

from core.food_turn import _undeferred


def _c(name):
    return {"name": "log_food", "input": {"food_name": name}}


def _names(calls):
    return [c["input"]["food_name"] for c in calls]


@pytest.mark.parametrize("held", [
    ["Rice", "Rice cakes"],
    ["Coffee", "Coffee cake"],
    ["Orange", "Orange juice"],
    ["Egg", "Egg roll"],
    ["Milk", "Milk chocolate"],
    ["Butter", "Peanut butter"],
])
def test_two_distinct_held_foods_both_survive(held):
    """Nothing in the plan covers either, so both must be written."""
    assert _names(_undeferred([_c(h) for h in held], [])) == held


def test_the_rice_collapse_still_works():
    """The duplicate this function exists for: the answer turn re-read the
    sentence and named the food more precisely. One row, not two."""
    assert _undeferred([_c("White rice")], [_c("White rice, cooked")]) == []


def test_a_plan_call_accounts_for_only_one_held_call():
    """The failing direction. [Orange, Orange juice] against a plan naming the
    juice must write the ORANGE — the juice is covered, the orange is not."""
    assert _names(_undeferred(
        [_c("Orange"), _c("Orange juice")], [_c("Orange juice")])) == ["Orange"]
    # ...and symmetrically.
    assert _names(_undeferred(
        [_c("Orange"), _c("Orange juice")], [_c("Orange")])) == ["Orange juice"]


def test_an_unrelated_plan_covers_nothing():
    assert _names(_undeferred(
        [_c("Orange"), _c("Orange juice")], [_c("Burrito")])) \
        == ["Orange", "Orange juice"]


def test_an_exact_repeat_within_held_is_still_one_row():
    assert _names(_undeferred([_c("Corn"), _c("Corn")], [])) == ["Corn"]


def test_the_turkey_and_corn_case_is_unchanged():
    """The prod bug the whole mechanism was built for — disjoint names, so it
    never exercised the join at all. Pinned so it stays that way."""
    assert _names(_undeferred(
        [_c("Turkey"), _c("Corn")], [_c("Turkey")])) == ["Corn"]


def test_ambiguity_carries_rather_than_drops():
    """When several plan calls could account for one held call, none of them
    claims it. A food written twice is visible and recoverable; one silently
    dropped is not.

    The example changed with the head-noun rule: "Rice pudding" is no longer a
    candidate at all (a new head noun after the match makes it a different
    food), so it is no longer ambiguous with "Fried rice". Two genuine renames
    are.
    """
    out = _undeferred([_c("Rice")],
                      [_c("Fried rice"), _c("Cooked rice")])
    assert _names(out) == ["Rice"]


# ── a rename is not "any name that contains this one" ─────────────────────────

@pytest.mark.parametrize("held,plan", [
    ("Orange", "Orange juice"),
    ("Coffee", "Coffee cake"),
    ("Peanut", "Peanut butter"),
    ("Egg", "Egg roll"),
    ("Apple", "Apple pie"),
    ("Rice", "Rice cakes"),
])
def test_a_different_food_never_claims_a_held_one(held, plan):
    """THE ACROSS-TURNS HALF, which the first fix missed entirely.

    `_same_food` is a token-subset test, so it could not tell "the answer turn
    renamed the same food" from "a different food whose name contains this
    one". Driven end to end through two real turns, held foods VANISHED:

        "an orange and a glass of orange juice" -> the orange, gone
        "coffee and coffee cake"                -> the coffee, gone

    with no row, no tombstone, and `outcome=covered` logged over the loss. 26
    such pairs exist among the 275 food names in `portions.py` alone.

    English compounds put the head noun last, so a new head AFTER the match
    means a different food — while words BEFORE it, and preparation words
    anywhere, are the same food described better.
    """
    assert _names(_undeferred([_c(held)], [_c(plan)])) == [held]


@pytest.mark.parametrize("held,plan", [
    ("White rice", "White rice, cooked"),   # symptom 5, the reason this exists
    ("Beef", "Ground beef"),
    ("Turkey", "Ground turkey"),
    ("Oil", "Olive oil"),
    ("Chicken", "Grilled chicken"),
    # A LEADING modifier NAMES THE SAME FOOD MORE PRECISELY, even when it is an
    # ingredient rather than a preparation. I first asserted the opposite for
    # these two, having lifted them off a list of token COLLISIONS without
    # asking which way each should resolve — the code was right and the test
    # was wrong.
    #
    # The reason it resolves this way is the deferral's own context: `held` and
    # `plan` are two readings of the SAME message. If the user had said "bread
    # and banana bread", the answer turn's re-read would emit both; emitting
    # only "banana bread" means it is the one item, described better. That is
    # not true of a trailing head noun — "orange juice" is not a more precise
    # "orange", it is a different thing made from one.
    ("Bread", "Banana bread"),
    ("Soup", "Miso soup"),
])
def test_a_genuine_rename_still_collapses(held, plan):
    """The narrowing may not cost the duplicate-collapse it was built for."""
    assert _undeferred([_c(held)], [_c(plan)]) == []
