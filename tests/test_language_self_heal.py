"""Deterministic language self-heal — the Gi 2026-06-14 stale-pref case."""
from core.language import needs_language_reset, script_for_language


def test_gi_case_russian_pref_but_english_messages_resets():
    """Stored 'Russian' but every recent message is English → stale, reset."""
    texts = ["Having two slices of pizza", "Regular size", "Lucia on Avenue X",
             "Oat milk medium", "Yeah about 4 shots"]
    assert needs_language_reset("Russian", texts) is True


def test_genuine_russian_user_not_reset():
    """Recent messages actually in Cyrillic → real pref, keep it."""
    texts = ["Здорово, я не могу двигать телефон", "уже поел", "What's next"]
    assert needs_language_reset("Russian", texts) is False


def test_english_or_null_pref_never_resets():
    assert needs_language_reset(None, ["hi"]) is False
    assert needs_language_reset("English", ["hi"]) is False


def test_latin_script_language_never_resets():
    """Spanish is Latin-script — can't prove staleness by script, so never
    touch it (the prompt-level self-heal handles Latin-script langs)."""
    assert needs_language_reset("Spanish", ["had chicken and rice", "gym at 6"]) is False


def test_no_recent_texts_no_reset():
    """No evidence to judge from → conservative, don't reset."""
    assert needs_language_reset("Russian", []) is False
    assert needs_language_reset("Russian", [None, "", "   "]) is False


def test_chinese_japanese_korean_detection():
    assert needs_language_reset("Chinese", ["hello", "thanks"]) is True
    assert needs_language_reset("Chinese", ["你好", "thanks"]) is False
    assert needs_language_reset("Japanese", ["こんにちは"]) is False
    assert needs_language_reset("Korean", ["안녕하세요"]) is False


def test_script_for_language_latin_returns_none():
    assert script_for_language("French") is None
    assert script_for_language("Russian") is not None
