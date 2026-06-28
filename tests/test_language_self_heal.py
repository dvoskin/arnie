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


# ── reply_language_directive — the INTERACTIVE self-heal (latest message wins) ──
from core.language import reply_language_directive


def test_directive_fires_when_stored_russian_but_latest_is_english():
    d = reply_language_directive("Russian", "hey what's my protein at today")
    assert d is not None
    assert "Russian" in d and "latest message" in d.lower()


def test_directive_silent_when_latest_matches_stored_script():
    # still writing Russian → no override needed
    assert reply_language_directive("Russian", "сколько у меня белка сегодня") is None


def test_directive_silent_for_latin_or_null_pref():
    # English/Spanish/null stored language → script can't disambiguate → no directive
    assert reply_language_directive("English", "hola que tal") is None
    assert reply_language_directive("Spanish", "had chicken and rice") is None
    assert reply_language_directive(None, "anything") is None


def test_directive_silent_on_empty_message():
    assert reply_language_directive("Russian", "") is None
    assert reply_language_directive("Russian", None) is None


def test_directive_fires_for_other_nonlatin_scripts():
    assert reply_language_directive("Chinese", "what's my recovery") is not None
    assert reply_language_directive("Chinese", "我的恢复怎么样") is None
