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


# ── command locale (B-1) ─────────────────────────────────────────────────────
#
# WHY A CLARIFICATION NEEDS A LOCALE AT ALL.
#
# `skills.nutrition.answer_parsers.parse_command` is an ENGLISH phrase parser
# that decides whether to cancel a meal, skip an item, or assume a portion.
# Run against text in another language it is not neutral — it is a matcher with
# no idea the ground moved. This repo has shipped that exact defect before:
# EN-only rescue detectors in the food lane let Russian meals go unlogged
# (2026-08-03). The routing gate was fixed then; the DETECTORS were not, and
# this is one of them.
#
# Today the English patterns mostly return nothing on foreign text by luck —
# "не знаю" and "no importa" match no rule, and the anchored bare `cancel`
# does not fire on "cancela". This turns that luck into a guarantee before
# B-1.8's constrained classifier widens the surface. The case it genuinely
# closes is MIXED script: a Russian message carrying an English brand name or
# a transliterated fragment.

ENGLISH = "en"
UNKNOWN_LOCALE = "und"

#: Stored `preferred_language` values that mean "English". The column holds
#: an LLM-written language NAME, not a code, and null means English/auto.
_ENGLISH_NAMES = frozenset({"english", "en", "en-us", "en-gb", "american english",
                            "british english"})

#: Language name -> locale code, for the scripts we can prove. Latin-script
#: languages are deliberately absent: script cannot tell Spanish from English,
#: so they resolve from the stored preference or not at all.
_LOCALE_OF = {
    "russian": "ru", "ukrainian": "uk", "bulgarian": "bg", "serbian": "sr",
    "macedonian": "mk", "belarusian": "be", "chinese": "zh",
    "mandarin": "zh", "cantonese": "zh", "japanese": "ja", "korean": "ko",
    "arabic": "ar", "hebrew": "he", "greek": "el", "thai": "th",
    "hindi": "hi", "spanish": "es", "french": "fr", "german": "de",
    "portuguese": "pt", "italian": "it", "dutch": "nl", "polish": "pl",
    "turkish": "tr", "vietnamese": "vi", "indonesian": "id",
}

#: Non-Latin scripts, checked against a message when no preference is stored.
_SCRIPT_LOCALES = (
    (_CYRILLIC, "ru"), (_JAPANESE, "ja"), (_KOREAN, "ko"), (_HAN, "zh"),
    (_ARABIC, "ar"), (_HEBREW, "he"), (_GREEK, "el"), (_THAI, "th"),
    (_DEVANAGARI, "hi"),
)


def command_locale(preferred_language: Optional[str] = None,
                   message: Optional[str] = None,
                   established: Optional[str] = None) -> str:
    """The locale a clarification ANSWER must be interpreted under.

    Priority, highest first, per the rollout design:

      1. the user's explicit stored preference,
      2. the locale ESTABLISHED on the operation — so an answer is read in the
         same language context the question was asked in,
      3. script evidence in this message, as a fallback only.

    Step 3 is last on purpose: one-word replies are exactly where detection is
    least reliable, and "6 oz" carries no language signal at all. Falling back
    to English there is safe because English is what the parser already
    assumes; falling back to a DETECTED language on two characters would be a
    guess with a destructive command behind it.
    """
    stored = (preferred_language or "").strip().lower()
    if stored:
        if stored in _ENGLISH_NAMES:
            return ENGLISH
        return _LOCALE_OF.get(stored, UNKNOWN_LOCALE)
    if established:
        return established
    text = message or ""
    for script, locale in _SCRIPT_LOCALES:
        if script.search(text):
            return locale
    return ENGLISH


def is_english(locale: Optional[str]) -> bool:
    """Only an explicit English locale passes. `UNKNOWN_LOCALE` does not —
    "we could not tell" must never authorise a destructive command."""
    return (locale or "").strip().lower() in _ENGLISH_NAMES


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
