"""Which signal owned the routing decision, and what deciding cost.

`food_relevance` is two tiers behind one boolean: free regexes first, a Haiku
call only for what they miss. From the caller's side those are indistinguishable
— so "how often do we pay a model round trip to be told something a regex
already knew" could not be answered from outside that function, and it is the
number the ≤1-decision-model-call target is made of.

Routing is claimed rather than noted, because this field has a property the
others do not: more than one caller writes it and only the EARLIEST is the
answer.

  * The free signals claim before the gate is consulted. `or` short-circuits,
    so on a thread turn the model never runs — and every claim there is a
    round trip not paid for.
  * The shadow coordinator calls `food_relevance` again near the end of the
    same turn, inside the same trace span. Under plain overwrite semantics
    that second call would relabel every free-signal turn `gate_model`, and
    the histogram would report that we pay Haiku on every turn — the exact
    opposite of what it exists to measure.

`route` and `context` also become real stages here. Context loading — day
line, board, regulars, last assistant turn — is DB work on the critical path
sitting immediately ahead of the turn's largest model call, and none of it was
timed, so a slow regulars query read as a slow interpreter.
"""
import os

import pytest

import core.food_trace as TR
import core.food_turn as FT
from core.food_trace import Stage


def _trace(tid="t"):
    return TR.begin(turn_id=tid, user_id=1, mode="moderate", channel="ios")


# ── first claim wins ─────────────────────────────────────────────────────────
def test_the_first_claim_is_the_answer():
    t = _trace()
    TR.claim_route("thread")
    TR.claim_route("gate_model")
    assert t.route_owner == "thread"


def test_a_free_signal_is_not_relabelled_by_the_shadow_pass():
    """The concrete regression this shape prevents: the coordinator re-asks
    `food_relevance` late in the same turn."""
    t = _trace()
    TR.claim_route("prior")
    for _ in range(5):
        TR.claim_route("gate_model")
    assert t.route_owner == "prior"


def test_an_empty_claim_does_not_take_the_slot():
    t = _trace()
    TR.claim_route("")
    TR.claim_route("undo")
    assert t.route_owner == "undo"


def test_claiming_with_no_trace_is_silent():
    TR.claim_route("thread")


# ── the gate labels itself ───────────────────────────────────────────────────
async def test_the_regex_tier_claims_when_the_model_gate_is_off(monkeypatch):
    monkeypatch.setenv("FOOD_GATE_MODEL", "false")
    t = _trace()
    await FT.food_relevance("150g chicken breast")
    assert t.route_owner == "gate_regex"


async def test_the_regex_tier_claims_when_it_wins_first(monkeypatch):
    """The model gate is ON, but `applies()` matched — no round trip."""
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")
    t = _trace()
    await FT.food_relevance("150g chicken breast")
    assert t.route_owner == "gate_regex"


async def test_reaching_the_model_is_recorded_as_the_cost_it_is(monkeypatch):
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")

    async def _fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": "yes", "tool_calls": [], "raw_content": []}

    monkeypatch.setattr("core.llm.chat", _fake)
    FT._RELEVANCE_CACHE.clear()
    t = _trace()
    # A message no regex claims, so tier 3 runs.
    await FT.food_relevance("oh and a bag of quest chips")
    assert t.route_owner == "gate_model"


async def test_a_paid_round_trip_that_still_fell_back_is_its_own_shape(
        monkeypatch):
    """More expensive than never having asked, so it must not hide inside
    `gate_regex`."""
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")

    async def _boom(*a, **k):
        raise RuntimeError("529 overloaded")

    monkeypatch.setattr("core.llm.chat", _boom)
    FT._RELEVANCE_CACHE.clear()
    t = _trace()
    await FT.food_relevance("oh and a bag of quest chips")
    assert t.route_owner == "gate_model_failed"


# ── the new stages ───────────────────────────────────────────────────────────
def test_route_and_context_are_reportable_now_that_they_are_stamped():
    t = _trace()
    t.record(Stage.ROUTE, duration_ms=18)
    t.record(Stage.CONTEXT, duration_ms=96)
    d = t.as_dict()
    assert d["route_ms"] == 18 and d["context_load_ms"] == 96


def test_they_come_before_the_interpreter_in_the_funnel():
    from core.food_trace import STAGE_ORDER
    assert STAGE_ORDER.index("route") < STAGE_ORDER.index("context")
    assert STAGE_ORDER.index("context") < STAGE_ORDER.index("interpret")


def test_routing_contributes_one_record_however_many_exits_reach_it():
    """`stage_ms` sums, so a turn that declines twice would otherwise report
    double the time it spent deciding. Pinned on the arithmetic the guard in
    `_end_route` exists to protect."""
    t = _trace()
    t.record(Stage.ROUTE, duration_ms=20)
    t.record(Stage.ROUTE, duration_ms=20)
    assert t.stage_ms(Stage.ROUTE) == 40, (
        "if this ever reads 20, the sum semantics changed and _end_route's "
        "idempotence guard is no longer what keeps route_ms honest")


# ── the escape reason joins the timings ──────────────────────────────────────
def test_the_legacy_reason_rides_the_latency_line():
    t = _trace()
    t.note(legacy_escape_reason="interpreter_none")
    assert "legacy_escape=interpreter_none" in t.log_line()


def test_a_turn_that_never_escaped_says_so():
    assert "legacy_escape=- " in _trace().log_line()
