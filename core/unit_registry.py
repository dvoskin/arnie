"""WHAT A UNIT MEANS, exactly, in one closed table.

A serving expression says `1 tbsp`. Proving that it means the quantity stored
beside it requires knowing what a tablespoon is — and knowing it the same way
every time, from a registry, rather than from a renderer's opinion or a
food-name conditional. An unregistered unit is refused rather than guessed at:
a chip that says `1 wibble` is a chip nobody can price.

DECIMAL, NOT FLOAT. `skills.nutrition.normalize` holds the same numbers as
floats, which is correct for its job — it parses human text and its output
feeds an estimate. This table feeds an equality check between what the user is
shown and what would be committed, and `Decimal("14.787") * 1` must be exactly
`Decimal("14.787")`. A float round trip is not.

THE VALUES ARE THE ONES ALREADY IN USE, to the digit, for the reason
`core.units` gives at length: promoting a constant to its defined value is a
deliberate change with its own commit, not a side effect of adding a registry.
`tbsp` is 14.787 here because it is 14.787 there.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from core.units import G_PER_OZ, KG_PER_LB, ML_PER_FLOZ

#: DERIVED, NEVER RESPELLED. `core.units` is the one place that knows what a
#: pound is, and the ratchet in
#: `tests/test_one_place_knows_what_a_pound_is_0804.py` caught this module
#: writing the grams-per-ounce constant out again on its first run — the gate
#: doing exactly its job, on a module added to improve exactness.
#:
#: `Decimal(str(...))` rather than `Decimal(float)`, so the value is the one
#: written there and not its binary neighbour.
_G_PER_OZ = Decimal(str(G_PER_OZ))
_G_PER_LB = Decimal(str(KG_PER_LB)) * Decimal(1000)
_ML_PER_FLOZ = Decimal(str(ML_PER_FLOZ))

#: The canonical measure each dimension resolves to.
MASS = "mass"
VOLUME = "volume"
COUNT = "count"


class UnknownUnit(ValueError):
    """A unit the registry does not define.

    Raised rather than defaulted. A silent fallback to "1 of something" is how
    an unpriced chip reaches a screen looking like a priced one.
    """


@dataclass(frozen=True)
class UnitDefinition:
    unit_id: str
    dimension: str
    #: Canonical units per 1 of this unit — grams, millilitres, or count.
    per_unit: Decimal


def _mass(**kw):
    return {k: UnitDefinition(unit_id=k, dimension=MASS, per_unit=Decimal(v))
            for k, v in kw.items()}


def _volume(**kw):
    return {k: UnitDefinition(unit_id=k, dimension=VOLUME, per_unit=Decimal(v))
            for k, v in kw.items()}


_REGISTRY: dict = {}
_REGISTRY.update(_mass(g="1", gram="1", grams="1", gm="1",
                       kg="1000", kilogram="1000", kilograms="1000"))
_REGISTRY.update({u: UnitDefinition(unit_id=u, dimension=MASS,
                                    per_unit=_G_PER_OZ)
                  for u in ("oz", "ounce", "ounces")})
_REGISTRY.update({u: UnitDefinition(unit_id=u, dimension=MASS,
                                    per_unit=_G_PER_LB)
                  for u in ("lb", "lbs", "pound", "pounds")})
_REGISTRY.update(_volume(ml="1", milliliter="1", millilitre="1",
                         milliliters="1", millilitres="1",
                         l="1000", liter="1000", litre="1000",
                         liters="1000", litres="1000",
                         cup="236.588", cups="236.588",
                         tbsp="14.787", tablespoon="14.787",
                         tablespoons="14.787",
                         tsp="4.929", teaspoon="4.929", teaspoons="4.929",
                         pint="473.176", pints="473.176",
                         quart="946.353", quarts="946.353"))
_REGISTRY["floz"] = UnitDefinition(unit_id="floz", dimension=VOLUME,
                                   per_unit=_ML_PER_FLOZ)

#: COUNTABLE UNITS CARRY NO MASS OF THEIR OWN — the food decides, which is
#: exactly why a piece candidate needs a cited piece weight to reach grams.
#: One of these is one of these; the registry says nothing more.
_COUNTABLE = (
    "piece", "pieces", "slice", "slices", "serving", "servings",
    "unit", "units", "item", "items", "package", "packages", "packet",
    "packets", "container", "containers", "can", "cans", "bottle",
    "bottles", "bar", "bars", "scoop", "scoops", "egg", "eggs",
    "breast", "breasts", "fillet", "fillets", "stick", "sticks",
    "pat", "pats", "handful", "handfuls",
)
_REGISTRY.update({u: UnitDefinition(unit_id=u, dimension=COUNT,
                                    per_unit=Decimal(1)) for u in _COUNTABLE})


def resolve(unit_id: str) -> UnitDefinition:
    """The definition of this unit, or `UnknownUnit`."""
    key = str(unit_id or "").strip().lower()
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownUnit(
            f"{unit_id!r} is not a registered unit, so an amount stated in it "
            f"cannot be shown to mean the quantity beside it") from None


def canonical_amount(amount, unit_id: str) -> Decimal:
    """`amount` of `unit_id`, in that unit's canonical measure."""
    return Decimal(str(amount)) * resolve(unit_id).per_unit


def dimension_of(unit_id: str) -> str:
    return resolve(unit_id).dimension


def is_registered(unit_id: str) -> bool:
    return str(unit_id or "").strip().lower() in _REGISTRY


def registered_units() -> frozenset:
    return frozenset(_REGISTRY)
