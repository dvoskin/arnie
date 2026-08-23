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


# ══════════════════════════════════════════════════════════════════════════
# VOLUME — THE SEMANTIC BOUNDARY, PROVEN TO THE COMMITTED NUTRITION
#
#     г       exact MASS
#     мл / л  exact VOLUME
#     мл / л  NOT exact mass without an authoritative density/conversion
#
# ⛔ THE DENSITY ASYMMETRY RECORDED IN CF22 HAD TO BE PROVEN, NOT WAVED PAST
# *(Danny, review of PR #85)*. "Metadata-only, out of scope" is a claim about
# CAUSALITY, and a claim about causality has to be demonstrated at the layer
# that commits — which is exactly the argument CF22 itself makes about the gram
# defect being invisible at the parser and catastrophic at the pricer.
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("food", ["Кефир", "Kefir"])
@pytest.mark.parametrize("cyrillic,ascii_control", [
    ("300 мл", "300 ml"), ("250 мл", "250 ml"),
    ("1 л", "1 l"), ("0.5 л", "0.5 l"),
])
def test_the_unit_SPELLING_never_changes_the_normalized_facts(
        cyrillic, ascii_control, food):
    """⛔ 1 AND 2 — `300 мл` ≡ `300 ml`, `1 л` ≡ `1 l`. Every field, same food.

    Comparing whole objects rather than one attribute: a fix that got the
    millilitres right and the `mass_is_exact` flag wrong would pass a
    single-field assertion and still change what canonical is allowed to do."""
    ru = normalize_quantity(cyrillic, food)
    en = normalize_quantity(ascii_control, food)
    fields = ("milliliters", "grams", "count", "mass_is_exact",
              "normalization_source", "amount")
    got = {f: getattr(ru, f, None) for f in fields}
    want = {f: getattr(en, f, None) for f in fields}
    assert got == want, (
        f"{cyrillic!r} and {ascii_control!r} disagree for {food!r}: "
        f"{got} vs {want}")


@pytest.mark.parametrize("text", ["300 мл", "300 ml", "1 л", "1 l", "250 мл"])
@pytest.mark.parametrize("food", ["Кефир", "Kefir", "Сок"])
def test_3_a_stated_volume_is_NEVER_a_count(text, food):
    """⛔ 3 — THE DEFECT'S SHAPE, ON THE VOLUME SIDE. `300 г` became
    `count=300` and multiplied a countable basis into 60,000 kcal. `300 мл`
    must never be able to do the same thing."""
    q = normalize_quantity(text, food)
    assert q.count is None, (
        f"{text!r} of {food!r} parsed as count={q.count} — a count MULTIPLIES "
        f"a countable basis, which is the 150x defect on the volume side")
    assert q.milliliters, f"{text!r} carried no volume at all"


def test_4_a_volume_against_per100g_REFUSES_rather_than_assuming_1ml_is_1g():
    """⛔⛔⛔ 4 — THE CLAIM THAT MATTERS. `Кефир` is absent from the density
    table, so `250 мл` carries `mass_is_exact=True` with `grams=None`. Rung 1
    of the precedence ladder (`user_stated_exact`) therefore FIRES.

    The question is what happens next, and the honest answer must be a refusal:
    a per-100 g basis needs a MASS, and the only way to produce one from a
    volume is a density. Assuming 1 ml = 1 g would manufacture a mass and hand
    it rung 1's authority — an invented number wearing the strongest claim the
    system makes. Measured: `_factor` raises `ScalingRefused` and the whole
    resolution refuses."""
    from skills.nutrition.scaling import Per100g, ScalingRefused, resolve_scaling

    consumed = normalize_quantity("250 мл", "Кефир")
    assert consumed.mass_is_exact is True and consumed.grams is None, (
        "precondition changed: this test exists because rung 1 fires with no "
        "mass available")
    with pytest.raises(ScalingRefused):
        resolve_scaling(Per100g(), consumed, ())


@pytest.mark.parametrize("cyrillic,ascii_control", [("250 мл", "250 ml"),
                                                    ("1 л", "1 l")])
