"""⛔⛔⛔ CF22 — A CYRILLIC MASS IS A MASS, NOT A COUNT OF 300 THINGS.

Found while partitioning the single-food cohort (2026-08-22). The normalizer
had no entry for `г` or `мл`, so a Russian user's exact mass parsed as a COUNT:

    "300 г"   ->  count=300.0, grams=None, mass_is_exact=False
    "300 g"   ->  grams=300.0,             mass_is_exact=True

⛔⛔ AND A COUNT MULTIPLIES. Priced through the ESTIMATE rung — whose basis is
`PerServing(as_served=True)`, deliberately countable so "2 servings" works —
`300 г` of tvorog committed **60,000 kcal** against the correct 400. A 150x
overcount, and the number LOOKS like a real answer.

⭐ LATENT, NOT LIVE — and that distinction is the whole risk profile. Production
holds 399 entries with a Cyrillic unit, max 825 kcal, and **zero entries over
5000 kcal all-time**: the path is unreachable today because canonical
settlement is cohort-gated and dark. **P17g's rollout is exactly what would
switch it on.** So this is release-blocking for the rollout while being
invisible in the current data — the worst combination for something a canary
would be relied on to catch.

⭐ OBSERVED FORMS ONLY, AND THE AMBIGUOUS ONES ARE LEFT ALONE. Surveyed against
production's 461 Cyrillic quantities: `г` x366 and `мл` x26 are unambiguous
mass and volume. `шт` / `штука` (pieces) and `яйца` (eggs) are genuinely
COUNTS and already correct. `ст`, `ч` and `ложки` are ambiguous — spoon, glass
and cup collide — and guessing at them would be the generalized translation
work this fix is explicitly not. `л` appears ONCE and is included only because
it is exact and unambiguous; `кг`, `гр`, `грамм` are absent from the corpus and
are NOT added on speculation.
"""
from __future__ import annotations

import pytest

from skills.nutrition.normalize import normalize_quantity


# ── THE PARSE ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cyrillic,ascii_control,grams", [
    ("300 г", "300 g", 300.0),
    ("150 г", "150 g", 150.0),
    ("200г", "200g", 200.0),
])
def test_a_cyrillic_gram_is_the_same_quantity_as_an_ascii_gram(
        cyrillic, ascii_control, grams):
    """⛔ THE CONTROL IS THE POINT. `300 g` already works; the claim is that
    `300 г` means the identical thing. Asserting the Cyrillic form alone would
    not show that the two agree — and agreeing with the ASCII path is exactly
    what "semantically equivalent unit form" means."""
    ru = normalize_quantity(cyrillic, "Творог")
    en = normalize_quantity(ascii_control, "Tvorog")

    assert ru.grams == grams, (
        f"{cyrillic!r} did not parse as a mass: grams={ru.grams}, "
        f"count={ru.count}")
    assert ru.mass_is_exact is True, (
        f"{cyrillic!r} is a stated exact mass and must be marked exact, or it "
        f"can never be authoritative")
    assert ru.count is None, (
        f"{cyrillic!r} kept count={ru.count} — a count MULTIPLIES a countable "
        f"basis, which is how 300 г became 60,000 kcal")
    assert (ru.grams, ru.mass_is_exact) == (en.grams, en.mass_is_exact)


@pytest.mark.parametrize("cyrillic,ascii_control,ml", [
    ("250 мл", "250 ml", 250.0),
    ("200мл", "200ml", 200.0),
])
@pytest.mark.parametrize("food", ["Кефир", "Kefir"])
def test_a_cyrillic_millilitre_is_the_same_quantity_as_an_ascii_one(
        cyrillic, ascii_control, ml, food):
    """⛔ THE FOOD IS HELD CONSTANT, AND THE FIRST VERSION DID NOT HOLD IT.

    It compared `250 мл`/"Кефир" against `250 ml`/"Kefir" and failed — but not
    on the unit. `Kefir` is in the density table and `Кефир` is not, so a
    stated volume converts to grams (257.5 g, `mass_is_exact=False`,
    src='vessel') for one and stays a pure volume (`mass_is_exact=True`,
    src='volume_conversion') for the other. The test was measuring a DENSITY
    difference and blaming the alphabet.

    ⚠ THAT ASYMMETRY IS REAL AND IS NOT FIXED HERE. A stated volume can be
    exact for a food whose density is unknown and inexact for one whose
    density is known — which is defensible (the density is an assumption) and
    is nonetheless worth someone's attention. Out of scope: this commit is the
    unit forms, narrowly.
    """
    ru = normalize_quantity(cyrillic, food)
    en = normalize_quantity(ascii_control, food)
    assert ru.milliliters == ml, (
        f"{cyrillic!r} did not parse as a volume: ml={ru.milliliters}, "
        f"count={ru.count}")
    assert ru.count is None, (
        f"{cyrillic!r} kept count={ru.count} — a count multiplies")
    assert (ru.milliliters, ru.grams, ru.mass_is_exact) == \
        (en.milliliters, en.grams, en.mass_is_exact), (
        f"{cyrillic!r} and {ascii_control!r} disagree for the same food "
        f"{food!r} — the unit spelling changed the quantity")


