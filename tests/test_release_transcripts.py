"""The five release transcripts, end to end.

Directive 2026-07-26: "the bar now needs to be end-to-end behavior, not green
isolated modules." These are the five exact inputs named there, each asserted
on both of the things that were wrong in the shipped session:

  1. WHAT THE TURN DOES — a question or a write, and if a question, whether it
     is one the user can actually answer. Driven through the real
     `food_turn.run()` with a fake interpreter, so the gate, the staging, the
     materiality policy and the clarification renderer all run for real.

  2. WHAT THE NUMBERS ARE — which source determined the macros, and what the
     provenance line says about it. Driven through the real `analyze()` with
     controlled candidates, so the ladder runs for real.

Split deliberately. Forcing both through one fake full stack would mean
asserting on proxies, and the executor's DB writes are not the thing under
test — the resolution and the conversation are. Where a transcript's failure
was in neither layer (the "Estimated" badge on a labelled product) it is
recorded as an xfail rather than quietly omitted.

Published label values, from the manufacturers, as cited in the directive:

    Royo Plain Bagel                    70 cal   9g protein
    Royo Everything Bagel               80 cal  10g protein
    Nissin Cup Noodles Protein         320 cal  16g protein
    Barebells Caramel Cashew           200 cal  20g protein  18g C  8g F
    Legendary Milk Chocolate Sweet Roll 210 cal  20g protein  24g C
"""
import json
from types import SimpleNamespace

import pytest

import core.food_turn as FT
from core.food_intelligence import analyze
from skills.nutrition import authority


# ── layer 1: what the turn does ───────────────────────────────────────────────
def _interpreter(payload):
    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


def _user(mode="moderate"):
    return SimpleNamespace(
        preferences=SimpleNamespace(food_logging_mode=mode))


async def _turn(monkeypatch, message, payload, mode="moderate"):
    monkeypatch.setattr(FT, "chat", _interpreter(payload))
    return await FT.run(message, _user(mode))


def _foods(out):
    return [c["input"]["food_name"] for c in (out or {}).get("tool_calls", [])]


# ── layer 2: what the numbers are ─────────────────────────────────────────────
def _label(cal, serving="", **macros):
    """A manufacturer/branded candidate the ladder will seat.

    `serving` matters more than it looks. A real branded record carries its
    serving size, and that is what turns "1 bagel" into a known mass and lets
    the label's density determine the macros. Without it the candidate still
    wins IDENTITY — the rung is branded_exact — but the macros fall back to the
    model, which is the seam that put 190/17 on a 210/20 sweet roll.
    """
    out = {"per100g": dict(calories=cal, **macros), "_match": "exact",
           "fdc_id": "label"}
    if serving:
        out["serving_text"] = serving
    return out


def _usda_generic(cal, **macros):
    return {"per100g": dict(calories=cal, **macros), "_match": "likely",
            "fdc_id": "usda-row"}


# ══ 1. "I also had a plain Royo bagel" ══════════════════════════════════════
#
#   Arnie:  I'm reading that as a royo bagel, plain. Does that look right?
#   User:   Yes it does
#   Arnie:  Royo Bagel, Plain logged, 80 cal, 8g protein.   [Estimated]
#           Portion estimated · nutrition profile supplemented with USDA data
#
# One clearly stated bagel. There was nothing for "yes" to settle, and the
# manufacturer publishes 70/9.
_ROYO_PLAIN = {
    "action": "log",
    "items": [{"food": "Royo Bagel, Plain", "amount": 1, "unit": "bagel",
               "branded": True, "basis": "stated",
               "calories": 80, "protein": 8, "carbs": 12, "fats": 1}],
    "say": "Bagel logged, {batch_cal} cal."}


@pytest.mark.asyncio
async def test_1_a_stated_packaged_serving_logs_without_a_question(monkeypatch):
    out = await _turn(monkeypatch, "I also had a plain Royo bagel", _ROYO_PLAIN)
    assert out["action"] == "log", out
    assert _foods(out) == ["Royo Bagel, Plain"]


@pytest.mark.asyncio
async def test_1_it_does_not_ask_on_strict_either(monkeypatch):
    """The whole-parse confirm is gone. One stated bagel is one stated bagel
    whatever the mode."""
    out = await _turn(monkeypatch, "I also had a plain Royo bagel",
                      _ROYO_PLAIN, mode="strict")
    assert out["action"] == "log", out


def test_1_the_label_determines_the_macros_not_the_model():
    """A branded record with its serving size resolves "1 bagel" completely:
    known mass x label density, and the model's 80/8 is discarded."""
    result = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                     off_candidate=_label(123, serving="1 bagel (57 g)",
                                          protein=16),
                     usda_candidate=_usda_generic(250, protein=10),
                     is_packaged=True)
    assert result.provenance.food_class == authority.FoodClass.MANUFACTURED.value
    assert result.provenance.rung == "branded_exact"
    assert not result.provenance.macros_are_estimated
    assert result.calories != 80, "the model's number must not survive a label"


