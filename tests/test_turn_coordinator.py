"""The parallel turn coordinator (P0.2 Phase 1, review 2026-07-25).

Built ABOVE the existing pipeline, not instead of it: the coordinator owns
progress, contracts and the trace while unmigrated lanes delegate to
run_turn() through the legacy adapter. Default mode is legacy_only, so
production behavior is unchanged until a lane is explicitly enabled.

These tests pin the properties that make the migration safe:
  • illegal phase edges raise (render-before-commit, double execute,
    finalize-unrendered) — the failure classes the review named;
  • a stage crash still answers the user and lands in FAILED;
  • observe mode can never execute;
  • lane/allowlist gating is exact.
"""
import pytest

from core.turns import coordinator as CO
from core.turns.coordinator import (TurnCoordinator, transition,
                                    InvalidTurnTransition,
                                    lane_executes_natively)
from core.turns.models import (TurnPhase, TurnLane, TurnRequest, TurnState,
                               ContextManifest, RouteDecision, TurnPlan,
                               ValidationResult, TurnSnapshot)
from core.turns.stages.route import RouteStage


def _req(text="had a banana", **meta):
    return TurnRequest(turn_id="imessage:G-1", user_id=7, platform="imessage",
                       source_type="imessage", text=text, metadata=meta)


# ── transition legality ───────────────────────────────────────────────────────
def test_illegal_transitions_are_structurally_refused():
    st = TurnState(request=_req())
    # render before commit
    with pytest.raises(InvalidTurnTransition):
        transition(st, TurnPhase.RENDERED)
    # skip straight to finalized
    with pytest.raises(InvalidTurnTransition):
        transition(st, TurnPhase.FINALIZED)
    # legal walk
    for ph in (TurnPhase.CONTEXT_READY, TurnPhase.ROUTED, TurnPhase.PLANNED,
               TurnPhase.VALIDATED, TurnPhase.EXECUTED,
               TurnPhase.SNAPSHOT_READY, TurnPhase.RENDERED,
               TurnPhase.FINALIZED):
        transition(st, ph)
    assert st.phase is TurnPhase.FINALIZED
    # terminal
    with pytest.raises(InvalidTurnTransition):
        transition(st, TurnPhase.RENDERED)


def test_cannot_execute_twice():
    st = TurnState(request=_req())
    for ph in (TurnPhase.CONTEXT_READY, TurnPhase.ROUTED, TurnPhase.PLANNED,
               TurnPhase.VALIDATED, TurnPhase.EXECUTED):
        transition(st, ph)
    with pytest.raises(InvalidTurnTransition):
        transition(st, TurnPhase.EXECUTED)


# ── stage plumbing ────────────────────────────────────────────────────────────
class _Stage:
    def __init__(self, result, record=None, name=""):
        self.result, self.record, self.name = result, record, name

    async def run(self, *a, **k):
        if self.record is not None:
            self.record.append(self.name)
        return self.result


class _Finalizer:
    def __init__(self, record):
        self.record = record

    async def run(self, state):
        self.record.append("finalize")

    async def recover(self, state):
        self.record.append("recover")
        return "recovered"


def _coordinator(record, disposition="execute", execution="EXEC"):
    return TurnCoordinator(
        context_stage=_Stage(ContextManifest(system_prompt="SYS"), record, "context"),
        route_stage=_Stage(RouteDecision(TurnLane.GENERAL, "test"), record, "route"),
        plan_stage=_Stage(TurnPlan(response_intent="delegate_legacy"), record, "plan"),
        validation_stage=_Stage(ValidationResult(disposition=disposition), record, "validate"),
        execution_stage=_Stage(execution, record, "execute"),
        snapshot_stage=_Stage(TurnSnapshot(turn_id="t"), record, "snapshot"),
        render_stage=_Stage("REPLY", record, "render"),
        finalizer=_Finalizer(record))


@pytest.mark.asyncio
async def test_full_run_walks_every_phase_in_order():
    record = []
    state = await _coordinator(record).run(_req())
    assert record == ["context", "route", "plan", "validate", "execute",
                      "snapshot", "render", "finalize"]
    assert state.phase is TurnPhase.FINALIZED
    assert state.response == "REPLY"
    # every phase recorded a timing
    assert "executed" in state.timings_ms and "finalized" in state.timings_ms


