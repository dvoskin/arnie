"""Typed ambiguity and materiality (directive 2026-07-25, build order 3, 6).

A question should not be asked because ambiguity exists. It should be asked
because the ambiguity materially changes the log.

That distinction needs two things this module provides. First, ambiguity has
to be an OBJECT rather than a flag: which field is unresolved, what the
candidate values are, what each one would cost, and what to ask. A boolean
cannot be ranked, bundled, or answered.

Second, materiality has to be a number computed against the mode's thresholds,
so "is this worth interrupting for" is a comparison instead of a judgement
call buried in a prompt. A 10-calorie doubt between Royo Plain and Royo
Everything is not worth a turn in any mode. A 190-calorie doubt between two
Fairlife bottles is worth one in most.

Thresholds live here as data, tuned from production traces — not in prompts,
where they cannot be tested or changed without a deploy.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AmbiguityType(str, Enum):
    PRODUCT_IDENTITY = "product_identity"     # which product entirely
    PRODUCT_LINE = "product_line"             # which line within a brand
    PRODUCT_VARIANT = "product_variant"       # which flavour/variant
    PACKAGE_SIZE = "package_size"             # which size of the same product
    CONSUMED_QUANTITY = "consumed_quantity"   # how much of it went in
    SERVING_BASIS = "serving_basis"           # what the label's numbers mean
    PREPARATION = "preparation"               # raw/cooked/fried
    COMPONENT_BREAKDOWN = "component_breakdown"   # what's in the composite
    UNIT_INTERPRETATION = "unit_interpretation"   # "a scoop" of what size

    @property
    def is_identity(self) -> bool:
        return self in (AmbiguityType.PRODUCT_IDENTITY,
                        AmbiguityType.PRODUCT_LINE,
                        AmbiguityType.PRODUCT_VARIANT,
                        AmbiguityType.PACKAGE_SIZE)


@dataclass(frozen=True)
class AmbiguityOption:
    """One thing it might be, with how likely we think that is. `payload`
    carries whatever the answer parser needs to apply this choice — a
    candidate id, a quantity, a fraction."""
    label: str
    confidence: float = 0.0
    payload: Any = None
    candidate_id: Optional[str] = None


@dataclass(frozen=True)
class FoodAmbiguity:
    """One unresolved detail on one item.

    The spans are the point: they are what turns "we're unsure" into "being
    wrong here costs 190 calories and 16 g of protein", which is the only
    basis on which interrupting someone is justifiable.
    """
    ambiguity_id: str
    staged_item_id: str
    ambiguity_type: AmbiguityType
    field_name: str
    candidate_values: tuple = ()
    calorie_span: Optional[float] = None
    protein_span: Optional[float] = None
    carb_span: Optional[float] = None
    fat_span: Optional[float] = None
    confidence: float = 0.0
    materiality_score: float = 0.0
    clarification_prompt: str = ""
    identity_risk: float = 0.0
    serving_basis_risk: float = 0.0
    #: The item's own reading, which the span is a spread AROUND. It was already
    #: being passed to `build_ambiguity` — to size the fraction rule — and then
    #: dropped on the floor, which left the span a width with no position and
    #: made `calorie_range` underivable downstream. Kept so a question can say
    #: what the answer is worth in the units the user reads.
    item_calories: Optional[float] = None

    @property
    def is_material(self) -> bool:
        """Scores are normalized against the mode's thresholds, so 1.0 is
        exactly "at the line"."""
        return self.materiality_score >= 1.0

    # ── `calorie_range` REMOVED (2026-07-28) ────────────────────────────────
    #
    # It returned the reading ± half the span, floored at zero, and its own
    # docstring called that "an approximation". The floor is where the
    # approximation stops being one: whenever the span is at least twice the
    # reading the low end is 0, so Cheez Doodles shipped as "somewhere between
    # 0 and 500 cal" — between nothing and a lot, which is worse than saying
    # nothing at all. Nobody eats zero calories of a thing they just said they
    # ate.
    #
    # The obvious repair — endpoints from real pack sizes instead — is the same
    # mistake pointing the other way: a 24 oz share bag is a real product and a
    # ridiculous thing to offer as an equal option for one sitting. Both
    # versions compute plausibility out of data that does not encode it.
    # Whether a food is eaten whole or eaten FROM is world knowledge; it varies
    # by product, size and occasion, and no formula here can hold it.
    #
    # So there is no third formula. `calorie_span` stays — it is a width, it
    # ranks questions honestly, and `stakes` is built from it. What the
    # question SAYS is now formed by whoever writes the sentence, from the
    # reading, the span and the priced shelf options, with the reading marked
    # explicitly unsettled. A clarification commits nothing, so its numbers are
    # framing rather than a claim, and `validate()` still holds the other half:
    # it checks a sentence against `committed_snapshot`, and a clarification
    # has none.
    def top_options(self, n: int = 3) -> tuple:
        return tuple(sorted(self.candidate_values,
                            key=lambda o: -o.confidence)[:n])


# ── thresholds (directive 6) ──────────────────────────────────────────────────
#: What counts as a material difference, per mode. Data, not prose: these are
#: the first implementation and are meant to be tuned from production traces.
#: Overridable per-key by environment so a threshold can move without a code
#: change (NUTRITION_ASK_MODERATE_CALORIES=80).
#: Re-exported from `skills.nutrition.materiality`, which is now the only place
#: these are decided. This table used to hold its own numbers — moderate at 60
#: calories against 200 everywhere else, including the figure written into the
#: interpreter's own prompt. The engine asking the questions and the model
#: deciding what to report were working to different definitions.
from skills.nutrition.materiality import (  # noqa: E402
    DEFAULT_THRESHOLDS, FRACTION_FLOOR, consequence, day_fraction_for,
    fraction_for, thresholds_for)


def materiality(*, mode: str, calorie_span: Optional[float] = None,
                protein_span: Optional[float] = None,
                carb_span: Optional[float] = None,
                fat_span: Optional[float] = None,
                identity_risk: float = 0.0,
                serving_basis_risk: float = 0.0,
                item_calories: Optional[float] = None,
                targets: Optional[dict] = None,
                confidence: Optional[float] = None) -> float:
    """How much this ambiguity matters, normalized so 1.0 is the mode's line.

    The MAX across axes, not the sum: an ambiguity that is 3× over on protein
    matters whether or not calories also moved, and averaging would let a
    large protein swing hide behind unchanged calories.

    Identity and serving-basis risk enter directly rather than through a
    threshold, because they are not measured in grams — getting the product
    wrong is a different kind of error from getting the portion slightly wrong,
    and it stays material even when the calorie difference is small.
    """
    # WITH TARGETS, the two proportions decide — see materiality.DAY_FRACTIONS.
    # Normalised the same way as everything below: each proportion over its own
    # dial, and the MINIMUM of the two, because both have to clear. Identity and
    # serving-basis risk still enter directly; they are not measured in grams
    # and a proportion of a day says nothing about them.
    if targets:
        of_day, of_item = consequence(
            spans={"calories": calorie_span, "protein": protein_span,
                   "carbs": carb_span, "fat": fat_span},
            targets=targets, item_calories=item_calories,
            confidence=confidence)
        gate = of_day / max(day_fraction_for(mode), 1e-9)
        if item_calories:
            gate = min(gate, of_item / max(fraction_for(mode), 1e-9))
        return round(max(gate, identity_risk, serving_basis_risk), 3)

    t = thresholds_for(mode)
    scores = [identity_risk, serving_basis_risk]
    for span, key in ((calorie_span, "calories"), (protein_span, "protein"),
                      (carb_span, "carbs"), (fat_span, "fat")):
        if span is None:
            continue
        limit = t.get(key) or 0.0
        if limit > 0:
            scores.append(abs(float(span)) / limit)

    # THE FRACTION RULE, which this scorer did not have. It compared spans
    # against a flat threshold only, so it needed a very low one to catch
    # proportionally-large uncertainty on small items — moderate sat at 60
    # calories while every other layer used 200, and the interpreter was
    # briefed on 200.
    #
    # A flat threshold cannot see that 90 calories of doubt on a 120-calorie
    # item is most of the item, and a proportion can. With this here, the one
    # calibrated threshold is safe to share: the absolute axis handles the
    # platter, the relative axis handles the granola bar, and neither has to be
    # distorted to cover for the other.
    if calorie_span is not None and item_calories:
        span = abs(float(calorie_span))
        if span >= FRACTION_FLOOR:
            fraction = span / max(float(item_calories), 1.0)
            limit = fraction_for(mode)
            if limit > 0:
                scores.append(fraction / limit)
    return round(max(scores) if scores else 0.0, 3)


def make_ambiguity_id(staged_item_id: str, field_name: str) -> str:
    """One ambiguity per (item, field). Asking the same question twice about
    the same field is the loop this prevents."""
    digest = hashlib.sha1(
        f"{staged_item_id}|{field_name}".encode("utf-8")).hexdigest()[:10]
    return f"amb_{digest}"


def build_ambiguity(*, staged_item_id: str, ambiguity_type: AmbiguityType,
                    field_name: str, options=(), mode: str = "moderate",
                    calorie_span=None, protein_span=None, carb_span=None,
                    fat_span=None, identity_risk: float = 0.0,
                    serving_basis_risk: float = 0.0,
                    item_calories=None,
                    targets=None, confidence: Optional[float] = None,
                    prompt: str = "") -> FoodAmbiguity:
    """Construct an ambiguity with its materiality already scored, so nothing
    downstream has to know the thresholds."""
    options = tuple(options)
    score = materiality(mode=mode, calorie_span=calorie_span,
                        protein_span=protein_span, carb_span=carb_span,
                        fat_span=fat_span, identity_risk=identity_risk,
                        serving_basis_risk=serving_basis_risk,
                        item_calories=item_calories,
                        targets=targets, confidence=confidence)
    # Confidence in the LEADING option: a 0.9/0.05/0.05 split is barely
    # ambiguous, while 0.35/0.33/0.32 is a coin toss wearing three hats.
    top = max((o.confidence for o in options), default=0.0)
    return FoodAmbiguity(
        ambiguity_id=make_ambiguity_id(staged_item_id, field_name),
        staged_item_id=staged_item_id, ambiguity_type=ambiguity_type,
        field_name=field_name, candidate_values=options,
        calorie_span=calorie_span, protein_span=protein_span,
        carb_span=carb_span, fat_span=fat_span, confidence=top,
        materiality_score=score, clarification_prompt=prompt,
        identity_risk=identity_risk, serving_basis_risk=serving_basis_risk,
        item_calories=(float(item_calories) if item_calories else None))


def spans_across(profiles) -> dict:
    """The macro spread across a set of candidate nutrient profiles — what the
    choice between them actually costs. Fields no candidate knows contribute
    nothing rather than a zero span, since "all unknown" is not "all agree"."""
    out = {}
    for key in ("calories", "protein", "carbs", "fat"):
        values = [p.amount(key) for p in (profiles or ())
                  if p is not None and p.amount(key) is not None]
        out[f"{key}_span"] = (round(max(values) - min(values), 1)
                              if len(values) >= 2 else None)
    return out
