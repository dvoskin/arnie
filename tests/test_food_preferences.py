"""User-specific defaults and correction learning (directive 14, 15).

Two halves of one idea: stop asking a question that has been answered, and stop
making a mistake that has been corrected.

The guard that matters most: a preference is never created from ONE occurrence.
A single answer is a fact about one bottle, not a standing default, and promoting
on first sight makes the system confidently wrong for anyone who drank something
unusual once.
"""
from datetime import datetime, timedelta

import pytest

from skills.nutrition.preferences import (CONTRADICTION_WINDOW,
                                          PROMOTION_CONFIRMATIONS,
                                          STRICT_CONFIRMATIONS,
                                          UserFoodPreference, build_correction,
                                          confirm, confused_pairs,
                                          is_possessive_reference,
                                          normalize_term, observe_answer,
                                          resolve_from_preference)

NOW = datetime(2026, 7, 25, 12, 0)


def _answer(term="my Fairlife", line="Core Power Elite", fraction=None,
            pref=None, at=NOW):
    return observe_answer(pref, term=term, now=at,
                          identity={"brand": "Fairlife", "product_line": line},
                          consumed_fraction=fraction)


# ── the promotion guard ───────────────────────────────────────────────────────
def test_one_answer_never_becomes_a_default():
    """A single answer is a fact about one bottle. Promoting here makes the
    system confidently wrong for anyone who drank something unusual once."""
    pref = _answer()
    assert pref.confirmations == 1
    assert not pref.is_promoted
    assert resolve_from_preference(pref, now=NOW) == {}


def test_two_answers_are_still_not_enough():
    pref = _answer(pref=_answer())
    assert pref.confirmations == 2 and not pref.is_promoted


def test_the_third_consistent_answer_promotes():
    pref = None
    for _ in range(PROMOTION_CONFIRMATIONS):
        pref = _answer(pref=pref)
    assert pref.confirmations == 3
    assert pref.is_promoted
    assert pref.applies(NOW)
    fields = resolve_from_preference(pref, now=NOW)
    assert fields["product_line"] == "Core Power Elite"
    assert fields["brand"] == "Fairlife"


def test_confidence_grows_with_confirmations_and_is_bounded():
    pref, seen = None, []
    for _ in range(6):
        pref = _answer(pref=pref)
        seen.append(pref.confidence)
    assert seen == sorted(seen)
    assert pref.confidence <= 0.98


# ── contradiction demotes rather than decrementing ────────────────────────────
def test_a_contradiction_stops_the_default_immediately():
    """Not a decrement — a demotion. A default that has been wrong once should
    stop applying now, not after it has been wrong three times."""
    pref = None
    for _ in range(3):
        pref = _answer(pref=pref)
    assert pref.is_promoted

    contradicted = _answer(line="Nutrition Plan", pref=pref)
    assert contradicted.contradictions == 1
    assert not contradicted.is_promoted
    assert resolve_from_preference(contradicted, now=NOW) == {}


def test_confirmations_survive_a_contradiction_so_re_promotion_is_fast():
    """The evidence is not thrown away — only the default's force."""
    pref = None
    for _ in range(3):
        pref = _answer(pref=pref)
    contradicted = _answer(line="Nutrition Plan", pref=pref)
    assert contradicted.confirmations == 3


def test_a_recent_contradiction_blocks_re_promotion():
    """Three confirmations after a disagreement last week is not yet a settled
    default."""
    pref = UserFoodPreference(
        trigger_term="fairlife", brand="Fairlife",
        product_line="Core Power Elite", confirmations=2,
        contradictions=1, last_contradicted_at=NOW - timedelta(days=7))
    promoted = confirm(pref, NOW)
    assert promoted.confirmations == 3
    assert not promoted.is_promoted        # blocked by the recent disagreement


def test_an_old_contradiction_does_not_hold_a_good_default_hostage():
    stale = NOW - CONTRADICTION_WINDOW - timedelta(days=1)
    pref = UserFoodPreference(
        trigger_term="fairlife", brand="Fairlife",
        product_line="Core Power Elite", confirmations=2,
        contradictions=1, last_contradicted_at=stale)
    assert confirm(pref, NOW).is_promoted


