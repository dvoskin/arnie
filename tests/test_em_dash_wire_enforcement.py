"""
Em-dash wire enforcement — the brand rule says "no em dashes" and the
sanitizer in core/platform.py::_sanitize_bubble enforces it deterministically
on the way out. The streaming path (Telegram) and the on_interim heads-up
path (iMessage) used to BYPASS Response.from_text, so em dashes the model
slipped past the prompt rule reached the user verbatim despite the rule
being technically present.

These tests pin that:
  • _sanitize_bubble itself substitutes em dashes correctly
  • _BubbleStreamer._emit sanitizes BEFORE calling on_bubble (Telegram fix)
  • run_turn's on_interim callsite sanitizes BEFORE invoking the callback
    (iMessage heads-up fix)
  • Response.from_text continues to sanitize (legacy path)
  • Idempotence — calling sanitize on already-clean text leaves it unchanged
  • Hyphens (-) and en-dashes (–) are NOT touched (number ranges, brand
    names like "Built bar 11-12g protein" must survive)
"""
import pytest

from core.platform import Response, _sanitize_bubble


# ── _sanitize_bubble unit ────────────────────────────────────────────────────


def test_sanitize_replaces_em_dash_with_comma():
    """The canonical case from the screenshots: '— ' between clauses
    becomes ', '."""
    assert _sanitize_bubble("Before I lock it in — was this small?") \
        == "Before I lock it in, was this small?"


def test_sanitize_replaces_unspaced_em_dash():
    """Some models emit em dash without surrounding spaces ('word—word').
    Still replaced (the existing fallback path)."""
    out = _sanitize_bubble("good meal—solid protein")
    assert "—" not in out


def test_sanitize_handles_multiple_em_dashes_in_one_bubble():
    """A single message can contain multiple em dashes (a common Claude
    pattern). All get replaced."""
    out = _sanitize_bubble("Got it — solid call — keep it going")
    assert "—" not in out
    assert "Got it, solid call, keep it going" == out


def test_sanitize_does_not_touch_hyphens():
    """Hyphen-minus '-' is used in number ranges ('12-13%'), brand names
    ('Built-bar'), word compounds ('post-workout'). Must survive
    untouched."""
    inputs = [
        "12-13% body fat",
        "post-workout shake",
        "the 5-rep PR",
        "high-protein meal",
    ]
    for s in inputs:
        assert _sanitize_bubble(s) == s, f"hyphen disturbed in: {s!r}"


def test_sanitize_does_not_touch_en_dashes():
    """En dash '–' (U+2013) is sometimes used for number ranges. Must
    survive — only em dash U+2014 is banned by the brand rule."""
    s = "2–3 cubes each"  # en dash, NOT em dash
    assert _sanitize_bubble(s) == s


def test_sanitize_is_idempotent():
    """Applying sanitize twice must yield the same result. This is what
    lets us add the call to the streaming path without worrying about
    Response.from_text running it a second time on catch-up."""
    inputs = [
        "Before I lock it in — was this small?",
        "Got it, solid call",
        "12-13% body fat",
        "",
    ]
    for s in inputs:
        once = _sanitize_bubble(s)
        twice = _sanitize_bubble(once)
        assert once == twice, f"not idempotent: {s!r} → {once!r} → {twice!r}"


def test_sanitize_handles_empty_and_none():
    """Defensive: empty / None input must not crash."""
    assert _sanitize_bubble("") == ""
    assert _sanitize_bubble(None) == ""


def test_sanitize_collapses_double_space_after_replacement():
    """An em dash flanked by spaces collapses to ', ' — no double space."""
    out = _sanitize_bubble("hello — world")
    assert "  " not in out
    assert out == "hello, world"


# ── Response.from_text — the canonical (non-streaming) path ─────────────────


def test_response_from_text_strips_em_dashes_per_bubble():
    """The existing path: Response.from_text → split on ||| → sanitize each
    bubble. Verifies the legacy enforcement is still alive."""
    resp = Response.from_text("Got it — solid|||1,200 cal — light day")
    assert all("—" not in b for b in resp.bubbles)
    assert resp.bubbles == ["Got it, solid", "1,200 cal, light day"]


# ── _BubbleStreamer — Telegram streaming path (was the leak) ────────────────


@pytest.mark.asyncio
async def test_streamer_emit_strips_em_dashes_before_calling_on_bubble():
    """The Telegram bug: streamer emitted bubbles directly to on_text_bubble
    without sanitization. Pin that the leak is closed."""
    from core.conversation import _BubbleStreamer

    received: list[str] = []

    async def _capture(text):
        received.append(text)

    streamer = _BubbleStreamer(_capture)
    # Simulate a streamed delta containing an em dash, then |||
    await streamer.on_delta("Before I lock it in — was this small?|||Got it.")
    await streamer.finalize()

    assert received, "streamer did not emit"
    for bubble in received:
        assert "—" not in bubble, f"em dash leaked through stream: {bubble!r}"


@pytest.mark.asyncio
async def test_streamer_emit_preserves_hyphens():
    """Hyphens in streamed text (number ranges, brand names) must survive
    — sanitize must not over-reach."""
    from core.conversation import _BubbleStreamer

    received: list[str] = []

    async def _capture(text):
        received.append(text)

    streamer = _BubbleStreamer(_capture)
    await streamer.on_delta("you're at 12-13% body fat|||post-workout shake next.")
    await streamer.finalize()

    assert received == ["you're at 12-13% body fat", "post-workout shake next."]


@pytest.mark.asyncio
async def test_streamer_emit_handles_em_dash_mid_buffer_across_chunks():
    """Streaming delivers chunks that may split text mid-clause. The em
    dash must still be sanitized once the bubble completes (||| arrives)."""
    from core.conversation import _BubbleStreamer

    received: list[str] = []

    async def _capture(text):
        received.append(text)

    streamer = _BubbleStreamer(_capture)
    # Chunk 1: text up to (but not including) the dash
    await streamer.on_delta("Got it ")
    # Chunk 2: dash and continuation
    await streamer.on_delta("— solid call")
    # Chunk 3: bubble separator
    await streamer.on_delta("|||1,200 cal so far.")
    await streamer.finalize()

    assert received == ["Got it, solid call", "1,200 cal so far."]


# ── run_turn's on_interim callsite — iMessage heads-up path ─────────────────


@pytest.mark.asyncio
async def test_on_interim_path_sanitizes_em_dashes(monkeypatch, make_user, db):
    """When the model writes a heads-up bubble before a slow tool and that
    bubble contains an em dash, the iMessage interim send must strip it
    before invoking the on_interim callback. Pin the iMessage fix."""
    import core.conversation as C

    user = await make_user(telegram_id="im-em-dash")
    seen_interims: list[str] = []

    async def _capture_interim(text):
        seen_interims.append(text)

    async def _fake_chat(messages, system, tools=True, max_tokens=4096,
                          model=None, stream_handler=None):
        return {
            # First-pass text with an em dash — the bug scenario.
            "text": "lemme check your log — give me a sec.",
            "tool_calls": [{"name": "query_history", "id": "q1",
                            "input": {"metric": "food_entries",
                                      "period": "last saturday"}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system,
                              max_tokens=512, stream_handler=None):
        return "saturday recap. 1,500 cal."

    async def _fake_execute(tool_calls, user, log, db, source_type, **_kw):
        return {"query_history": "HISTORY data"}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "what did i eat saturday?"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
        on_interim=_capture_interim,
    )

    assert seen_interims, "on_interim was not called"
    for text in seen_interims:
        assert "—" not in text, f"em dash leaked through on_interim: {text!r}"
