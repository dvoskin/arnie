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
FRACTION_FLOOR = 50.0


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


def is_material(*, mode: str, calorie_span: Optional[float] = None,
                protein_span: Optional[float] = None,
                carb_span: Optional[float] = None,
                fat_span: Optional[float] = None,
                item_calories: Optional[float] = None) -> bool:
    """Whether this uncertainty is worth interrupting for.

    ONE rule, wherever the question is being considered. Any dimension crossing
    its own threshold is enough — an item can be calorie-tight and protein-wild,
    and a calorie-only test calls that settled.

    `item_calories` enables the fraction rule. Without it the proportional check
    cannot run, and a caller that has the item's size and does not pass it is
    silently getting the flat threshold alone.
    """
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