def test_a_silence_is_not_a_contradiction():
    """An answer naming the product line but not the size neither confirms nor
    contradicts the size. Treating silence as disagreement would demote a good
    default for being incompletely restated."""
    pref = None
    for _ in range(3):
        pref = _answer(pref=pref)
    partial = observe_answer(pref, term="my Fairlife", now=NOW,
                            identity={"brand": "Fairlife"})
    assert partial.contradictions == 0
    assert partial.is_promoted


# ── strict mode ───────────────────────────────────────────────────────────────
def test_strict_confirms_a_learned_default_for_its_first_few_uses():
    """A learned default is still an assumption, and strict users opted into
    being asked."""
    pref = None
    for _ in range(PROMOTION_CONFIRMATIONS):
        pref = _answer(pref=pref)
    assert pref.applies(NOW, "moderate")
    assert not pref.applies(NOW, "strict")

    for _ in range(STRICT_CONFIRMATIONS):
        pref = _answer(pref=pref)
    assert pref.applies(NOW, "strict")


def test_a_contradiction_blocks_the_default_in_every_mode():
    pref = None
    for _ in range(6):
        pref = _answer(pref=pref)
    contradicted = _answer(line="Nutrition Plan", pref=pref)
    for mode in ("quick", "moderate", "strict"):
        assert not contradicted.applies(NOW, mode)


# ── term normalization ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("my Fairlife", "fairlife"),
    ("a fairlife", "fairlife"),
    ("Fairlife", "fairlife"),
    ("2 Fairlifes", "fairlifes"),
    ("my usual bagel", "usual bagel"),
    # "slices" is kept: it is part of the food phrase here, and stripping it
    # would collapse "turkey slices" with "turkey breast". Only a unit
    # following a NUMBER is a quantity.
    ("some turkey slices", "turkey slices"),
    # And the count-prefixed form collapses to the SAME key — which is the
    # point: "some turkey slices" and "6 turkey slices" are one default.
    ("6 turkey slices", "turkey slices"),
])
def test_phrasings_collapse_to_one_key(text, expected):
    """A default learned from one phrasing must apply to the others, or the
    system learns three separate times."""
    assert normalize_term(text) == expected


def test_a_possessive_reference_is_recognised():
    assert is_possessive_reference("my Fairlife")
    assert is_possessive_reference("the usual yogurt")
    assert not is_possessive_reference("a Fairlife Core Power")


def test_portion_defaults_are_learned_too():
    pref = None
    for _ in range(3):
        pref = _answer(fraction=0.5, pref=pref)
    assert resolve_from_preference(pref, now=NOW)["consumed_fraction"] == 0.5


def test_no_preference_contributes_nothing():
    assert resolve_from_preference(None, now=NOW) == {}


# ── corrections as evidence ───────────────────────────────────────────────────
class _Cand:
    def __init__(self, cid, name, score, alias=None):
        self.candidate_id = cid
        self.canonical_name = name
        self.overall_score = score
        self.tier = 3
        self.via_alias = alias


class _Item:
    staged_item_id = "i1"
    original_text = "royal bagel"
    ambiguities = ()


def test_a_correction_snapshots_the_ranking_that_produced_it():
    """"Why did it pick that?" is unanswerable after the fact without the
    ranking as it stood — a later replay would produce a different order and
    hide the bug being investigated."""
    candidates = [_Cand("c1", "Royo Everything Bagel", 0.71, alias="royal→royo"),
                  _Cand("c2", "Royo Plain Bagel", 0.66)]
    rec = build_correction(
        user_id=7, field_name="variant", chosen="Royo Everything Bagel",
        corrected="Royo Plain Bagel", item=_Item(), candidates=candidates,
        mode="moderate", turn_id="turn_9", entry_id=41)

    assert rec.chosen_candidate_id == "c1"
    assert rec.corrected_candidate_id == "c2"
    assert len(rec.candidate_ranking) == 2
    assert rec.candidate_ranking[0]["score"] == 0.71
    assert rec.entry_id == 41 and rec.turn_id == "turn_9"