def test_1_the_provenance_line_names_the_label_not_usda():
    result = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                     off_candidate=_label(123, serving="1 bagel (57 g)",
                                          protein=16),
                     usda_candidate=_usda_generic(250, protein=10),
                     is_packaged=True)
    detail = authority.display_detail(result.provenance)
    assert "USDA" not in detail, detail
    assert "estimated" not in detail.lower(), detail


def test_1_without_a_serving_size_the_label_wins_identity_but_not_the_macros():
    """THE RESIDUAL SEAM, pinned as it actually behaves.

    A branded record with per-100g figures and NO serving size cannot size
    "1 bagel" — so the rung is branded_exact for identity while the macros stay
    the model's. The provenance says so rather than claiming the label, which
    is the honest half. What is still missing is a better fallback than the
    model: a named product with a known density and an unknown count-mass could
    take its mass from the portion ontology instead of guessing outright.
    """
    result = analyze("Royo Bagel, Plain", "1 bagel", 80, 8, 12, 1,
                     off_candidate=_label(123, protein=16), is_packaged=True)
    assert result.provenance.identity_source == "branded_exact"
    assert result.provenance.primary_macro_source == "estimate"
    # And the line the user sees says estimate, which is true of the macros —
    # though it drops the fact that the product WAS identified. "Best estimate
    # from the description" is the same sentence an unrecognised food gets.
    assert "estimate" in authority.display_detail(result.provenance).lower()


# ══ 2. "I had 2 chicken thighs grilled marinated teriyaki" ══════════════════
#
#   Arnie:  Here's what I'm about to log:
#           · Two chicken thigh, grilled teriyaki marinateds
#           Does that all look right?
#
# Two defects. The grammar, and a whole-parse approval standing in for the
# question that would actually matter — skin-on or skinless changes this
# materially and "yes" cannot answer it.
_THIGHS = {
    "action": "log",
    "items": [{"food": "Chicken thigh, grilled teriyaki marinated",
               "amount": 2, "unit": "thigh", "basis": "stated",
               "calories": 370, "protein": 62, "carbs": 6, "fats": 12}],
    "say": "Chicken logged, {batch_cal} cal."}


@pytest.mark.asyncio
async def test_2_no_whole_parse_approval_is_requested(monkeypatch):
    out = await _turn(monkeypatch, "I had 2 chicken thighs grilled marinated "
                                   "teriyaki", _THIGHS, mode="strict")
    assert out.get("kind") != "confirm", out
    if out["action"] == "ask":
        assert "look right" not in out["text"].lower(), out["text"]


def test_2_the_preparation_is_not_pluralized():
    """"Two chicken thigh, grilled teriyaki marinateds" — the head noun ends at
    the comma; everything after it says how it was cooked."""
    from core.food_response import _plural_food
    assert _plural_food("chicken thigh, grilled teriyaki marinated", 2) == \
        "chicken thighs, grilled teriyaki marinated"


# ══ 3. "Just had a Cup Noodles Protein Chicken Flavor" ══════════════════════
#
# A textbook manufacturer lookup. The published product is 320/16; the turn
# committed 220/15 from the model and called the unit word "cup" a volume.
_CUP_NOODLES = {
    "action": "log",
    "items": [{"food": "Nissin Cup Noodles Protein, Chicken Flavor",
               "amount": 1, "unit": "cup", "branded": True, "basis": "stated",
               "calories": 220, "protein": 15, "carbs": 30, "fats": 8}],
    "say": "Cup Noodles logged, {batch_cal} cal."}


@pytest.mark.asyncio
async def test_3_a_named_product_with_a_stated_serving_just_logs(monkeypatch):
    out = await _turn(monkeypatch, "Just had a Cup Noodles Protein Chicken "
                                   "Flavor", _CUP_NOODLES)
    assert out["action"] == "log", out


def test_3_the_unit_word_is_the_product_not_a_measure_of_it():
    """"1 cup" of Cup Noodles is one package, not 236 ml of noodles."""
    from skills.nutrition.normalize import normalize_quantity
    norm = normalize_quantity("1 cup", "Nissin Cup Noodles Protein")
    assert norm.grams is None, norm
    assert norm.milliliters is None, norm


def test_3_estimate_is_not_allowed_to_win_over_a_label():
    result = analyze("Nissin Cup Noodles Protein, Chicken Flavor", "1 container",
                     220, 15, 30, 8,
                     off_candidate=_label(376, serving="1 container (85 g)",
                                          protein=19),
                     is_packaged=True)
    assert not result.provenance.macros_are_estimated
    assert result.provenance.rung in authority.BRANDED_RUNGS


