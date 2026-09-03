"""⛔ THE RETRY CONTRACT, AT THE SEAM WHERE IT COST A BUILD. `egg|fried` failed
rebuild #2 on one timed-out USDA query out of five; the build correctly refused
to write, and 83 identities' qualification went with it. A query that gave NO
answer is asked again, bounded. A judge that answered is never re-asked."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def _row(fdc, desc, kcal=250.0):
    return {"fdc_id": fdc, "description": desc, "data_type": "SR Legacy",
            "per100g": {"calories": kcal, "protein": 20.0, "carbs": 0.0, "fat": 10.0}}


@pytest.fixture
def build(monkeypatch):
    import api.usda as usda
    import scripts.build_pricing_artifact as bp
    import skills.nutrition.evidence_qualification as eq
    from skills.nutrition import retrieval_intent as ri

    async def _no_expansion(identity, **_k):
        return ri.RetrievalIntent(original=identity, queries=(identity,))

    async def _qualified(food_name, rows, *_a, **_k):
        return SimpleNamespace(rows=tuple(rows), disposition="qualified",
                               resolver_version="test", kept_count=len(rows))

    monkeypatch.setattr(ri, "expand", _no_expansion)
    monkeypatch.setattr(eq, "qualify_usda_rows", _qualified)
    monkeypatch.setattr(bp, "_PROVIDER_BACKOFF_S", 0)
    return bp, usda


def _retrieval_that_fails_for(usda, failing_calls):
    """`_search` swallows failures into [] and WARNS — that warning is the only
    signal the build has, so the stub emits exactly it. Rounds are derived as
    calls / distinct queries: the first version detected "first in round" by
    query text, and with two queries per round that both start with the
    entity it counted every round twice."""
    state = {"calls": 0, "queries": set()}

    async def _search(query, *_a, **_k):
        state["calls"] += 1
        state["queries"].add(query)
        if state["calls"] <= failing_calls:
            usda.logger.warning("USDA search failed: TimeoutError: ")
            return []
        return [_row(1, "Beef, chuck, cooked, roasted")]

    def rounds():
        return state["calls"] // len(state["queries"])
    return _search, rounds


def test_one_timed_out_query_is_retried_and_the_identity_still_builds(build, monkeypatch):
    bp, usda = build
    search, rounds = _retrieval_that_fails_for(usda, failing_calls=1)
    monkeypatch.setattr(usda, "_search", search)
    r = asyncio.run(bp.build_one("beef", "roasted"))
    assert r["status"] == "ok", r
    assert rounds() == 2, "one failed round, one clean round — not three"


def test_a_persistent_provider_failure_is_bounded_and_named(build, monkeypatch):
    bp, usda = build
    search, rounds = _retrieval_that_fails_for(usda, failing_calls=10**6)
    monkeypatch.setattr(usda, "_search", search)
    r = asyncio.run(bp.build_one("beef", "roasted"))
    assert r["status"] == "failed" and r["failure_class"] == "RETRYABLE_PROVIDER"
    assert rounds() == bp._PROVIDER_ATTEMPTS
    assert r["provider_attempts"] == bp._PROVIDER_ATTEMPTS
    assert f"after {bp._PROVIDER_ATTEMPTS} attempt" in r["reason"]


def test_a_clean_round_is_not_retried(build, monkeypatch):
    """The NO-transition case: success must not loop."""
    bp, usda = build
    search, rounds = _retrieval_that_fails_for(usda, failing_calls=0)
    monkeypatch.setattr(usda, "_search", search)
    r = asyncio.run(bp.build_one("beef", "roasted"))
    assert r["status"] == "ok" and rounds() == 1


def test_a_semantic_abstention_is_never_retried(build, monkeypatch):
    """⛔ THE OTHER HALF OF THE CONTRACT. The judge ANSWERED (it abstained on
    every row) — re-asking it until it agrees is sampling. Retrieval happens
    exactly once and the failure is classed SEMANTIC, not RETRYABLE."""
    import skills.nutrition.evidence_qualification as eq
    bp, usda = build

    async def _abstains(food_name, rows, *_a, **_k):
        return SimpleNamespace(rows=(), disposition="qualified", resolver_version="test",
                               kept_count=0, abstained=tuple(rows))
    monkeypatch.setattr(eq, "qualify_usda_rows", _abstains)
    search, rounds = _retrieval_that_fails_for(usda, failing_calls=0)
    monkeypatch.setattr(usda, "_search", search)
    r = asyncio.run(bp.build_one("beef", "roasted"))
    assert r["status"] == "failed" and r["failure_class"] == "SEMANTIC_UNRESOLVED", r
    assert rounds() == 1, "a semantic answer must not re-enter retrieval"
