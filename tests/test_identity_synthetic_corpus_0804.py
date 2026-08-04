"""The synthetic corpus, and an honest account of what passing it proves.

Production inputs are unavailable here, so the corpus is grown from families —
rules about how food language varies — applied across the registry's own
vocabulary.

READ `tests/data/identity_synthetic.py` FIRST. Most of these pairs are
circular by construction, and the module says so. These tests are therefore
split into what they can and cannot establish, rather than reported as one
number.
"""
import collections
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from data.identity_synthetic import (SYNTHETIC_PAIRS,              # noqa: E402
                                     UNCOVERED_FAMILIES)

from core.food_turn import _claims_the_same_food                   # noqa: E402


def _score(pairs):
    fm = [(a, b, w) for a, b, s, w in pairs
          if _claims_the_same_food(a, b) and not s]
    mr = [(a, b, w) for a, b, s, w in pairs
          if s and not _claims_the_same_food(a, b)]
    return fm, mr


def test_the_corpus_is_large_enough_to_be_worth_running():
    """A generated corpus that collapses to a handful of cases is a test of the
    generator."""
    assert len(SYNTHETIC_PAIRS) > 300
    families = {w.split(" (")[0] for _a, _b, _s, w in SYNTHETIC_PAIRS}
    assert len(families) >= 6, families


def test_no_synthetic_pair_causes_a_false_match():
    """The number that deletes rows, across every generated family."""
    fm, _ = _score(SYNTHETIC_PAIRS)
    assert not fm, ("synthetic false matches:\n  "
                    + "\n  ".join(f"{a!r} claims {b!r} ({w})" for a, b, w in fm))


def test_no_synthetic_pair_causes_a_missed_rename():
    _, mr = _score(SYNTHETIC_PAIRS)
    assert not mr, ("synthetic missed renames:\n  "
                    + "\n  ".join(f"{a!r} vs {b!r} ({w})" for a, b, w in mr))


# ── the part that is NOT circular ────────────────────────────────────────────

def test_the_normaliser_is_tested_independently_of_the_table():
    """Casing and punctuation are the one family whose ANSWER does not come
    from the registry: the pair is generated from a name, but resolving it
    exercises the normaliser, which does not read the relation table.

    This is the family that would have caught the comma bug — "White rice,
    cooked" resolved to nothing until 2026-08-04, and no amount of relation
    data would have revealed it.
    """
    cased = [p for p in SYNTHETIC_PAIRS if "casing" in p[3]]
    assert len(cased) >= 100
    fm, mr = _score(cased)
    assert not fm and not mr


def test_unrelated_foods_are_the_control_group():
    """A corpus of near-misses cannot show that ordinary pairs still behave."""
    unrelated = [p for p in SYNTHETIC_PAIRS if p[3] == "unrelated"]
    assert len(unrelated) >= 10
    for a, b, _s, _w in unrelated:
        assert not _claims_the_same_food(a, b), f"{b!r} claimed {a!r}"


def test_ingredient_edges_never_unify():
    """THE DANGEROUS FAMILY, isolated. Every one of these shares a token with a
    dish made from it, which is exactly the shape a string rule collapses —
    and each pair is a row that would disappear."""
    edges = [p for p in SYNTHETIC_PAIRS if p[3].startswith("ingredient_of")]
    assert edges, "no ingredient edges generated"
    for a, b, same, _w in edges:
        assert same is False
        assert not _claims_the_same_food(a, b), (
            f"{b!r} is MADE WITH {a!r} and claimed it")


# ── and what it cannot establish ─────────────────────────────────────────────

def test_the_uncovered_families_are_declared_not_forgotten():
    """Misspellings, speech-to-text errors, branded products, restaurant
    dishes and non-English aliases are all named by the directive and NONE is
    generated — a synthetic misspelling tests a spellchecker nobody wrote.

    They are a value in the code so the gap is visible to a reader and to CI,
    rather than living in a commit message nobody re-reads.
    """
    assert len(UNCOVERED_FAMILIES) >= 5
    for family in ("misspellings", "branded products",
                   "multilingual and transliterated aliases"):
        assert family in UNCOVERED_FAMILIES


def test_most_of_the_corpus_is_circular_and_says_so():
    """Passing the plural and relation families proves the LOOKUP works, not
    that the declarations are right: a wrong parent row produces a wrong pair
    and a passing test. The hand-labelled 36 in `identity_collisions.py`
    predate the registry and remain the non-circular ground truth."""
    fam = collections.Counter(w.split(" (")[0] for _a, _b, _s, w in SYNTHETIC_PAIRS)
    circular = fam["plural"] + sum(v for k, v in fam.items()
                                   if k.endswith("_of"))
    assert circular > len(SYNTHETIC_PAIRS) / 2, (
        "if this stops being true the docstring needs rewriting, not the "
        "assertion")