# ══ 4. "Everything Royo bagel w 4 slices honey turkey and some mustard" ═════
#
#   Arnie:  · Four honey turkey deli slices
#           · One some of mustard
#           · A royo everything bagel
#           Which Royo Everything Bagel was it?
#
# Three items, all stated. The hedge became a count, and the identity question
# contained its own answer.
_MEAL = {
    "action": "log",
    "items": [
        {"food": "Royo Everything Bagel", "amount": 1, "unit": "bagel",
         "branded": True, "basis": "stated", "calories": 80, "protein": 10},
        {"food": "Honey turkey deli slices", "amount": 4, "unit": "slice",
         "basis": "stated", "calories": 60, "protein": 10},
        {"food": "Mustard", "amount": 1, "unit": "some", "basis": "estimate",
         "calories": 3, "protein": 0},
    ],
    "ambiguities": [{"item": "Royo Everything Bagel", "field": "identity",
                     "impact_cal": 30}],
    "say": "Bagel, turkey, mustard — {batch_cal} cal."}


@pytest.mark.asyncio
async def test_4_no_identity_question_for_a_product_already_named(monkeypatch):
    out = await _turn(monkeypatch, "Everything Royo bagel w 4 slices honey "
                                   "turkey and some mustard", _MEAL)
    text = (out.get("text") or "") if out.get("action") == "ask" else ""
    assert "Everything Bagel" not in text, text


@pytest.mark.asyncio
async def test_4_all_three_items_reach_the_log(monkeypatch):
    out = await _turn(monkeypatch, "Everything Royo bagel w 4 slices honey "
                                   "turkey and some mustard", _MEAL)
    assert out["action"] == "log", out
    assert len(_foods(out)) == 3, _foods(out)


def test_4_a_hedge_is_not_a_count():
    """"some mustard", not "One some of mustard"."""
    from core.food_response import FoodItemSummary, plan_review, fallback
    text = fallback(plan_review([FoodItemSummary(name="Mustard",
                                                 portion="1 some")]))
    assert "one some" not in text.lower(), text


# ══ 5. "Got a caramel cashew Barebells bar and a Legendary sweet roll" ══════
#
# The numbers were right for Barebells (200/20/18/8 matches the label) and
# wrong for Legendary (190/17 against a published 210/20). Both reported the
# portion as estimated.
#
# "Got a" is also the acquisition case: having a bar is not eating one. That
# state model does not exist yet, so the consumption assertion is xfail rather
# than absent — an omitted test reads as a passing one.
_ACQUIRED = {
    "action": "log",
    "items": [
        {"food": "Barebells Caramel Cashew Protein Bar", "amount": 1,
         "unit": "bar", "branded": True, "basis": "stated",
         "calories": 200, "protein": 20, "carbs": 18, "fats": 8},
        {"food": "Legendary Foods Milk Chocolate Sweet Roll", "amount": 1,
         "unit": "roll", "branded": True, "basis": "stated",
         "calories": 190, "protein": 17, "carbs": 19, "fats": 7},
    ],
    "say": "Bar and roll logged, {batch_cal} cal."}


def test_5_one_whole_labelled_serving_is_a_known_mass_not_an_estimate():
    """"1 roll" is one label serving. Treating it as an unknown portion is what
    let the model's 190/17 stand over a published 210/20."""
    result = analyze("Legendary Foods Milk Chocolate Sweet Roll", "1 roll",
                     190, 17, 19, 7,
                     off_candidate={"per100g": {"calories": 350,
                                                "protein": 33},
                                    "serving_text": "1 roll (60 g)",
                                    "_match": "exact"},
                     is_packaged=True)
    assert not result.provenance.macros_are_estimated, (
        "a whole serving of a labelled product is not a portion estimate")


def test_5_a_right_answer_still_needs_a_right_provenance():
    """Barebells committed the correct 200/20/18/8 and reported it as
    'portion estimated · supplemented with USDA data'. The number being right
    does not make the attribution true."""
    result = analyze("Barebells Caramel Cashew Protein Bar", "1 bar",
                     200, 20, 18, 8,
                     off_candidate=_label(364, serving="1 bar (55 g)",
                                          protein=36),
                     is_packaged=True)
    detail = authority.display_detail(result.provenance)
    assert "USDA" not in detail, detail


@pytest.mark.xfail(reason="acquisition-vs-consumption state model is not built "
                          "— 'got a bar' still writes as though it was eaten",
                   strict=True)
@pytest.mark.asyncio
async def test_5_acquiring_food_is_not_eating_it(monkeypatch):
    out = await _turn(monkeypatch, "Got a caramel cashew Barebells bar and a "
                                   "Legendary Milk Chocolate Sweet Roll",
                      _ACQUIRED)
    assert out["action"] == "ask", (
        "having food is not a consumption assertion; moderate should ask "
        "rather than write")
