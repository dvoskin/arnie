"""⛔ RETRIEVAL MUST NOT RE-ROLL BETWEEN BUILDS OF THE SAME CODE. `expand()` is a
model call; rebuilds #2→#3→#4 (2026-09-03, identical code) moved the retrieved
pool of 3 of 9 pinned seeds and made `beef|grilled` reprice on the fourth. The
artifact now stores each identity's expansion queries and the build reuses them
under the same EXPANSION_VERSION — the way annotations are already reused."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def _row(fdc, desc):
    return {"fdc_id": fdc, "description": desc, "data_type": "SR Legacy",
            "per100g": {"calories": 200.0, "protein": 20.0, "carbs": 0.0, "fat": 10.0}}


@pytest.fixture
def build(monkeypatch):
    import api.usda as usda
    import scripts.build_pricing_artifact as bp
    import skills.nutrition.evidence_qualification as eq
    from skills.nutrition import retrieval_intent as ri
    seen = {"queries": [], "expand_calls": 0}

    async def _search(query, *_a, **_k):
        seen["queries"].append(query)
        return [_row(1, "Beef, chuck, cooked, roasted")]

    async def _expand(identity, **_k):
        seen["expand_calls"] += 1
        return ri.RetrievalIntent(original=identity, queries=(identity, "Beef, roast, cooked"))

    async def _qualified(food_name, rows, *_a, **_k):
        return SimpleNamespace(rows=tuple(rows), disposition="qualified", resolver_version="test", kept_count=len(rows))

    monkeypatch.setattr(usda, "_search", _search)
    monkeypatch.setattr(ri, "expand", _expand)
    monkeypatch.setattr(eq, "qualify_usda_rows", _qualified)
    monkeypatch.setattr(bp, "_PROVIDER_BACKOFF_S", 0)
    return bp, seen


def test_stored_expansion_is_reused_and_the_model_is_not_asked(build):
    bp, seen = build
    out = {}
    r = asyncio.run(bp.build_one("beef", "roasted", expansion=["beef, roasted", "STORED QUERY"], expansions_out=out))
    assert r["status"] == "ok"
    assert seen["expand_calls"] == 0, "a stored expansion must not re-roll the model"
    assert "STORED QUERY" in seen["queries"]
    assert out == {"beef|roasted": ["beef, roasted", "STORED QUERY"]}


def test_without_a_stored_expansion_the_model_is_asked_once_and_recorded(build):
    bp, seen = build
    out = {}
    asyncio.run(bp.build_one("beef", "roasted", expansions_out=out))
    assert seen["expand_calls"] == 1
    assert out["beef|roasted"] == ["beef, roasted", "Beef, roast, cooked"]
    assert "Beef, roast, cooked" in seen["queries"]


def test_stored_expansions_are_only_reused_under_the_same_version():
    import scripts.build_pricing_artifact as bp
    from skills.nutrition.retrieval_intent import EXPANSION_VERSION
    doc = {"expansions": {"version": EXPANSION_VERSION, "queries": {"egg|": ["egg", "Egg, whole"], "x|": []}}}
    assert bp._stored_expansions(doc) == {"egg|": ["egg", "Egg, whole"]}
    assert bp._stored_expansions({"expansions": {"version": "retrieval_intent_v0", "queries": {"egg|": ["egg"]}}}) == {}
    assert bp._stored_expansions({}) == {} and bp._stored_expansions(None) == {}
