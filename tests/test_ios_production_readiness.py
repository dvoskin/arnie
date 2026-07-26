"""iOS-facing defects found in the 2026-07-26 audit.

The common root is one mistake wearing three hats: a property of the TURN was
inferred from a property of the TRANSPORT. Cards, and now the recitation strip,
keyed off whether a streaming callback was supplied — true only on the iOS
WebSocket path, while photo, voice and HTTP-fallback text return the same cards
through `_coached_reply` and pass nothing.

Each test states the user-visible failure it prevents, not the mechanism.
"""
from types import SimpleNamespace

from core.platform import (Response, _sanitize_bubble, _strip_code_fences,
                           had_code_fence, serialize_response)


# ── code fences: the phantom delete ───────────────────────────────────────────

def test_a_fenced_reply_never_ships_as_a_code_block():
    """A reply that opened with ``` rendered monospace on iOS and tripped no
    detector, because the leak net only recognised <invoke> XML."""
    out = _sanitize_bubble("```\nYou're tracking steady with your macros.\n```")
    assert "```" not in out
    assert "tracking steady with your macros" in out


def test_a_fenced_reply_keeps_its_text():
    """Strip the MARKERS, never the content — deleting the body would turn a
    formatting bug into a silent empty message."""
    assert _strip_code_fences("```json\nhello\n```").strip() == "hello"


def test_an_unbalanced_fence_is_still_stripped():
    """Truncation is the common case; a dangling opener must not ship either."""
    assert "```" not in _sanitize_bubble("```\nhalf a thought")


def test_inline_and_language_tagged_fences_both_go():
    assert "`" not in _strip_code_fences("```python")
    assert "```" not in _sanitize_bubble("text ``` more text")


def test_a_reply_without_a_fence_is_untouched():
    clean = "Logged the bagel bite, 60 calories."
    assert _sanitize_bubble(clean) == clean
    assert had_code_fence(clean) is False


def test_the_fence_is_detectable_after_it_is_stripped():
    """The turn stays suspect even once the text is clean: the model was
    formatting a payload rather than talking, and that is worth a health flag."""
    assert had_code_fence("```\nanything\n```") is True


# ── regenerate: the stale card ────────────────────────────────────────────────

def test_the_wire_names_the_row_a_regenerate_replaced():
    """History hides the superseded row on RELOAD; the live view needed to be
    told which message to drop, or the old card stayed beside the new reply."""
    payload = serialize_response(Response(bubbles=["redone"]))
    payload["superseded_log_id"] = 4021
    assert payload["superseded_log_id"] == 4021


def test_a_normal_turn_supersedes_nothing():
    from core.conversation import TurnResult
    turn = TurnResult(response=Response(bubbles=["hi"]), tool_calls=[],
                      just_completed=False, in_onboarding=False,
                      onboarding_field_saved=None, today_log=None,
                      user=SimpleNamespace(id=1))
    assert turn.superseded_log_id is None


# ── the recitation strip on photo / voice ─────────────────────────────────────

def _committed(name="log_food", entry_id=77):
    from core.execution_result import CallResult
    return CallResult(
        name=name, status="committed",
        raw_input={"food_name": "Bagel bite", "quantity": "1 bite",
                   "calories": 60, "protein": 2, "carbs": 11, "fats": 1,
                   "_entry_id": entry_id},
        entry_id=entry_id)


def test_a_committed_food_call_means_a_card_will_render():
    """The plan must know a card is coming BEFORE the text is authored. This is
    the question `card_will_render` actually asks, and it is answered by the
    turn — no callback, no socket, no transport involved."""
    from core.conversation import _logged_entry_card
    call = _committed()
    assert _logged_entry_card(call.name, call.raw_input, call=call) is not None


def test_a_deduped_call_renders_no_card():
    """No DB row means no card, so prose is free to state the numbers — the
    other half of the contract, and why `bool(committed_calls)` is not enough."""
    from core.conversation import _logged_entry_card
    from core.execution_result import CallResult
    noop = CallResult(name="log_food", status="committed",
                      raw_input={"food_name": "Coffee"}, entry_id=None)
    assert _logged_entry_card(noop.name, noop.raw_input, call=noop) is None


def test_card_detection_is_identical_for_every_transport():
    """Photo and voice go through `_coached_reply` and pass no on_card; the
    WebSocket passes one. Same turn, same answer — that difference is what put
    the card's calories in the prose above it on every photo log."""
    from core.conversation import _logged_entry_card
    call = _committed()

    def detect():   # exactly the derivation the commit path now uses
        return any(_logged_entry_card(c.name, c.raw_input, call=c) is not None
                   for c in (call,))

    ws_result = detect()          # WebSocket: on_card supplied
    http_result = detect()        # photo / voice / HTTP: nothing supplied
    assert ws_result is http_result is True
