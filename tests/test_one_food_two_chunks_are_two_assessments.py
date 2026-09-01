"""⛔⛔⛔ A SHARED KEY THAT IGNORES ITS SUBJECT HANDS BACK THE WRONG ANSWER.

`EvidenceContext.shared` is SINGLE-FLIGHT: the first caller's result goes to
every later caller with the same key. `assessment_key` used to say only "an
assessment of chicken" — but `build_one` qualifies ONE identity in successive
CHUNKS of three rows, and inside a turn a single ambient context spans all of
them. So chunk 2 onward received chunk 1's `Qualification`. Rows in those chunks
appeared in neither `judged` nor `abstained`, and the caller treats an unlisted
row as a judged NEGATIVE — so they were silently declined.

Only the first three eligible rows of any food were ever really assessed
in-turn, and it bit hardest on the foods with the MOST rows: the common ones.

⭐ THE PROOF IS THE MODEL CALL COUNT, NOT THE RETURNED IDS. A stub whose reply
fails to parse returns empty for both chunks, and empty == empty proves nothing.
"How many times did the model get asked" cannot be faked by a parse failure.
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

from core.evidence_context import EvidenceContext
from skills.nutrition import evidence_qualification as EQ


def _rows(*ids):
    return [{"fdc_id": i, "description": f"desc {i}", "data_type": "SR Legacy",
             "per100g": {"calories": 100, "protein": 10, "carbs": 1, "fat": 1}}
            for i in ids]


def _recording_complete(calls):
    async def complete(prompt):
        calls.append(prompt)
        ids = re.findall(r'(\d{3,})', prompt)
        return json.dumps({"assessments": [
            {"evidence_id": f"usda:{i}", "relationship": "SAME_IDENTITY",
             "confidence": 0.95} for i in ids]})
    return complete


@pytest.mark.asyncio
async def test_two_chunks_of_one_food_are_two_assessments():
    """THE REGRESSION. One turn, one context, two chunks -> TWO model calls."""
    calls = []
    ctx = EvidenceContext()
    await EQ.qualify_usda_rows("chicken", _rows(111, 112, 113),
                               complete=_recording_complete(calls), context=ctx)
    await EQ.qualify_usda_rows("chicken", _rows(221, 222, 223),
                               complete=_recording_complete(calls), context=ctx)
    assert len(calls) == 2, (
        f"{len(calls)} model call(s) for two different chunks — the second "
        "chunk's rows were never assessed and are silently declined")
    # and each call was asked about ITS OWN rows
    assert "111" in calls[0] and "221" not in calls[0]
    assert "221" in calls[1] and "111" not in calls[1]


@pytest.mark.asyncio
async def test_the_same_rows_still_share_one_call():
    """⭐ THE SHARING THAT WAS ALWAYS WANTED IS PRESERVED. Speculative
    enrichment and B-1 derivation asking about the SAME rows must still cost one
    model call — the fix must not turn a dedup into a duplicate."""
    calls = []
    ctx = EvidenceContext()
    rows = _rows(111, 112, 113)
    await EQ.qualify_usda_rows("chicken", rows,
                               complete=_recording_complete(calls), context=ctx)
    await EQ.qualify_usda_rows("chicken", list(reversed(rows)),
                               complete=_recording_complete(calls), context=ctx)
    assert len(calls) == 1, (
        f"{len(calls)} calls for identical rows — sharing regressed, and a "
        "reordered batch is the same question")


@pytest.mark.asyncio
async def test_a_different_food_never_shares_with_another():
    calls = []
    ctx = EvidenceContext()
    await EQ.qualify_usda_rows("chicken", _rows(111),
                               complete=_recording_complete(calls), context=ctx)
    await EQ.qualify_usda_rows("salmon", _rows(111),
                               complete=_recording_complete(calls), context=ctx)
    assert len(calls) == 2, "two foods collapsed onto one assessment"


def test_the_key_is_order_independent_and_row_scoped():
    from skills.nutrition.evidence_qualification import assessment_key as key
    a, b = _rows(1, 2, 3), _rows(3, 2, 1)
    assert key("x", "v", a) == key("x", "v", b), "reordering changed the question"
    assert key("x", "v", a) != key("x", "v", _rows(4)), "different rows collided"
    assert key("x", "v", a) != key("x", "v"), "row-scoped key equals the bare one"
    # a row with no id must not collapse onto every other id-less row
    assert (key("x", "v", [{"description": "alpha"}])
            != key("x", "v", [{"description": "beta"}]))
