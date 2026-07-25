"""Promoting the resolver to own committed nutrition (review 2026-07-25, step 3).

Until this, there were two states: legacy commits, resolver observes. An
architecture that chooses nutrition better changes nothing for a user until it
owns the number that gets saved.

The promotion is deliberately narrow — it replaces which candidate's nutrients
become the committed values and nothing else. These tests pin that narrowness,
because the whole safety argument for flipping the flag is "the resolver is the
only thing that changed".
"""
import pytest

from skills.nutrition import promotion as P
from skills.nutrition.models import (NormalizedQuantity, NutritionResolution,
                                     profile_from_values)
from skills.nutrition.provenance import MatchGrade, SourceTier


class _Legacy:
    """Stand-in for the cascade's FoodAnalysis."""
    def __init__(self, calories=290, protein=11, carbs=56, fat=1.5,
                 source="usda", micros=None, sodium=None, fiber=None):
        self.calories = calories
        self.protein = protein
        self.carbs = carbs
        self.fat = fat
        self.source = source
        self.enrichment_source = source
        self.confidence = "likely"
        self.micros = micros or {}
        self.micros_estimated = bool(micros)
        self.sodium = sodium
        self.fiber = fiber
        self.sugar = None


def _resolution(source="off", tier=SourceTier.BRANDED_EXACT, cal=80,
                protein=8, carbs=6, fat=1, grade=MatchGrade.EXACT, **extra):
    return NutritionResolution(
        canonical_name="Royo Plain Bagel",
        quantity=NormalizedQuantity(amount=100, unit="g", grams=100),
        nutrients=profile_from_values(source, calories=cal, protein=protein,
                                      carbs=carbs, fat=fat, **extra),
        source=source, tier=tier, match_grade=grade, confidence=0.9)


# ── the mode switch ───────────────────────────────────────────────────────────
def test_off_by_default(monkeypatch):
    monkeypatch.delenv("NUTRITION_RESOLVER_MODE", raising=False)
    monkeypatch.delenv("NUTRITION_RESOLVER_SHADOW", raising=False)
    assert P.resolver_mode() == P.MODE_OFF
    assert not P.owns_committed_values(7)
    assert not P.shadow_enabled()


def test_the_already_deployed_shadow_flag_keeps_working(monkeypatch):
    """NUTRITION_RESOLVER_SHADOW is documented and may already be set. Landing
    the new switch must not silently turn it off."""
    monkeypatch.delenv("NUTRITION_RESOLVER_MODE", raising=False)
    monkeypatch.setenv("NUTRITION_RESOLVER_SHADOW", "1")
    assert P.resolver_mode() == P.MODE_SHADOW
    assert P.shadow_enabled()
    assert not P.owns_committed_values(7)      # shadow never commits


def test_shadow_mode_observes_but_never_commits(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "shadow")
    assert P.shadow_enabled() and not P.owns_committed_values(7)


def test_live_mode_commits_and_keeps_logging(monkeypatch):
    """Turning the comparison off at the moment of promotion would blind the
    rollout — the log IS the record of what changed."""
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "live")
    monkeypatch.delenv("NUTRITION_RESOLVER_ALLOWLIST", raising=False)
    assert P.owns_committed_values(7)
    assert P.shadow_enabled()


def test_an_allowlist_narrows_live_mode_to_named_users(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "live")
    monkeypatch.setenv("NUTRITION_RESOLVER_ALLOWLIST", "12,84")
    assert P.owns_committed_values(84)
    assert not P.owns_committed_values(7)


def test_an_unknown_mode_falls_back_to_off(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "banana")
    monkeypatch.delenv("NUTRITION_RESOLVER_SHADOW", raising=False)
    assert P.resolver_mode() == P.MODE_OFF


# ── the guards ────────────────────────────────────────────────────────────────
@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "live")
    monkeypatch.delenv("NUTRITION_RESOLVER_ALLOWLIST", raising=False)


def test_an_unresolved_resolution_never_promotes(live):
    """No candidate surviving validation means we know LESS than the cascade
    did, not more."""
    unresolved = NutritionResolution(
        canonical_name="x",
        quantity=NormalizedQuantity(amount=1, unit="serving"),
        nutrients=profile_from_values("none"), source="unresolved")
    legacy = _Legacy()
    assert P.promote(unresolved, food_name="x", quantity="100g",
                     legacy=legacy, user_id=7) is legacy


