"""Confidence-gated web enrichment for composite meals (2026-07-21).

The restaurant composites the DBs miss (CAVA bowl, poke bowl, Med platter)
resolve to a low-confidence LLM estimate that runs ~30% low and wanders
run-to-run. _web_lookup_meal pulls the ABSOLUTE total from the web and only
overrides on a confident, in-bounds hit — else the estimate stands.

These mock BOTH the search and the Haiku extract so nothing touches the network.
"""
import asyncio

import core.search as cs
import core.llm as llm
import handlers.tool_executor as te


def _run(coro):
    return asyncio.run(coro)


def test_gate_targets_composites_not_single_ingredients():
    assert te._worth_web_meal("CAVA Greens and Grains bowl", 650) is True
    assert te._worth_web_meal("large poke bowl", 700) is True
    assert te._worth_web_meal("Mediterranean chicken platter", 800) is True
    assert te._worth_web_meal("apple", 95) is False
    assert te._worth_web_meal("banana", 105) is False
    assert te._worth_web_meal("egg", 70) is False


def _patch(monkeypatch, snippet, chat_json):
    async def fake_search(q):
        return cs.SearchResult(answer=snippet, results=[], query=q)
    async def fake_chat(*a, **k):
        return {"text": chat_json, "tool_calls": [], "raw_content": []}
    monkeypatch.setattr(cs, "search", fake_search)
    monkeypatch.setattr(llm, "chat", fake_chat)


def test_confident_hit_returns_totals(monkeypatch):
    _patch(monkeypatch, "CAVA steak bowl ~1010 cal, 53g protein",
           '{"calories":1010,"protein":53,"carbs":78,"fat":52,"confidence":"high"}')
    m = _run(te._web_lookup_meal("CAVA Greens and Grains bowl", "1 bowl"))
    assert m is not None
    assert round(m["calories"]) == 1010 and m["confidence"] == "high"


def test_low_confidence_is_rejected(monkeypatch):
    _patch(monkeypatch, "not much here",
           '{"calories":900,"protein":40,"carbs":50,"fat":30,"confidence":"low"}')
    assert _run(te._web_lookup_meal("mystery dish", "1")) is None


def test_out_of_bounds_is_rejected(monkeypatch):
    # A parse that yields an absurd total (>3000) is dropped, not logged.
    _patch(monkeypatch, "bad parse 9999",
           '{"calories":9999,"protein":40,"carbs":50,"fat":30,"confidence":"high"}')
    assert _run(te._web_lookup_meal("giant thing", "1")) is None


def test_empty_search_fails_safe(monkeypatch):
    async def empty_search(q):
        return cs.SearchResult(answer="", results=[], query=q)
    monkeypatch.setattr(cs, "search", empty_search)
    # No snippets -> returns None before any extract; estimate will stand.
    assert _run(te._web_lookup_meal("CAVA bowl", "1")) is None