# ── THE DAMAGE IT PREVENTS ────────────────────────────────────────────────


def test_a_cyrillic_mass_can_no_longer_multiply_a_countable_basis():
    """⛔⛔⛔ THE WRONG-NUTRITION PROOF, THROUGH THE REAL PRICER.

    The ESTIMATE rung declares `PerServing(as_served=True)` — countable ON
    PURPOSE, so "2 servings" scales. Feed it `count=300` and it scales by 300.
    Measured before the fix: 60,000 kcal for 300 g of tvorog whose honest
    answer is 400.

    ⭐ This drives `price()` itself, not the normalizer, because the defect
    only becomes NUTRITION one layer down — and a parser test alone would not
    have shown that a missing dictionary entry could commit a five-figure
    calorie row."""
    from core.canonical_pricing import EstimateEvidence, price

    estimate = EstimateEvidence(calories=200.0, protein=20.0, carbs=5.0,
                                fat=8.0, basis_grams=150.0)
    ru = price(entity="Tvorog", consumed=normalize_quantity("300 г", "Творог"),
               estimate=estimate)
    en = price(entity="Tvorog", consumed=normalize_quantity("300 g", "Tvorog"),
               estimate=estimate)

    assert ru.calories == en.calories, (
        f"the Cyrillic mass priced at {ru.calories} kcal and the identical "
        f"ASCII mass at {en.calories} — the unit spelling changed the food")
    assert ru.calories < 1000, (
        f"300 г of tvorog priced at {ru.calories} kcal — a count multiplied a "
        f"per-serving basis")


def test_a_cyrillic_mass_reaches_the_authoritative_path():
    """⭐ AND THE COVERAGE HALF. Before the fix a Russian exact mass could
    never be authoritative — not for want of evidence, but because the quantity
    was unreadable. This is the reason the fix is a PARSER repair and not an
    acquisition tranche."""
    from core.canonical_pricing import MemoryEvidence, Rung, price

    memory = MemoryEvidence(per100g={"calories": 155.0, "protein": 13.0,
                                     "carbs": 1.1, "fat": 11.0},
                            source_id="m", confidence=1.0)
    priced = price(entity="Tvorog",
                   consumed=normalize_quantity("300 г", "Творог"),
                   memory=memory, require_authoritative=True)
    assert priced.rung is Rung.MEMORY
    assert priced.calories == pytest.approx(465.0, abs=0.5)


# ── THE FORMS DELIBERATELY LEFT ALONE ─────────────────────────────────────


@pytest.mark.parametrize("text,why", [
    ("2 шт", "'штука' is a PIECE — genuinely a count, and already correct"),
    ("3 штуки", "the same word inflected"),
    ("2 яйца", "'яйца' is the FOOD (eggs), not a unit"),
])
def test_genuine_cyrillic_counts_are_left_as_counts(text, why):
    """⛔ THE NEGATIVE INVARIANT. A fix that turned every Cyrillic unit into a
    mass would trade one wrong number for another — and `шт` really does mean
    "pieces". Only the forms that ARE masses become masses."""
    q = normalize_quantity(text, "Пельмени")
    assert q.count is not None, f"{text!r}: {why}"
    assert q.grams is None or not q.mass_is_exact, (
        f"{text!r} was given an exact mass it never stated — {why}")


@pytest.mark.parametrize("text", ["2 ст", "1 ч", "2 ложки"])
def test_ambiguous_cyrillic_units_are_NOT_guessed(text):
    """⛔⛔ `ст` IS EITHER A TABLESPOON OR A GLASS; `ч` EITHER A TEASPOON OR AN
    HOUR; `ложки` A SPOON OF UNSTATED SIZE. Each appears a handful of times in
    the corpus and each has more than one honest reading.

    ⭐ AN AMBIGUOUS UNIT MUST NOT BECOME AN EXACT ONE. Picking a reading here
    would put an invented conversion behind `mass_is_exact=True`, which is the
    strongest claim the system can make about a quantity — the CF20 failure
    shape, one layer earlier. They stay unresolved, and a heuristic path that
    declines canonically is the correct outcome."""
    q = normalize_quantity(text, "Суп")
    assert not getattr(q, "mass_is_exact", False), (
        f"{text!r} was resolved to an EXACT quantity — it is ambiguous and no "
        f"reading of it is stated evidence")