def test_a_resolution_with_no_calories_never_promotes(live):
    """The rest of the system treats calories as the anchor; a profile without
    one cannot anchor it."""
    no_cal = _resolution(cal=None, protein=8)
    legacy = _Legacy()
    assert P.promote(no_cal, food_name="x", quantity="100g", legacy=legacy,
                     user_id=7) is legacy


def test_a_missing_resolution_never_promotes(live):
    legacy = _Legacy()
    assert P.promote(None, food_name="x", quantity="100g", legacy=legacy,
                     user_id=7) is legacy


def test_a_crash_inside_promotion_keeps_the_legacy_value(live, monkeypatch):
    """A failure here must leave the turn with the value it would have
    committed anyway."""
    def _boom(*a, **k):
        raise RuntimeError("analyze exploded")
    monkeypatch.setattr(P, "to_food_analysis", _boom)
    legacy = _Legacy()
    assert P.promote(_resolution(), food_name="x", quantity="100g",
                     legacy=legacy, user_id=7) is legacy


def test_promotion_is_a_no_op_when_not_live(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "shadow")
    legacy = _Legacy()
    assert P.promote(_resolution(), food_name="x", quantity="100g",
                     legacy=legacy, user_id=7) is legacy


# ── what promotion actually changes ───────────────────────────────────────────
def test_the_resolvers_values_become_the_committed_ones(live):
    """The Royo bagel case: the cascade committed the USDA generic at 290, the
    resolver picks the product's own label at 80."""
    out = P.promote(_resolution(cal=80, protein=8),
                    food_name="Royo Plain Bagel", quantity="100g",
                    legacy=_Legacy(calories=290), user_id=7)
    assert out.calories == 80
    assert out.protein == 8
    assert out.source == "off"
    assert out.enrichment_source == "off"


@pytest.mark.parametrize("tier,expected", [
    (SourceTier.USER_LABEL, "user-confirmed"),
    (SourceTier.USER_REGULAR, "user-confirmed"),
    (SourceTier.BRANDED_EXACT, "exact"),
    (SourceTier.GENERIC_EXACT, "likely"),
    (SourceTier.ESTIMATED, "estimated"),
    (SourceTier.PROVISIONAL, "estimated"),
])
def test_tiers_map_onto_the_confidence_vocabulary_already_in_use(live, tier,
                                                                 expected):
    out = P.promote(_resolution(tier=tier), food_name="x", quantity="100g",
                    legacy=_Legacy(), user_id=7)
    assert out.confidence == expected


def test_derived_fields_are_computed_by_the_same_code_as_every_other_path(live):
    """Routed through food_intelligence.analyze so protein density, satiety,
    quality and the coaching note are not a second implementation."""
    out = P.promote(_resolution(cal=200, protein=30, carbs=10, fat=4),
                    food_name="chicken", quantity="100g", legacy=_Legacy(),
                    user_id=7)
    assert out.protein_density is not None
    assert out.satiety and out.quality


def test_unknown_stays_unknown_through_promotion(live):
    """A resolution silent on sodium produces sodium=None, not 0 — the rule
    the whole layer is built on does not stop applying at the commit boundary."""
    out = P.promote(_resolution(), food_name="x", quantity="100g",
                    legacy=_Legacy(sodium=None), user_id=7)
    assert out.sodium is None


def test_a_known_micro_from_the_resolution_is_carried(live):
    out = P.promote(_resolution(sodium=480, fiber=3),
                    food_name="x", quantity="100g", legacy=_Legacy(),
                    user_id=7)
    assert out.sodium == 480
    assert out.fiber == 3


def test_micros_the_cascade_resolved_are_not_discarded(live):
    """The resolver does not fetch micro panels. Dropping the cascade's would
    make promotion a regression on a dimension it never touched."""
    legacy = _Legacy(micros={"iron": 2.1, "calcium": 120})
    out = P.promote(_resolution(), food_name="x", quantity="100g",
                    legacy=legacy, user_id=7)
    assert out.micros == {"iron": 2.1, "calcium": 120}
    assert out.micros_estimated is True


def test_a_legacy_micro_fills_a_field_the_resolution_is_silent_on(live):
    legacy = _Legacy(sodium=534)
    out = P.promote(_resolution(), food_name="x", quantity="100g",
                    legacy=legacy, user_id=7)
    assert out.sodium == 534          # inherited, not invented


