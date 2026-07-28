"""Having food is not eating it.

    User:   Got a caramel cashew Barebells bar and a Legendary Milk Chocolate
            Sweet Roll
    Arnie:  [logs both — 400 calories against a day nothing had been eaten in]

The gate that let that through reads `_CONSUMED_RE`, which bundles "ate" with
"bought". That bundle is right for deciding whether the logger should LOOK at
a message — both are about food — and wrong for deciding whether to WRITE one.

Four states, one of which is a log.
"""
from types import SimpleNamespace

import pytest

import core.food_turn as FT
from core.food_turn import (STATE_ACQUIRED, STATE_CONSUMED, STATE_PLANNED,
                            STATE_UNCERTAIN, acquisition_question,
                            consumption_state)


# ── the classifier ────────────────────────────────────────────────────────────
def test_obtaining_is_not_eating():
    for line in ("Got a caramel cashew Barebells bar",
                 "bought a protein bar", "picked up a poke bowl",
                 "grabbed a coffee", "ordered a burrito",
                 "packed a sandwich for work"):
        assert consumption_state(line) == STATE_ACQUIRED, line


def test_an_eating_verb_wins_outright():
    for line in ("I ate a Barebells bar", "had a bagel",
                 "just finished a shake", "drank a Fairlife"):
        assert consumption_state(line) == STATE_CONSUMED, line


def test_an_eating_verb_wins_even_alongside_an_acquisition_one():
    """"picked up a poke bowl and ate half of it" is one sentence about lunch."""
    assert consumption_state(
        "picked up a poke bowl and ate half of it") == STATE_CONSUMED


def test_a_future_frame_beats_a_bare_acquisition():
    """"got some steaks for tomorrow" is a shopping trip."""
    assert consumption_state("got some steaks for tomorrow") == STATE_PLANNED
    assert consumption_state("going to have salmon") == STATE_PLANNED


def test_an_open_thread_settles_it():
    """"and a coffee" after a logged meal is part of that meal, not an errand."""
    assert consumption_state("grabbed a coffee too",
                             thread_active=True) == STATE_CONSUMED


def test_nothing_to_go_on_stays_uncertain():
    assert consumption_state("") == STATE_UNCERTAIN
    assert consumption_state("a bagel") == STATE_UNCERTAIN


# ── the question ──────────────────────────────────────────────────────────────
def test_the_question_names_the_food():
    """A question the user has to scroll up to understand is a worse one."""
    q = acquisition_question([{"food": "Barebells Caramel Cashew Protein Bar"}])
    assert "Barebells Caramel Cashew Protein Bar" in q
    assert q.endswith("?")


def test_two_items_are_both_named():
    q = acquisition_question([{"food": "Barebells Bar"},
                              {"food": "Legendary Sweet Roll"}])
    assert "Barebells Bar" in q and "Legendary Sweet Roll" in q


def test_more_than_two_are_counted_not_listed():
    """Reading five things back is the roll-call the card exists to avoid."""
    q = acquisition_question([{"food": f"Item {i}"} for i in range(5)])
    assert "all 5 of those" in q
    assert "Item 3" not in q


# ── the turn ──────────────────────────────────────────────────────────────────
def _interp(payload):
    import json

    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


_TWO_BARS = {
    "action": "log",
    "items": [{"food": "Barebells Caramel Cashew Protein Bar", "amount": 1,
               "unit": "bar", "branded": True, "basis": "stated",
               "calories": 200, "protein": 20},
              {"food": "Legendary Foods Milk Chocolate Sweet Roll", "amount": 1,
               "unit": "roll", "branded": True, "basis": "stated",
               "calories": 210, "protein": 20}],
    "say": "Logged, {batch_cal} cal."}


async def _run(monkeypatch, message, mode="moderate"):
    monkeypatch.setattr(FT, "chat", _interp(_TWO_BARS))
    return await FT.run(message, SimpleNamespace(
        preferences=SimpleNamespace(food_logging_mode=mode)))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
async def test_moderate_and_strict_ask_rather_than_write(monkeypatch, mode):
    out = await _run(monkeypatch, "Got a caramel cashew Barebells bar and a "
                                  "Legendary Milk Chocolate Sweet Roll", mode)
    assert out["action"] == "ask", out
    assert "eat" in out["text"].lower()


@pytest.mark.asyncio
async def test_the_question_holds_the_items_for_a_deterministic_replay(
        monkeypatch):
    """A yes must log THESE items, not re-parse the sentence. `kind="confirm"`
    is the existing replay contract and this rides it.

    THE ITEMS ARE THE REPLAY VEHICLE, and `tool_calls` never was. The yes path
    (`_confirm_hit` in core/conversation.py) rebuilds the calls from the stored
    `items` through `_log_call`; it does not read the `tool_calls` this turn
    carried. So carrying them bought the replay nothing and cost the thing this
    module is named after: a non-empty `tool_calls` on an ask turn IS the
    write, so the question "did you actually eat it?" shipped alongside the 400
    calories it was asking permission for. It also destroyed itself —
    `discard_held()` drops the streamed bubble whenever a logging tool fires,
    and the structured-narration branch has no "ask" in its action tuple, so
    the turn fell through to `voice_log` and narrated the write instead.
    """
    out = await _run(monkeypatch, "Got a caramel cashew Barebells bar and a "
                                  "Legendary Milk Chocolate Sweet Roll")
    assert out["kind"] == "confirm"
    assert len(out["items"]) == 2
    assert out["tool_calls"] == [], (
        "an acquisition confirm must not write the food it is asking about")


@pytest.mark.asyncio
async def test_quick_commits_and_does_not_ask(monkeypatch):
    out = await _run(monkeypatch, "Got a caramel cashew Barebells bar and a "
                                  "Legendary Milk Chocolate Sweet Roll",
                     "quick")
    assert out["action"] == "log", out


@pytest.mark.asyncio
async def test_saying_you_ate_them_writes_immediately(monkeypatch):
    out = await _run(monkeypatch, "Just ate a caramel cashew Barebells bar and "
                                  "a Legendary Milk Chocolate Sweet Roll")
    assert out["action"] == "log", out
