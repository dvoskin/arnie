"""A PREFERENCE MAY ONLY DECIDE THE DIMENSION IT NAMES.

`as_eaten_over_trimmed` was a ±0.4 tie-break, and a tie-break can only
overturn a near-tie — so on real USDA data it seated rows that differed from
the runner-up in CUT and in COATING, dimensions it never evaluated:

    beef|fried      knuckle      -> striploin lean+fat   +123 kcal  (CUT)
    beef|grilled    ribeye filet -> shoulder steak        -22 kcal  (CUT)
    beef|roasted    NZ ribs      -> chuck eye roast       +44 kcal  (CUT)
    chicken|fried   meat only    -> meat+skin, BATTER     +70 kcal  (COATING)
    chicken|roasted meat only    -> meat and skin         +56 kcal  (trim only)

Only the last is the comparison the rule was written to make. The others are
cut choices wearing a trim rule's clothes.

⭐ THE FIX IS COMPARABILITY, NOT A BIGGER NUMBER. A larger score would move
the same wrong rows further. Instead the preference is only allowed to choose
between candidates that are IDENTICAL EXCEPT IN ITS OWN DIMENSION.

⭐⭐ AND COMPARABILITY IS DEFINED BY SUBTRACTION, NOT BY A CUT VOCABULARY.
Enumerating cuts — knuckle, striploin, ribeye, chuck, brisket, thigh, wing —
would be a curated list that has to be maintained, is wrong for every cuisine
nobody thought of, and encodes one market's butchery into food identity. So
instead: strip the tokens the preference GOVERNS from both descriptions, and
require what remains to be identical. Anything the preference does not govern
— cut, coating, species, grade, origin — survives the subtraction and blocks
the comparison by simply being different.

That makes the guarantee structural rather than enumerated: the preference
CANNOT change a cut, because a differing cut is exactly what stops it
applying. No list of cuts is needed to know that.
"""
from __future__ import annotations

#: ⭐ THE CONSTRUCTIONS THIS PREFERENCE OWNS — PHRASES, NOT TOKENS.
#:
#: The first implementation subtracted a token SET globally: `meat`, `lean`,
#: `fat`, `and` deleted wherever they appeared. Two things were wrong with it,
#: and neither had reproduced in production yet, which is exactly why they had
#: to be fixed before the baseline froze against them.
#:
#: DELETION WAS TOO BROAD. `fat` and `lean` carry meaning outside the trim
#: phrases — "Beef, fat, raw" and "Beef, lean, raw" both reduced to
#: {beef, raw} and compared EQUAL, so the preference could have swapped two
#: genuinely different rows on the authority of a rule that owns neither word.
#:
#: AND A `frozenset` LOST ORDER AND MULTIPLICITY. Two descriptions with the
#: same bag of remaining words compared equal however differently those words
#: were arranged.
#:
#: So: normalise the owned CONSTRUCTIONS to one marker and compare the ORDERED
#: token sequence. Longest first, because "meat and skin" must be consumed
#: before "skin" could be.
_OWNED_FORMS = ("meat and skin", "lean and fat", "meat only", "lean only",
                "skin removed", "skinless", "trimmed")

#: ⚠ THE MARKER MUST SURVIVE `normalize_name`, AND THE FIRST ONE DID NOT.
#: `\x00trim_form` looked safe precisely because it was not word-like — and
#: `normalize_name` strips every non-alphanumeric, so a second pass shredded
#: it into "trim form" and normalisation stopped being idempotent. Both sides
#: of every comparison run through this, so a function that moves on the
#: second application can put a record and a query on different footings.
#: An all-lowercase token survives normalisation unchanged and is not a word
#: any food description contains.
_OWNED_MARKER = "ownedtrimform"

#: The eaten form and the laboratory reference.
_AS_EATEN = ("meat and skin", "lean and fat")
_TRIMMED = ("meat only", "lean only", "skinless", "skin removed")


def _tokens(description: str) -> str:
    from core.food_intelligence import normalize_name
    return normalize_name(description or "", split_separators=True)


def normalize_owned_dimension(description: str) -> str:
    """Collapse every construction this preference owns to one marker.

    Idempotent: a marker is not a phrase, so running this twice changes
    nothing — which matters because both sides of every comparison pass
    through it and a second application must not shift one of them.
    """
    text = _tokens(description)
    for phrase in sorted(_OWNED_FORMS, key=len, reverse=True):
        text = text.replace(phrase, _OWNED_MARKER)
    return text


def residue(description: str) -> tuple:
    """The ORDERED tokens left once the owned construction is normalised.

    A tuple, not a set: order and repetition are part of what a description
    says, and collapsing them would let this preference call two different
    foods comparable because they share a vocabulary.
    """
    return tuple(normalize_owned_dimension(description).split())


def comparable(one: str, other: str) -> bool:
    """May the skin/trim preference choose between these two descriptions?

    ⭐ FALSE IS THE IMPORTANT ANSWER. Cut, coating, species, grade, origin and
    preparation all survive the normalisation and make this False — so the
    preference is structurally unable to decide them, and nobody has to
    enumerate what a cut is for that to hold.
    """
    return residue(one) == residue(other)


def is_as_eaten(description: str) -> bool:
    from core.food_intelligence import normalize_name
    text = normalize_name(description or "", split_separators=True)
    return any(phrase in text for phrase in _AS_EATEN)


def is_trimmed_reference(description: str) -> bool:
    from core.food_intelligence import normalize_name
    text = normalize_name(description or "", split_separators=True)
    return any(phrase in text for phrase in _TRIMMED)


def prefer_as_eaten(winner: dict, candidates) -> dict:
    """The as-eaten form of `winner`, when one is COMPARABLE to it.

    Applied AFTER ranking, deliberately: the ranker settles identity, form and
    cut on its own terms, and the preference then refines within that answer
    rather than competing with it. A refinement that cannot reach outside its
    comparability class cannot repeat the defect that parked it.

    Returns `winner` unchanged when nothing comparable is more as-eaten —
    including when the winner already is.
    """
    if not winner or not is_trimmed_reference(winner.get("description", "")):
        return winner

    description = winner.get("description", "")
    comparable_forms = [c for c in (candidates or ())
                        if c is not winner
                        and is_as_eaten(c.get("description", ""))
                        and comparable(description, c.get("description", ""))]

    # ⭐⭐ ZERO KEEP · ONE REFINE · MANY REFUSE. Taking the first comparable
    # row would make CANDIDATE ORDER an implicit preference — a silent third
    # policy nobody declared, decided by whatever the retrieval happened to
    # return first. There is no ranking to do here: if the ladder offers two
    # equally comparable as-eaten forms, this preference genuinely does not
    # know which, and saying so leaves the winner where an owned policy put it.
    if len(comparable_forms) != 1:
        return winner

    chosen = comparable_forms[0]
    # EXACTLY ONE OWNED DIMENSION CHANGED — not merely "the leftovers match".
    # The residues are ordered sequences, so this asserts the two descriptions
    # are identical outside the construction this preference owns.
    assert residue(description) == residue(chosen.get("description", ""))
    return chosen
