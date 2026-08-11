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
