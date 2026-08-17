"""⛔⛔ A DUPLICATE TURN REACHED THE USER AS AN OUTAGE.

`ExactlyOnceRefusal` is raised by `NativeExecutionStage` when
`claim_processed_turn` finds the same (user, lowercased text, plan) inside its
60-minute window. Nothing caught it, so it propagated out of `run_turn` and the
iOS client rendered the 500 as "Arnie's temporarily unavailable · Retry".
Observed in production 2026-08-16 on `3b03943`, and reproduced through the real
turn by sending one message twice.

⭐ THE GESTURE IS ORDINARY, NOT AN EDGE CASE: clear the day, re-log the same
food in the same words. Exactly-once exists to DEDUPLICATE, and erroring is the
one thing it must not do — the refusal is indistinguishable from the outage it
imitates, and it teaches the user to retry the one thing that cannot work.

⛔⛔ AND THE OBVIOUS REPAIR IS THE DANGEROUS ONE. On a refusal
`state.execution` is None, which is exactly the condition the `native_no_plan`
delegation reads — so absorbing the error and falling through would hand an
already-logged meal to the legacy executor and write it a second time. The
claim's own repair would become the double-log the claim exists to prevent.

⭐⭐⭐ WHAT THE MUTATIONS ACTUALLY PROVED, WHICH IS NOT WHAT I FIRST WROTE HERE.
Removing the early `return` alone left every test GREEN. The delegation is
guarded by `not _bubbles`, so the moment the duplicate is given a REPLY it can
no longer reach legacy — the reply is what closes that door, and the return is
defence-in-depth behind it. Only removing BOTH turns the twin red:

    return removed only          GREEN  <- the twin does NOT bite here
    return AND reply removed     RED    <- delegation reached, double write

⚠ SO THE ORDER OF THE TWO LINES IS LOAD-BEARING AND SILENT. A future edit that
makes the reply conditional, or moves it below the return, re-opens the path
with nothing to catch it. That is the mutation to run against this file.
"""
from __future__ import annotations

import types

import pytest


def _state(error=None, execution=None, response=None, request=None):
    """The fields `run_turn`'s tail actually reads, and nothing invented."""
    return types.SimpleNamespace(
        error=error, execution=execution, response=response,
        request=request if request is not None else _request(),
        health_flags=(), snapshot=None, phase=None, route=None, plan=None,
        validation=None, context=None)


def _request(turn_id="ios:DUP-1"):
    from core.turns.models import TurnRequest
    return TurnRequest(turn_id=turn_id, user_id=26, platform="ios",
                       source_type="ios", text="150g of cucumber", metadata={})


async def _run_with(monkeypatch, state, *, legacy_spy):
    """Drive `run_turn`'s tail over a coordinator that produced `state`."""
    import core.turns.factory as F
    from core.turns.stages import execute as E

    class _Coordinator:
        route_stage = types.SimpleNamespace(decision=None)

        async def run(self, request):
            return state

    async def _build(request, **kwargs):
        return _Coordinator()

    monkeypatch.setattr(F, "build_coordinator", _build)
    monkeypatch.setattr(E, "LegacyExecutionStage", legacy_spy)

    from core.turns.entrypoint import run_turn
    return await run_turn(request=_request())


@pytest.fixture
def legacy_spy():
    """Stands in for the legacy executor and RECORDS being reached.

    ⚠ It does not merely count — it is the thing whose invocation would mean a
    second row for a meal already logged.
    """
    calls = []

    class _Spy:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def run(self, request):
            return None

    _Spy.calls = calls
    return _Spy


# ══ the positive ════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_duplicate_answers_the_user_instead_of_raising(monkeypatch,
                                                               legacy_spy):
    from core.turns.stages.execute_native import ExactlyOnceRefusal

    result = await _run_with(monkeypatch,
                             _state(error=ExactlyOnceRefusal("ios:DUP-1")),
                             legacy_spy=legacy_spy)

    response = getattr(result, "response", None)
    bubbles = list(getattr(response, "bubbles", None) or [])
    assert bubbles and any(b.strip() for b in bubbles), (
        "a duplicate turn produced no reply — an empty response is substituted "
        "by the recovery bubble at delivery, which is the same outage the user "
        "was already seeing")


# ══ THE NEGATIVE TWIN THAT MATTERS ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_duplicate_never_reaches_the_legacy_executor(monkeypatch,
                                                             legacy_spy):
    """⛔⛔ THE DOUBLE-WRITE THE REPAIR COULD HAVE CAUSED.

    `state.execution is None` on a refusal, which is precisely the
    `native_no_plan` delegation's condition. If the absorbed duplicate falls
    through instead of returning, legacy runs the turn and the meal is logged
    TWICE — by the mechanism whose entire purpose is exactly-once.
    """
    from core.turns.stages.execute_native import ExactlyOnceRefusal

    await _run_with(monkeypatch,
                    _state(error=ExactlyOnceRefusal("ios:DUP-1")),
                    legacy_spy=legacy_spy)

    assert legacy_spy.calls == [], (
        "an already-logged duplicate was handed to the legacy executor — the "
        "claim's repair reintroduced the double-write the claim prevents")


@pytest.mark.asyncio
async def test_every_other_error_still_raises(monkeypatch, legacy_spy):
    """⭐ THE ABSORPTION IS ONE CLASS WIDE, NOT A BARE EXCEPT.

    Swallowing `state.error` generally would hide real failures behind a
    friendly sentence — the failure mode this project keeps finding in its own
    instruments. Only the refusal is absorbed.
    """
    with pytest.raises(RuntimeError, match="the database fell over"):
        await _run_with(monkeypatch,
                        _state(error=RuntimeError("the database fell over")),
                        legacy_spy=legacy_spy)


@pytest.mark.asyncio
async def test_a_genuine_no_plan_turn_still_delegates(monkeypatch, legacy_spy):
    """⭐ THE TWIN OF THE TWIN. Returning early must not disable the corn fix:
    a turn with no error and no plan still belongs to legacy, because nothing
    was settled and no ownership was taken."""
    await _run_with(monkeypatch, _state(error=None, execution=None),
                    legacy_spy=legacy_spy)

    assert legacy_spy.calls, (
        "a turn the native lane could not execute stopped reaching legacy — "
        "the corn swallow is back")
