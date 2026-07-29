"""Four briefs, one persona — and the profiles are derived, never maintained.

The food lane already sent the right voice: since the shared-persona work it
passes `voice_core()`, all ~3,400 tokens of IDENTITY, LANGUAGE, VOICE and
EMOJI_SYSTEM, to write "rice cake logged, 35 cal". The full persona on a
two-bubble acknowledgement buys nothing a third of it would not, and it is
paid on every routine turn.

The danger in fixing that is obvious and worse than the cost: four hand-written
briefs are four personalities that drift apart, and the first one to drift is
the one nobody reads until something breaks. So a profile is a SELECTION of
canonical contracts, each LIFTED from `core/prompts/arnie.py` by anchor. There
is no second copy of a personality rule anywhere in this system.

The load-bearing test in this file is `test_editing_the_canonical_voice_…`: it
edits the persona and asserts every profile changes. If that ever passes while
the profiles hold still, the compiler has become a fifth personality and the
whole design is void.

One product decision worth stating because it looks like an omission:
`thread_alive` — "end every reply with the next move OR a question" — is NOT in
the micro brief. That instruction is what turns a two-line confirmation into
unasked-for coaching, and it is why routine logs have read as over-eager. It is
exactly right for the coaching profile, which is where it stays.
"""
import pytest

from core.prompts import arnie as canon
from core.prompts import voice as V
from core.food_response import (FoodResponseIntent, arnie_voice,
                                voice_profile_for)

ALL = V.profiles()
#: True of every Arnie sentence on every lane, so absent from none of them.
NON_NEGOTIABLE = ("not_an_ai", "tone", "sentence_case", "capitalization")


# ── the profiles are derived ─────────────────────────────────────────────────
def test_every_contract_still_resolves_against_the_persona():
    """A missed anchor degrades to the whole section rather than dropping a
    rule — survivable in production, never acceptable in the tree."""
    V.UNRESOLVED.clear()
    for p in ALL:
        V.compile_voice(p)
    assert not V.UNRESOLVED, (
        f"the persona moved and these no longer lift: {V.UNRESOLVED}")


@pytest.mark.parametrize("c", V.CONTRACTS, ids=lambda c: c.name)
def test_a_contract_is_a_slice_of_the_persona_not_a_copy_of_it(c):
    """The mechanism, asserted directly: every character of every contract
    comes out of the canonical constant."""
    source = getattr(canon, c.source)
    assert V.contract(c.name) in source


def test_editing_the_canonical_voice_changes_every_profile(monkeypatch):
    """THE load-bearing test. If the profiles hold still while the persona
    moves, they have become separately maintained personalities and the
    compiler is a lie."""
    edited = canon.VOICE.replace(
        "Sentence case, like a real person texting.",
        "Sentence case, like a real person texting. NEWLY ADDED RULE.")
    assert edited != canon.VOICE, "the anchor moved — update this test"
    monkeypatch.setattr(canon, "VOICE", edited)
    for p in ALL:
        assert "NEWLY ADDED RULE." in V.compile_voice(p), (
            f"{p} did not inherit a change to the canonical voice")


def test_a_change_to_identity_propagates_too(monkeypatch):
    monkeypatch.setattr(canon, "IDENTITY",
                        canon.IDENTITY.replace(
                            "TONE, the core of who you are:",
                            "TONE, the core of who you are: ANCHORED."))
    for p in ALL:
        assert "ANCHORED." in V.compile_voice(p)


# ── every profile is still Arnie ─────────────────────────────────────────────
@pytest.mark.parametrize("profile", ALL)
@pytest.mark.parametrize("rule", NON_NEGOTIABLE)
def test_no_profile_may_drop_a_non_negotiable(profile, rule):
    assert rule in V.PROFILES[profile]


@pytest.mark.parametrize("profile", ALL)
def test_no_profile_lets_him_call_himself_software(profile):
    text = V.compile_voice(profile)
    assert "NEVER refer to yourself as AI or software" in text


@pytest.mark.parametrize("profile", ALL)
def test_the_recovery_and_routine_briefs_are_not_generic(profile):
    """The fallback paths are where the user is most likely to notice a
    different product answering. Every brief carries the tone contract, which
    is the part that bans receipt language and empty praise."""
    assert "Direct. Human. Specific." in V.compile_voice(profile)


