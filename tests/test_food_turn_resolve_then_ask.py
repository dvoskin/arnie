"""Part 5 — resolve, then ask (NUTRITION_ACCURACY_V2).

The failure this closes, from production: a "spoon" of something dense logged at
350 calories nobody established, corrected by hand to 130, with a confident
receipt on top of the wrong number. The interpreter proposed no ask, so the ask
gate — which only ever judged asks the model PROPOSED — never saw it.

These pin the two new pure pieces: the portion-ontology helpers that SIZE the
doubt (`core.portions`), and `_resolved_ambiguities`, which states the doubt the
overconfident log omitted in the exact shape the existing consequence engine
scores. The promotion itself is that engine (`_proposed_ask_is_material`), so it
is tested here through the same call the turn makes — no LLM, no flag, no I/O.
"""
from core.portions import prep_fat_span, is_vague_unit, mentions_fat
from core.food_turn import (_resolved_ambiguities, _proposed_ask_is_material,
                            _v2_accuracy)


# ── the food-knowledge tables ────────────────────────────────────────────────

def test_vague_units_are_the_ones_with_no_definite_mass():
    for u in ("spoon", "Scoop", "handful", "a piece", "serving", "bowl"):
        assert is_vague_unit(u.replace("a ", "")), u
    for u in ("g", "gram", "oz", "ml", "cup", "tbsp", "tsp", "bottle", "can"):
        assert not is_vague_unit(u), u


def test_prep_fat_span_only_for_fat_prone_foods():
    assert prep_fat_span("sirloin steak") == 100
    assert prep_fat_span("grilled chicken breast") == 100
    assert prep_fat_span("green salad") == 145
    assert prep_fat_span("scrambled eggs") == 90
    assert prep_fat_span("white rice") == 0       # grain: no material fat doubt
    assert prep_fat_span("apple") == 0
    assert prep_fat_span("almonds") == 0


def test_mentions_fat_covers_named_and_denied():
    assert mentions_fat("sirloin in butter")            # named
    assert mentions_fat("grilled chicken, no oil")      # denied
    assert mentions_fat("plain green salad")            # denied ("plain")
    assert not mentions_fat("sirloin steak")            # silence == a doubt


# ── the omitted doubt, sized ─────────────────────────────────────────────────

def _item(food, cal, unit="", amount=None):
    it = {"food": food, "calories": cal, "unit": unit}
    if amount is not None:
        it["amount"] = amount
    return it


def test_vague_unit_becomes_a_quantity_doubt_sized_to_the_item():
    # A "spoon" logged at 350 — the whole item is in doubt because the unit
    # names no mass; the span is the item's own calories.
    data = {"items": [_item("Peanut butter", 350, unit="spoon", amount=1)]}
    out = _resolved_ambiguities(data, message="a spoon of peanut butter")
    amb = [a for a in out["ambiguities"] if a["field"] == "quantity"]
    assert len(amb) == 1
    assert amb[0]["item"] == "Peanut butter"
    assert amb[0]["impact_cal"] == 350
    assert out["points"] and "how much" in out["points"][0]["qs"][0]


def test_explicit_mass_carries_no_quantity_doubt():
    data = {"items": [_item("Peanut butter", 94, unit="g", amount=16)]}
    out = _resolved_ambiguities(data, message="16 g peanut butter")
    assert not any(a["field"] == "quantity" for a in out["ambiguities"])


def test_low_calorie_vague_unit_is_raised_but_immaterial():
    # A handful of spinach IS a vague unit, so the doubt is stated — but sized to
    # 7 calories it will never clear a mode's bar. Self-filtering by size, not by
    # a food list.
    data = {"items": [_item("Spinach", 7, unit="handful", amount=1)]}
    out = _resolved_ambiguities(data, message="a handful of spinach")
    q = [a for a in out["ambiguities"] if a["field"] == "quantity"]
    assert q and q[0]["impact_cal"] == 7
    assert not _proposed_ask_is_material(
        {"items": data["items"], "ambiguities": q}, mode="moderate", user=None)


def test_unstated_fat_on_a_protein_becomes_a_prep_doubt():
    data = {"items": [_item("Sirloin steak", 440, unit="g", amount=225)]}
    out = _resolved_ambiguities(data, message="sirloin steak")
    prep = [a for a in out["ambiguities"] if a["field"] == "prep"]
    assert len(prep) == 1 and prep[0]["impact_cal"] == 100


def test_addressed_fat_asks_nothing():
    for msg in ("sirloin steak cooked in butter",     # named
                "grilled chicken breast, no oil",     # denied
                "plain green salad"):                  # denied
        data = {"items": [_item(msg.split(",")[0].title(), 300,
                                unit="g", amount=200)]}
        out = _resolved_ambiguities(data, message=msg)
        assert not any(a["field"] == "prep" for a in out["ambiguities"]), msg


def test_a_plain_weighed_grain_raises_no_doubt_at_all():
    data = {"items": [_item("White rice", 260, unit="g", amount=200)]}
    out = _resolved_ambiguities(data, message="200g white rice")
    assert out["ambiguities"] == [] and out["points"] == []


# ── the promotion: the SAME gate the demote uses, run on the synth doubt ──────

def test_material_spoon_promotes_but_a_small_prep_doubt_does_not():
    # 350-cal quantity doubt clears moderate's absolute bar (200); the 100-cal
    # prep doubt does not — so on moderate the spoon is asked and the steak is
    # logged. Mode is the throttle, and it is the mode dial, not a new one.
    spoon = {"items": [_item("Peanut butter", 350, unit="spoon", amount=1)]}
    syn = _resolved_ambiguities(spoon, message="a spoon of peanut butter")
    assert _proposed_ask_is_material(
        {**spoon, "ambiguities": syn["ambiguities"]},
        mode="moderate", user=None)

    steak = {"items": [_item("Sirloin steak", 440, unit="g", amount=225)]}
    syn = _resolved_ambiguities(steak, message="sirloin steak")
    assert not _proposed_ask_is_material(
        {**steak, "ambiguities": syn["ambiguities"]},
        mode="moderate", user=None)
    # strict cares about a 100-cal swing (bar == 100): now it asks.
    assert _proposed_ask_is_material(
        {**steak, "ambiguities": syn["ambiguities"]},
        mode="strict", user=None)


def test_flag_defaults_off():
    # The whole capability is inert until Danny flips it; the suite runs v1.
    assert _v2_accuracy() is False
