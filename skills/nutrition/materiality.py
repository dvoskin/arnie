"""One materiality policy, for every layer that decides whether to ask.

Four tables decided this, and they disagreed:

    core/food_turn._THRESH            {quick 300, moderate 200, strict 100}
    core/food_ledger.ASK_THRESHOLDS   {quick 300, moderate 200, strict 100}
    skills/nutrition/ambiguity        {quick 120, moderate  60, strict  20}
    skills/nutrition/resolver         {quick 300, moderate 200, strict 100}
                                      + protein spans, a fraction rule, a floor

So a moderate user's meal was judged material at 60 calories by the staged
pipeline and at 200 by everything else — including the number written into the
interpreter's own prompt, which is what the model was told to report against.
The engine asking the questions and the model deciding what to report were
working to different definitions of "worth interrupting for".

**Which numbers are right.** The resolver's are calibrated — its comment records
the sweep that produced them. The staged pipeline's describe themselves as "the
first implementation and are meant to be tuned from production traces". So the
calibrated set wins, and the tighter placeholder does not survive as a second
opinion.

That is not a loosening. The 60 was a crude stand-in for the thing the fraction
rule does properly: a 90-calorie span on a 120-calorie item is most of the item,
and a flat calorie floor cannot see that while a proportion can. The fraction
rule now applies everywhere rather than only in the resolver, which is what
makes one calorie threshold safe to share.

Every value is env-overridable per mode and dimension, so a threshold moves
without a code change and moves in ONE place:

    NUTRITION_ASK_MODERATE_CALORIES=80
"""
from __future__ import annotations

import os
from typing import Optional

MODES = ("quick", "moderate", "strict")

#: The calibrated spans. A span is the range of plausible values for a field —
#: how much the answer could move if the uncertainty resolved the other way.
#:
#: Calories and protein carry the decision on their own; carbs and fat are
#: reported and ranked but rarely decisive, and their thresholds exist so a
#: carb-or-fat-only uncertainty is not structurally unaskable.
DEFAULT_THRESHOLDS = {
    "quick":    {"calories": 300.0, "protein": 15.0, "carbs": 40.0, "fat": 18.0},
    "moderate": {"calories": 200.0, "protein": 8.0,  "carbs": 25.0, "fat": 11.0},
    "strict":   {"calories": 100.0, "protein": 4.0,  "carbs": 12.0, "fat": 5.0},
}

#: A span this large a FRACTION of the item is material whatever its absolute
#: size. "A scoop of peanut butter" spans maybe 190 calories against an item of
#: 190 — the flat threshold nearly misses it and the proportion cannot.
#:
#: Quick is above 1.0 on purpose: it opts out, which is what quick is for.
MATERIAL_FRACTIONS = {"quick": 1.01, "moderate": 0.3, "strict": 0.15}

#: ...but not on trivia. A 100% span on a 12-calorie item is still 12 calories,
#: and asking about it is how a clarification ladder loses its credibility.
#:
#: A FLAT floor cannot draw that line. It throws away every small span
#: regardless of proportion, so a modest uncertainty on a small food is
#: discarded before the fraction rule it was designed for ever runs — and the
#: identical proportional uncertainty on a portion twice the size clears it.
#: The size of the serving decides, which is not a nutrition judgement.
#:
#: Retained for the legacy path below, where there is nothing better to use.
#: When headroom is known, `is_material` does not consult it at all.
FRACTION_FLOOR = 50.0

#: THE PRIMARY RULE: two proportions, both of which must clear their dial.
#:
#: An absolute calorie line is scale-blind — 200 calories means one thing
#: against a 1,400 target and another against 2,900 — and nutrient-blind, since
#: 200 calories of fat doubt is not 200 calories of protein doubt to someone
#: chasing protein. Both are fixed by measuring proportions instead.
#:
#: What it must NOT depend on is when the food was logged. Scoring against the
#: day's REMAINDER did exactly that: the same food gets a different standard at
#: breakfast than at night, an entry backfilled in the evening is held to a
#: stricter rule than the one typed as it was eaten, and retroactive logging
#: ("that was yesterday") has no meaningful remainder to divide by at all. How
#: accurately something is understood cannot depend on the clock. Coaching may
#: read the remainder; the record may not.
#:
#: So the denominators are both fixed for the day:
#:
#:   OF THE ITEM  — is this uncertainty a large part of THIS food? Catches a
#:                  small item that is mostly unknown, which a flat calorie
#:                  line cannot see.
#:   OF THE DAY   — is it a large enough part of a whole day's target to be
#:                  worth a question at all? This is what keeps a trivially
#:                  small food out without a magic floor: something can be 100%
#:                  uncertain and still be a rounding error on the day.
#:
#: Requiring BOTH is what separates a genuinely uncertain small food from
#: trivia, since trivia fails the second while passing the first.
DAY_FRACTIONS = {"quick": 0.02, "moderate": 0.01, "strict": 0.005}


