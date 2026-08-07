"""WHAT PREPARATIONS B-1.5 CAN ASK ABOUT — and why the list is this short.

Preparation is separately material: raw versus roasted moves calories, while
the plate it was served on does not. B-1.5 asks about it as a second
independent field on the same operation as quantity.

THE IDS ARE THE RESOLVER'S OWN TOKENS. This is the whole design constraint and
it is not stylistic. Preparation reaches pricing through the CANONICAL FOOD
NAME — `settle` composes "chicken breast, grilled" and the enrichment lane
looks that up — and `skills.nutrition.validators` then extracts preparation
words from the requested name AND from each candidate's name, downgrading any
candidate whose preparation disagrees. So a preparation id the validator does
not recognise is INERT: the question gets asked, the answer gets stored, and
not one number moves. A chip that changes nothing is worse than no chip,
because its usage rate looks like engagement.

TWO CANDIDATE VALUES WERE REJECTED FOR EXACTLY THAT REASON:

* `breaded` — not in the validator's table. Real, and materially caloric, but
  it cannot be enforced today. Owed: a validator entry, then this option.
* `plain` / `dry` — the same, and worse: "plain" is an ASSERTION OF ABSENCE,
  which needs a different mechanism than a token match on a name.

AND ONE WAS RENAMED RATHER THAN DROPPED:

* `baked` is ACTIVELY HARMFUL as an id. USDA says *roasted*, the validator
  holds `baked` and `roasted` as separate tokens, and disjoint sets DOWNGRADE
  — so answering "Baked" would push away the correct candidate for a food
  whose reference row is "roasted". The id is `roasted`; the LABEL says
  "Baked or roasted", because a label is presentation and an id is semantics.

Everything here is a deliberate, checkable claim: `test_preparation_ids_are
_tokens_the_resolver_acts_on` reads `validators._PREPARATIONS` and fails if any
id drifts out of it.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Bumped when the offered set or its wording changes, so a persisted decision
#: can be read against the ontology that produced it rather than today's.
PREPARATION_ONTOLOGY_VERSION = "b1_preparation_v1"

#: The id meaning "we did not learn it". Carries NO name composition — an
#: unknown preparation must leave the food exactly as it was, not add a word.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Preparation:
    preparation_id: str
    label: str

    @property
    def known(self) -> bool:
        return self.preparation_id != UNKNOWN


#: ORDERED AS OFFERED. Deliberately three plus an out, matching the shape B-1
#: already uses for quantity — and deliberately NOT an attempt at every
#: cooking method. Expanding this is a later commit with its own evidence.
OFFERED = (
    Preparation("grilled", "Grilled"),
    Preparation("roasted", "Baked or roasted"),
    Preparation("fried", "Fried"),
    Preparation(UNKNOWN, "Not sure"),
)

_BY_ID = {p.preparation_id: p for p in OFFERED}


def resolve(preparation_id: str) -> Preparation:
    """The preparation, or `UNKNOWN`.

    Never raises: an id we do not hold means we do not know the preparation,
    and that is a state this ontology can express. Refusing here would turn a
    stale chip into a failed meal.
    """
    return _BY_ID.get(str(preparation_id or "").strip().lower(),
                      _BY_ID[UNKNOWN])


def name_with(food_name: str, preparation_id: str) -> str:
    """The food as the pricing path should look it up.

    THIS IS THE WHOLE PRICING MECHANISM, and it is a composition rather than
    an arithmetic adjustment on purpose. Scaling calories by a
    preparation factor here would be a second opinion about nutrition inside
    an operation with no business holding one — the same defect B-1.75 deleted
    on the quantity side. Naming the food correctly lets the enrichment lane
    find preparation-specific evidence and lets the validator reject
    preparation-mismatched evidence. Both already work.

    IDEMPOTENT, because it has to be. If the interpreter already read
    "grilled chicken" out of the message, the name arrives carrying it, and
    appending again would produce "chicken, grilled, grilled" — a string no
    candidate matches, which would make a correct answer PRICE WORSE than no
    answer at all.
    """
    prep = resolve(preparation_id)
    base = (food_name or "").strip().rstrip(",")
    if not prep.known or not base:
        return base
    if prep.preparation_id in base.lower():
        return base
    return f"{base}, {prep.preparation_id}"
