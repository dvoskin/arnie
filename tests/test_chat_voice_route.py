"""
/chat/voice — the native (iOS) voice-note route's transcription outcomes.

Three outcomes, three answers. They used to collapse into one 422
"empty_transcript": a missing OPENAI_API_KEY, a Whisper error and a genuinely
silent clip all read the same to the app, and the real cause lived only in the
server log. Whisper + ffmpeg are stubbed — this pins the routing, not the binaries.
"""
import base64

import pytest
from fastapi import HTTPException

import api.chat as C
import multimodal.audio as audio
import multimodal.voice_handler as VH


def _req(payload: bytes = b"m4a-bytes", filename: str = "voice.m4a"):
    return C.VoiceChatRequest(audio_base64=base64.b64encode(payload).decode(),
                              filename=filename)


@pytest.fixture
def transcribing(monkeypatch):
    """Key present, ffmpeg 'works', and a programmable Whisper."""
    monkeypatch.setattr("core.llm.OPENAI_API_KEY", lambda: "sk-test")

    async def fake_transcode(b, ext=".m4a"):
        return b"WAV:" + b
    monkeypatch.setattr(audio, "transcode_to_wav", fake_transcode)

    class Whisper:
        def __init__(self):
            self.results = []
            self.calls = []

        async def __call__(self, data, filename="voice.ogg"):
            self.calls.append((data, filename))
            out = self.results.pop(0)
            if isinstance(out, Exception):
                raise out
            return out
    w = Whisper()
    monkeypatch.setattr(VH, "transcribe_voice", w)
    return w


async def _status_of(coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    return exc.value.status_code, exc.value.detail


async def test_transcript_reaches_the_coaching_turn(transcribing, monkeypatch):
    seen = []

    async def spy(identity, text, source_type, **kw):
        seen.append((text, source_type))
        return {"bubbles": ["ok"]}
    monkeypatch.setattr(C, "_coached_reply", spy)
    transcribing.results = ["two eggs and a coffee"]

    await C.chat_voice(_req(), identity="ios:voice-route")

    assert seen == [("[Voice note]: two eggs and a coffee", "voice")]
    # Whisper got the transcoded WAV, not the raw container.
    assert transcribing.calls == [(b"WAV:m4a-bytes", "audio.wav")]


async def test_empty_transcript_is_422_only_after_both_attempts(transcribing):
    transcribing.results = ["", ""]   # heard nothing in the WAV, nor in the raw bytes
    status, detail = await _status_of(C.chat_voice(_req(), identity="ios:voice-route"))
    assert (status, detail) == (422, "empty_transcript")
    assert [f for _, f in transcribing.calls] == ["audio.wav", "voice.m4a"]


async def test_whisper_error_is_502_not_empty_transcript(transcribing):
    transcribing.results = [RuntimeError("Invalid file format")]
    status, detail = await _status_of(C.chat_voice(_req(), identity="ios:voice-route"))
    assert (status, detail) == (502, "transcription_failed")


async def test_missing_api_key_is_503_not_empty_transcript(transcribing, monkeypatch):
    # Without a key, transcribe_voice returns "" without calling Whisper — the
    # route must not tell the user to re-record something we never listened to.
    monkeypatch.setattr("core.llm.OPENAI_API_KEY", lambda: "")
    transcribing.results = ["", ""]
    status, detail = await _status_of(C.chat_voice(_req(), identity="ios:voice-route"))
    assert (status, detail) == (503, "transcription_unavailable")


async def test_raw_bytes_fallback_when_ffmpeg_unavailable(transcribing, monkeypatch):
    async def no_ffmpeg(b, ext=".m4a"):
        return None
    monkeypatch.setattr(audio, "transcode_to_wav", no_ffmpeg)
    transcribing.results = ["banana"]
    seen = []

    async def spy(identity, text, source_type, **kw):
        seen.append(text)
        return {}
    monkeypatch.setattr(C, "_coached_reply", spy)

    await C.chat_voice(_req(filename="note.m4a"), identity="ios:voice-route")

    assert transcribing.calls == [(b"m4a-bytes", "note.m4a")]
    assert seen == ["[Voice note]: banana"]


# ── process_voice keeps its swallow-to-empty contract for the bot callers ─────

async def test_process_voice_swallows_by_default_and_raises_when_strict(monkeypatch):
    async def boom(data, filename="voice.ogg"):
        raise RuntimeError("quota")
    monkeypatch.setattr(VH, "transcribe_voice", boom)

    assert await VH.process_voice(b"x", "a.ogg") == ""
    with pytest.raises(VH.TranscriptionFailed):
        await VH.process_voice(b"x", "a.ogg", strict=True)
