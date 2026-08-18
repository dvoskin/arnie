"""⛔⛔ THE DUPLICATE STILL READ AS AN OUTAGE, THROUGH A DIFFERENT DOOR.

`8f5501d` stopped `ExactlyOnceRefusal` propagating as a 500 and gave the
duplicate a reply. Production kept answering **"Something went sideways on my
end. Resend that and I'll catch it."** — the `llm_error` recovery line, telling
the user to retry the one thing that cannot succeed.

⭐⭐⭐ THE REPLY WAS ALREADY WRITTEN BY THE TIME THE ABSORPTION RAN.
`TurnCoordinator.run` catches every exception and sets
`state.response = await finalizer.recover(state)` — the coordinator's failure
floor, which is `recovery_message("llm_error", seed=request.text)`. Only THEN
does `entrypoint.run_turn` absorb the refusal, and its replacement was guarded
by `if not state.response.bubbles`. The floor had already filled them, so
"Already logged that one." was unreachable on the live path.

⭐⭐⭐ AND THE FIRST TEST WAS GREEN BECAUSE ITS FIXTURE SUPPLIED THAT VERY FIELD.
`test_a_duplicate_turn_is_absorbed_not_raised` stubs the whole coordinator and
hands in `response=None` by hand — so `Finalizer.recover` never runs, and the
one value that decides the outcome in production was the one the test invented.
**These tests drive the REAL `TurnCoordinator` and the REAL `Finalizer`**, and
stub only the execution stage, which is the layer that genuinely raises.

The production fingerprint, for the record — `seed` is the user's own text, so
the stored line identifies the pool index that produced it:

    len("100g of white rice") + len("llm_error") = 27,  27 % 3 = 0
    RECOVERY_BUBBLES["llm_error"][0]
        == "Something went sideways on my end.|||Resend that and I'll catch it."
        == conversation_logs #9223 / #9224, user 26, 2026-08-17 02:40 UTC

⚠ AND AN EMPTY RESPONSE IS A DIFFERENT POOL. `Response.from_text("")` falls
back to `stall` ("Lost the thread there"), never to `llm_error` — so the line
production stored could only have come from the coordinator's floor.
"""
from __future__ import annotations

import types

import pytest

from core.recovery import is_recovery_text


# ── the real coordinator, with only the raising stage replaced ───────────────

def _request(text="100g of white rice", turn_id="ios:DUP-1"):
    from core.turns.models import TurnRequest
    return TurnRequest(turn_id=turn_id, user_id=26, platform="ios",
                       source_type="ios", text=text, metadata={})


_OP = {"name": "log_food", "input": {"food_name": "White rice", "grams": 100}}


class _Stage:
    """A stage that returns a fixed result, whatever it is handed."""

    def __init__(self, result):
        self._result = result

    async def run(self, *a, **k):
        return self._result


class _Raises:
    """The execution stage, and the only thing about this turn that fails."""

    def __init__(self, exc):
        self._exc = exc

    async def run(self, *a, **k):
        raise self._exc


class _SilentFloor:
    """A finalizer whose `recover` yields nothing.

    ⭐ NOT AN INVENTION — the real `Finalizer.recover` returns None whenever its
    own imports fail, and it is the ONLY configuration in which the delegation
    guard is reachable. With the real floor `state.response` always has bubbles
    by the time the absorption runs, so `not _bubbles` blocks legacy on its own
    and a delegation test driven that way CANNOT FAIL. This is the fixture that
    lets it.
    """

    async def run(self, state) -> None:
        return None

    async def recover(self, state):
        return None


def _coordinator(exc, floor=None):
    """A REAL `TurnCoordinator` driven to `execute` and raising there — the
    shape of a duplicate in production. `floor` defaults to the REAL
    `Finalizer`, which is the layer that produced the observed reply."""
    from core.turns.coordinator import TurnCoordinator
    from core.turns.models import (ContextManifest, RouteDecision, TurnLane,
                                   TurnPlan, ValidationResult)
    from core.turns.stages.finalize import Finalizer

    route = RouteDecision(TurnLane.STRUCTURED_FOOD, "cold_food_gate", 0.9, "t")
    coordinator = TurnCoordinator(
        context_stage=_Stage(ContextManifest(system_prompt="", messages=())),
        route_stage=_Stage(route),
        plan_stage=_Stage(TurnPlan(operations=(_OP,), response_intent="log",
                                   planner_version="test")),
        validation_stage=_Stage(ValidationResult(
            disposition="execute", approved_operations=(_OP,),
            policy_version="test")),
        execution_stage=_Raises(exc),
        snapshot_stage=_Stage(None),
        render_stage=_Stage(None),
        finalizer=floor or Finalizer())
    coordinator.route_stage.decision = route
    return coordinator


async def _run(monkeypatch, exc, *, legacy_spy, text="100g of white rice",
               floor=None):
    import core.turns.factory as F
    from core.turns.stages import execute as E

    coordinator = _coordinator(exc, floor=floor)

    async def _build(request, **kwargs):
        return coordinator

    monkeypatch.setattr(F, "build_coordinator", _build)
    monkeypatch.setattr(E, "LegacyExecutionStage", legacy_spy)

    from core.turns.entrypoint import run_turn
    return await run_turn(request=_request(text))


@pytest.fixture
def legacy_spy():
    calls = []

    class _Spy:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def run(self, request):
            return None

    _Spy.calls = calls
    return _Spy


def _bubbles(result):
    return [b for b in
            (getattr(getattr(result, "response", None), "bubbles", None) or [])
            if (b or "").strip()]


