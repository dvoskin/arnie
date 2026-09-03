"""⛔⛔ QUERY EXPANSION IMPROVES RECALL AND NOTHING ELSE. Now that it is WIRED
into the producer for publication, these are its shipping invariants:

  * it returns QUERY STRINGS — never evidence, authority, or an identity mapping
  * the user's own words are ALWAYS the first query
  * a model outage degrades to exactly today's behaviour, never to nothing
  * changing the expansion moves `retrieval_fingerprint` — evidence found under
    a different expansion was found by a different instrument

The 86-item census measured it: 20 identities recovered, 0 qualification
regressions, with the gate untouched. These tests are what keep that claim true.
"""
from __future__ import annotations

from dataclasses import fields

import pytest

from skills.nutrition import retrieval_intent as ri


async def _ok(prompt):
    return '["cottage cheese, dry curd", "farmer cheese", "cottage cheese, dry curd"]'


async def _outage(prompt):
    raise RuntimeError("model unavailable")


async def _garbage(prompt):
    return "Sure! Here are some ideas: not json at all"


@pytest.mark.asyncio
async def test_the_original_query_is_always_first_and_duplicates_collapse():
    intent = await ri.expand("творог", complete=_ok)
    assert intent.queries[0] == "творог", "expansion must ADD, never replace the user's words"
    assert intent.queries.count("cottage cheese, dry curd") == 1
    assert intent.original == "творог"


@pytest.mark.asyncio
@pytest.mark.parametrize("complete,why", [
    (_outage, "model raised"), (_garbage, "reply unparseable")])
async def test_a_failed_expansion_degrades_to_todays_behaviour_not_to_nothing(complete, why):
    """⛔ FAIL OPEN. An outage must not reduce recall below the status quo."""
    intent = await ri.expand("творог", complete=complete)
    assert intent.queries == ("творог",), why


def test_the_intent_carries_no_evidence_authority_or_mapping():
    """Structural: the shape cannot express a decision. `__post_init__` refuses
    the names; this pins the current field set so an addition is deliberate."""
    names = {f.name for f in fields(ri.RetrievalIntent)}
    assert names == {"original", "queries", "expansion_version", "provenance"}
    for forbidden in ("evidence", "authority", "grade", "identity_map", "verdict"):
        assert forbidden not in names


def test_changing_the_expansion_moves_the_retrieval_fingerprint(monkeypatch):
    """The staleness contract covers expansion. Without this, someone edits the
    expansion prompt, leaves the fingerprint alone, and two instruments' evidence
    share one label."""
    from skills.nutrition import pricing_artifact as art
    before = art.retrieval_fingerprint()
    monkeypatch.setattr(ri, "EXPANSION_VERSION", ri.EXPANSION_VERSION + "-mutated")
    assert art.retrieval_fingerprint() != before


@pytest.mark.asyncio
async def test_the_query_budget_is_bounded():
    async def many(prompt):
        return "[" + ",".join(f'"q{i}"' for i in range(50)) + "]"
    intent = await ri.expand("x", complete=many, max_queries=4)
    assert len(intent.queries) <= 5, "original + max_queries; a runaway list is a provider DoS"
