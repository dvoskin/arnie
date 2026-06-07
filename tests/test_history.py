"""
core.history.conversations_to_messages rendering — the pure row→message transform
both bot handlers feed to the LLM.

Covers the proactive branch specifically (T0.6 follow-up): a ConversationLog row
with source_type=='proactive' must render as a SINGLE assistant turn
"(I checked in:) {response}" and NEVER a synthetic empty user turn.
"""
from types import SimpleNamespace

from core.history import conversations_to_messages


def _row(raw_message="", response="", source_type="text"):
    """Duck-typed ConversationLog row (the renderer only reads these attrs)."""
    return SimpleNamespace(
        raw_message=raw_message, response=response, source_type=source_type
    )


def test_proactive_row_renders_single_assistant_turn():
    rows = [_row(response="how's the cut going?", source_type="proactive")]
    msgs = conversations_to_messages(rows)
    # exactly ONE turn — no empty user turn paired with it
    assert msgs == [{"role": "assistant", "content": "(I checked in:) how's the cut going?"}]


def test_proactive_row_never_emits_empty_user_turn():
    rows = [_row(raw_message="", response="ping", source_type="proactive")]
    msgs = conversations_to_messages(rows)
    assert all(m["role"] != "user" for m in msgs)
    assert len(msgs) == 1


def test_proactive_row_handles_missing_response():
    rows = [_row(response=None, source_type="proactive")]
    msgs = conversations_to_messages(rows)
    assert msgs == [{"role": "assistant", "content": "(I checked in:) "}]


def test_normal_row_renders_user_then_assistant_pair():
    rows = [_row(raw_message="had eggs", response="nice, logged it")]
    msgs = conversations_to_messages(rows)
    assert msgs == [
        {"role": "user", "content": "had eggs"},
        {"role": "assistant", "content": "nice, logged it"},
    ]


def test_mixed_rows_interleave_correctly():
    # CONTRACT: rows are passed newest-first (as get_recent_conversations returns them).
    # conversations_to_messages reverses internally → output is oldest-first (LLM order).
    rows = [
        _row(raw_message="yeah", response="let's go"),                    # newest
        _row(response="you still on for a workout?", source_type="proactive"),  # middle
        _row(raw_message="morning", response="hey"),                      # oldest
    ]
    msgs = conversations_to_messages(rows)
    assert msgs == [
        {"role": "user", "content": "morning"},
        {"role": "assistant", "content": "hey"},
        {"role": "assistant", "content": "(I checked in:) you still on for a workout?"},
        {"role": "user", "content": "yeah"},
        {"role": "assistant", "content": "let's go"},
    ]
