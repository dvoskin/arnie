"""Food adapting INTO the shared contracts, not beside them.

The direction matters and is the whole point of the layering: `core/semantics`
knows nothing about food, and food knows about `core/semantics`. A cross-domain
module that imports a domain is not cross-domain.

This is the Phase 3 seam. It runs in shadow — nothing here is on a write path —
so `NormalizedQuantity` and `CanonicalQuantity` can be compared on real traffic
before anything depends on the second. A disagreement found here is free; the
same disagreement found after migration is a wrong number on a card.

WHAT THE ADAPTER CANNOT DO, and says so rather than guessing:

  * `NormalizedQuantity` has no provenance field. It has `assumptions` (a tuple
    of strings) and a bare `unit_label`, and whether a figure was TYPED by the
    user or TAPPED from a chip is not recorded anywhere on it — that lives on
    the item, in `_item_is_stated`, several layers away. So provenance arrives
    as an argument here rather than being read off the object, and defaults to
    UNKNOWN rather than to something flattering.
  * it has no dimension. The dimension is inferred from which resolved value is
    present, which is exactly the inference `CanonicalQuantity` makes
    impossible to get wrong going forward.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from core.semantics import (CanonicalQuantity, Confidence, Dimension,
                            Provenance)


def _dec(value) -> Optional[Decimal]:
    """A float becomes a Decimal via its repr, not its binary expansion.
    `Decimal(158.5)` is 158.5000000000000284…; `Decimal("158.5")` is 158.5."""
    if value is None:
        return None
    return Decimal(str(value))


#: Units whose dimension is not in doubt. Anything else is decided by which
#: resolved value the quantity actually carries, and DIMENSIONLESS when it
#: carries none — an honest answer, and one the contract will not let anyone
#: silently promote.
_UNIT_DIMENSION = {
    "g": Dimension.MASS, "gram": Dimension.MASS, "grams": Dimension.MASS,
    "kg": Dimension.MASS, "oz": Dimension.MASS, "ounce": Dimension.MASS,
    "lb": Dimension.MASS, "lbs": Dimension.MASS,
    "ml": Dimension.VOLUME, "l": Dimension.VOLUME, "liter": Dimension.VOLUME,
    "cup": Dimension.VOLUME, "cups": Dimension.VOLUME,
    "tbsp": Dimension.VOLUME, "tsp": Dimension.VOLUME,
    "floz": Dimension.VOLUME, "fl oz": Dimension.VOLUME,
    "piece": Dimension.COUNT, "pieces": Dimension.COUNT,
    "slice": Dimension.COUNT, "slices": Dimension.COUNT,
    "serving": Dimension.COUNT, "servings": Dimension.COUNT,
}


def dimension_of(unit: str, *, grams=None, milliliters=None,
                 count=None) -> Dimension:
    """What this quantity MEASURES — what the user said, not what we resolved.

    The distinction is the whole reason the field exists. "3 eggs" is a COUNT
    that we happen to have resolved to 150 g; the grams are the answer, not the
    question. Reading the resolution instead labelled every countable food as
    mass, because a countable food is exactly the case where both are present.

    So COUNT is checked before mass: a quantity carrying a count carries it
    because the user counted something. The unit table still wins first, since
    "1 cup" is a volume whether or not a density resolved it.
    """
    known = _UNIT_DIMENSION.get((unit or "").strip().lower())
    if known is not None:
        return known
    if count is not None:
        return Dimension.COUNT
    if grams is not None:
        return Dimension.MASS
    if milliliters is not None:
        return Dimension.VOLUME
    return Dimension.DIMENSIONLESS


def to_canonical(nq, *, provenance: Provenance = Provenance.UNKNOWN,
                 confidence: Optional[Confidence] = None
                 ) -> CanonicalQuantity:
    """`NormalizedQuantity` -> `CanonicalQuantity`.

    Raises `ValueError` when the source object is dimensionally inconsistent —
    and that is the useful part. `CanonicalQuantity` rejects "a mass resolved
    only to millilitres", which `NormalizedQuantity` permits, so running this
    over production traffic in shadow finds the shapes food has been carrying
    all along. Callers in shadow should catch, count and log rather than fail
    the turn.
    """
    grams = _dec(getattr(nq, "grams", None))
    millis = _dec(getattr(nq, "milliliters", None))
    count = _dec(getattr(nq, "count", None))
    unit = str(getattr(nq, "unit", "") or "")
    dim = dimension_of(unit, grams=grams, milliliters=millis, count=count)

    # A volume that has been converted to a mass carries BOTH, legitimately —
    # the density conversion produced them together. The contract allows that;
    # what it refuses is a dimension whose own resolved value is missing.
    return CanonicalQuantity(
        amount=_dec(getattr(nq, "amount", None)),
        unit_id=unit,
        dimension=dim,
        grams=grams,
        milliliters=millis,
        count=count,
        provenance=provenance,
        confidence=confidence or Confidence(),
        uncertainty=_dec(getattr(nq, "uncertainty_g", None)),
        surface_text=str(getattr(nq, "unit_label", "") or ""),
    )


def provenance_for(*, user_stated: bool, from_chip: bool = False,
                   from_label: bool = False,
                   from_mode_default: bool = False) -> Provenance:
    """The mapping food's current flags imply, made explicit.

    `_item_is_stated` returns one boolean for "the user's own words", and a
    tapped chip currently satisfies it — which is how a system-generated
    portion is recorded as user precision. Here the two are separate values,
    and `USER_SELECTED.is_users_own` is False.
    """
    if from_label:
        return Provenance.LABEL
    if from_chip:
        return Provenance.USER_SELECTED
    if user_stated:
        return Provenance.USER_STATED
    if from_mode_default:
        return Provenance.MODE_DEFAULT
    return Provenance.MODEL_ESTIMATE
