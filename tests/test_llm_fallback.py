"""Anthropic -> OpenAI fallback so a sustained Anthropic outage doesn't take
Arnie fully dark (AUDIT.md #8)."""
import os
import importlib
import pytest


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    import core.llm as m
    importlib.reload(m)
    return m


async def test_chat_falls_back_to_openai_when_anthropic_fails(llm):
    async def boom(*a, **k):
        raise RuntimeError("anthropic 529 overloaded")

    async def ok(messages, system, tools, max_tokens):
        return {"text": "fallback", "tool_calls": [], "raw_content": None, "stop_reason": "end"}

    llm._anthropic_chat = boom
    llm._openai_chat = ok
    r = await llm.chat([{"role": "user", "content": "hi"}], system="s")
    assert r["text"] == "fallback"


async def test_chat_raises_if_both_fail(llm):
    async def boom(*a, **k):
        raise RuntimeError("down")
    llm._anthropic_chat = boom
    llm._openai_chat = boom
    with pytest.raises(Exception):
        await llm.chat([{"role": "user", "content": "hi"}], system="s")


async def test_follow_up_returns_empty_on_failure(llm):
    async def boom(*a, **k):
        raise RuntimeError("boom")
    llm._anthropic_follow_up = boom
    # empty -> caller uses deterministic_confirmation instead of erroring
    assert await llm.chat_follow_up([], None, [], {}, "s") == ""
