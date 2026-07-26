"""The lookups get a vote on whether this is a product.

Session after #47 went live. The receipt finally showed what was happening,
and what it showed was three different failures:

    I had 2 Milky Way minis
    → Searched for Milky Way Minis
      Checked USDA food database            no match
      Checked Open Food Facts               found a match
      Checked the product label on the web  not a named product — skipped
      Portion estimated · nutrition profile supplemented with label data
      Logged Milky Way Minis — 80 cal, 1g protein

Open Food Facts found the product and the macros were estimated anyway. Both
lines were accurate. `candidate_map` seats an OFF candidate only for a
MANUFACTURED item, "Milky Way Minis" carries no package noun so every
name-shape heuristic classified it GENERIC, and on the generic ladder OFF is
not a weaker answer — it is not an answer. Then the web lane, which is exactly
the lane for a named product the databases could not resolve, declined to run
because the same name-shape heuristic said "not a named product".

    Also had a Polly-O string cheese stick
    → ... Checked Open Food Facts  found a match
          From the product label

The one that worked, and it worked because the interpreter happened to set
`branded: true` on that item and not on the candy.

    Also had some ritz crackers
    → Searched for Ritz Crackers
      Portion estimated · nutrition profile supplemented with USDA data

No lane lines at all. The lookup block was skipped and the receipt showed that
as nothing, which reads as a pipeline that never fired.
"""
import core.reasoning as RSN
import skills.nutrition.authority as A

_WEAK = {"_match": "estimated", "per100g": {"calories": 450}}
_LIKELY = {"_match": "likely", "per100g": {"calories": 450}}
_EXACT = {"_match": "exact", "per100g": {"calories": 450}}


def _resolve(usda, off, *, name="X", declared=False):
    """Classification → ladder → did anything set the macros."""
    packaged = declared or A.branded_by_evidence(usda_candidate=usda,
                                                 off_candidate=off)
    food_class = A.classify(name, is_packaged=packaged)
    rung, hit = A.select(
        A.candidate_map(food_class=food_class, usda_candidate=usda,
                        off_candidate=off), food_class)
    return food_class, rung, hit


# ── the promotion ─────────────────────────────────────────────────────────────
def test_a_branded_match_usda_cannot_answer_names_a_product():
    """Milky Way Minis: not in USDA's curated index, exact in a branded one."""
    assert A.branded_by_evidence(usda_candidate=None, off_candidate=_EXACT)


def test_the_promoted_item_gets_its_label_instead_of_an_estimate():
    food_class, rung, hit = _resolve(None, _EXACT, name="Milky Way Minis")
    assert food_class is A.FoodClass.MANUFACTURED
    assert rung == "branded_exact"
    assert hit is not None, "the macros come from the label, not an estimate"


def test_a_weak_usda_match_does_not_block_the_promotion():
    """Polly-O String Cheese — USDA has "string cheese" and it is not this."""
    assert A.branded_by_evidence(usda_candidate=_WEAK, off_candidate=_EXACT)


# ── what must NOT be promoted ─────────────────────────────────────────────────
def test_a_food_usda_answers_exactly_stays_generic():
    """USDA's curated index is exactly where plain foods live. A branded index
    also carrying a product named after the food proves nothing."""
    for off in (_EXACT, _LIKELY):
        assert not A.branded_by_evidence(usda_candidate=_EXACT,
                                         off_candidate=off)


def test_the_generics_still_take_the_usda_rung():
    for name in ("white rice", "grilled chicken", "chicken breast"):
        food_class, rung, hit = _resolve(_EXACT, _LIKELY, name=name)
        assert food_class is A.FoodClass.GENERIC, name
        assert rung == "usda_exact", name


def test_a_loose_branded_match_promotes_nothing():
    """A weak name hit in a branded index is a guess wearing a database's
    name — the rule this module already applies one layer down."""
    assert not A.branded_by_evidence(usda_candidate=None, off_candidate=_WEAK)


def test_no_branded_candidate_at_all_promotes_nothing():
    assert not A.branded_by_evidence(usda_candidate=_EXACT, off_candidate=None)
    assert not A.branded_by_evidence(usda_candidate=None, off_candidate=None)


# ── the receipt has to tell these apart ───────────────────────────────────────
def _labels(steps):
    return [(s["label"], s.get("detail", "")) for s in steps]


def _trace(lanes, source="estimate"):
    return RSN._food_detailed(
        {"food_name": "X",
         "_sourcing": {"source": source, "quantity": "2 piece",
                       "calories": 80, "lanes": lanes}},
        "Logged: X, 80 cal")


def test_a_match_too_loose_to_use_is_not_reported_as_found():
    """"found a match" directly above "Portion estimated" reads as a broken
    lane when it is a deliberate refusal. Say which it was."""
    detail = dict(_labels(_trace([("off", "weak")])))
    assert "not used" in detail["Checked Open Food Facts"]


def test_a_seated_match_still_reads_as_found():
    detail = dict(_labels(_trace([("off", "hit")], source="off")))
    assert detail["Checked Open Food Facts"] == "found a match"


def test_a_skipped_lookup_says_why_instead_of_showing_nothing():
    """Ritz Crackers had no lane section at all. A blank is the one thing a
    receipt must never be."""
    labels = dict(_labels(_trace([("lookup", "your saved match answered it")])))
    assert "Skipped the database lookup" in labels
    assert labels["Skipped the database lookup"] == "your saved match answered it"
