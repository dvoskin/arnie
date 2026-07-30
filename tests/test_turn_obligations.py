"""The obligations note rides the newest user message, and only the request.

Danny, 2026-07-30: "Arnie is significantly more reliable when I actually
instruct him to make sure he calls all the necessary tools." The rule already
exists in the system prompt; what his instruction changes is placement —
adjacent to the message being answered, where it does not decay with session
depth. `with_turn_obligations` makes that placement mechanical.

The properties that matter, each tested:
  * the note lands on the newest USER turn, string or block content
  * the CALLER'S list and dicts are untouched — the same list is extended by
    the self-heal retry and the follow-up pass, and a leaked appendix would
    compound once per pass
  * anything unexpected passes through unchanged — this must never be able to
    break a turn
  * the stored conversation never carries it (request-side only, by
    construction: the caller's objects are not mutated)
"""
import os

from core.turn_obligations import (OBLIGATIONS_NOTE, obligations_enabled,
                                   with_turn_obligations)


def _msgs():
    return [
        {"role": "user", "content": "did 3 sets of incline at 205"},
        {"role": "assistant", "content": "Strong. Logged."},
        {"role": "user", "content": "and 8 and 5 body weight"},
    ]


def test_the_note_lands_on_the_newest_user_turn():
    out = with_turn_obligations(_msgs())
    assert out[-1]["content"].startswith("and 8 and 5 body weight")
    assert OBLIGATIONS_NOTE in out[-1]["content"]
    # earlier turns untouched
    assert OBLIGATIONS_NOTE not in out[0]["content"]
    assert OBLIGATIONS_NOTE not in out[1]["content"]


def test_the_callers_messages_are_never_mutated():
    """The same list is reused by the retry and follow-up passes; an in-place
    appendix would compound once per pass."""
    msgs = _msgs()
    before = [dict(m) for m in msgs]
    with_turn_obligations(msgs)
    assert msgs == before, "caller's messages were mutated"


def test_block_content_gains_a_text_block():
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "data": "..."}},
        {"type": "text", "text": "[Photo received]"},
    ]}]
    out = with_turn_obligations(msgs)
    blocks = out[-1]["content"]
    assert blocks[-1] == {"type": "text", "text": OBLIGATIONS_NOTE}
    assert len(blocks) == 3
    assert len(msgs[-1]["content"]) == 2, "caller's blocks were mutated"


def test_unexpected_shapes_pass_through_unchanged():
    assert with_turn_obligations([]) == []
    tail_assistant = [{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": "hey"}]
    assert with_turn_obligations(tail_assistant) == tail_assistant
    weird = [{"role": "user", "content": 42}]
    assert with_turn_obligations(weird) == weird


def test_an_empty_user_message_carries_the_note_alone():
    out = with_turn_obligations([{"role": "user", "content": "   "}])
    assert out[-1]["content"] == OBLIGATIONS_NOTE


def test_the_kill_switch_reverts_without_a_deploy():
    os.environ["TURN_OBLIGATIONS"] = "false"
    try:
        assert obligations_enabled() is False
        msgs = _msgs()
        assert with_turn_obligations(msgs) == msgs
    finally:
        os.environ.pop("TURN_OBLIGATIONS", None)
    assert obligations_enabled() is True


def test_the_note_declares_itself_not_the_user():
    """The model must be able to tell this is not something the user wrote —
    quoting it back would leak the mechanism into the chat."""
    assert "not written by the user" in OBLIGATIONS_NOTE
    assert OBLIGATIONS_NOTE.startswith("[TURN OBLIGATIONS")
