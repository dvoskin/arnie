"""⛔ THE INSTRUMENTATION COMMIT MUST NOT CHANGE A QUALIFICATION DECISION.

`_qualify_and_trace` replaced two inline filters that each computed

    relationship in IDENTITY_BEARING and confidence >= MINIMUM_IDENTITY_CONFIDENCE

The hard invariant for this commit is **same inputs → same decisions**. It is
checked here against an independent reimplementation of the original
expression, over a grid that straddles the threshold in both dimensions, so a
drift of one comparison operator (`>` for `>=`) or one relationship cannot pass.

## Why the tracing exists at all

`event=evidence_qualified` emitted `raw`, `kept` and a relationship histogram —
the verdict distribution, and never the number that did the filtering. So a
candidate the model AGREED was the same product, refused at confidence 0.79,
was indistinguishable in the logs from junk the model rejected outright:
`off_identity_refused ... verdicts=SAME_IDENTITY` reads as *identity refused*
when identity was *agreed*.

⭐ Two different populations under one label, and the field separating them was
computed, used for the filter, and thrown away. Whether canonical adoption is
blocked by *missing evidence* or by *a threshold rejecting evidence it has* is
the difference between an expensive producer tranche and a calibration — and
the logs could not tell them apart.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import pytest

from skills.nutrition.evidence_qualification import (_confidence_buckets,
                                                     _identify,
                                                     _qualify_and_trace)
from skills.nutrition.evidence_semantics import (IDENTITY_BEARING,
                                                 MINIMUM_IDENTITY_CONFIDENCE,
                                                 RELATIONSHIPS)


@dataclass
class _A:
    relationship: str
    confidence: float
    abstained: bool = False


#: Straddles the threshold deliberately, including the boundary itself — `>=`
#: versus `>` is exactly the kind of drift an instrumentation refactor makes.
CONFIDENCES = (0.0, 0.49, 0.5, 0.79, 0.7999, MINIMUM_IDENTITY_CONFIDENCE,
               0.8001, 0.95, 1.0)


def _original(candidates, assessments):
    """The expression as it stood before the refactor, reimplemented here so
    the test does not check the new code against itself."""
    return tuple(c for c, a in zip(candidates, assessments)
                 if a.relationship in IDENTITY_BEARING
                 and a.confidence >= MINIMUM_IDENTITY_CONFIDENCE)


@pytest.mark.parametrize("relationship", RELATIONSHIPS)
@pytest.mark.parametrize("confidence", CONFIDENCES)
def test_same_inputs_same_decision(relationship, confidence):
    cands = [{"code": "0000000000001", "product_name": "X"}]
    assessments = [_A(relationship, confidence)]
    kept, threshold = _qualify_and_trace(cands, assessments,
                                         food_name="X", lane="test")
    assert kept == _original(cands, assessments), (
        f"decision changed for {relationship} @ {confidence}")
    assert threshold == MINIMUM_IDENTITY_CONFIDENCE, (
        "the threshold must be READ from the source, never restated")


def test_a_whole_mixed_batch_decides_identically():
    """⭐ ORDER AND MEMBERSHIP TOO, not just the verdict per row. `kept` feeds
    a ladder that seats the FIRST acceptable candidate, so a reordering is a
    behaviour change even when the set is equal."""
    combos = list(itertools.product(RELATIONSHIPS, CONFIDENCES))
    cands = [{"code": f"c{i}"} for i, _ in enumerate(combos)]
    assessments = [_A(r, c) for r, c in combos]
    kept, _ = _qualify_and_trace(cands, assessments, food_name="mixed",
                                 lane="test")
    assert list(kept) == list(_original(cands, assessments))


def test_the_boundary_is_inclusive_exactly_as_before():
    """`>=`, not `>`. Pinned on its own because a single character here silently
    rejects every candidate that lands exactly on the bar."""
    at = [_A("SAME_IDENTITY", MINIMUM_IDENTITY_CONFIDENCE)]
    kept, _ = _qualify_and_trace([{"code": "a"}], at, food_name="a", lane="t")
    assert len(kept) == 1, "a candidate exactly at the threshold is now rejected"


def test_an_abstained_assessment_is_not_silently_promoted():
    """Abstention is 'no answer', which must never become 'yes'."""
    a = [_A("SAME_IDENTITY", 0.0, abstained=True)]
    kept, _ = _qualify_and_trace([{"code": "a"}], a, food_name="a", lane="t")
    assert kept == ()


def test_the_candidate_is_IDENTIFIABLE_not_just_counted():
    """⛔ THE POINT OF THE WHOLE COMMIT. Discovering `SAME_IDENTITY 0.74` later
    and being unable to say whether it was the exact product, a flavour
    variant, or junk would leave the census exactly as blind as the event it
    replaces."""
    assert _identify({"code": "0038000138416"}) == "code:0038000138416"
    assert _identify({"product_name": "Muscle Milk Pro Series Vanilla"}) \
        == "Muscle Milk Pro Series Vanilla"
    assert _identify({"fdc_id": 174702}) == "fdc_id:174702"
    assert _identify({}) == "-"          # never raises, never invents


def test_confidence_buckets_cut_at_the_threshold():
    """The bucket edge must BE the decision boundary, or 'just under' is
    invisible — which is the entire diagnostic value."""
    b = _confidence_buckets([_A("SAME_IDENTITY", 0.79),
                             _A("SAME_IDENTITY", 0.80),
                             _A("DIFFERENT_IDENTITY", 0.31)])
    assert b == {"0.70-0.79": 1, "0.80-0.89": 1, "<0.50": 1}
