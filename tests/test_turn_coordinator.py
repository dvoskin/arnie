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


# ── Phase 2: native food stages + observe mode ────────────────────────────────
@pytest.mark.asyncio
async def test_food_plan_stage_lifts_the_interpreter_into_a_typed_plan():
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage

    async def _fake_interpreter(text, user, **kw):
        return {"action": "log",
                "tool_calls": [{"name": "log_food",
                                "input": {"food_name": "Banana"}}],
                "say": "Logged."}
    plan = await FoodPlanStage(_fake_interpreter).run(_req())
    assert plan.response_intent == "log" and len(plan.operations) == 1
    validation = await FoodValidationStage().run(_req(), plan=plan)
    assert validation.disposition == "execute"
    assert len(validation.approved_operations) == 1


@pytest.mark.asyncio
async def test_ask_and_confirm_hold_the_write():
    """The disposition is the SYSTEM's call: an ask/confirm plan carries no
    approved operations, so the coordinator's phase model can't execute it."""
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage

    for kind, intent in (("clarify", "ask"), ("confirm", "confirm")):
        async def _fake(text, user, _k=kind, **kw):
            return {"action": "ask", "kind": _k, "text": "how much?"}
        plan = await FoodPlanStage(_fake).run(_req())
        assert plan.response_intent == intent
        v = await FoodValidationStage().run(_req(), plan=plan)
        assert v.disposition == "ask" and v.approved_operations == ()


@pytest.mark.asyncio
async def test_interpreter_pass_becomes_a_pass_disposition():
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage

    async def _none(text, user, **kw):
        return None
    plan = await FoodPlanStage(_none).run(_req())
    v = await FoodValidationStage().run(_req(), plan=plan)
    assert v.disposition == "pass" and v.approved_operations == ()


@pytest.mark.asyncio
async def test_observe_mode_predicts_without_side_effects(monkeypatch, caplog):
    """Shadow running: the coordinator's read-only stages record what they
    WOULD do. Nothing executes — proven by the interpreter being the only
    thing called and no executor touched."""
    import logging as _logging
    import core.turns.observe as OB
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.setenv("TURN_COORDINATOR_OBSERVE_DEEP", "1")

    called = {"interpreter": 0}
    async def _fake_interpreter(text, user, **kw):
        called["interpreter"] += 1
        return {"action": "log",
                "tool_calls": [{"name": "log_food", "input": {"food_name": "Egg"}}]}

    import core.turns.stages.food as FS
    monkeypatch.setattr(FS.FoodPlanStage, "_interpreter", None, raising=False)
    orig_init = FS.FoodPlanStage.__init__
    monkeypatch.setattr(FS.FoodPlanStage, "__init__",
                        lambda self, interpreter=None: orig_init(self, _fake_interpreter))

    async def _boom(*a, **k):
        raise AssertionError("observe mode must never execute")
    import handlers.tool_executor as TE
    monkeypatch.setattr(TE, "execute_tool_calls", _boom)

    with caplog.at_level(_logging.INFO, logger="core.turns.observe"):
        pred = await OB.observe_turn(_req("had 2 eggs and toast"),
                                     actual_route="structured_food",
                                     actual_disposition="execute")
    assert pred["lane"] == "structured_food"
    assert pred["disposition"] == "execute"
    assert called["interpreter"] == 1
    line = [r.message for r in caplog.records if "event=turn_observe" in r.message][-1]
    assert "agree=yes" in line


@pytest.mark.asyncio
async def test_observe_is_inert_in_legacy_only(monkeypatch):
    import core.turns.observe as OB
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "legacy_only")
    assert await OB.observe_turn(_req()) is None


@pytest.mark.asyncio
async def test_observe_flags_disagreement(monkeypatch, caplog):
    """A divergence between predicted and actual is what promotion gating
    reads — it must be loud, not silent."""
    import logging as _logging
    import core.turns.observe as OB
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    with caplog.at_level(_logging.INFO, logger="core.turns.observe"):
        await OB.observe_turn(_req("hey what's up"), actual_route="structured_food")
    line = [r.message for r in caplog.records if "event=turn_observe" in r.message][-1]
    assert "agree=NO" in line


# ── Phase 3: deterministic lanes go native ────────────────────────────────────
@pytest.mark.asyncio
async def test_undo_stage_lifts_the_ledger_inverse(monkeypatch):
    """"undo" is answered by the ledger, not the model — the stage produces a
    plan with zero model calls."""
    from core.turns.stages.deterministic import (UndoPlanStage,
                                                 DeterministicValidationStage)
    import core.ledger_undo as LU

    async def _plan(db, user, text):
        return {"action": "delete", "kinds": ["delete"],
                "tool_calls": [{"name": "delete_food_entry",
                                "input": {"entry_id": 4}}]}
    monkeypatch.setattr(LU, "build_plan", _plan)

    req = _req("undo", db=object(), user=object())
    plan = await UndoPlanStage().run(req)
    assert plan.planner_version == "undo_planner_v1"
    assert [c["name"] for c in plan.operations] == ["delete_food_entry"]
    v = await DeterministicValidationStage().run(req, plan=plan)
    assert v.disposition == "execute"
    assert v.policy_version == "deterministic_policy_v1"


