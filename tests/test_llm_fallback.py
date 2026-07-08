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


# ── Thinking OFF, explicitly (Sonnet 5 adaptive-thinking guard) ───────────────

class _RecordingMessages:
    def __init__(self):
        self.kwargs = None
    async def create(self, **kwargs):
        self.kwargs = kwargs
        from types import SimpleNamespace as NS
        return NS(content=[NS(type="text", text="ok")], stop_reason="end_turn")


class _RecordingClient:
    def __init__(self):
        self.messages = _RecordingMessages()


async def test_anthropic_chat_disables_thinking(llm, monkeypatch):
    """Sonnet 5 runs adaptive thinking when `thinking` is OMITTED — which adds
    latency to simple prompts and lets hidden thinking tokens truncate replies.
    Every chat call MUST pass thinking={'type':'disabled'} explicitly."""
    client = _RecordingClient()
    monkeypatch.setattr(llm, "_get_anthropic", lambda: client)
    await llm._anthropic_chat([{"role": "user", "content": "hi"}], "SYS",
                              use_tools=False, max_tokens=100)
    assert client.messages.kwargs["thinking"] == {"type": "disabled"}


async def test_anthropic_follow_up_disables_thinking(llm, monkeypatch):
    client = _RecordingClient()
    monkeypatch.setattr(llm, "_get_anthropic", lambda: client)
    await llm._anthropic_follow_up(
        [{"role": "user", "content": "hi"}], [{"type": "text", "text": "x"}],
        [{"name": "t", "id": "1"}], {"t": "done"}, "SYS", max_tokens=100,
    )
    assert client.messages.kwargs["thinking"] == {"type": "disabled"}