def test_the_alias_that_led_to_the_wrong_pick_is_recorded():
    """"royal bagel" → "Royo" is a transcription guess. If corrections cluster
    on it, the alias is wrong — and that is only visible if it was recorded."""
    candidates = [_Cand("c1", "Royo Everything Bagel", 0.71, alias="royal→royo")]
    rec = build_correction(user_id=7, field_name="variant",
                           chosen="Royo Everything Bagel",
                           corrected="Royo Plain Bagel", item=_Item(),
                           candidates=candidates)
    assert rec.via_alias == "royal→royo"


def test_the_correction_line_is_greppable():
    rec = build_correction(user_id=7, field_name="product_line",
                           chosen="Core Power", corrected="Core Power Elite",
                           item=_Item(), mode="moderate", turn_id="turn_9")
    line = rec.log_line()
    assert line.startswith("event=food_correction ")
    for token in ("user=7", "field=product_line", "turn=turn_9"):
        assert token in line


def test_the_ranking_serializes():
    rec = build_correction(user_id=7, field_name="variant", chosen="A",
                           corrected="B",
                           candidates=[_Cand("c1", "A", 0.5)])
    import json
    assert json.loads(rec.ranking_json())[0]["candidate_id"] == "c1"


def test_repeatedly_confused_pairs_are_surfaced_commonest_first():
    """The actionable output: a pair appearing repeatedly is either a missing
    alias or a wrong scoring weight, and this names which to look at."""
    def rec(chosen, meant):
        return build_correction(user_id=7, field_name="product_line",
                                chosen=chosen, corrected=meant)
    corrections = [rec("Core Power", "Core Power Elite")] * 3
    corrections += [rec("Royo Everything", "Royo Plain")] * 2
    corrections += [rec("Chobani Complete", "Chobani Zero Sugar")]

    pairs = confused_pairs(corrections)
    assert pairs[0][0] == ("Core Power", "Core Power Elite")
    assert pairs[0][1] == 3
    assert pairs[1][1] == 2
    # A single occurrence is noise, not a pattern.
    assert all(n >= 2 for _, n in pairs)


def test_a_self_correction_is_not_a_confusion():
    """Correcting something to itself carries no signal."""
    rec = build_correction(user_id=7, field_name="variant", chosen="A",
                           corrected="A")
    assert confused_pairs([rec] * 5) == []


# ── persistence ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_tables_exist_and_round_trip(db, make_user):
    from db.models import FoodCorrection, UserFoodPreference as Row
    user = await make_user()

    db.add(Row(user_id=user.id, trigger_term="fairlife", brand="Fairlife",
               product_line="Core Power Elite", confirmations=3,
               confidence=0.9, promoted_at=NOW))
    db.add(FoodCorrection(user_id=user.id, field_name="product_line",
                          chosen_value="Core Power",
                          corrected_value="Core Power Elite",
                          turn_id="turn_9", candidate_ranking_json="[]"))
    await db.commit()

    from sqlalchemy import select
    pref = (await db.execute(
        select(Row).where(Row.user_id == user.id))).scalars().first()
    assert pref.product_line == "Core Power Elite"
    assert pref.promoted_at is not None

    corr = (await db.execute(
        select(FoodCorrection).where(
            FoodCorrection.user_id == user.id))).scalars().first()
    assert corr.corrected_value == "Core Power Elite"


@pytest.mark.asyncio
async def test_one_preference_row_per_phrase(db, make_user):
    """A second row for the same phrase would make "which default applies"
    undecidable."""
    from sqlalchemy.exc import IntegrityError
    from db.models import UserFoodPreference as Row
    user = await make_user()
    db.add(Row(user_id=user.id, trigger_term="fairlife"))
    await db.commit()
    db.add(Row(user_id=user.id, trigger_term="fairlife"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
