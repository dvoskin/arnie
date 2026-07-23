"""Model safety-net (A, 2026-07-23): a bad configured model degrades to a
known-good Anthropic model instead of taking the turn dark, the real error is
logged, and a placeholder OpenAI key is never chased. Switch: MODEL_FALLBACK."""
import pytest
import core.llm as L


def _ok(model):
    return {"text": f"ok from {model}", "tool_calls": [], "raw_content": [],
            "stop_reason": "end_turn"}


@pytest.mark.asyncio
async def test_fallback_retries_known_good_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_FALLBACK", "true")
    monkeypatch.setenv("DEFAULT_MODEL", "claude-broken-9")
    monkeypatch.setenv("FALLBACK_MODEL", "claude-sonnet-4-6")

    seen = []
    async def fake(messages, system, use_tools, max_tokens, model=None, stream_handler=None):
        seen.append(model)
        if model == "claude-broken-9":
            raise RuntimeError("not_found_error: model claude-broken-9")
        return _ok(model)
    monkeypatch.setattr(L, "_anthropic_chat", fake)

    r = await L.chat([{"role": "user", "content": "hi"}], "SYS")
    assert r["text"] == "ok from claude-sonnet-4-6"
    assert seen == ["claude-broken-9", "claude-sonnet-4-6"]  # primary, then fallback


@pytest.mark.asyncio
async def test_switch_off_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_FALLBACK", "false")
    monkeypatch.setenv("DEFAULT_MODEL", "claude-broken-9")
    monkeypatch.setenv("OPENAI_API_KEY", "your-openai-key-here")  # placeholder

    async def fake(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(L, "_anthropic_chat", fake)

    with pytest.raises(RuntimeError):
        await L.chat([{"role": "user", "content": "hi"}], "SYS")


@pytest.mark.asyncio
async def test_placeholder_openai_key_never_chased(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_FALLBACK", "true")
    monkeypatch.setenv("DEFAULT_MODEL", "claude-broken-9")
    monkeypatch.setenv("FALLBACK_MODEL", "claude-also-broken")
    monkeypatch.setenv("OPENAI_API_KEY", "your-openai-key-here")  # placeholder, not sk-

    async def fake(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(L, "_anthropic_chat", fake)
    hit = {"openai": False}
    async def fake_oai(*a, **k):
        hit["openai"] = True
        return _ok("gpt-4o")
    monkeypatch.setattr(L, "_openai_chat", fake_oai)

    with pytest.raises(RuntimeError):
        await L.chat([{"role": "user", "content": "hi"}], "SYS")
    assert hit["openai"] is False  # a 'your-key' placeholder must never be attempted