@pytest.mark.asyncio
async def test_non_execute_disposition_skips_execution_and_snapshot():
    """An ask/pass turn renders without ever entering execution — the phase
    model makes 'nothing was written' structural, not a convention."""
    record = []
    state = await _coordinator(record, disposition="ask").run(_req())
    assert "execute" not in record and "snapshot" not in record
    assert state.phase is TurnPhase.FINALIZED
    assert state.execution is None and state.snapshot is None


@pytest.mark.asyncio
async def test_stage_failure_lands_in_failed_and_still_answers():
    record = []
    coord = _coordinator(record)

    class _Boom:
        async def run(self, *a, **k):
            raise RuntimeError("planner down")
    coord.plan_stage = _Boom()

    state = await coord.run(_req())
    assert state.phase is TurnPhase.FAILED
    assert isinstance(state.error, RuntimeError)
    assert state.response == "recovered"      # the user is never left silent
    assert "execute" not in record            # and nothing was written


# ── routing ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_route_stage_reuses_the_live_gates():
    stage = RouteStage()
    assert (await stage.run(_req("had 2 eggs and toast"))).lane is TurnLane.STRUCTURED_FOOD
    assert (await stage.run(_req("undo"))).lane is TurnLane.LEDGER_UNDO
    assert (await stage.run(_req("hey what's up"))).lane is TurnLane.GENERAL
    onb = await stage.run(_req("Danny", in_onboarding=True))
    assert onb.lane is TurnLane.ONBOARDING
    # a single-entry delete only routes structured when there IS a board
    assert (await stage.run(_req("remove the fries"))).lane is TurnLane.GENERAL
    assert (await stage.run(_req("remove the fries", has_board=True))).lane \
        is TurnLane.STRUCTURED_FOOD


# ── rollout gating ────────────────────────────────────────────────────────────
def test_default_mode_is_legacy_only(monkeypatch):
    monkeypatch.delenv("TURN_COORDINATOR_MODE", raising=False)
    assert CO.coordinator_mode() == CO.MODE_LEGACY_ONLY
    assert not lane_executes_natively(TurnLane.STRUCTURED_FOOD, 7)


def test_observe_mode_never_executes_natively(monkeypatch):
    """The safety property of shadow running: observe mode compares, it never
    writes."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.setenv("TURN_COORDINATOR_LANES", "structured_food,ledger_undo")
    assert not lane_executes_natively(TurnLane.STRUCTURED_FOOD, 7)
    assert not lane_executes_natively(TurnLane.LEDGER_UNDO, 7)


def test_execute_mode_is_gated_by_lane_then_allowlist(monkeypatch):
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_execute")
    monkeypatch.setenv("TURN_COORDINATOR_LANES", "ledger_undo")
    monkeypatch.delenv("TURN_COORDINATOR_ALLOWLIST", raising=False)
    assert lane_executes_natively(TurnLane.LEDGER_UNDO, 7)
    assert not lane_executes_natively(TurnLane.STRUCTURED_FOOD, 7)  # lane off
    monkeypatch.setenv("TURN_COORDINATOR_ALLOWLIST", "12,84")
    assert not lane_executes_natively(TurnLane.LEDGER_UNDO, 7)      # not listed
    assert lane_executes_natively(TurnLane.LEDGER_UNDO, 84)


def test_unknown_mode_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "yolo")
    assert CO.coordinator_mode() == CO.MODE_LEGACY_ONLY


# ── the legacy bridge ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_legacy_execution_stage_delegates_with_its_kwargs():
    from core.turns.legacy_adapter import LegacyTurnAdapter
    from core.turns.stages.execute import LegacyExecutionStage
    seen = {}

    async def _fake_run_turn(**kwargs):
        seen.update(kwargs)
        return "LEGACY_RESULT"

    stage = LegacyExecutionStage(adapter=LegacyTurnAdapter(_fake_run_turn),
                                 system="SYS", platform="imessage")
    out = await stage.run(_req())
    assert out == "LEGACY_RESULT"
    assert seen == {"system": "SYS", "platform": "imessage"}
