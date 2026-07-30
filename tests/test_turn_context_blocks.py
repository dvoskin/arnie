"""State facts ride with the message — each block a pure function of state.

The sequel to `test_turn_obligations.py`. The rule for every block: present
exactly when its state exists, absent (empty string) when it does not, and
never a judgment about the message. Each block traces to a production defect:

  [OPEN QUESTION]  — "It's the same one" escaped to a legacy model that had no
                     idea a question was open (interpreter_none, 07-29)
  [RECENT WRITES]  — corrections re-interpreted prose instead of binding to
                     the row just written (causes B and C)
  [REPLY LANGUAGE] — English scaffolding on Russian replies (cause E)
  [TIME]           — "yesterday's turkey" landed on no day; midnight rollover
  [UNITS]          — kg-vs-lb confusion in workout loads
"""
from types import SimpleNamespace

import pytest

from core.turn_obligations import (OBLIGATIONS_NOTE, last_action_block,
                                   open_question_block, reply_language_block,
                                   time_block, units_block,
                                   with_turn_obligations)


# ── [OPEN QUESTION] ───────────────────────────────────────────────────────────
def test_open_question_carries_question_report_and_held_reading():
    block = open_question_block({
        "question": "The Harvest Cheddar ones, or a different flavor?",
        "original": "Having the sun chips again",
        "items": [{"food": "Sun Chips Harvest Cheddar", "amount": 1,
                   "unit": "bag", "calories": 210}],
    })
    assert block.startswith("[OPEN QUESTION")
    assert "Harvest Cheddar ones, or a different flavor?" in block
    assert "Having the sun chips again" in block
    assert "Sun Chips Harvest Cheddar (1 bag) — 210 cal as read" in block
    assert "do not re-ask" in block


def test_no_pending_means_no_block():
    assert open_question_block(None) == ""
    assert open_question_block({}) == ""
    assert open_question_block({"original": "x"}) == ""   # no question text


# ── [RECENT WRITES] ───────────────────────────────────────────────────────────
def test_recent_writes_carry_entry_ids_newest_first():
    block = last_action_block([
        {"id": 601, "food": "Shrimp", "qty": "7 small", "cal": 35,
         "mins_ago": 2},
        {"id": 590, "food": "Oatmeal", "qty": "1 cup", "cal": 300,
         "mins_ago": 175},
        {"id": 500, "food": "Breakfast burrito", "qty": "", "cal": 550,
         "mins_ago": 480},              # too old — the board already has it
    ])
    assert block.startswith("[RECENT WRITES")
    assert "entry 601: Shrimp 7 small, 35 cal — 2 min ago" in block
    assert "entry 590" in block
    assert "Breakfast burrito" not in block
    assert block.index("entry 601") < block.index("entry 590")
    assert "never log it again as new food" in block


def test_stale_or_ageless_boards_produce_no_block():
    assert last_action_block([]) == ""
    assert last_action_block(None) == ""
    # a row without an age cannot claim recency
    assert last_action_block([{"id": 1, "food": "X", "cal": 1,
                               "mins_ago": None}]) == ""
    assert last_action_block([{"id": 1, "food": "X", "cal": 1,
                               "mins_ago": 481}]) == ""


# ── [REPLY LANGUAGE] ──────────────────────────────────────────────────────────
def test_non_latin_letters_pin_the_reply_language():
    assert "[REPLY LANGUAGE" in reply_language_block("съел борщ")
    assert "[REPLY LANGUAGE" in reply_language_block("食べた")


def test_latin_and_punctuation_do_not():
    """The same letters-only rule as the gate: a smart apostrophe or an emoji
    is not a language."""
    assert reply_language_block("I've had 2 eggs") == ""
    assert reply_language_block("7 couldn’t do more") == ""
    assert reply_language_block("nice \U0001F4AA") == ""
    assert reply_language_block("") == ""


# ── [TIME] ────────────────────────────────────────────────────────────────────
def test_time_block_names_the_clock_and_the_logging_day():
    block = time_block(SimpleNamespace(timezone="America/New_York"))
    assert block.startswith("[TIME")
    assert "America/New_York" in block
    assert "logging day" in block
    assert "never server time" in block


def test_an_unparseable_timezone_yields_no_block_not_a_wrong_one():
    """The Marina crash, inverted: free-text tz used to take the turn down;
    here it just means no clock is asserted."""
    assert time_block(SimpleNamespace(timezone="somewhere nice")) == ""
    assert time_block(SimpleNamespace(timezone="")) == ""
    assert time_block(SimpleNamespace()) == ""


def test_rollover_hour_is_stated_when_configured(monkeypatch):
    monkeypatch.setenv("LOGGING_DAY_ROLLOVER_HOUR", "4")
    block = time_block(SimpleNamespace(timezone="UTC"))
    assert "rolls over at 04:00" in block


# ── [UNITS] ───────────────────────────────────────────────────────────────────
def test_units_state_storage_versus_display():
    block = units_block(SimpleNamespace(units_preference="imperial"))
    assert block.startswith("[UNITS")
    assert "imperial (lb, oz, ft)" in block
    assert "Storage is ALWAYS metric" in block
    metric = units_block(SimpleNamespace(units_preference="metric"))
    assert "metric (kg, g, cm)" in metric


def test_no_preference_no_block():
    assert units_block(SimpleNamespace(units_preference="")) == ""
    assert units_block(SimpleNamespace()) == ""


# ── assembly ──────────────────────────────────────────────────────────────────
def test_blocks_ride_before_the_obligations_note():
    msgs = [{"role": "user", "content": "and the shrimp was fried"}]
    out = with_turn_obligations(msgs, ["[RECENT WRITES]\n- entry 601"])
    content = out[-1]["content"]
    assert content.startswith("and the shrimp was fried")
    assert content.index("[RECENT WRITES]") < content.index("[TURN OBLIGATIONS")


def test_empty_blocks_are_dropped_from_the_appendix():
    msgs = [{"role": "user", "content": "hi"}]
    out = with_turn_obligations(msgs, ["", "", ""])
    assert out[-1]["content"] == "hi\n\n" + OBLIGATIONS_NOTE


def test_the_caller_is_still_never_mutated():
    msgs = [{"role": "user", "content": "hi"}]
    before = [dict(m) for m in msgs]
    with_turn_obligations(msgs, ["[TIME]\nnow"])
    assert msgs == before
