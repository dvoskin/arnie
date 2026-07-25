"""Shadow comparison against the live enrichment path (work order step 10).

Before the resolver owns a committed number it runs beside the current cascade
on real traffic, and the disagreement rate is the promotion gate.

Two properties matter more than the comparison itself:
  • it must cost NO extra network. A shadow that doubles USDA traffic is its
    own incident.
  • it must never affect the committed result. It observes; it does not vote.
"""
import pytest

from skills.nutrition import shadow as SH


class _Legacy:
    """Stand-in for FoodAnalysis."""
    def __init__(self, calories, source="usda", enrichment_source=None):
        self.calories = calories
        self.source = source
        self.enrichment_source = enrichment_source


@pytest.fixture
def shadowing(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_SHADOW", "1")


def test_it_is_inert_unless_switched_on(monkeypatch):
    monkeypatch.delenv("NUTRITION_RESOLVER_SHADOW", raising=False)
    assert SH.compare("Royo Plain Bagel", {"quantity": "100g"},
                      _Legacy(290)) is None


def test_no_source_is_ever_fetched(shadowing, monkeypatch):
    """The whole design constraint: the shadow reuses what the live path
    already fetched. If it ever reaches the network, this fails."""
    import api.usda as USDA
    import skills.nutrition.off as OFF

    async def _boom(*a, **k):
        raise AssertionError("the shadow must not fetch anything")
    monkeypatch.setattr(USDA, "search_food", _boom)
    monkeypatch.setattr(OFF, "search", _boom)

    out = SH.compare(
        "Royo Plain Bagel", {"quantity": "100g", "calories": 260},
        _Legacy(290),
        off={"per100g": {"calories": 80, "protein": 8}, "_match": "exact",
             "name": "Royo Plain Bagel", "brand": "Royo"})
    assert out is not None


def test_the_divergence_the_resolver_exists_to_catch(shadowing, caplog):
    """Live picked the USDA generic at 290; the resolver picks the product's
    own label at 80. That is the disagreement the promotion gate reads."""
    import logging
    with caplog.at_level(logging.INFO, logger="skills.nutrition.shadow"):
        out = SH.compare(
            "Royo Plain Bagel", {"quantity": "100g"},
            _Legacy(290, enrichment_source="usda"),
            usda={"description": "Bagel, plain, enriched", "fdc_id": 1,
                  "per100g": {"calories": 290, "protein": 11}},
            off={"per100g": {"calories": 80, "protein": 8}, "_match": "exact",
                 "name": "Royo Plain Bagel", "brand": "Royo"})
    assert out["new_source"] == "off"
    assert out["new_calories"] == 80
    assert out["diverged"] is True
    line = [r.message for r in caplog.records
            if "event=nutrition_shadow" in r.message][-1]
    assert "agree=NO" in line


def test_agreement_is_not_flagged(shadowing):
    out = SH.compare(
        "chicken breast, roasted", {"quantity": "100g"},
        _Legacy(165, enrichment_source="usda"),
        usda={"description": "Chicken breast, roasted", "fdc_id": 2,
              "per100g": {"calories": 165, "protein": 31}})
    assert out["diverged"] is False


def test_rounding_is_not_a_divergence(shadowing):
    """A few calories apart is the same answer. Flagging it would bury the
    real disagreements."""
    out = SH.compare(
        "chicken breast, roasted", {"quantity": "100g"},
        _Legacy(168, enrichment_source="usda"),
        usda={"description": "Chicken breast, roasted", "fdc_id": 2,
              "per100g": {"calories": 165, "protein": 31}})
    assert out["diverged"] is False


def test_a_shadow_failure_never_reaches_the_caller(shadowing, monkeypatch):
    """It observes. A bug in the observer must not touch the turn."""
    def _boom(*a, **k):
        raise RuntimeError("resolver exploded")
    monkeypatch.setattr(SH, "resolve", _boom)
    assert SH.compare("anything", {"quantity": "100g"}, _Legacy(100)) is None


def test_the_comparison_carries_the_full_resolution(shadowing):
    """The log line is the summary; the structured resolution is what makes a
    disagreement diagnosable without reproducing the turn."""
    out = SH.compare(
        "Royo Plain Bagel", {"quantity": "100g"}, _Legacy(290),
        off={"per100g": {"calories": 80, "protein": 8}, "_match": "exact",
             "name": "Royo Plain Bagel", "brand": "Royo"})
    r = out["resolution"]
    assert r["canonical_name"] == "Royo Plain Bagel"
    assert r["tier"] == "branded_exact"
    assert "sodium" in r["unknown_fields"]
    assert r["resolver_version"]


def test_a_user_label_is_recognised_as_tier_one(shadowing):
    out = SH.compare(
        "Royo Plain Bagel", {"quantity": "100g", "calories": 80, "protein": 8,
                             "user_label": True},
        _Legacy(80),
        usda={"description": "Bagel, plain", "fdc_id": 1,
              "per100g": {"calories": 290, "protein": 11}})
    assert out["new_source"] == "user_label"


@pytest.mark.asyncio
async def test_the_executor_calls_the_shadow_without_changing_its_answer(
        shadowing, db, make_user, monkeypatch):
    """End to end through _analyze_food: the shadow runs, and the committed
    analysis is what it would have been without it."""
    import handlers.tool_executor as TE
    user = await make_user()

    seen = {"n": 0, "legacy_calories": None}
    def _spy(food_name, inp, legacy_result, **k):
        seen["n"] += 1
        seen["legacy_calories"] = legacy_result.calories
        return None
    monkeypatch.setattr(SH, "compare", _spy)

    async def _no_web(*a, **k):
        return None
    monkeypatch.setattr(TE, "_web_lookup_meal", _no_web)

    inp = {"quantity": "1 bowl", "calories": 400, "protein": 28, "carbs": 30,
           "fats": 18}
    result = await TE._analyze_food(db, user, "homemade beef stew", inp)
    assert seen["n"] == 1
    # The shadow saw the SAME object the caller gets back — it observed the
    # committed answer rather than producing one.
    assert seen["legacy_calories"] == result.calories


@pytest.mark.asyncio
async def test_a_tier_one_label_skips_the_shadow_too(shadowing, db, make_user,
                                                     monkeypatch):
    """A stated label returns before enrichment, so there is nothing to
    compare — both paths would say user_label. Observing it would add volume
    and no signal."""
    import handlers.tool_executor as TE
    user = await make_user()
    seen = {"n": 0}
    monkeypatch.setattr(SH, "compare", lambda *a, **k: seen.__setitem__("n", 1))

    result = await TE._analyze_food(
        db, user, "Royo Plain Bagel",
        {"quantity": "100g", "calories": 80, "protein": 8, "user_label": True})
    assert seen["n"] == 0
    assert result.source == "user_label" and result.calories == 80
