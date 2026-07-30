"""A correction is a typed operation on a resolved food (plan cause B).

The update path takes the interpreter's mutated STRING and re-searches it. So a
correction that changes nothing about what the food IS still went through
identity re-resolution — or, when the name happened to stay the same, through
nothing at all, and the model's freshly-invented macros were written straight to
the row's columns.

Both failures are the same missing thing: the entry was written from a
resolution — a source, a per-100g basis, an anchor — and none of it was kept, so
a correction had nothing to correct against. From the plan:

    preparation / form  apply the form to the same resolved food
    identity            full re-resolve; disclose when it cannot be priced
    portion             **arithmetic on the stored basis, no lookup**
    macros              the user's numbers win, no lookup

This module owns the PORTION arm, which is the one production kept producing
evidence for — "Update the sun chips to just 9 chips please", "Okay make that
3/4 of that cube lol". It is deliberately the same shape as
`answer_application`: settle the changed field on a stored resolution, price
from numbers already in hand, and return None the moment anything is missing.
The caller's fallback for None is exactly what it does today.

**The old portion is derived, not stored.** An entry keeps its committed
calories and a quantity string; the mass behind that string was thrown away.
With the per-100g basis the created event now carries, the mass comes back as
arithmetic — 210 committed calories at 536 cal/100 g is a 39 g portion — which
is what lets "1 bag" become "9 chips" without a lookup. Without the basis there
is nothing to scale and this declines; a guessed ratio here would put a number
on the board that no source ever produced.

The macros arm is not here because it needs no code: the user's numbers already
win at the call site. The identity and preparation arms stay with the executor's
re-resolution — see the module's caller for what is and is not routed.
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

#: Macros a portion scales. Fiber, sugar and sodium scale identically and are
#: carried when the basis knows them — a correction that rescales the calories
#: and leaves the sodium is a row describing two different portions.
_SCALED = ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium")

#: Column names, which differ from the nutrient names in exactly one place.
_COLUMN = {"fat": "fats"}


def _num(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _grams(raw_quantity: str, food_name: str,
           serving_text: str = "") -> Optional[float]:
    """The mass a quantity string describes, or None.

    `normalize_quantity` is the repo's one answer to this and already knows
    piece weights, vessels and volume conversions. A second table here would be
    a second answer.

    THE PRODUCT'S OWN PANEL FIRST, when the portion is a count. "28 g (about 15
    chips)" says one chip of THIS product is 1.9 g, and `PIECE_WEIGHTS_G`
    describes foods — no table of food-shaped averages knows a Sun Chip from a
    tortilla chip, and its head-noun rule declines on a branded name anyway
    ("Sun Chips Harvest Cheddar" is a cheddar, not a chip). Same helper the
    resolver uses to anchor a count at write time; this is that answer applied
    one turn later.
    """
    text = (raw_quantity or "").strip()
    if not text:
        return None
    try:
        from skills.nutrition.normalize import (count_units_compatible,
                                                normalize_quantity,
                                                serving_unit_mass)
        quantity = normalize_quantity(text, food_name or "")
        grams = _num(quantity.grams)
        if grams and grams > 0:
            return grams
        count = _num(quantity.count)
        panel = serving_unit_mass(serving_text or "") if serving_text else None
        if count and count > 0 and panel:
            unit_mass, panel_unit = panel[0], panel[1]
            # The panel's unit has to answer the portion's. "9 chips" against a
            # panel of "15 chips" is the same object; "9 chips" against "1 bar"
            # is not, and scaling one by the other turns a portion into a
            # package.
            if _num(unit_mass) and count_units_compatible(
                    quantity.unit or "", panel_unit or ""):
                return float(unit_mass) * float(count)
    except Exception:
        return None
    return None


def portion_from_basis(per100: Mapping, *, calories: Optional[float]
                       ) -> Optional[float]:
    """How much was eaten, from what it cost and what it costs per 100 g.

    The entry never stored its mass. It stored the committed calories, and the
    created event now stores the per-100g row they were computed from, so the
    portion is recoverable exactly rather than re-guessed from its wording.
    """
    per_100 = _num((per100 or {}).get("calories"))
    total = _num(calories)
    if not per_100 or per_100 <= 0 or not total or total <= 0:
        return None
    return (total / per_100) * 100.0


def rescale(per100: Mapping, grams: float) -> Optional[dict]:
    """The macros for `grams` of a per-100g row, as entry columns."""
    per_100_cal = _num((per100 or {}).get("calories"))
    if not per_100_cal or per_100_cal <= 0 or not grams or grams <= 0:
        return None
    factor = float(grams) / 100.0
    out = {}
    for nutrient in _SCALED:
        value = _num((per100 or {}).get(nutrient))
        if value is None:
            # Unknown stays unknown. A missing sodium is not a zero sodium —
            # the same rule the nutrient types keep, applied to a rescale.
            continue
        out[_COLUMN.get(nutrient, nutrient)] = round(value * factor, 1)
    return out or None


def scale_by_ratio(committed: Mapping, ratio: float) -> Optional[dict]:
    """The committed row's own numbers at a new fraction of the portion.

    The fallback when there is no stored basis but both portions are
    mass-comparable — or when the user states a fraction of what is already
    there ("make that 3/4"). Arithmetic on numbers that were once resolved
    beats a fresh guess about the same food.
    """
    if not ratio or ratio <= 0:
        return None
    out = {}
    for nutrient in _SCALED:
        column = _COLUMN.get(nutrient, nutrient)
        value = _num((committed or {}).get(column))
        if value is None:
            continue
        out[column] = round(value * float(ratio), 1)
    return out or None


def apply_portion(*, food_name: str, old_quantity: str, new_quantity: str,
                  committed: Mapping, per100: Optional[Mapping] = None,
                  serving_text: str = "") -> Optional[dict]:
    """New macros for a portion correction on the SAME food, or None.

    Two routes, better one first:

    1. **From the stored basis.** The per-100g row the entry was written from,
       scaled to the corrected mass. Exact, and independent of what the old
       portion was worded as.
    2. **By ratio.** No basis stored (older rows), but both portions resolve to
       a mass — so the row's own committed numbers scale by their ratio.

    None whenever neither route is available. That is the honest outcome for
    "1 bag" -> "a couple handfuls" with no basis to anchor either end, and the
    caller falls back to what it does today.
    """
    new_grams = _grams(new_quantity, food_name, serving_text)
    if new_grams is None:
        return None

    if per100 and _num((per100 or {}).get("calories")):
        scaled = rescale(per100, new_grams)
        if scaled is not None:
            logger.info("event=correction_apply outcome=applied route=basis "
                        "food=%r grams=%.1f cal=%s", food_name, new_grams,
                        scaled.get("calories"))
            return scaled

    old_grams = _grams(old_quantity, food_name, serving_text)
    if old_grams:
        scaled = scale_by_ratio(committed, new_grams / old_grams)
        if scaled is not None:
            logger.info("event=correction_apply outcome=applied route=ratio "
                        "food=%r ratio=%.3f cal=%s", food_name,
                        new_grams / old_grams, scaled.get("calories"))
            return scaled

    logger.info("event=correction_apply outcome=declined reason=no_basis "
                "food=%r old=%r new=%r", food_name, old_quantity, new_quantity)
    return None


def apply_count_correction(*, food_name: str, old_quantity: str,
                           new_quantity: str, committed: Mapping
                           ) -> Optional[dict]:
    """"1 bar" -> "half a bar", priced by counting. No mass, no basis, no lookup.

    THE GROUND-TRUTH POPULATION. Verified on the first post-deploy log
    (2026-07-30 20:14, ev#519, "Happy Wolf chocolate chip bar", `basis:
    regular`): when the user's own regular or their read of a label answers the
    food, `_analyze_food` takes the override path and **no lane runs** — so
    there is no per-100g row, and `resolution` is correctly stored as null.
    That is honest, and it left the whole repeat-logging population with no
    arithmetic at all: mass is unknown at both ends, so `apply_portion`
    declines and the model's re-guess stands.

    It does not need mass. One bar and half a bar are the same object counted
    twice, so the ratio of the counts prices it exactly — from numbers the user
    themselves established.

    `count_units_compatible` is the whole safety property, and it is not
    decoration: without it "1 bar" against "60 g" would divide a count by a
    mass and scale a 110-calorie bar to 2,750. It rejects a bare unit and a
    cross-dimension pair, so a portion can never become a package.
    """
    try:
        from skills.nutrition.normalize import (count_units_compatible,
                                                normalize_quantity)
        old = normalize_quantity((old_quantity or "").strip(), food_name or "")
        new = normalize_quantity((new_quantity or "").strip(), food_name or "")
        old_n, new_n = _num(old.count), _num(new.count)
        if not old_n or not new_n or old_n <= 0 or new_n <= 0:
            return None
        if not count_units_compatible(old.unit or "", new.unit or ""):
            return None
        scaled = scale_by_ratio(committed, new_n / old_n)
        if scaled is not None:
            logger.info("event=correction_apply outcome=applied route=count "
                        "food=%r ratio=%.3f cal=%s", food_name, new_n / old_n,
                        scaled.get("calories"))
        return scaled
    except Exception as e:
        logger.warning(f"count correction unavailable: {e}")
        return None