def test_the_resolution_wins_where_both_know_the_field(live):
    legacy = _Legacy(sodium=534)
    out = P.promote(_resolution(sodium=120), food_name="x", quantity="100g",
                    legacy=legacy, user_id=7)
    assert out.sodium == 120


# ── visibility ────────────────────────────────────────────────────────────────
def test_every_promotion_is_logged(live, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="skills.nutrition.promotion"):
        P.promote(_resolution(cal=80), food_name="Royo Plain Bagel",
                  quantity="100g", legacy=_Legacy(calories=290), user_id=7)
    line = [r.message for r in caplog.records
            if "event=nutrition_promotion " in r.message][-1]
    assert "outcome=promoted" in line
    assert "legacy_cal=290" in line and "new_cal=80" in line


def test_a_declined_promotion_says_why(live, caplog):
    import logging
    unresolved = NutritionResolution(
        canonical_name="x",
        quantity=NormalizedQuantity(amount=1, unit="serving"),
        nutrients=profile_from_values("none"), source="unresolved")
    with caplog.at_level(logging.INFO, logger="skills.nutrition.promotion"):
        P.promote(unresolved, food_name="x", quantity="100g",
                  legacy=_Legacy(), user_id=7)
    line = [r.message for r in caplog.records
            if "event=nutrition_promotion " in r.message][-1]
    assert "outcome=declined" in line


def test_a_large_move_is_loud_but_still_promoted(live, caplog):
    """290 → 80 is often exactly the fix we want, so it is not blocked. It is
    never silent either, so a systematic regression is one grep away."""
    import logging
    with caplog.at_level(logging.WARNING, logger="skills.nutrition.promotion"):
        out = P.promote(_resolution(cal=80), food_name="Royo Plain Bagel",
                        quantity="100g", legacy=_Legacy(calories=290),
                        user_id=7)
    assert out.calories == 80          # promoted
    loud = [r.message for r in caplog.records
            if "nutrition_promotion_large_move" in r.message]
    assert loud and "x=3.6" in loud[-1]


def test_a_small_move_is_not_flagged_as_large(live, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="skills.nutrition.promotion"):
        P.promote(_resolution(cal=280), food_name="x", quantity="100g",
                  legacy=_Legacy(calories=290), user_id=7)
    assert not [r for r in caplog.records
                if "nutrition_promotion_large_move" in r.message]


# ── one resolution, shared by the log and the commit ──────────────────────────
@pytest.mark.asyncio
async def test_the_executor_commits_the_resolvers_answer(live, db, make_user,
                                                         monkeypatch):
    """End to end: with the flag on, _analyze_food returns the resolver's
    values rather than the cascade's."""
    import handlers.tool_executor as TE
    user = await make_user()

    async def _no_web(*a, **k):
        return None
    monkeypatch.setattr(TE, "_web_lookup_meal", _no_web)

    # The cascade's own answer is an estimate from the model's numbers; the
    # resolver has an exact branded label to work from.
    inp = {"quantity": "100g", "calories": 290, "protein": 11,
           "is_packaged": True, "brand": "Royo"}
    monkeypatch.setattr(
        TE, "_looks_branded", lambda *a, **k: True)

    from skills.nutrition import shadow as SH
    monkeypatch.setattr(
        SH, "resolve_from_live",
        lambda *a, **k: _resolution(cal=80, protein=8))

    out = await TE._analyze_food(db, user, "Royo Plain Bagel", inp)
    assert out.calories == 80 and out.source == "off"


@pytest.mark.asyncio
async def test_the_executor_keeps_the_cascade_when_not_live(db, make_user,
                                                            monkeypatch):
    import handlers.tool_executor as TE
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "shadow")
    user = await make_user()

    async def _no_web(*a, **k):
        return None
    monkeypatch.setattr(TE, "_web_lookup_meal", _no_web)
    from skills.nutrition import shadow as SH
    monkeypatch.setattr(SH, "resolve_from_live",
                        lambda *a, **k: _resolution(cal=80))

    out = await TE._analyze_food(
        db, user, "homemade beef stew",
        {"quantity": "1 bowl", "calories": 400, "protein": 28, "carbs": 30,
         "fats": 18})
    assert out.calories != 80          # the resolver observed, did not vote
