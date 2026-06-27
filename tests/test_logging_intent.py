"""Unit tests for the turn-intent gate (skills/logging_intent.py).

The gate is what lets a LEGIT second serving through the food/water/exercise
dedup guards: an explicit add/repeat cue in the user's current turn opens it,
everything else keeps it closed. Pins the exact behavior Danny's 2026-06-27 logs
needed — "second cottage cheese" / "a second barebells" must read as add-intent,
while retries ("log the elmhurst again"), topic pivots, and bare time-"second"
must not.

Pure function — fast, no DB.
"""
import pytest

from skills.logging_intent import has_add_intent, turn_supports_log


# ── True: explicit add / repeat cues ──────────────────────────────────────────

ADD_INTENT_TRUE = [
    "another coffee",
    "another",
    "one more",
    "1 more",
    "2 more",
    "make it 2 more",
    "a second cottage cheese",   # Danny 2026-06-27
    "second cottage cheese",     # word form, no article
    "add a second barebells",    # Danny 2026-06-27 — the one that never logged
    "2nd Barebells",             # numeral form
    "third helping",
    "I had a fourth slice",
    "twice",
    "double espresso",
    "two of those",
    "a couple more",
    "an extra one",
    "round 2",
    "x2",
    "add another 150g",
    "some more rice",
    "ещё один",                  # RU: one more
    "ещё",                       # RU: more
    "вторую порцию",             # RU: a second portion
]


@pytest.mark.parametrize("msg", ADD_INTENT_TRUE)
def test_turn_supports_log_true(msg):
    assert turn_supports_log(msg) is True, msg
    assert has_add_intent(msg) is True, msg


# ── False: retries, pivots, negations, bare time-"second", empty ──────────────

ADD_INTENT_FALSE = [
    "log the elmhurst again",    # retry — names the item + "again"
    "log the elmhurst",          # bare item mention
    "connect apple health",      # topic pivot
    "",                          # empty → default closed
    None,                        # None → default closed
    "no more",                   # negation
    "no more food",
    "больше не надо",            # RU negation
    "again please",              # bare "again" is not a cue
    "where is it",               # dedup pushback, not an add
    "I don't see them",
    "wait a second",             # time-"second", not a serving
    "give me a second",
    "one second",
    "hold on a second",
    "just a second",
    "in a second",
    "I ate 3 eggs total",        # "N total" deliberately excluded
]


@pytest.mark.parametrize("msg", ADD_INTENT_FALSE)
def test_turn_supports_log_false(msg):
    assert turn_supports_log(msg) is False, msg
    assert has_add_intent(msg) is False, msg


# ── Specific requirements called out in the task ──────────────────────────────

def test_another_and_one_more_and_second_open_the_gate():
    assert turn_supports_log("another coffee")
    assert turn_supports_log("one more")
    assert turn_supports_log("a second cottage cheese")
    assert turn_supports_log("2nd Barebells")
    assert turn_supports_log("twice")
    assert turn_supports_log("ещё один")


def test_retry_and_pivot_and_empty_keep_the_gate_closed():
    assert not turn_supports_log("log the elmhurst again")
    assert not turn_supports_log("connect apple health")
    assert not turn_supports_log("")
    assert not turn_supports_log("no more")


def test_bare_time_second_is_not_add_intent():
    """A bare time 'second' must never be read as a serving — the time idioms
    are stripped before the serving-noun cue can fire."""
    for phrase in ("wait a second", "give me one second", "hold on a second",
                   "just a second", "in a second"):
        assert not turn_supports_log(phrase), phrase


def test_second_with_serving_noun_is_add_intent():
    """'second' DOES open the gate when followed by the item or a serving noun."""
    for phrase in ("second serving of rice", "a second glass", "second cottage cheese",
                   "third round", "a second helping"):
        assert turn_supports_log(phrase), phrase


def test_item_name_arg_is_accepted_but_does_not_change_result():
    """item_name is a forward hook — present for call-site symmetry, unused today.
    Passing it must not change the gate decision."""
    assert turn_supports_log("another", "coffee") is True
    assert turn_supports_log("connect apple health", "coffee") is False
