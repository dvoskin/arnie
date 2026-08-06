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


#: WHICH DISPLAY RULES WROTE A LABEL. Bumped when a rendering changes, so a
#: persisted `rendered_label` can be read against the rules that produced it
#: rather than against today's.
UNIT_DISPLAY_VERSION = "unit_display_v1"


@dataclass(frozen=True)
class UnitDefinition:
    unit_id: str
    dimension: str
    #: Canonical units per 1 of this unit — grams, millilitres, or count.
    per_unit: Decimal
    #: HOW THE UNIT IS SAID, singular and plural. REGISTERED, not derived:
    #: appending "s" to a canonical unit id produces `240 mls`, `3 tbsps` and
    #: `2 ozs`. Abbreviations do not pluralise in English at all, and a rule
    #: that cannot know which ids are abbreviations cannot be written. It is
    #: also not a rule that survives translation, which is the deeper reason
    #: it belongs in a table.
    singular: str = ""
    plural: str = ""

    def say(self, amount: Decimal) -> str:
        """`1 piece`, `2 pieces`, `240 ml`, `3 tbsp`."""
        one = self.singular or self.unit_id
        many = self.plural or one
        return one if amount == 1 else many


def _abbrev(dimension, **kw):
    """Units whose written form never changes with the amount."""
    return {k: UnitDefinition(unit_id=k, dimension=dimension,
                              per_unit=Decimal(v), singular=k, plural=k)
            for k, v in kw.items()}


def _mass(**kw):
    return _abbrev(MASS, **kw)


def _volume(**kw):
    return _abbrev(VOLUME, **kw)


_REGISTRY: dict = {}
_REGISTRY.update(_mass(g="1", gram="1", grams="1", gm="1",
                       kg="1000", kilogram="1000", kilograms="1000"))
_REGISTRY.update({u: UnitDefinition(unit_id=u, dimension=MASS,
                                    per_unit=_G_PER_OZ,
                                    singular="oz", plural="oz")
                  for u in ("oz", "ounce", "ounces")})
_REGISTRY.update({u: UnitDefinition(unit_id=u, dimension=MASS,
                                    per_unit=_G_PER_LB,
                                    singular="lb", plural="lb")
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
                                   per_unit=_ML_PER_FLOZ,
                                   singular="fl oz", plural="fl oz")

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
#: COUNTABLE UNITS ARE WORDS, so they do inflect — and the plural is written
#: here rather than computed, because "pieces" and "fries" do not come from
#: one rule.
#: Only for countable units the table actually holds.
_PLURALS = {"handful": "handfuls"}
_REGISTRY.update({
    u: UnitDefinition(unit_id=u, dimension=COUNT, per_unit=Decimal(1),
                      singular=u.rstrip("s") if u.endswith("s") else u,
                      plural=_PLURALS.get(u.rstrip("s") if u.endswith("s")
                                          else u,
                                          (u if u.endswith("s")
                                           else f"{u}s")))
    for u in _COUNTABLE})


def say(amount, unit_id: str) -> str:
    """The unit, written for this amount, from the REGISTRY.

    The alternative — appending "s" when the amount is not one — produces
    `240 mls`, `3 tbsps` and `2 ozs`, and cannot be fixed by a better rule
    because no rule can know which ids are abbreviations. It also does not
    survive a second language, which is the deeper reason this is a table.
    """
    return resolve(unit_id).say(Decimal(str(amount)))


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