def _env(mode: str, key: str) -> Optional[float]:
    raw = os.getenv(f"NUTRITION_ASK_{mode.upper()}_{key.upper()}")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def thresholds_for(mode: str) -> dict:
    """Every dimension's threshold for a mode, environment applied."""
    mode = (mode or "moderate").strip().lower()
    if mode not in DEFAULT_THRESHOLDS:
        mode = "moderate"
    base = dict(DEFAULT_THRESHOLDS[mode])
    for key in list(base):
        override = _env(mode, key)
        if override is not None:
            base[key] = override
    return base


def calorie_threshold(mode: str) -> float:
    """The single number the interpreter's prompt and the legacy calorie-only
    policy both need. Derived, so it cannot drift from the rest."""
    return thresholds_for(mode)["calories"]


def fraction_for(mode: str) -> float:
    mode = (mode or "moderate").strip().lower()
    override = _env(mode, "fraction")
    if override is not None:
        return override
    return MATERIAL_FRACTIONS.get(mode, MATERIAL_FRACTIONS["moderate"])


def day_fraction_for(mode: str) -> float:
    mode = (mode or "moderate").strip().lower()
    override = _env(mode, "day_fraction")
    if override is not None:
        return override
    return DAY_FRACTIONS.get(mode, DAY_FRACTIONS["moderate"])


def _inflate(confidence: Optional[float]) -> float:
    """A shaky estimate deserves more scrutiny than a firm one of the same
    nominal width, because its true range is wider than the number we can name.
    Widens the span rather than lowering the bar, so one dial still means one
    thing. Bounded to 2x: uncertainty about the estimate cannot outrun the
    estimate."""
    if confidence is None:
        return 1.0
    try:
        return 2.0 - min(max(float(confidence), 0.0), 1.0)
    except (TypeError, ValueError):
        return 1.0


def consequence(*, spans: dict, targets: dict,
                item_calories: Optional[float] = None,
                confidence: Optional[float] = None) -> tuple:
    """`(of_the_day, of_the_item)` — the two proportions, worst nutrient first.

    Scored per nutrient against that nutrient's own DAILY TARGET, and the worst
    carries the decision. That is what makes it nutrient-aware without a table
    of weights to keep in sync: a protein span is judged against the protein
    target, so a user chasing protein has protein uncertainty decide for them,
    automatically and without anyone configuring it.

    Targets, not remainders — see DAY_FRACTIONS. The same food must be
    understood to the same standard whenever it is logged.
    """
    inflate = _inflate(confidence)
    of_day = 0.0
    for key, span in (spans or {}).items():
        if span is None:
            continue
        try:
            span = abs(float(span))
        except (TypeError, ValueError):
            continue
        target = (targets or {}).get(key)
        try:
            target = float(target) if target else 0.0
        except (TypeError, ValueError):
            target = 0.0
        if not span or target <= 0:
            continue
        of_day = max(of_day, (span * inflate) / target)

    of_item = 0.0
    cal_span = (spans or {}).get("calories")
    if cal_span and item_calories:
        try:
            of_item = (abs(float(cal_span)) * inflate) / max(float(item_calories), 1.0)
        except (TypeError, ValueError):
            of_item = 0.0
    return round(of_day, 5), round(of_item, 4)


def is_material(*, mode: str, calorie_span: Optional[float] = None,
                protein_span: Optional[float] = None,
                carb_span: Optional[float] = None,
                fat_span: Optional[float] = None,
                item_calories: Optional[float] = None,
                targets: Optional[dict] = None,
                confidence: Optional[float] = None) -> bool:
    """Whether this uncertainty is worth interrupting for.

    ONE rule, wherever the question is being considered.

    WITH `targets` — the day's goals, which do not move as the day fills — the
    decision is both proportions clearing their dials: large enough a part of
    the food to be worth resolving, AND large enough a part of a day to be
    worth a question. Neither alone is sufficient, which is what separates a
    small food that is genuinely uncertain from one that cannot matter.

    WITHOUT them, the legacy absolute thresholds and the flat fraction floor
    stand in. Those are scale-blind, so a caller that HAS the user's targets and
    does not pass them is choosing a worse answer than it could have.
    """
    if targets:
        of_day, of_item = consequence(
            spans={"calories": calorie_span, "protein": protein_span,
                   "carbs": carb_span, "fat": fat_span},
            targets=targets, item_calories=item_calories,
            confidence=confidence)
        if of_day < day_fraction_for(mode):
            return False
        # An item we cannot size cannot fail the second gate — the day
        # proportion already cleared, and refusing on a missing denominator
        # would silently drop every uncertainty whose item has no calories yet.
        return (not item_calories) or of_item >= fraction_for(mode)

    limits = thresholds_for(mode)
    spans = (("calories", calorie_span), ("protein", protein_span),
             ("carbs", carb_span), ("fat", fat_span))
    for key, span in spans:
        if span is not None and float(span) >= limits[key]:
            return True

    if calorie_span is not None and item_calories:
        span = float(calorie_span)
        if span >= FRACTION_FLOOR:
            if span / max(float(item_calories), 1.0) >= fraction_for(mode):
                return True
    return False
