"""
Reset-confirmation matching (iMessage).

REGRESSION: the confirmation phrase was matched with a case-sensitive `==` against
"RESET confirm". iOS auto-capitalizes the first letter, so users actually send
"Reset confirm" — which failed the check, fell through to the LLM, and produced a
fake "data cleared" reply while every row survived. These lock the matching down.
"""
from bot.imessage_handler import _is_reset_confirmation


# ── The exact bug from the screenshot ──────────────────────────────────────────

def test_ios_autocapitalized_phrase_confirms():
    # "Reset confirm" is what iOS produces from typing "reset confirm".
    assert _is_reset_confirmation("Reset confirm", pending=True) is True
    assert _is_reset_confirmation("Reset confirm", pending=False) is True


def test_all_case_variants_confirm():
    for variant in ("RESET confirm", "reset confirm", "Reset Confirm", "RESET CONFIRM",
                    "confirm reset", "Confirm Reset"):
        assert _is_reset_confirmation(variant, pending=True) is True, variant


def test_trailing_punctuation_and_space_ok():
    assert _is_reset_confirmation("Reset confirm.", pending=True) is True
    assert _is_reset_confirmation("reset confirm!", pending=True) is True
    assert _is_reset_confirmation("  reset confirm  ", pending=False) is True


# ── Bare confirm only counts when a reset is pending ───────────────────────────

def test_bare_confirm_requires_pending():
    assert _is_reset_confirmation("confirm", pending=True) is True
    assert _is_reset_confirmation("yes", pending=True) is True
    # not pending → a stray "yes"/"confirm" must NOT wipe data
    assert _is_reset_confirmation("confirm", pending=False) is False
    assert _is_reset_confirmation("yes", pending=False) is False


# ── Non-confirmations never trigger a reset ────────────────────────────────────

def test_unrelated_messages_do_not_confirm():
    for txt in ("had eggs for breakfast", "reset my data", "start over",
                "what's my protein", "confirmation", "yesterday I ran"):
        assert _is_reset_confirmation(txt, pending=True) is False, txt