@pytest.mark.asyncio
async def test_uninvertible_undo_passes_to_the_conversational_lane(monkeypatch):
    """Nothing to invert (a weight change, an expired event) must fall back,
    never fabricate a write."""
    from core.turns.stages.deterministic import UndoPlanStage
    import core.ledger_undo as LU

    async def _none(db, user, text):
        return None
    monkeypatch.setattr(LU, "build_plan", _none)
    plan = await UndoPlanStage().run(_req("undo", db=object(), user=object()))
    assert plan.operations == () and plan.response_intent == "pass"


@pytest.mark.asyncio
async def test_undo_defers_while_a_question_is_open():
    """An undo mid-question means "cancel", which the ack path owns. The
    stage must not reach the ledger at all."""
    from core.turns.stages.deterministic import UndoPlanStage
    plan = await UndoPlanStage().run(
        _req("undo", db=object(), user=object(),
             food_prior={"kind": "clarify", "items": [{"food": "rice"}]}))
    assert plan.response_intent == "pass"


@pytest.mark.asyncio
async def test_confirm_replay_skips_the_interpreter_entirely():
    """"yes" to a confirm replays the stashed items through the same call
    builder — no re-parse, and the interpreter is never invoked."""
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage

    called = {"n": 0}
    async def _interpreter(*a, **k):
        called["n"] += 1
        return {"action": "log", "tool_calls": []}

    req = _req("yes", food_prior={"kind": "confirm",
                                  "items": [{"food": "chicken breast",
                                             "qty": "8 oz"}]})
    plan = await FoodPlanStage(_interpreter).run(req)
    assert called["n"] == 0
    assert plan.planner_version == "confirm_replay_v1"
    assert len(plan.operations) == 1
    # Provenance survives the replay: a confirmed item is not a parsed one.
    assert plan.operations[0]["input"]["source"] == "structured_food:confirm_replay"
    v = await FoodValidationStage().run(req, plan=plan)
    assert v.disposition == "execute"


@pytest.mark.asyncio
async def test_a_correction_to_a_confirm_still_reaches_the_interpreter():
    """Only an affirmative replays. "no, make it 6 oz" is a correction and
    still needs parsing."""
    from core.turns.stages.food import FoodPlanStage

    called = {"n": 0}
    async def _interpreter(*a, **k):
        called["n"] += 1
        return {"action": "log",
                "tool_calls": [{"name": "log_food", "input": {"food_name": "X"}}]}

    plan = await FoodPlanStage(_interpreter).run(
        _req("no, make it 6 oz", food_prior={"kind": "confirm",
                                             "items": [{"food": "chicken"}]}))
    assert called["n"] == 1
    assert plan.planner_version == "food_planner_v1"


@pytest.mark.asyncio
async def test_observe_predicts_the_undo_lane(monkeypatch, caplog):
    import logging as _logging
    import core.turns.observe as OB
    import core.ledger_undo as LU
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")

    async def _plan(db, user, text):
        return {"action": "delete",
                "tool_calls": [{"name": "delete_food_entry", "input": {}}]}
    monkeypatch.setattr(LU, "build_plan", _plan)

    with caplog.at_level(_logging.INFO, logger="core.turns.observe"):
        pred = await OB.observe_turn(_req("undo", db=object(), user=object()),
                                     actual_route="ledger_undo",
                                     actual_disposition="execute")
    assert pred["lane"] == "ledger_undo" and pred["disposition"] == "execute"
    line = [r.message for r in caplog.records if "event=turn_observe" in r.message][-1]
    assert "agree=yes" in line


# ── Phase 4: the universal committed snapshot ────────────────────────────────
def _call(name, status="committed", entry_id=None, event_id=None):
    from core.execution_result import CallResult
    return CallResult(name=name, raw_input={}, status=status,
                      entry_id=entry_id, event_id=event_id)


def _exec(*calls):
    from core.execution_result import ExecutionResult
    return ExecutionResult(calls=tuple(calls))


class _Prefs:
    calorie_target = 2200
    protein_target = 180
    carb_target = None
    fat_target = None


class _Log:
    date = None
    total_calories = 1500.0
    total_protein = 120.0
    total_carbs = 140.0
    total_fats = 50.0
    total_water_ml = 900.0
    total_steps = 6000
    exercise_entries = ()