@pytest.mark.parametrize("profile", ALL)
def test_no_brief_leaks_machinery(profile):
    lowered = V.compile_voice(profile).lower()
    for word in ("resolver", "schema", "usda", "database", "endpoint",
                 "tool call", "confidence score"):
        # Named only where the brief FORBIDS them, which is the clarification
        # and recovery task text.
        if word in lowered:
            assert ("never" in lowered or "do not" in lowered), word


# ── the profiles differ where they should ────────────────────────────────────
def test_a_routine_acknowledgement_is_narrower_than_coaching():
    assert len(V.compile_voice("micro_acknowledgement")) < len(
        V.compile_voice("coaching"))


def test_the_routine_brief_does_not_demand_a_next_move():
    """The specific rule whose absence makes a confirmation a confirmation."""
    assert "thread_alive" not in V.PROFILES["micro_acknowledgement"]
    assert "thread_alive" in V.PROFILES["coaching"]


def test_the_routine_brief_still_obeys_the_canonical_bubble_rule():
    """The canonical voice ends with "never one bubble alone after logging
    food". The micro brief asks for two short bubbles rather than one — it
    narrows the persona, it does not contradict it."""
    assert "never one bubble alone after logging food" in canon.VOICE
    assert "Two short bubbles" in _flat(V.compile_voice("micro_acknowledgement"))


def _flat(text: str) -> str:
    """The briefs are line-wrapped prose. Asserting on wrapped text pins the
    line breaks, which is a formatting detail nobody should have to preserve
    to keep a rule."""
    return " ".join(text.split())


def test_recovery_may_not_claim_a_write_that_failed():
    text = _flat(V.compile_voice("recovery"))
    assert "Never claim a write that did not land." in text
    assert "failure language" in text


def test_clarification_asks_once_about_one_thing():
    text = _flat(V.compile_voice("clarification"))
    assert "Ask about ONE item" in text


def test_coaching_is_told_to_use_the_non_food_context():
    """The mixed-turn case: "chicken and rice after a brutal meeting". A brief
    that does not mention it produces a reply that ignores it."""
    assert "not about food" in _flat(V.compile_voice("coaching"))


# ── the mapping ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("intent", list(FoodResponseIntent))
def test_every_intent_has_a_declared_profile(intent):
    """Voice-profile coverage is a success metric: an unmapped intent is an
    unmeasured path, not a cosmetic gap."""
    assert voice_profile_for(intent) in ALL


@pytest.mark.parametrize("intent", list(FoodResponseIntent))
def test_every_intent_compiles_to_a_real_brief(intent):
    text = arnie_voice(intent)
    assert len(text) > 500 and "Arnie" in text


def test_an_unknown_profile_is_an_error_not_an_empty_brief():
    """Silently returning "" would ship a reply with no persona at all."""
    with pytest.raises(KeyError):
        V.compile_voice("chatty")


def test_the_unmapped_default_is_the_widest_brief():
    """Over-explaining an unknown moment is recoverable; being curt is not."""
    assert voice_profile_for(None) == "coaching"


def test_no_intent_answers_a_failure_with_a_routine_ack():
    assert voice_profile_for(FoodResponseIntent.FAILURE) == "recovery"


def test_a_partial_commit_is_not_treated_as_routine():
    """Some went in and some did not; "confirm it and stop" is the wrong
    shape for a reply that has to say which was which."""
    assert voice_profile_for(
        FoodResponseIntent.PARTIAL_COMMIT) != "micro_acknowledgement"


# ── one persona, still ───────────────────────────────────────────────────────
def test_the_food_lane_defines_no_personality_of_its_own():
    """No standalone persona CONSTANT. The name still appears in a comment
    recording why it was removed, and that history is worth keeping — so this
    looks for an assignment, not a mention."""
    import pathlib
    import re
    src = pathlib.Path("core/food_response.py").read_text()
    assert not re.search(r"^\s*ARNIE_VOICE\s*=", src, re.M), (
        "a standalone lane persona came back")


def test_calling_without_an_intent_still_gets_the_full_persona():
    """Callers that pass nothing do not know what moment they are in."""
    assert len(arnie_voice()) > len(arnie_voice(FoodResponseIntent.COMMIT))
