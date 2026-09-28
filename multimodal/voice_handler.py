import logging
from core.llm import transcribe_voice

logger = logging.getLogger(__name__)


class TranscriptionFailed(Exception):
    """Whisper raised — the audio was never judged. Distinct from an EMPTY
    transcript (Whisper ran and heard nothing), which callers report as a
    "didn't catch that" while this is a "couldn't transcribe" they should
    say so about, and which should land in the logs with its real cause."""


async def process_voice(audio_data: bytes, filename: str = "voice.ogg", *,
                        strict: bool = False) -> str:
    """Transcribe a voice note. Returns empty string on failure.

    `strict=True` re-raises a transcription error as `TranscriptionFailed`
    instead of collapsing it to "" — the native chat route needs to tell
    "the transcription service broke" (a 5xx to fix on our side) from
    "the clip had nothing in it" (a 422 the user can fix by re-recording).
    The Telegram / iMessage callers keep the swallow-to-empty contract."""
    try:
        return await transcribe_voice(audio_data, filename)
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        if strict:
            raise TranscriptionFailed(str(e)) from e
        return ""
