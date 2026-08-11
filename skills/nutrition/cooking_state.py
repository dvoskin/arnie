"""PHASE 0.2 — RAW VERSUS COOKED, decided by code from a DECLARED vocabulary.

This is the dimension that actually caused the pricing-spine instability. For
`mackerel|roasted` USDA returns eight rows, and the discriminating fact is
plain in every one of them:

    Fish, mackerel, Atlantic, raw                  RAW
    Fish, mackerel, king, raw                      RAW
    Fish, mackerel, spanish, raw                   RAW
    Fish, mackerel, Atlantic, cooked, dry heat     COOKED
    Fish, mackerel, king, cooked, dry heat         COOKED
    Fish, mackerel, spanish, cooked, dry heat      COOKED
    Fish, mackerel, salted                         neither
    Fish, mackerel, jack, canned, drained solids   neither

A request for a ROASTED food is a request for a COOKED one, so the raw rows are
mechanically incompatible — a fact no language model is needed to establish,
and one a model was getting wrong nondeterministically. The three rows the
stable qualifier kept are exactly the three cooked ones, and the three the
drift destroyed were cooked rows too.

⭐ THE VOCABULARY IS DECLARED, NOT INVENTED HERE. Tokens come from
`validators._PREPARATIONS` — the set the resolver already acts on — so this
module adds no new words to the system. What it adds is a STATE GROUPING over
that existing set, which is a small, versioned, auditable claim rather than a
food table. There is no food name anywhere in this file, and a new food needs
nothing.

⭐⭐ CONSERVATIVE BY CONSTRUCTION. Three states, and `UNCLASSIFIED` is a
first-class one. Salted and canned resolve to `UNCLASSIFIED` — canned fish is
usually cooked, and "usually" is not a mechanical fact, so the rule declines to
speak. A veto requires BOTH sides classified AND in conflict; anything else is
silence.

    THIS IS THE SESSION'S INVARIANT AGAIN. "I cannot classify this
    description" must never become "this evidence is incompatible". The
    qualifier this replaces failed by making exactly that substitution.

⭐⭐⭐ AND IT ONLY EVER VETOES. Establishing that a raw row cannot serve a
roasted request is mechanical. Deciding that a cooked row IS the right one is
identity work, and stays with ranking.
"""
from __future__ import annotations

from enum import Enum

#: Bumped when the grouping changes, so a candidate that disappears between
#: builds is attributable to a POLICY CHANGE rather than filed as drift.
COOKING_STATE_POLICY_VERSION = "food_cooking_state_v1"


class State(str, Enum):
    RAW = "raw"
    COOKED = "cooked"
    #: Not a failure — a legitimate answer meaning the description states no
    #: mechanically decidable state. It NEVER supports a veto.
    UNCLASSIFIED = "unclassified"


#: Declared tokens that assert the food was NOT cooked.
_RAW_TOKENS = frozenset({"raw"})

#: Declared tokens that assert the food WAS cooked. Every one is already in
#: `validators._PREPARATIONS`; the assertion here is only which side of the
#: raw/cooked line it falls on.
_COOKED_TOKENS = frozenset({"cooked", "baked", "roasted", "grilled", "fried",
                            "boiled", "steamed", "broiled", "braised",
                            "stewed", "sauteed", "sautéed", "poached",
                            "toasted", "microwaved"})

#: Declared tokens that describe PRESERVATION rather than cooking. Named
#: explicitly so their silence is a decision on the record, not an oversight:
#: canned fish is usually cooked and "usually" is not mechanical.
_PRESERVED_TOKENS = frozenset({"canned", "salted", "smoked", "dried",
                               "dehydrated", "frozen", "cured", "pickled",
                               "powdered", "concentrate"})


def _tokens(text: str) -> frozenset:
    """WORD boundaries, never substrings.

    A substring test would read "fried" inside "friedcake" and, far worse,
    "raw" inside "strawberry" — silently changing which foods are eligible.
    The same lesson `pricing_artifact._without` was written for.
    """
    cleaned = []
    for char in str(text or "").lower():
        cleaned.append(char if char.isalnum() else " ")
    return frozenset("".join(cleaned).split())


def classify(text: str) -> State:
    """The state a description ASSERTS, or UNCLASSIFIED.

    A description carrying BOTH a raw and a cooked token is UNCLASSIFIED
    rather than one of them — "raw, then cooked" is a real USDA phrasing and
    guessing which one governs would be identity work.
    """
    words = _tokens(text)
    raw, cooked = bool(words & _RAW_TOKENS), bool(words & _COOKED_TOKENS)
    if raw and cooked:
        return State.UNCLASSIFIED
    if raw:
        return State.RAW
    if cooked:
        return State.COOKED
    # A preservation term on its own says nothing about cooking, and neither
    # does a description with no state token at all. Both decline to speak.
    return State.UNCLASSIFIED


