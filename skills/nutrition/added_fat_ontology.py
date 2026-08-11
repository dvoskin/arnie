"""WHAT FATS B-1.7 CAN ASK ABOUT — and why every id here is a FOOD.

    _ADDED_FAT_CAL["olive oil"] = 120         a constant, from a phrase
    AddedFat("olive_oil").entity  -> a food   an ingredient, priced

That is the entire difference between this module and the table it replaces.
A fat identity is not a modifier that adds calories; it is a second thing the
user ate, with its own rows, its own density and its own micronutrients. So
pricing becomes COMPOSITION through the canonical pricer, and a typed field
that resolved to "+120 kcal" would be the legacy heuristic with better
manners.

⭐ AN ID THE PRICER CANNOT ACT ON IS INERT — the same constraint
`preparation_ontology` documents, and the reason its list is short. If we
offer "Olive oil" and nothing can price olive oil, the question gets asked,
the answer gets stored, and not one number moves. Worse, its usage rate looks
like engagement. So this module states what it offers and
`test_the_added_fat_ontology_is_priceable` decides whether it MAY be offered,
by asking the artifact rather than by asserting confidence.

MEASURED 2026-08-11: the pricing artifact holds 27 entries and NONE of them is
a fat. Every id below currently MISSES. That is why the field registers as
`Evidence.GENERATED` — not offered when there is no evidence to build an
option from — rather than as an ONTOLOGY field that would ship a chip bar of
unpriceable choices. Extending the artifact's seed set to cover these foods is
the concrete unblocking step, and it is a BUILD-TIME action, not a turn-time
one.

NO `UNKNOWN` MEMBER THAT PRICES. Preparation has one, because an unknown
preparation legitimately leaves the food's name alone. There is no equivalent
here: an unknown FAT cannot be priced as anything, and a member meaning "some
fat, unspecified" would immediately need a calorie value — which is the
default this whole design refuses. Unresolved identity stays an unresolved
FIELD, and B-1.7b decides whether it is worth asking about.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Bumped when the offered set or its wording changes, so a persisted decision
#: can be read against the ontology that produced it rather than today's.
ADDED_FAT_ONTOLOGY_VERSION = "b17_added_fat_v1"


@dataclass(frozen=True)
class AddedFat:
    #: THE FOOD, in the form the pricer looks foods up by. Not a label and not
    #: a phrase — `priced_identity` normalises it exactly as it would any
    #: other entity, so a fat is addressable by the machinery that already
    #: prices chicken.
    entity_id: str
    label: str

    @property
    def entity(self) -> str:
        """The name the pricing path resolves. Underscores are an ID
        convention; the pricer reads foods."""
        return self.entity_id.replace("_", " ")


#: ORDERED AS OFFERED, and deliberately short. These are the fats that carry
#: most of the caloric spread in the legacy table and that a user can name
#: without being coached. Breadth is not the goal — a long list of
#: near-synonyms would make the question harder to answer and no more precise.
#:
#: DELIBERATELY EXCLUDED, each for a stated reason rather than by oversight:
#:
#:   "ranch"/"caesar"/"alfredo"  are DRESSINGS AND SAUCES, not fats. They are
#:                               composite foods and belong to a future
#:                               `added_sauce` field with its own amounts —
#:                               folding them in here would make one field mean
#:                               two things, which is how `_ADDED_FAT_CAL`
#:                               became a phrase table in the first place.
#:   "marinade"                  same, and worse: its calories depend almost
#:                               entirely on what was IN it.
#:   "cooking spray"             real and near-zero, but its amount is
#:                               unmeasurable by the user in the units this
#:                               field offers.
OFFERED: tuple = (
    AddedFat("olive_oil", "Olive oil"),
    AddedFat("butter", "Butter"),
    AddedFat("vegetable_oil", "Vegetable or seed oil"),
    AddedFat("coconut_oil", "Coconut oil"),
    AddedFat("mayonnaise", "Mayonnaise"),
)


def resolve(entity_id: str):
    """The offered fat with this id, or None. NEVER a default.

    Returning something for an unrecognised id is the exact failure this
    module exists to prevent: it would mean an identity we do not hold gets
    priced as one we do.
    """
    wanted = str(entity_id or "").strip().lower()
    for fat in OFFERED:
        if fat.entity_id == wanted:
            return fat
    return None


def priceable() -> tuple:
    """The subset the canonical pricer can ACT on today, measured against the
    committed artifact rather than assumed.

    The field's options are built from THIS, not from `OFFERED`, so an
    unpriceable fat is never offered — and the gap between the two lists is a
    measurement of what the artifact still owes rather than a silent
    degradation.
    """
    from skills.nutrition import pricing_artifact as artifact

    return tuple(f for f in OFFERED if artifact.evidence_for(f.entity))
