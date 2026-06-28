"""Deterministic language helpers for proactive sends.

The problem (Gi, 2026-06-14): a single foreign-language message freezes
`UserPreferences.preferred_language` via the onboarding LANGUAGE rule. Interactive
replies still match each message live, but the proactive scheduler reads the
stored pref — so one stray Russian text made every check-in Russian while the
user kept writing English.

This module gives a cheap, deterministic stale-pref check based on WRITING
SCRIPT. It only fires for non-Latin-script languages (Russian/Cyrillic,
Chinese/Japanese/Korean, Arabic, Hebrew, Greek, Thai, Hindi), where the script
alone proves which language the user is actually writing. Latin-script languages
(Spanish, French, German, …) can't be told apart from English by script, so we
never touch those — the prompt-level LANGUAGE self-heal covers them instead.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# Unicode script ranges, compiled once.
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_HAN = re.compile(r"[一-鿿]")
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")  # kana + kanji
_KOREAN = re.compile(r"[가-힯]")
_ARABIC = re.compile(r"[؀-ۿ]")
_HEBREW = re.compile(r"[֐-׿]")
_GREEK = re.compile(r"[Ͱ-Ͽ]")
_THAI = re.compile(r"[฀-๿]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Language name (as the LLM stores it, English, lowercased) → its writing script.
# ONLY non-Latin-script languages belong here; a language absent from this map is
# treated as "can't disambiguate by script" and never triggers a reset.
_LANG_SCRIPT: dict[str, re.Pattern] = {
    "russian": _CYRILLIC, "ukrainian": _CYRILLIC, "bulgarian": _CYRILLIC,
    "serbian": _CYRILLIC, "macedonian": _CYRILLIC, "belarusian": _CYRILLIC,
    "chinese": _HAN, "mandarin": _HAN, "cantonese": _HAN,
    "japanese": _JAPANESE, "korean": _KOREAN,
    "arabic": _ARABIC, "hebrew": _HEBREW, "greek": _GREEK,
    "thai": _THAI, "hindi": _DEVANAGARI,
}


def script_for_language(language: Optional[str]) -> Optional[re.Pattern]:
    """The writing-script regex for a stored language name, or None when the
    language is Latin-script / unknown (and so can't be checked by script)."""
    if not language:
        return None
    return _LANG_SCRIPT.get(language.strip().lower())


def reply_language_directive(
    preferred_language: Optional[str],
    user_message: Optional[str],
) -> Optional[str]:
    """A deterministic, top-priority reply-language anchor for INTERACTIVE turns.

    Targets the 'frozen in a non-Latin language' bug: once `preferred_language`
    locked to e.g. Russian, a heavily-Russian conversation history could keep
    Arnie replying in Russian even after the user switched BACK to English — the
    per-message LANGUAGE prompt rule loses to conversational momentum.

    Fires ONLY when the stored language is a non-Latin script AND the user's
    latest message is NOT in that script (i.e. they switched to a Latin-script
    language). Returns None otherwise — zero noise for English/Latin users (whose
    Latin↔Latin switches the prompt already handles, since script can't tell
    English from Spanish). The injected directive makes the latest message's
    language authoritative over the history."""
    script = script_for_language(preferred_language)
    if script is None:                       # Latin / unknown / null pref → nothing to override
        return None
    if not user_message or not user_message.strip():
        return None
    if script.search(user_message):          # latest IS in the stored non-Latin script → fine
        return None
    return (
        f"[REPLY LANGUAGE — AUTHORITATIVE] The user's CURRENT message is NOT written in "
        f"{preferred_language} (their stored language); they have switched to the "
        f"Latin-script language they just typed (English unless the words are clearly "
        f"Spanish/French/etc.). Reply in THAT language. Do NOT reply in {preferred_language} "
        f"or any non-Latin language just because earlier messages in this conversation used "
        f"it — the latest message's language wins, every single turn."
    )


def needs_language_reset(
    preferred_language: Optional[str],
    recent_user_texts: Iterable[Optional[str]],
) -> bool:
    """True when `preferred_language` is a non-Latin-script language but NONE of
    the recent USER messages actually use that script — i.e. the stored pref is
    stale and proactive sends would go out in a language the user isn't writing.

    Conservative by construction:
      - returns False for English / null / Latin-script languages (can't prove
        staleness by script — leave them to the prompt-level self-heal).
      - returns False when there are no recent user texts to judge from.
    """
    script = script_for_language(preferred_language)
    if script is None:
        return False
    texts = [t for t in recent_user_texts if t and t.strip()]
    if not texts:
        return False
    # If ANY recent user message uses the language's script, the pref is real.
    if any(script.search(t) for t in texts):
        return False
    return True