# ══ the defect ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_duplicate_is_never_answered_with_a_recovery_bubble(
        monkeypatch, legacy_spy):
    """⛔ THE OBSERVED SYMPTOM, AS AN ASSERTION.

    A recovery bubble is the product's word for "this turn FAILED, do it
    again". A duplicate did not fail — the meal is on the board — so the one
    reply it must never carry is an instruction to resend.
    """
    from core.turns.stages.execute_native import ExactlyOnceRefusal

    result = await _run(monkeypatch, ExactlyOnceRefusal("ios:DUP-1"),
                        legacy_spy=legacy_spy)

    bubbles = _bubbles(result)
    assert bubbles, "a duplicate turn produced no reply at all"
    assert not any(is_recovery_text(b) for b in bubbles), (
        "the duplicate was answered with the coordinator's failure floor "
        f"({bubbles!r}) — the user is told to resend an already-logged meal")


@pytest.mark.asyncio
async def test_the_duplicate_is_told_it_was_already_logged(monkeypatch,
                                                           legacy_spy):
    """The positive half: the reply says the honest thing, not merely
    something that is not a recovery line."""
    from core.turns.stages.execute_native import ExactlyOnceRefusal

    result = await _run(monkeypatch, ExactlyOnceRefusal("ios:DUP-1"),
                        legacy_spy=legacy_spy)

    assert "already logged" in " ".join(_bubbles(result)).lower(), (
        f"the duplicate's reply does not say it was already logged: "
        f"{_bubbles(result)!r}")


# ══ the negatives that keep the repair honest ═══════════════════════════════

@pytest.mark.asyncio
async def test_the_duplicate_still_never_reaches_the_legacy_executor(
        monkeypatch, legacy_spy):
    """⛔⛔ THE DOUBLE-WRITE, THROUGH THE REAL COORDINATOR THIS TIME.

    `state.execution` is None on a refusal, which is exactly the
    `native_no_plan` delegation's condition. Handing that turn to legacy logs
    an already-logged meal a second time.

    ⭐ DRIVEN OVER A SILENT FLOOR, AND THAT IS THE POINT. Run this against the
    real `Finalizer` and it passes under every mutation — the floor's own
    recovery bubble satisfies `not _bubbles` and blocks the delegation by
    accident. The assertion only means something where the guard is reachable.
    """
    from core.turns.stages.execute_native import ExactlyOnceRefusal

    await _run(monkeypatch, ExactlyOnceRefusal("ios:DUP-1"),
               legacy_spy=legacy_spy, floor=_SilentFloor())

    assert legacy_spy.calls == [], (
        "an already-logged duplicate was handed to the legacy executor")


@pytest.mark.asyncio
async def test_a_real_failure_still_reaches_the_user_as_a_failure(
        monkeypatch, legacy_spy):
    """⭐ THE FLOOR IS NOT BEING DELETED — only kept off the duplicate.

    A genuine stage crash must still raise out of `run_turn`, so the caller's
    own recovery runs. Replacing recovery text unconditionally would hide every
    real failure behind "already logged that one", which is a worse lie than
    the one being fixed.
    """
    with pytest.raises(RuntimeError, match="the database fell over"):
        await _run(monkeypatch, RuntimeError("the database fell over"),
                   legacy_spy=legacy_spy)


@pytest.mark.asyncio
async def test_the_failure_floor_still_answers_the_turns_it_is_for(monkeypatch):
    """⭐ THE INSTRUMENT CHECK. If `Finalizer.recover` had stopped producing a
    recovery bubble, the test above would pass for the wrong reason — a green
    that proves the floor is gone rather than that the duplicate escaped it.
    """
    from core.turns.stages.finalize import Finalizer

    state = types.SimpleNamespace(request=_request())
    response = await Finalizer().recover(state)
    bubbles = [b for b in (getattr(response, "bubbles", None) or []) if b.strip()]

    assert bubbles and any(is_recovery_text(b) for b in bubbles), (
        "the coordinator's failure floor no longer produces a recovery bubble "
        "— the duplicate assertions above are now vacuous")


# ── A CANONICAL REFUSAL IS AN ANSWER, NOT AN OUTAGE (P17 live canary #2) ─────

@pytest.mark.asyncio
async def test_a_correction_refusal_is_answered_in_words_never_legacy_never_raised(
        monkeypatch, legacy_spy):
    """"Salty peanut" became a correction on a deleted row; correct_identity
    refused; the refusal propagated (A8) and the client showed "Arnie's
    temporarily unavailable" six times. Now: a sentence, no write, no legacy,
    no raise — and a StaleUndo / ProductSelectionRefused get their own copy."""
    from core.canonical_correction import (CorrectionRefused,
                                           ProductSelectionRefused, StaleUndo)
    r = await _run(monkeypatch, CorrectionRefused("entry 3029 does not exist"),
                   legacy_spy=legacy_spy)
    text = " ".join(r.response.bubbles)
    assert "isn't on the board" in text and "does not exist" not in text
    assert legacy_spy.calls == [], "a refusal reached the legacy executor"

    r = await _run(monkeypatch, StaleUndo("undo of event 9 is stale"), legacy_spy=legacy_spy)
    assert "out of date" in " ".join(r.response.bubbles)
    r = await _run(monkeypatch, ProductSelectionRefused("candidate x not in universe"),
                   legacy_spy=legacy_spy)
    assert "scanned product" in " ".join(r.response.bubbles)
    r = await _run(monkeypatch, CorrectionRefused("no local evidence-backed rung can price"),
                   legacy_spy=legacy_spy)
    assert "couldn't apply that correction" in " ".join(r.response.bubbles)
    assert legacy_spy.calls == []
