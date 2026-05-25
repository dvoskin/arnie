import logging
from core.llm import transcribe_voice

logger = logging.getLogger(__name__)


async def process_voice(audio_data: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe a Telegram voice note. Returns empty string on failure."""
    try:
        return await transcribe_voice(audio_data, filename)
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        return ""
