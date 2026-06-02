"""Dashboard hand-off line — must read as a mid-conversation continuation, never a
fresh greeting ("yo Danny"). Covers the deterministic fallbacks; the live LLM line is
checked in tests/test_coaching_behavior.py (gated)."""
import re
from core.blurbs import _DASH_FALLBACKS

_GREETING = re.compile(r"^(yo|hey|hi|sup|hello|howdy)\b", re.I)


def test_fallbacks_do_not_open_with_a_greeting():
    for f in _DASH_FALLBACKS:
        assert not _GREETING.match(f.strip()), f"fallback opens with a greeting: {f!r}"


def test_fallbacks_have_no_link_or_unfilled_name_placeholder():
    for f in _DASH_FALLBACKS:
        assert "http" not in f.lower(), f"fallback contains a url: {f!r}"
        assert "{" not in f and "}" not in f, f"fallback has an unfilled placeholder: {f!r}"
