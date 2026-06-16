"""
Image media-type sniffing for the vision call.

Regression guard for the iOS photo 400: screenshots are PNG but the backend
declared every image image/jpeg, so the Anthropic vision API rejected them
("appears to be a image/png image") and every photo log — food OR workout —
dead-ended with "hit a snag analyzing this". analyze_image now sniffs the real
format from the magic bytes and ignores the (often wrong) caller hint.
"""
import asyncio
from unittest.mock import patch

import pytest

from core.llm import _sniff_image_mime, analyze_image


# Minimal but valid magic-byte prefixes for each format (padded past the 12-byte
# floor the sniffer needs).
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16  # default iOS camera format


def run(coro):
    """Fresh event loop per call — matches tests/test_photo_pipeline_smoke.py."""
    return asyncio.run(coro)


# ─── _sniff_image_mime ──────────────────────────────────────────────────────

@pytest.mark.parametrize("data,expected", [
    (PNG, "image/png"),
    (JPEG, "image/jpeg"),
    (GIF, "image/gif"),
    (WEBP, "image/webp"),
    (HEIC, None),                  # recognized but unsupported → None (+ warns)
    (b"not-an-image-at-all-xx", None),
    (b"\x89PNG", None),            # too short to classify
    (b"", None),
])
def test_sniff(data, expected):
    assert _sniff_image_mime(data) == expected


# ─── analyze_image uses the sniffed type, not the hint ──────────────────────

class _FakeMessages:
    def __init__(self, sink):
        self._sink = sink

    async def create(self, **kwargs):
        self._sink.update(kwargs)

        class _Block:
            text = "OK"

        class _Resp:
            content = [_Block()]

        return _Resp()


class _FakeClient:
    def __init__(self, sink):
        self.messages = _FakeMessages(sink)


def _sent_media_type(image_bytes: bytes, hint: str) -> str:
    """Run analyze_image against a fake client and return the media_type that
    actually went out on the wire."""
    sink: dict = {}
    with patch("core.llm._get_anthropic", return_value=_FakeClient(sink)), \
         patch("core.llm.ANTHROPIC_API_KEY", return_value="test-key"):
        run(analyze_image(image_bytes, "describe", mime_type=hint))
    image_block = sink["messages"][0]["content"][0]
    return image_block["source"]["media_type"]


def test_png_sent_as_jpeg_is_corrected():
    # The exact prod bug: caller declares jpeg, bytes are PNG → must send png.
    assert _sent_media_type(PNG, "image/jpeg") == "image/png"


def test_real_jpeg_passes_through():
    assert _sent_media_type(JPEG, "image/jpeg") == "image/jpeg"


def test_unknown_bytes_fall_back_to_hint():
    # No reliable sniff → keep the caller's hint rather than guess wrong.
    assert _sent_media_type(b"random-non-image-bytes", "image/jpeg") == "image/jpeg"
