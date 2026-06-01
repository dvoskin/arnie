"""
Audio-message transcription for iMessage voice notes.

iMessage records voice notes as Core Audio Format (`.caf`, AAC/Opus inside),
which OpenAI Whisper does NOT accept. So we transcode whatever BlueBubbles hands
us to 16 kHz mono WAV with ffmpeg first — ffmpeg is format-agnostic, so the same
path handles `.caf`, `.amr`, `.m4a`, `.mp3`, etc.

ffmpeg isn't on the (pip-only) Render runtime, so we use the static binary bundled
by `imageio-ffmpeg`, falling back to a system ffmpeg on PATH for local dev. If no
ffmpeg is available at all, we still try Whisper on the original bytes (works when
the attachment is already an accepted format), then give up gracefully.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile

from multimodal.voice_handler import process_voice

logger = logging.getLogger(__name__)


def _ffmpeg_exe() -> str | None:
    """Path to an ffmpeg binary: imageio-ffmpeg's bundled static build, else PATH."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception as e:
        logger.debug(f"imageio-ffmpeg unavailable: {e}")
    return shutil.which("ffmpeg")


def _ext_of(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ".caf"  # iMessage default
    return "." + filename.rsplit(".", 1)[-1].lower()


async def transcode_to_wav(audio_bytes: bytes, src_ext: str = ".caf") -> bytes | None:
    """
    Transcode arbitrary audio to 16 kHz mono WAV via ffmpeg. Returns the WAV bytes,
    or None if ffmpeg is unavailable or the conversion fails. Input is written to a
    temp file (so ffmpeg can seek — more robust than a stdin pipe for `.caf`).
    """
    exe = _ffmpeg_exe()
    if not exe:
        logger.warning("No ffmpeg available — cannot transcode audio message")
        return None

    src_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=src_ext, delete=False) as f:
            f.write(audio_bytes)
            src_path = f.name
        proc = await asyncio.create_subprocess_exec(
            exe, "-hide_banner", "-loglevel", "error",
            "-i", src_path,
            "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0 or not out:
            logger.warning(
                f"ffmpeg transcode failed (rc={proc.returncode}): "
                f"{(err or b'').decode('utf-8', 'replace')[:200]}"
            )
            return None
        return out
    except Exception as e:
        logger.error(f"Audio transcode error: {e}")
        return None
    finally:
        if src_path:
            try:
                os.unlink(src_path)
            except OSError:
                pass


async def transcribe_audio_message(audio_bytes: bytes,
                                   transfer_name: str = "audio.caf") -> str:
    """
    Transcribe an iMessage audio attachment. Transcodes to WAV first (handles
    `.caf` and friends), then runs Whisper. Falls back to sending the original
    bytes straight to Whisper if transcoding isn't possible. Returns '' on failure
    (caller surfaces a friendly message). Requires OPENAI_API_KEY for the Whisper call.
    """
    if not audio_bytes:
        return ""

    wav = await transcode_to_wav(audio_bytes, _ext_of(transfer_name))
    if wav:
        text = await process_voice(wav, "audio.wav")
        if text:
            return text.strip()
        logger.warning("Whisper returned empty for transcoded WAV")

    # Fallback: maybe the attachment was already an accepted format.
    text = await process_voice(audio_bytes, transfer_name or "audio.m4a")
    return (text or "").strip()