@pytest.mark.asyncio
async def test_snapshot_reports_every_domain_not_just_food():
    """The whole point of universal: a fitness or water turn gets the same
    committed contract a food turn does."""
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    execution = _exec(_call("log_food", entry_id=1, event_id=11),
                      _call("log_exercise", entry_id=2, event_id=12),
                      _call("log_water", entry_id=3, event_id=13),
                      _call("delete_food_entry", entry_id=4, event_id=14))
    snap = await CommittedSnapshotStage().run(
        _req(today_log=_Log()), execution=execution)
    domains = [e["domain"] for e in snap.affected_entities]
    assert domains == ["food", "exercise", "water", "food"]
    assert snap.affected_entities[-1]["action"] == "deleted"
    assert snap.ledger_event_ids == (11, 12, 13, 14)


@pytest.mark.asyncio
async def test_refused_writes_never_appear_as_affected():
    """A dedup-blocked log or a refused CAS update changed nothing. Listing it
    would put a row on the card that is not in the day."""
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    execution = _exec(_call("log_food", status="blocked", event_id=9),
                      _call("update_food_entry", status="failed", event_id=10),
                      _call("log_food", entry_id=5, event_id=11))
    snap = await CommittedSnapshotStage().run(
        _req(today_log=_Log()), execution=execution)
    assert len(snap.affected_entities) == 1
    assert snap.ledger_event_ids == (11,)


@pytest.mark.asyncio
async def test_totals_come_from_the_committed_day_not_the_plan():
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    snap = await CommittedSnapshotStage().run(
        _req(today_log=_Log()), execution=_exec(_call("log_food", entry_id=1)))
    assert snap.day_totals["calories"] == 1500.0
    assert snap.day_totals["water_ml"] == 900.0
    assert snap.day_totals["calories_burned"] == 0.0


@pytest.mark.asyncio
async def test_remaining_targets_are_clamped_and_omit_unset_ones():
    """Never negative — "200 over" is a sentence for the coach to write, not a
    number for a progress ring. An unset target is absent, which is not the
    same as zero remaining."""
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage

    class _U:
        id = 7
        preferences = _Prefs()

    log = _Log()
    log.total_calories = 2500.0          # over target
    snap = await CommittedSnapshotStage().run(
        _req(today_log=log, user=_U()), execution=_exec(_call("log_food")))
    assert snap.remaining_targets["calories"] == 0.0
    assert snap.remaining_targets["protein"] == 60.0
    assert "carbs" not in snap.remaining_targets     # unset ≠ nothing left


@pytest.mark.asyncio
async def test_snapshot_degrades_without_inventing_numbers():
    """No day row available → no totals. An empty snapshot is honest; a
    zero-filled one reads as "you've eaten nothing today"."""
    from core.turns.stages.snapshot_builder import CommittedSnapshotStage
    snap = await CommittedSnapshotStage().run(_req(), execution=_exec())
    assert snap.day_totals is None and snap.remaining_targets is None
    assert snap.affected_entities == ()
    assert snap.snapshot_version == "turn_snapshot_v1"


@pytest.mark.asyncio
async def test_day_revision_is_monotonic_across_a_delete(db, make_user):
    """The staleness token must still advance when a turn REMOVES something —
    a count of rows would go backwards and mask the change."""
    from db.queries import record_ledger_event, ledger_revision
    user = await make_user()
    before = await ledger_revision(db, user.id)
    await record_ledger_event(db, user.id, "food", "created", entry_id=1,
                              payload={"food_name": "Rice"})
    mid = await ledger_revision(db, user.id)
    await record_ledger_event(db, user.id, "food", "deleted", entry_id=1,
                              payload={"food_name": "Rice"})
    after = await ledger_revision(db, user.id)
    assert before < mid < after


def test_legacy_routes_map_onto_lanes():
    """Comparison is only meaningful where both sides model the same lane. A
    route with no coordinator equivalent yet reports no verdict rather than a
    false disagreement."""
    from core.turns.observe import legacy_lane
    assert legacy_lane("structured_log") == "structured_food"
    assert legacy_lane("structured_ask") == "structured_food"
    assert legacy_lane("confirm_replay") == "structured_food"
    assert legacy_lane("ledger_undo") == "ledger_undo"
    assert legacy_lane("legacy") == "general"
    assert legacy_lane("duplicate") == ""        # no equivalent — no verdict


@pytest.mark.asyncio
async def test_shallow_observation_costs_no_model_call(monkeypatch):
    """Route agreement is free; re-planning is a second interpreter call per
    food turn. Deep observation must be opt-in, not the default."""
    import core.turns.observe as OB
    import core.turns.stages.food as FS
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.delenv("TURN_COORDINATOR_OBSERVE_DEEP", raising=False)

    async def _boom(*a, **k):
        raise AssertionError("shallow observation must not plan")
    monkeypatch.setattr(FS.FoodPlanStage, "run", _boom)

    pred = await OB.observe_turn(_req("had 2 eggs and toast"))
    assert pred["lane"] == "structured_food"
    assert pred["disposition"] == ""