def conflict(requested: str, candidate: str) -> bool:
    """Do these two descriptions assert OPPOSITE cooking states?

    True ONLY when both sides classify and disagree. Every other combination —
    either side unclassified, or both on the same side — returns False, which
    is silence rather than approval: this function answers "is there a proven
    mechanical conflict", and nothing else.
    """
    left, right = classify(requested), classify(candidate)
    if State.UNCLASSIFIED in (left, right):
        return False
    return left is not right


# ── PHASE 0.3 — PREPARATION COMPATIBILITY, deliberately narrow ─────────────
#
# Raw versus cooked was safe because the states are MUTUALLY EXCLUSIVE: a row
# cannot be both. Preparation is not symmetric in that way, and a naive token
# conflict would be worse than the defect it replaces:
#
#     requested "roasted"  vs  "cooked, dry heat"   NOT a conflict — dry heat
#                                                   is a SUPERSET covering it
#     requested "grilled"  vs  "roasted"            NOT vetoable — different,
#                                                   but not exclusive
#     requested "roasted"  vs  "stewed"             a real conflict
#
# Vetoing the first would destroy correct evidence DETERMINISTICALLY, which is
# a worse failure than destroying it nondeterministically: it never varies, so
# nothing ever surfaces it.
#
# ⭐ SO THE RULE IS BY HEAT MEDIUM, WHICH IS USDA'S OWN VOCABULARY. Their rows
# literally say "cooked, dry heat" and "cooked, moist heat", alongside method
# terms already in `validators._PREPARATIONS`. Grouping by medium means a
# specific method never conflicts with the generic term that contains it, and
# two methods conflict only when their mediums are genuinely exclusive.
#
# Preparation discrimination WITHIN a medium stays with ranking. That is the
# conservative trade: grilled versus roasted is a real difference and not a
# mechanical incompatibility, so code declines and the ranker decides.


class Medium(str, Enum):
    DRY = "dry"          # roasted, baked, broiled, grilled, toasted
    MOIST = "moist"      # boiled, steamed, poached, braised, stewed
    FAT = "fat"          # fried, sauteed
    UNCLASSIFIED = "unclassified"


_DRY_METHODS = frozenset({"roasted", "baked", "broiled", "grilled",
                          "toasted", "barbecued"})
_MOIST_METHODS = frozenset({"boiled", "steamed", "poached", "braised",
                            "stewed", "simmered"})
_FAT_METHODS = frozenset({"fried", "sauteed", "sautéed"})

#: USDA's two-word medium terms. Both words must be present — "dry" alone
#: describes a dried food, which is preservation, not a cooking medium.
_DRY_PHRASE = ("dry", "heat")
_MOIST_PHRASE = ("moist", "heat")

#: Methods whose medium genuinely depends on the dish. `microwaved` can be
#: either; naming it here keeps its silence a decision rather than an
#: oversight.
_AMBIGUOUS_METHODS = frozenset({"microwaved", "cooked", "prepared", "heated"})


def medium(text: str) -> Medium:
    """The heat MEDIUM a description asserts, or UNCLASSIFIED.

    A description naming methods from two different mediums ("fried, then
    baked") declines to choose, for the same reason `classify` does.
    """
    words = _tokens(text)
    found = set()
    if all(w in words for w in _DRY_PHRASE):
        found.add(Medium.DRY)
    if all(w in words for w in _MOIST_PHRASE):
        found.add(Medium.MOIST)
    if words & _DRY_METHODS:
        found.add(Medium.DRY)
    if words & _MOIST_METHODS:
        found.add(Medium.MOIST)
    if words & _FAT_METHODS:
        found.add(Medium.FAT)
    return found.pop() if len(found) == 1 else Medium.UNCLASSIFIED


def medium_conflict(requested: str, candidate: str) -> bool:
    """Do these assert INCOMPATIBLE cooking media?

    True only when both classify and differ. A specific method never conflicts
    with the generic term containing it, because both resolve to one medium —
    which is the whole reason this is expressed as media rather than tokens.
    """
    left, right = medium(requested), medium(candidate)
    if Medium.UNCLASSIFIED in (left, right):
        return False
    return left is not right
