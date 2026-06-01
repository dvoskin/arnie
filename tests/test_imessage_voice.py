"""
iMessage voice-note path: attachment detection + transcription orchestration.

Pure/unit coverage. The end-to-end "transcript flows into the pipeline" check
lives in test_pipeline.py (reuses the pipeline harness). ffmpeg + Whisper are
stubbed here — we test the routing logic, not the binaries.
"""
import pytest

import bot.imessage_handler as H
import multimodal.audio as audio


# ── extract_audio_attachment (pure) ───────────────────────────────────────────

def test_detects_audio_by_mimetype():
    d = {"attachments": [{"guid": "g1", "mimeType": "audio/x-caf",
                          "transferName": "Audio Message.caf"}]}
    att = H.extract_audio_attachment(d)
    assert att == {"guid": "g1", "transfer_name": "Audio Message.caf", "mime": "audio/x-caf"}


def test_detects_audio_by_extension_without_mime():
    d = {"attachments": [{"guid": "g2", "transferName": "voice.caf"}]}
    assert H.extract_audio_attachment(d)["guid"] == "g2"


def test_detects_audio_by_uti():
    d = {"attachments": [{"guid": "g3", "uti": "com.apple.coreaudio-format",
                          "transferName": "x"}]}
    assert H.extract_audio_attachment(d)["guid"] == "g3"


def test_ignores_image_attachment():
    d = {"attachments": [{"guid": "i1", "mimeType": "image/jpeg",
                          "transferName": "IMG_1.jpg"}]}
    assert H.extract_audio_attachment(d) is None


def test_no_attachments_returns_none():
    assert H.extract_audio_attachment({}) is None
    assert H.extract_audio_attachment({"attachments": []}) is None


def test_attachment_without_guid_skipped():
    d = {"attachments": [{"mimeType": "audio/x-caf"}]}
    assert H.extract_audio_attachment(d) is None


def test_picks_audio_among_mixed():
    d = {"attachments": [
        {"guid": "img", "mimeType": "image/png", "transferName": "a.png"},
        {"guid": "snd", "mimeType": "audio/amr", "transferName": "b.amr"},
    ]}
    assert H.extract_audio_attachment(d)["guid"] == "snd"


# ── transcribe_audio_message (orchestration, ffmpeg+whisper stubbed) ───────────

class _FakeVoice:
    """Records process_voice calls and returns programmed results in order."""
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def __call__(self, data, filename="audio"):
        self.calls.append((data, filename))
        return self.results.pop(0) if self.results else ""


async def test_transcode_then_whisper(monkeypatch):
    async def fake_transcode(b, ext=".caf"):
        return b"WAVDATA"
    fv = _FakeVoice("chicken bowl and rice")
    monkeypatch.setattr(audio, "transcode_to_wav", fake_transcode)
    monkeypatch.setattr(audio, "process_voice", fv)

    out = await audio.transcribe_audio_message(b"CAFBYTES", "Audio Message.caf")
    assert out == "chicken bowl and rice"
    # Whisper was given the transcoded WAV, not the raw caf
    assert fv.calls == [(b"WAVDATA", "audio.wav")]


async def test_falls_back_to_original_when_transcode_unavailable(monkeypatch):
    async def no_ffmpeg(b, ext=".caf"):
        return None
    fv = _FakeVoice("hello from m4a")
    monkeypatch.setattr(audio, "transcode_to_wav", no_ffmpeg)
    monkeypatch.setattr(audio, "process_voice", fv)

    out = await audio.transcribe_audio_message(b"M4ABYTES", "note.m4a")
    assert out == "hello from m4a"
    assert fv.calls == [(b"M4ABYTES", "note.m4a")]  # original bytes tried


async def test_returns_empty_when_all_transcription_fails(monkeypatch):
    async def fake_transcode(b, ext=".caf"):
        return b"WAVDATA"
    fv = _FakeVoice("", "")  # whisper fails on both wav and fallback
    monkeypatch.setattr(audio, "transcode_to_wav", fake_transcode)
    monkeypatch.setattr(audio, "process_voice", fv)

    assert await audio.transcribe_audio_message(b"X", "a.caf") == ""


async def test_empty_audio_short_circuits(monkeypatch):
    fv = _FakeVoice("should not be called")
    monkeypatch.setattr(audio, "process_voice", fv)
    assert await audio.transcribe_audio_message(b"", "a.caf") == ""
    assert fv.calls == []


# ── bb_download_attachment: safe when unconfigured ────────────────────────────

async def test_download_returns_none_when_unconfigured(monkeypatch):
    # No BLUEBUBBLES_URL/PASSWORD in the test env → no network, returns None.
    monkeypatch.setattr(H, "_BB_URL", "")
    monkeypatch.setattr(H, "_BB_PASSWORD", "")
    assert await H.bb_download_attachment("any-guid") is None
