"""MORPHOLOGY, AND THE REFUSAL THAT MUST NOT BE SILENT.

Two changes, one defect. `banana|` and `potato|` scored an overlap of exactly
ZERO against "Bananas, raw" and "Potatoes, raw, skin" — the artifact held the
evidence, eligibility admitted it, a person signed it, and the ranker could
not see it because "banana" is not the string "bananas". `_from_artifact`
returned None and the turn priced from a lower rung without a word.

  1. `_singular` folds both sides of the comparison, so USDA's plural
     headings and a person's singular request meet.
  2. Having candidates and returning nothing is now a NAMED EVENT, because
     fixing the five cases we found does not fix the class.

⭐ SYMMETRY IS THE CONTRACT, NOT LINGUISTIC CORRECTNESS. The fold runs over
the query AND the record, so a wrong stem is harmless while it is the same
wrong stem on both sides — "molasses" folds to "molass", and still matches
"molasses". That is what lets this be six suffix rules instead of a
dictionary: it is not trying to know English, only to agree with itself. The
gates below therefore test SYMMETRY, IDEMPOTENCE and the protected set — the
properties that actually carry the behaviour — rather than a spelling list
somebody would have to maintain.

⭐⭐ AND THE BLAST RADIUS IS BOUNDED BY CONSTRUCTION. `_FORM_PENALTY`,
`_SPECIES_TOKENS`, `_CUT_NARROWERS` and `_COOKED_MARKERS` are literal-token
sets; folding what they are tested against would silently stop "chips"
matching `_FORM_PENALTY`. The fold is applied to the two coverage ratios and
to nothing else, and a gate pins that.
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager

import pytest

from core import canonical_pricing as cp
from core.canonical_pricing import ArtifactEvidence, _from_artifact, _ranker_query
from core.food_intelligence import (_COOKED_MARKERS, _CUT_NARROWERS,
                                    _FORM_PENALTY, _PREP_TOKENS,
                                    _SPECIES_TOKENS, _singular, best_candidate,
                                    score_match)
from skills.nutrition import pricing_artifact as art


@contextmanager
def _v2(active: bool):
    previous = os.environ.get("NUTRITION_ACCURACY_V2")
    os.environ["NUTRITION_ACCURACY_V2"] = "1" if active else ""
    try:
        from core.food_intelligence import _nutrition_accuracy_v2
        assert _nutrition_accuracy_v2() is active
        yield
    finally:
        if previous is None:
            os.environ.pop("NUTRITION_ACCURACY_V2", None)
        else:
            os.environ["NUTRITION_ACCURACY_V2"] = previous


# ── 1. the fold ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("plural, singular", [
    ("bananas", "banana"), ("potatoes", "potato"), ("oats", "oat"),
    ("eggs", "egg"), ("tomatoes", "tomato"), ("berries", "berry"),
    ("peaches", "peach"), ("dishes", "dish"), ("boxes", "box"),
])
def test_a_plural_heading_folds_to_the_singular_request(plural, singular):
    assert _singular(plural) == singular


@pytest.mark.parametrize("word", [
    "asparagus", "hummus", "couscous", "bass", "swiss", "gas", "analysis",
    "rice", "cheese", "chicken", "raw", "oat", "banana",
])
def test_a_word_that_merely_ends_in_s_is_left_alone(word):
    """⭐ THE DANGEROUS DIRECTION. Over-folding "asparagus" to "asparagu"
    would break a food that currently works, to fix one that does not."""
    assert _singular(word) == word


@pytest.mark.parametrize("token", [
    "bananas", "potatoes", "molasses", "asparagus", "berries", "leaves",
    "oats", "chicken", "bass",
])
def test_the_fold_is_idempotent_and_therefore_symmetric(token):
    """Both sides of every comparison run through this. If folding twice
    moved a token, a record and a query could land on different stems."""
    once = _singular(token)
    assert _singular(once) == once


def test_a_wrong_stem_still_matches_itself():
    """⭐ THE PROPERTY THAT REPLACES CORRECTNESS. "molasses" folds to a
    non-word. It does not matter: the record folds the same way."""
    assert _singular("molasses") == _singular("molasses")
    assert _singular("leaves") == _singular("leaves")


def test_the_fold_does_not_disturb_the_penalty_vocabularies():
    """The penalty sets are matched as LITERAL tokens against unfolded sets.
    This gate fails loudly if someone later folds those too — which would
    stop "chips" penalising a chip row while every test still passed."""
    for name, vocabulary in (("_FORM_PENALTY", _FORM_PENALTY),
                             ("_PREP_TOKENS", _PREP_TOKENS),
                             ("_SPECIES_TOKENS", _SPECIES_TOKENS),
                             ("_CUT_NARROWERS", _CUT_NARROWERS),
                             ("_COOKED_MARKERS", _COOKED_MARKERS)):
        moved = sorted(t for t in vocabulary if _singular(t) != t)
        assert moved == [], (
            f"{name} holds tokens the fold would move: {moved}. They are "
            f"tested by literal membership, so folding the sets they are "
            f"compared against would silently disable them")


@pytest.mark.parametrize("v2_on", [False, True])
@pytest.mark.parametrize("query, expected", [
    ("banana", "Bananas, raw"),
    ("potato", "Potatoes, raw, skin"),
])
def test_the_singular_request_now_reaches_the_plural_record(query, expected,
                                                            v2_on):
    """⭐ THE DEFECT, CLOSED IN BOTH LIVE MODES. Production runs
    NUTRITION_ACCURACY_V2 as an allowlist, so both are serving users."""
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    entry = (json.loads(art.ARTIFACT_PATH.read_text()).get("entries")
             or {}).get(f"{query}|")
    if entry is None:
        pytest.skip(f"{query} not committed")
    with _v2(v2_on):
        winner, _ = best_candidate(query, list(entry.get("candidates") or ()))
    assert winner is not None, f"{query!r} still reaches nothing"
    assert winner.get("description") == expected


@pytest.mark.parametrize("v2_on", [False, True])
@pytest.mark.parametrize("singular, plural", [
    ("egg", "eggs"), ("banana", "bananas"), ("potato", "potatoes"),
])
def test_the_singular_and_the_plural_agree_on_the_same_food(singular, plural,
                                                            v2_on):
    """⭐ THE CONSISTENCY THE FOLD BUYS. Before it, "egg" seated a poached row
    and "eggs" seated a Grade-A shell row — two different foods for the same
    word in two numbers. The fold is only worth having if BOTH spellings land
    on the same evidence."""
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    doc = json.loads(art.ARTIFACT_PATH.read_text())
    pool, seen = [], set()
    for entry in (doc.get("entries") or {}).values():
        for candidate in (entry.get("candidates") or ()):
            if candidate.get("fdc_id") not in seen:
                seen.add(candidate.get("fdc_id"))
                pool.append(candidate)
    with _v2(v2_on):
        one, one_conf = best_candidate(singular, pool)
        many, many_conf = best_candidate(plural, pool)
    assert one is not None and many is not None
    assert one.get("fdc_id") == many.get("fdc_id"), (
        f"{singular!r} seats {one.get('description')!r} but {plural!r} seats "
        f"{many.get('description')!r}")
    assert one_conf == many_conf


def test_the_label_agrees_with_the_winner_the_ranker_picked():
    """⭐⭐ THE SEAM THIS CLOSED. `best_candidate` chooses on FOLDED tokens;
    `score_match` labels the choice. Measuring them differently made the
    ranker seat "Egg, whole, cooked, poached" for "eggs" and then call it
    `estimated` — and `tool_executor` passes that label on. Two consumers of
    one notion, one of them updated: the identity-boundary defect again."""
    assert score_match("eggs", "Egg, whole, cooked, poached") == "likely"
    assert score_match("egg", "Egg, whole, cooked, poached") == "likely"
    assert score_match("bananas", "Bananas, raw") == "exact"
    # and the strict containment path is untouched by the fold
    assert score_match("banana", "Bananas, raw") == "exact"
    assert score_match("turkey breast",
                       "Roast turkey breast and gravy, frozen meal") == "likely"


# ── 2. the refusal that says so ───────────────────────────────────────────

def _evidence(candidates):
    return ArtifactEvidence(candidates=tuple(candidates), fingerprint="test")


def test_candidates_present_and_no_winner_is_a_named_event(caplog):
    """⭐⭐ THE CLASS, NOT THE FIVE CASES. Morphology repairs what we found;
    the next naming mismatch would reproduce the same silence. This is the
    instrument that would report it."""
    evidence = _evidence([{"fdc_id": "1", "description": "Wholly unrelated",
                           "per100g": {"calories": 100}}])
    with caplog.at_level(logging.WARNING, logger=cp.logger.name):
        assert _from_artifact(evidence, query="zzzzqqq") is None
    assert cp.ARTIFACT_RANKER_NO_WINNER in caplog.text
    assert "candidates=1" in caplog.text


def test_a_winner_with_no_numbers_is_also_named(caplog):
    evidence = _evidence([{"fdc_id": "77", "description": "banana",
                           "per100g": {}}])
    with caplog.at_level(logging.WARNING, logger=cp.logger.name):
        assert _from_artifact(evidence, query="banana") is None
    assert cp.ARTIFACT_WINNER_UNPRICEABLE in caplog.text


def test_no_evidence_at_all_is_not_reported_as_a_failure(caplog):
    """An empty candidate list is the rung having nothing to say, which is
    not the same thing as having evidence and failing to use it. Reporting
    both would make the signal useless."""
    with caplog.at_level(logging.WARNING, logger=cp.logger.name):
        assert _from_artifact(_evidence([]), query="banana") is None
    assert cp.ARTIFACT_RANKER_NO_WINNER not in caplog.text


def test_a_successful_rung_reports_nothing(caplog):
    evidence = _evidence([{"fdc_id": "9", "description": "Bananas, raw",
                           "per100g": {"calories": 89, "protein": 1.1}}])
    with caplog.at_level(logging.WARNING, logger=cp.logger.name):
        priced = _from_artifact(evidence, query="banana")
    assert priced is not None
    assert cp.ARTIFACT_RANKER_NO_WINNER not in caplog.text


def test_every_committed_identity_answers_or_explains_itself(caplog):
    """⭐⭐⭐ THE INVARIANT. For every identity the artifact commits, in every
    live ranking mode: either a winner, or a typed reason. Never silence."""
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    entries = {k: v for k, v in (json.loads(art.ARTIFACT_PATH.read_text())
                                 .get("entries") or {}).items()
               if (v.get("candidates") or ())}
    silent = []
    for v2_on in (False, True):
        with _v2(v2_on):
            for key, entry in entries.items():
                entity, _, preparation = key.partition("|")
                caplog.clear()
                with caplog.at_level(logging.WARNING, logger=cp.logger.name):
                    priced = _from_artifact(
                        _evidence(entry.get("candidates") or ()),
                        query=_ranker_query(entity, preparation))
                if priced is None and cp.ARTIFACT_RANKER_NO_WINNER not in \
                        caplog.text:
                    silent.append((("V2_ON" if v2_on else "V2_OFF"), key))
    assert silent == [], (
        f"{len(silent)} identity/mode pairs produced neither a price nor a "
        f"reason: {silent}")
