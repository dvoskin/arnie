"""An ask turn writes nothing — be65fb6's decision, restored.

History: partial commit shipped 2026-07-27 (72a0396), was WITHDRAWN the same
day (be65fb6) because an ask carrying writes loses its own question, and that
withdrawal NEVER MERGED — it lives only on dvoskin/credentials-food-turn-fixes.
553a365 then re-landed the writes on 07-28 as a wiring fix for the native path
(which had silently become atomic-hold), and the narration faults be65fb6
documented came back with them.

Live symptom 2026-08-03: "Had some chicken and rice" wrote
fe#2728 'White rice, steamed' 150 g, said nothing about it, and asked about the
chicken — a card that reads as finished above a question that says it is not.

Holding is a DECISION here, not the wiring loss 553a365 fixed: the coordinator
still separates SAY from WRITE and still executes approved_operations. It is
simply handed none on an ask.
"""
import os

import pytest

import core.food_turn as FT


def test_partial_commit_is_on_until_the_held_items_are_stashed():
    """NOT the intended end state. be65fb6's default was false and holding is
    the right call — but tests/test_leave_no_food_behind.py proves the premise
    ("the answer turn re-reads the whole message") false: an item neither asked
    about nor marked ready is LOST, not deferred, which is the corn that
    vanished behind a turkey clarification. Committing the orphans is currently
    the only thing between a clarification and silent data loss.

    Flips to false once held AND orphan items ride the pending question's
    staged_items, so the answer turn commits them deterministically."""
    os.environ.pop("FOOD_PARTIAL_COMMIT", None)
    assert FT.partial_commit_enabled() is True


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("1", True), ("yes", True),
    ("false", False), ("no", False),
])
def test_the_switch_works_in_both_directions(monkeypatch, raw, expected):
    """A kill switch both ways — which is why the narration guard below has to
    survive independently of whichever default is in force."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", raw)
    assert FT.partial_commit_enabled() is expected


def test_a_question_is_not_discarded_as_a_premature_confirmation():
    """`discard_held` bins pass-1 text that claims a write before the write
    landed. On an ASK turn that also wrote, the held bubble is the system's own
    QUESTION — dropping it is how the partial commit lost its question twice
    over. The guard keys on the turn's disposition, not on whether a tool
    fired, so flipping FOOD_PARTIAL_COMMIT back on cannot re-open it.
    """
    import inspect

    import core.conversation as C

    src = inspect.getsource(C._run_turn)
    assert "_streamer.discard_held()" in src
    # The call must be gated on the turn NOT being an ask.
    guarded = [ln for ln in src.splitlines()
               if "discard_held()" in ln or 'get("action") == "ask"' in ln]
    assert any('get("action") == "ask"' in ln for ln in guarded), (
        "discard_held is no longer gated on the ask disposition — an "
        "ask-with-writes will silently drop its own question again")