def test_5_with_a_density_BOTH_SCRIPTS_agree_on_grams_authority_and_price(
        cyrillic, ascii_control):
    """⛔ 5 — WHERE A DENSITY EXISTS, the two spellings must agree on every
    consequence, not merely on the parse: grams, resolver authority, committed
    calories and the provenance recorded on the row."""
    from core.canonical_pricing import MemoryEvidence, price
    from skills.nutrition.scaling import Per100g, resolve_scaling

    per100g = {"calories": 60.0, "protein": 3.0, "carbs": 4.0, "fat": 3.2}
    out = []
    for text in (cyrillic, ascii_control):
        consumed = normalize_quantity(text, "Kefir")
        resolution = resolve_scaling(Per100g(), consumed, ())
        priced = price(entity="Kefir", consumed=consumed,
                       memory=MemoryEvidence(per100g=dict(per100g),
                                             source_id="m", confidence=1.0))
        out.append((consumed.grams, resolution.authoritative, resolution.path,
                    round(priced.calories, 4), priced.rung, priced.basis))
    assert out[0] == out[1], (
        f"{cyrillic!r} and {ascii_control!r} committed differently: "
        f"{out[0]} vs {out[1]}")


def test_6_the_COMMITTED_nutrition_is_identical_across_scripts():
    """⛔ 6 — THE FINAL PATH, NOT THE NORMALIZER FIELDS. CF22's whole lesson is
    that a dictionary entry is invisible at the parser and decides a five-figure
    calorie row one layer down. So the volume claim is made where the number is
    actually produced."""
    from core.canonical_pricing import MemoryEvidence, price

    memory = MemoryEvidence(per100g={"calories": 60.0, "protein": 3.0,
                                     "carbs": 4.0, "fat": 3.2},
                            source_id="m", confidence=1.0)
    ru = price(entity="Kefir", consumed=normalize_quantity("250 мл", "Kefir"),
               memory=memory)
    en = price(entity="Kefir", consumed=normalize_quantity("250 ml", "Kefir"),
               memory=memory)
    assert (ru.calories, ru.protein, ru.carbs, ru.fats) == \
           (en.calories, en.protein, en.carbs, en.fats), (
        f"the unit spelling changed the committed nutrition: "
        f"{ru.calories} vs {en.calories} kcal")
    assert ru.calories == pytest.approx(154.5, abs=0.5), (
        "250 ml of kefir at density 1.03 is 257.5 g -> 154.5 kcal")


def test_the_density_asymmetry_CANNOT_REACH_SETTLEMENT_and_this_guard_says_when():
    """⛔⛔⛔ THE PARKING, MADE SELF-INVALIDATING.

    The asymmetry is real and it is NOT purely metadata: against a `Per100ml`
    basis the resolver gives a stated volume DIFFERENT AUTHORITY depending on
    whether the food has a density —

        Кефир (no density)  250 мл -> user_stated_exact  authoritative=True
        Kefir (density 1.03) 250 мл -> heuristic:vessel   authoritative=False

    — with the SAME factor, 2.500. The known-density food is denied authority
    for a conversion the per-100 ml path never uses.

    ⭐ IT CANNOT REACH SETTLEMENT TODAY, AND THE REASON IS STRUCTURAL: NOTHING
    CONSTRUCTS `Per100ml`. `_from_memory` and `_from_artifact` declare
    `Per100g()`, `_from_product` declares `PerServing` or `Per100g`,
    `_from_estimate` declares `PerServing`. Against every basis a producer
    actually emits, both branches REFUSE — one at `_factor` for want of a mass,
    the other at the authority gate for being heuristic. Neither can commit a
    number, so no committed nutrition differs.

    ⛔ SO IT IS PARKED — AND THIS TEST IS THE PARKING TICKET. CF22 exists
    because a latent defect was one rollout away from live. The day a producer
    emits `Per100ml`, this fails and the asymmetry must be revisited BEFORE
    that producer ships."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    emitters = []
    for path in list(root.glob("core/**/*.py")) + \
            list(root.glob("skills/**/*.py")) + \
            list(root.glob("api/**/*.py")) + list(root.glob("handlers/**/*.py")):
        if path.name == "scaling.py":
            continue                       # the definition, not an emission
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                # noqa: PERF203
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    getattr(node.func, "id", "") == "Per100ml":
                emitters.append(f"{path.relative_to(root)}:{node.lineno}")
    assert emitters == [], (
        "a producer now emits Per100ml: %s. The density asymmetry recorded in "
        "CF22 becomes REACHABLE — a stated volume gets different resolver "
        "authority for the same factor depending on whether the food has a "
        "density. Revisit it before that producer ships." % (emitters,))
