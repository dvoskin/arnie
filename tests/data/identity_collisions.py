"""Labelled ground truth for food identity, starting with the collisions.

The directive asks for a 1,000+ message corpus and lists the collision families
that must be in it. This is the first slice: the families themselves, labelled,
so "does the false-match rate go down?" becomes a number instead of a feeling.

It is NOT the corpus. It is roughly 5% of what the directive asks for, it is
authored rather than sampled from production, and both facts are recorded in
`docs/FOOD_SEMANTICS_MIGRATION.md` rather than glossed. What it does buy is the
thing the identity migration cannot safely start without: a red line under the
exact pairs that, when confused, delete a row the user reported.

THE LABEL'S MEANING, precisely, because it is easy to get backwards.

`SAME` means: these two strings, arriving from two readings of ONE message,
denote one food that the second reading described better. That is the situation
`_undeferred` is in — `held` and `plan` are two parses of the same sentence —
and collapsing them is correct there and nowhere else.

`DIFFERENT` means: a user saying both meant two foods, and collapsing them
loses one. Every DIFFERENT pair below is a row that can silently disappear.

The asymmetry is deliberate and load-bearing: a LEADING modifier refines the
same food ("white rice" is rice), while a TRAILING head noun names a new one
("rice cakes" are not rice). English compounds put the head last.
"""

#: (narrow, wide, same, why). `narrow` is the shorter/earlier reading.
IDENTITY_PAIRS = [
    # ── the directive's required families ────────────────────────────────────
    ("potato", "potatoes", True, "plural"),
    ("cookie", "cookies", True, "plural"),
    ("tomato", "tomatoes", True, "irregular plural"),
    ("berry", "berries", True, "-ies plural"),

    ("orange", "orange juice", False, "a drink made from it"),
    ("orange", "orange chicken", False, "a dish that merely names it"),
    ("orange juice", "orange chicken", False, "unrelated but share a token"),
    ("coffee", "coffee cake", False, "a cake, not a coffee"),
    ("banana", "banana bread", False, "a bread, not a banana"),
    ("rice", "rice cakes", False, "a cake, not rice"),
    ("egg", "egg roll", False, "a roll, not an egg"),
    ("egg", "eggplant parmesan", False, "not an egg at all"),
    ("peanut", "peanut butter", False, "a butter, not a peanut"),
    ("burger", "gummy burger candy", False, "candy shaped like a burger"),
    ("chicken", "chicken noodle soup", False, "a soup, not chicken"),
    ("milk", "milk chocolate", False, "chocolate, not milk"),
    ("butter", "peanut butter", False, "the head noun is shared, not the food"),
    ("apple", "apple pie", False, "a pie"),
    ("corn", "corn dog", False, "a dog"),
    ("soup", "noodle soup", True, "a leading modifier refines the soup"),
    ("soup", "miso soup", True, "still a soup"),
    ("noodle soup", "chicken noodle soup", True, "still that soup"),

    # ── renames: the reason the collapse exists at all ──────────────────────
    ("white rice", "white rice, cooked", True, "the prod duplicate"),
    ("rice", "white rice", True, "leading modifier"),
    ("rice", "fried rice", True, "preparation, still rice"),
    ("chicken", "grilled chicken", True, "preparation"),
    ("chicken", "chicken breast", True, "a cut, described better"),
    ("beef", "ground beef", True, "form"),
    ("turkey", "ground turkey", True, "form"),
    ("oil", "olive oil", True, "which oil"),
    ("bread", "banana bread", True, "an ingredient modifier, still a bread"),
    ("yogurt", "greek yogurt", True, "which yogurt"),
    ("cheese", "cheddar cheese", True, "which cheese"),

    # ── things that share nothing ───────────────────────────────────────────
    ("chicken", "rice", False, "the whole point"),
    ("turkey", "corn", False, "the prod case the mechanism was built for"),
    ("burrito", "burger", False, "different foods"),
]

#: Pairs where confusing them DELETES a row rather than merging two readings.
#: These are the mutation-critical subset — `_undeferred` drops a held food
#: when it believes a plan call already covers it.
DELETES_A_ROW = tuple(
    (a, b) for a, b, same, _ in IDENTITY_PAIRS if not same)

__all__ = ["IDENTITY_PAIRS", "DELETES_A_ROW"]
