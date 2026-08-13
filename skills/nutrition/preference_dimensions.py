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

#: The tokens this preference OWNS — the skin/trim axis and nothing else.
#: Subtracted from both sides before comparison, so two rows that differ only
#: here are comparable and two that differ anywhere else are not.
#:
#: "and" is included because "meat only" and "meat and skin" would otherwise
#: differ by it and never compare. "with"/"without" are deliberately EXCLUDED:
#: they carry salt and preparation distinctions this preference does not own.
_GOVERNED = frozenset({
    "meat", "only", "skin", "skinless", "lean", "fat", "separable",
    "removed", "trimmed", "and",
})

#: The eaten form and the laboratory reference. Phrases, because "meat and
#: skin" is a form and "skin" alone is a part.
_AS_EATEN = ("meat and skin", "lean and fat")
_TRIMMED = ("meat only", "lean only", "skinless", "skin removed")


def _tokens(description: str) -> tuple:
    from core.food_intelligence import normalize_name
    return tuple(normalize_name(description or "",
                                split_separators=True).split())


def residue(description: str) -> frozenset:
    """Everything the preference does NOT govern.

    Two candidates with the same residue are the same food, cut, coating and
    grade, differing only in how it was trimmed or whether skin was kept —
    which is exactly the comparison `as_eaten` exists to make.
    """
    return frozenset(_tokens(description)) - _GOVERNED


def comparable(one: str, other: str) -> bool:
    """May the skin/trim preference choose between these two descriptions?

    ⭐ FALSE IS THE IMPORTANT ANSWER. A differing cut, a batter, a different
    species or grade all survive the subtraction and make this False — so the
    preference is structurally unable to decide them, without anyone having to
    enumerate what a cut is.
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
    for candidate in candidates or ():
        if candidate is winner:
            continue
        description = candidate.get("description", "")
        if not is_as_eaten(description):
            continue
        if comparable(winner.get("description", ""), description):
            return candidate
    return winner
