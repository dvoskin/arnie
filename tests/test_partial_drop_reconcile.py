"""Partial-drop reconcile — the scribe-driven net that catches a distinct dish
the model logged part of and dropped the rest ("175g turkey and 100g rice" →
turkey logged, rice dropped, ~1/3 of the time), WITHOUT ever over-splitting a
composite. distinct_missing_items is pure (no LLM), so these are deterministic.
"""
from core.scribe import distinct_missing_items, should_run_scribe


def test_should_run_scribe_covers_food_turns_skips_chatter():
    # Runs on any substantive food-ish message (incl. space-separated lists), not
    # just separator lists — so completeness is deterministic on every food turn.
    assert should_run_scribe("175g turkey and 100g rice") is True
    assert should_run_scribe("eggs bacon toast") is True          # space-separated
    assert should_run_scribe("Barebells caramel cashew") is True  # bare name
    assert should_run_scribe("poke bowl with salmon tuna rice") is True
    # Skips pure acks and lookup questions (no consumed food to extract).
    assert should_run_scribe("thanks") is False
    assert should_run_scribe("ok") is False
    assert should_run_scribe("what should I eat") is False
    assert should_run_scribe("how many calories in a banana") is False


def _items(*names):
    return [{"name": n, "quantity": "", "raw": n} for n in names]


def test_distinct_drop_is_caught():
    # turkey logged, rice dropped → rice must be flagged.
    miss = distinct_missing_items(_items("turkey", "rice"), ["Ground turkey, 96% lean"])
    assert miss == ["rice"]


def test_multiple_distinct_drops_caught():
    miss = distinct_missing_items(_items("eggs", "toast", "banana"), ["Scrambled eggs"])
    assert set(miss) == {"toast", "banana"}


def test_composite_logged_as_one_never_flags():
    # The scribe extracts a composite as ONE long-named item; even though its
    # tokens don't match the shorter log name, the ≤3-token gate skips it so it
    # can NEVER trigger a rescue (which would duplicate / over-split it).
    scribe = _items("poke bowl with salmon, tuna, rice, edamame, avocado")
    assert distinct_missing_items(scribe, ["Poke bowl (salmon, tuna, rice, edamame, avocado)"]) == []
    scribe2 = _items("chicken caesar wrap with croutons and parmesan")
    assert distinct_missing_items(scribe2, ["Chicken Caesar wrap"]) == []


def test_nothing_missing_when_all_logged():
    miss = distinct_missing_items(_items("turkey", "rice"), ["Ground turkey", "White rice"])
    assert miss == []


def test_short_multiword_distinct_item_is_caught():
    # A genuine distinct side with a short name still rescues.
    miss = distinct_missing_items(_items("burger", "sweet potato fries"),
                                  ["Homemade turkey burger"])
    assert miss == ["sweet potato fries"]
