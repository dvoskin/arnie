"""`FoodIdentity.describe()` always names the food.

This label is not cosmetic. It names cards, it is the noun a clarification
question asks about, it is what a reply reads back, and — since cause A — it is
the name written on the logged row. Every one of those goes wrong the same way
when the label drops the food and keeps the maker.

Two live shapes, one rule:

  "Royo Everything Bagel" (brand "Royo") described itself as "Royo", so the
  question asked which Royo it was instead of which bagel.

  "Sopressata" (brand "Seppe") described itself as "Seppe" — the fix for the
  first case preferred the canonical name only when it had MORE words than the
  brand/line/variant parts, and 1 > 1 is false. A brand stood in for a food.

Word counts were never the question, so the rule is not about them: the
canonical name is always said, and a qualifier is said only when it adds words
the name does not already carry. That covers both shapes and, unlike a count,
cannot be defeated by how long the words happen to be.
"""
import pytest

from skills.nutrition.staging import FoodIdentity, Quantity


# ── the invariant ─────────────────────────────────────────────────────────────
IDENTITIES = [
    # the two live cases
    FoodIdentity(canonical_name="Royo Everything Bagel", brand="Royo"),
    FoodIdentity(canonical_name="Sopressata", brand="Seppe"),
    # every other way a name can be shorter than, longer than, or the same
    # length as its qualifiers
    FoodIdentity(canonical_name="Milk", brand="Fairlife"),
    FoodIdentity(canonical_name="Greek Yogurt", brand="Chobani",
                 product_line="Complete", variant="Vanilla"),
    FoodIdentity(canonical_name="Chobani Complete Vanilla Greek Yogurt",
                 brand="Chobani", product_line="Complete", variant="Vanilla"),
    FoodIdentity(canonical_name="Sopressata", brand="Seppe",
                 package_size=Quantity(8, "oz")),
    FoodIdentity(canonical_name="Cold Brew", brand="Starbucks",
                 variant="Nitro", package_size=Quantity(11, "fl oz")),
    FoodIdentity(canonical_name="Bar", brand="Kind",
                 product_line="Dark Chocolate"),
]


@pytest.mark.parametrize("identity", IDENTITIES,
                         ids=lambda i: i.describe() or "empty")
def test_a_description_never_omits_the_canonical_name(identity):
    """THE rule. Not "usually", not "when it is longer" — a description that
    does not say the food is a description of something other than the food."""
    described = identity.describe().lower()
    for word in identity.canonical_name.lower().split():
        assert word in described, (
            f"{identity.canonical_name!r} lost {word!r} in {described!r}")


# ── the case the old rule existed to protect ──────────────────────────────────
def test_a_brand_already_in_the_name_is_not_repeated():
    """The Royo case. The reason the canonical name got preferred at all — and
    the thing any replacement rule has to keep doing."""
    identity = FoodIdentity(canonical_name="Royo Everything Bagel", brand="Royo")
    assert identity.describe() == "Royo Everything Bagel"


def test_a_brand_the_name_does_not_carry_is_kept():
    """The Seppe case, which the word count missed: one word against one word.
    The label has to name the food AND say whose it is."""
    identity = FoodIdentity(canonical_name="Sopressata", brand="Seppe")
    assert identity.describe() == "Seppe Sopressata"


@pytest.mark.parametrize("name,brand,expected", [
    # the pair the word count decided wrongly, in both directions
    ("Sopressata", "Seppe", "Seppe Sopressata"),
    ("Bagel", "Royo", "Royo Bagel"),
    # name shorter than the brand, name longer than the brand: same rule
    ("Milk", "Fairlife Dairy", "Fairlife Dairy Milk"),
    ("Everything Bagel Thins", "Royo", "Royo Everything Bagel Thins"),
])
def test_word_count_no_longer_decides(name, brand, expected):
    assert FoodIdentity(canonical_name=name, brand=brand).describe() == expected


# ── what a qualifier adds, and when it adds nothing ───────────────────────────
def test_line_and_variant_qualify_the_name():
    identity = FoodIdentity(canonical_name="Greek Yogurt", brand="Chobani",
                            product_line="Complete", variant="Vanilla")
    assert identity.describe() == "Chobani Complete Vanilla Greek Yogurt"


def test_a_name_that_already_spells_out_every_qualifier_is_said_once():
    """Lookups hand back canonical names with the brand and line already in
    them. Saying them again is how a card reads "Chobani Complete Chobani
    Complete Vanilla Greek Yogurt"."""
    identity = FoodIdentity(canonical_name="Chobani Complete Vanilla Greek Yogurt",
                            brand="Chobani", product_line="Complete",
                            variant="Vanilla")
    assert identity.describe() == "Chobani Complete Vanilla Greek Yogurt"


def test_a_qualifier_repeating_an_earlier_qualifier_is_said_once():
    identity = FoodIdentity(canonical_name="Sopressata", brand="Seppe",
                            product_line="Seppe")
    assert identity.describe() == "Seppe Sopressata"


def test_a_qualifier_that_contains_the_whole_name_stands_in_for_it():
    """Canonical "Bagel" under line "Everything Bagel" is already named by the
    line. Appending the name too would say "Everything Bagel Bagel" — and the
    invariant is satisfied either way, because the food's words are all
    there."""
    identity = FoodIdentity(canonical_name="Bagel",
                            product_line="Everything Bagel")
    assert identity.describe() == "Everything Bagel"


def test_words_are_matched_as_words_not_as_substrings():
    """Brand "Kind" is NOT already said by "Kindness", and a substring test
    would have dropped it. Different maker, different food."""
    identity = FoodIdentity(canonical_name="Kindness Bar", brand="Kind")
    assert identity.describe() == "Kind Kindness Bar"


def test_an_apostrophe_is_not_a_different_brand():
    """Interpreters and lookups disagree about "Trader Joe's" vs "Trader
    Joes". Splitting on the apostrophe would make the name look like it was
    missing a brand it already carries."""
    identity = FoodIdentity(canonical_name="Trader Joes Everything Bagel",
                            brand="Trader Joe's")
    assert identity.describe() == "Trader Joes Everything Bagel"


# ── the shapes with nothing to name ───────────────────────────────────────────
def test_an_identity_with_no_name_is_described_by_its_qualifiers():
    """Staging leaves the canonical name empty when the user named a product
    and not a food ("a Fairlife Core Power Vanilla")."""
    identity = FoodIdentity(brand="Fairlife", product_line="Core Power",
                            variant="Vanilla")
    assert identity.describe() == "Fairlife Core Power Vanilla"


def test_package_size_comes_last():
    identity = FoodIdentity(canonical_name="Sopressata", brand="Seppe",
                            package_size=Quantity(8, "oz"))
    assert identity.describe() == "Seppe Sopressata 8 oz"


@pytest.mark.parametrize("identity", [
    FoodIdentity(),
    FoodIdentity(canonical_name="   ", brand=""),
    FoodIdentity(barcode="0123456789012"),
])
def test_an_empty_identity_describes_as_nothing(identity):
    """Empty, not "Unknown" — callers pair this with the user's own words
    (`item.original_text`), and a placeholder here would beat them to it."""
    assert identity.describe() == ""
