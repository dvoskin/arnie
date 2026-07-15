"""Pin the Sonnet 5 vision regression: thinking blocks in vision responses.

2026-07-11→15: analyze_image omitted the thinking param; Sonnet 5 runs
ADAPTIVE thinking when it's omitted, hard visual tasks (estimating a plated
meal) triggered it, `response.content[0]` became a thinking block, and
`.text` raised AttributeError — 71% of food photos collapsed to "hit a snag"
while easy label-reads (packaged products) sailed through.

These tests run the REAL analyze_image against a mocked Anthropic client, so
the block-order handling and the explicit thinking=disabled contract can
never silently regress, no network needed.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import core.llm as llm


def _block(type_, text=None):
    b = SimpleNamespace(type=type_)
    if text is not None:
        b.text = text
    return b


def _client_returning(content):
    client = SimpleNamespace()
    client.messages = SimpleNamespace(create=AsyncMock(
        return_value=SimpleNamespace(content=content)))
    return client


_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32   # minimal JPEG magic for the sniffer


@pytest.mark.asyncio
async def test_thinking_block_first_still_returns_text():
    """The exact prod failure shape: [thinking, text] — must return the text,
    never touch .text on the thinking block."""
    client = _client_returning([
        _block("thinking"),                      # no .text attribute at all
        _block("text", "[FOOD_LOG]\n• Chicken, 200g\n[/FOOD_LOG]"),
    ])
    with patch.object(llm, "_get_anthropic", return_value=client), \
         patch.object(llm, "ANTHROPIC_API_KEY", return_value="k"):
        out = await llm.analyze_image(_JPEG, "prompt")
    assert out.startswith("[FOOD_LOG]")


@pytest.mark.asyncio
async def test_thinking_only_response_returns_empty_not_crash():
    """Budget burned entirely on thinking → no text block. Empty string (the
    caller renders a graceful UNKNOWN), never an exception."""
    client = _client_returning([_block("thinking")])
    with patch.object(llm, "_get_anthropic", return_value=client), \
         patch.object(llm, "ANTHROPIC_API_KEY", return_value="k"):
        out = await llm.analyze_image(_JPEG, "prompt")
    assert out == ""


@pytest.mark.asyncio
async def test_vision_call_disables_thinking_explicitly():
    """The contract that prevents the whole class: vision calls MUST pass
    thinking=disabled — adaptive thinking is what broke prepared-meal photos."""
    client = _client_returning([_block("text", "ok")])
    with patch.object(llm, "_get_anthropic", return_value=client), \
         patch.object(llm, "ANTHROPIC_API_KEY", return_value="k"):
        await llm.analyze_image(_JPEG, "prompt")
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs.get("thinking") == {"type": "disabled"}


@pytest.mark.asyncio
async def test_plain_text_response_unchanged():
    client = _client_returning([_block("text", "PREPARED_MEAL")])
    with patch.object(llm, "_get_anthropic", return_value=client), \
         patch.object(llm, "ANTHROPIC_API_KEY", return_value="k"):
        out = await llm.analyze_image(_JPEG, "prompt", max_tokens=20)
    assert out == "PREPARED_MEAL"
