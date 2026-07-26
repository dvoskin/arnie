"""Serving-basis sanity checks (directive §9).

Scaling is arithmetic and arithmetic does not notice when its premise is
wrong. Every failure this catches is the same shape: the multiplication was
performed correctly against a basis that did not describe the source.

  * A per-100 g row read as a serving. One tablespoon of peanut butter logged
    as 588 calories, and two tablespoons as 588 as well, because the number
    being multiplied was already the whole 100 g.
  * A count multiplied against a serving panel it does not correspond to. "One
    plate" is not one of a 43 g label's servings; taking it as one and then
    scaling by the plate's estimated mass counts the portion twice.
  * A wrong database row, scaled faithfully. 6.5 oz of roast turkey enriched
    to 614 calories with 0 g protein and 123 g carbs — a grain's row wearing a
    protein food's name.

None of those are detectable from the numbers of any single field. They ARE
detectable from the relationships between them, and those relationships are
physics rather than nutrition: energy has an upper bound per gram, calories
are a fixed function of the macros, and a portion has a plausible mass.

The checks are ordered by what they justify. `IMPOSSIBLE` means the result
cannot describe any food and must not be persisted as though it did —
unknown is not zero, and it is also not the wrong portion. `SUSPECT` means the
number is physically possible but the basis is probably misread, which is a
confidence penalty and a disclosure, not a refusal. Refusing on merely
suspicious numbers would throw away correct answers about unusual foods, and
oils, nuts and spirits are exactly the foods that sit near these bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

#: kcal per gram of pure fat, the densest macronutrient there is. Nothing
#: edible exceeds it, so a result above it is scaled against the wrong basis —
#: but "above it" is not where the REFUSAL belongs.
#:
#: A mass is often derived rather than measured: a per-100ml oil row scaled
#: through a 0.91 g/ml density lands olive oil at 9.7 kcal/g, and olive oil is
#: a correct answer. The density is an estimate, the label figure is rounded,
#: and refusing on an 8% excess would throw away exactly the foods that sit at
#: the ceiling — oils, nut butters, spirits.
#:
#: So the ceiling discloses and the REFUSAL sits far above it. The failures
#: this exists for are not 8% over: one tablespoon of peanut butter carrying
#: the whole per-100g row is 36 kcal/g, four times pure fat. Nothing lands
#: between 12 and 36 by rounding.
MAX_KCAL_PER_G = 9.0
IMPOSSIBLE_KCAL_PER_G = 12.0

#: A single logged ITEM above this is a scaling artefact rather than a meal.
#: Deliberately generous — a large restaurant platter is a real 2,000-calorie
#: item and must survive; 5,000 in one line is the per-100 g row landing whole.
MAX_ITEM_KCAL = 5000.0
MAX_ITEM_MASS_G = 4000.0

#: How far the Atwater sum may sit from the stated calories before the row is
#: suspect. Labels round, fibre and sugar alcohols are counted differently in
#: different jurisdictions, and alcohol is not in the sum at all — so the band
#: is wide, and only a real disagreement clears it.
MACRO_ENERGY_TOLERANCE = 0.30

#: Below this many calories a proportional check is noise: 12 vs 18 kcal is a
#: 50% disagreement and means nothing.
MACRO_CHECK_MIN_KCAL = 40.0

#: How far the portion's mass may sit from `servings × the panel's serving
#: mass` before the count is probably not counting servings.
SERVING_MASS_RATIO = 3.0

IMPOSSIBLE = "impossible"
SUSPECT = "suspect"


@dataclass(frozen=True)
class SanityFinding:
    """One failed check. `code` is stable and greppable; `message` is what a
    human reads in the warnings."""
    code: str
    severity: str
    message: str

    @property
    def is_fatal(self) -> bool:
        return self.severity == IMPOSSIBLE


def _mass_of(quantity) -> Optional[float]:
    grams = getattr(quantity, "grams", None)
    if grams:
        return float(grams)
    ml = getattr(quantity, "milliliters", None)
    # Water-equivalent, only as a bound. Fats float and syrups sink, but no
    # food is dense enough for the 1 g/ml assumption to manufacture a
    # violation of a 9 kcal/g ceiling on its own.
    return float(ml) if ml else None


def check(profile, basis, quantity) -> Tuple[SanityFinding, ...]:
    """Every check that applies, worst first. Never raises.

    `profile` is the SCALED profile — the numbers about to be shown. Checking
    the source row instead would pass every one of the failures above, since
    each of them is a correct row scaled wrongly.
    """
    findings = []
    try:
        calories = profile.amount("calories")
    except Exception:
        return ()
    if calories is None:
        return ()

    mass = _mass_of(quantity)

    # ── Energy density: the hardest bound there is ──────────────────────────
    if mass and mass > 0:
        density = calories / mass
        if density > IMPOSSIBLE_KCAL_PER_G:
            findings.append(SanityFinding(
                "energy_density_impossible", IMPOSSIBLE,
                f"{calories:.0f} cal for {mass:.0f}g is {density:.1f} cal/g — "
                f"far above pure fat, so the serving basis is wrong"))
        elif density > MAX_KCAL_PER_G * 0.95:
            # Oils and nut butters live here legitimately. Worth saying,
            # never worth refusing.
            findings.append(SanityFinding(
                "energy_density_extreme", SUSPECT,
                f"{density:.1f} cal/g is at or above pure fat"))

    # ── Absolute bounds on one line item ────────────────────────────────────
    if calories > MAX_ITEM_KCAL:
        findings.append(SanityFinding(
            "item_calories_impossible", IMPOSSIBLE,
            f"{calories:.0f} cal in a single item — a per-100g row scaled as "
            f"a serving looks exactly like this"))
    if mass and mass > MAX_ITEM_MASS_G:
        findings.append(SanityFinding(
            "item_mass_impossible", IMPOSSIBLE,
            f"{mass:.0f}g in a single item is a portion nobody ate"))

    # ── Atwater: calories are a function of the macros, not an opinion ──────
    protein = profile.amount("protein")
    carbs = profile.amount("carbs")
    fat = profile.amount("fat")
    if (calories >= MACRO_CHECK_MIN_KCAL and protein is not None
            and carbs is not None and fat is not None):
        atwater = protein * 4.0 + carbs * 4.0 + fat * 9.0
        if atwater > 0:
            drift = abs(atwater - calories) / calories
            if drift > MACRO_ENERGY_TOLERANCE:
                findings.append(SanityFinding(
                    "macro_energy_disagreement", SUSPECT,
                    f"macros total {atwater:.0f} cal against {calories:.0f} "
                    f"stated — the row and the portion may not match"))

    # ── A count is only servings when it counts the panel's servings ───────
    servings = getattr(basis, "serving_mass_g", None)
    count = getattr(quantity, "count", None)
    as_served = bool(getattr(basis, "as_served", False))
    if (servings and count and mass and not as_served
            and getattr(basis, "basis", "") == "per_serving"):
        expected = float(servings) * float(count)
        if expected > 0:
            ratio = max(mass / expected, expected / mass)
            if ratio >= SERVING_MASS_RATIO:
                findings.append(SanityFinding(
                    "serving_count_mismatch", SUSPECT,
                    f"{_trim(count)} × {servings:.0f}g servings is "
                    f"{expected:.0f}g against a {mass:.0f}g portion — that "
                    f"count probably isn't counting servings"))

    findings.sort(key=lambda f: 0 if f.is_fatal else 1)
    return tuple(findings)


def _trim(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:g}"


def check_values(*, calories, protein=None, carbs=None, fat=None,
                 grams=None) -> Tuple[SanityFinding, ...]:
    """The same physics, against plain numbers.

    `check()` wants a NutrientProfile and a SourceBasis, which only the
    resolver has — and the resolver has never run on a real turn. So the
    checks that refuse a 588-calorie tablespoon of peanut butter were
    unreachable from the path that actually commits.

    This is the same rules on the values `core.food_intelligence.analyze`
    holds: floats and a gram figure. Deliberately a thin adapter rather than a
    second implementation — the thresholds and the reasoning live once, above.
    """
    class _V:
        def __init__(self, v):
            self.value = v

    class _P:
        def __init__(self, **kw):
            self._v = {k: v for k, v in kw.items() if v is not None}

        def amount(self, key):
            return self._v.get(key)

    class _Q:
        def __init__(self, g):
            self.grams = g
            self.milliliters = None
            self.count = None

    class _B:
        basis = "per_100g"
        serving_mass_g = None
        as_served = False

    return check(_P(calories=calories, protein=protein, carbs=carbs, fat=fat),
                 _B(), _Q(grams))
