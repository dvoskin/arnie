"""The gate the canary is measured by must be bound where the turn runs.

⛔⛔ THE PER-USER V2 CANARY WAS INERT ON EVERY COORDINATOR TURN, AND THE
INSTRUMENT SAID IT WAS RUNNING. `skills/nutrition/v2_gate` scopes
NUTRITION_ACCURACY_V2 to the ambient turn user, and its own docstring says
"`run_turn` binds the user for the turn's duration via `for_user`". That is true
of `core/conversation.run_turn` — the LEGACY wrapper — and it was false of
`core/turns/entrypoint.run_turn`, the coordinator, which is the one every iOS
turn actually goes through (`core/chat_service.py`: "THROUGH THE COORDINATOR,
ALWAYS"). Measured 2026-09-08 by grep: `for_user` appeared 0 times along
api/chat.py → core/chat_service.py → core/turns/entrypoint.py →
core/turns/stages/execute_native.py, and twice in the legacy wrapper alone.

So `v2_active()` returned False inside the coordinator for everyone, whatever
the allowlist said, and the settlement decision runs there. Production, user 26,
allowlisted on both services: `decision=Unsupported reason=the rung that would
price this scales only heuristically`, on `salmon|grilled` and `oats|` — two of
the exact six identities the artifact cannot reach under V2-OFF. The same
request, replayed locally against the same database and artifact, is Unsupported
with rung `''` unbound and Supported with rung `artifact` under `for_user(26)`.

⭐ THE COST WAS THE WHOLE CANARY. 2026-09-04 18:38Z → 2026-09-08 22:19Z ran with
the flag correctly set at the infrastructure layer and the mechanism inert at
the code layer, so four days of production evidence measured V2-OFF behaviour
while every dashboard reported a V2 cohort.

⭐⭐ THIS IS THE SAME OMISSION CLASS THE ENTRYPOINT HAS ALREADY BEEN REPAIRED FOR
TWICE — `CURRENT_TURN_ID` (canonical writes landing with turn_id NULL) and
`RequestTrace` (native turns leaving no turn_metrics row). Each time the native
path was built without an ambient binding the legacy wrapper provides, and each
time it was found in production rather than by a test. Hence a test: the
binding is asserted at the boundary, so the next ambient thing added to one
path and not the other has somewhere to fail.

The probe replaces `_run_coordinated`, so it observes the gate at the exact
moment the coordinator's work begins — everything downstream, native execution
and the legacy delegation alike, runs inside whatever scope this proves.
"""
import pytest

import core.turns.entrypoint as EP
from core.turns.models import TurnRequest
from skills.nutrition.v2_gate import v2_active


def _request(user_id: int, turn_id: str) -> TurnRequest:
    return TurnRequest(turn_id=turn_id, user_id=user_id, platform="ios",
                       source_type="ios", text="grilled salmon", metadata={})


async def _gate_seen_by_the_coordinator(monkeypatch, request) -> list:
    """Run one turn and report what `v2_active()` said inside it."""
    seen = []

    async def _probe(*, request, **legacy_kwargs):
        seen.append(v2_active())
        return None

    monkeypatch.setattr(EP, "_run_coordinated", _probe)
    await EP.run_turn(request=request)
    return seen


@pytest.mark.asyncio
async def test_the_gate_is_active_inside_the_coordinator_for_an_allowlisted_user(
        monkeypatch):
    """The invariant the canary was assumed to have and did not."""
    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")

    seen = await _gate_seen_by_the_coordinator(monkeypatch, _request(26, "ios:V2A"))

    assert seen == [True], (
        "v2_active() is False inside core/turns/entrypoint.run_turn for an "
        "allowlisted user — the coordinator does not bind the ambient user the "
        "gate reads, so the per-user canary cannot reach the settlement "
        "decision and every coordinator turn runs V2-OFF")


@pytest.mark.asyncio
async def test_a_user_outside_the_allowlist_stays_off_inside_the_coordinator(
        monkeypatch):
    """⭐ THE NEGATIVE HALF, WITHOUT WHICH THE POSITIVE ONE PROVES NOTHING.

    A binding that reported True for everybody would satisfy the test above and
    would be a fleet-wide rollout wearing a canary's name. The allowlist has to
    still decide.
    """
    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")

    seen = await _gate_seen_by_the_coordinator(monkeypatch, _request(99, "ios:V2B"))

    assert seen == [False], (
        "user 99 is not on the allowlist and the coordinator reports V2 active "
        "— the binding is not reading the turn's own user")


@pytest.mark.asyncio
async def test_the_binding_does_not_outlive_the_turn(monkeypatch):
    """⚠ A LEAKED CONTEXTVAR PRICES THE NEXT TURN AS THIS USER.

    The endpoint runs on a shared worker task, which is why `CURRENT_ROUTE` and
    `CURRENT_TURN_ID` are both reset in a `finally` three scopes down. The same
    rule applies here: an allowlisted user's turn must not leave the gate on for
    whoever the task serves next.
    """
    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")

    await _gate_seen_by_the_coordinator(monkeypatch, _request(26, "ios:V2C"))

    assert v2_active() is False, (
        "the V2 gate is still active after the turn returned — the ambient user "
        "leaked out of the turn that bound it")


@pytest.mark.asyncio
async def test_the_gate_is_still_bound_where_the_stages_actually_run(monkeypatch):
    """⭐ THE BINDING HAS TO SURVIVE INTO THE COORDINATOR, NOT JUST REACH IT.

    The test above probes at `_run_coordinated`, which is the entry. Between
    there and the settlement decision the turn passes through the route and
    turn-id contextvars and into `coordinator.run` — and it is
    `NativeExecutionStage` that asks `coverage_for`, whose refusal
    ("the rung that would price this scales only heuristically") is the line
    production emitted. So the assertion is made from inside `run`, where the
    stages are.

    `core/food_intelligence._nutrition_accuracy_v2` — the function the ranker
    actually calls — delegates to `v2_active()`, so this is the same boolean the
    pricing decision reads, one indirection away.
    """
    import types

    import core.turns.factory as F
    from core.food_intelligence import _nutrition_accuracy_v2

    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")

    request = _request(26, "ios:V2D")
    seen = []

    class _Coordinator:
        route_stage = types.SimpleNamespace(decision=None)

        async def run(self, req):
            seen.append(_nutrition_accuracy_v2())
            return types.SimpleNamespace(
                error=None, execution=types.SimpleNamespace(response="ok"),
                response=None, request=req, health_flags=(), snapshot=None,
                validation=None)

    async def _build(req, **kwargs):
        return _Coordinator()

    monkeypatch.setattr(F, "build_coordinator", _build)
    await EP.run_turn(request=request)

    assert seen == [True], (
        "the ranker's own accuracy gate reads False inside coordinator.run for "
        "an allowlisted user — whatever binds at the entrypoint is not reaching "
        "the stages, and the settlement decision is one of them")


@pytest.mark.asyncio
async def test_the_trace_a_coordinator_turn_emits_knows_its_channel(monkeypatch):
    """⭐ THE INSTRUMENT THAT MADE THE DEFECT LOOK LIKE ITS OWN OPPOSITE.

    With nothing opening a span at the top of the turn, the food trace was owned
    by the one `food_turn.run()` opens far downstream — which is handed the mode
    and the resolver cohort but never the channel. So a coordinator turn emitted
    `event=food_trace … user=u509ceb6d75af … channel=-`: a real user hash on a
    line that reads exactly like a turn whose bindings had run. That line is why
    the inert canary was diagnosed as a settlement failure first.

    Asserting the channel is asserting the OWNERSHIP: only a span opened where
    the platform is still known can carry it.
    """
    import types

    import core.turns.factory as F
    from core import food_trace

    monkeypatch.setenv("FOOD_TRACE", "1")
    monkeypatch.setenv("FOOD_TRACE_SALT", "test")

    lines = []

    class _Coordinator:
        route_stage = types.SimpleNamespace(decision=None)

        async def run(self, req):
            # one recorded stage, or `finish` correctly emits nothing at all
            with food_trace.stage(food_trace.Stage.INTERPRET):
                pass
            lines.append(food_trace.current().log_line())
            return types.SimpleNamespace(
                error=None, execution=types.SimpleNamespace(response="ok"),
                response=None, request=req, health_flags=(), snapshot=None,
                validation=None)

    async def _build(req, **kwargs):
        return _Coordinator()

    monkeypatch.setattr(F, "build_coordinator", _build)
    await EP.run_turn(request=_request(26, "ios:V2E"))

    assert lines, "the coordinator turn opened no food trace at all"
    assert "channel=ios" in lines[0], (
        f"the turn's trace does not know its channel: {lines[0][:160]!r} — the "
        "span is being opened downstream of the transport again")
    assert "turn=ios:V2E" in lines[0]


# ══ the trace must say WHICH RANKING POLICY produced the turn ════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("uid,expected", [(26, "rank_v2"), (99, "rank_v1")])
async def test_the_trace_says_which_ranking_policy_priced_the_turn(
        monkeypatch, uid, expected):
    """⛔⛔ V2 STATE WAS UNREADABLE FROM DURABLE EVIDENCE.

    Measured against production 2026-09-10, one web control turn:

        event=food_trace turn=- … channel=web resolver_cohort=live stopped_at=clarify

    `resolver_cohort` is `skills/nutrition/canary` — the RESOLVER rollout,
    answering "does the resolver own this user's committed values". It is NOT
    `NUTRITION_ACCURACY_V2`, and the two have overlapping vocabularies
    (`allowlist`, `off`), which is precisely the confusion `log_line` already
    warns about for `cohort` vs `resolver_cohort`. So nothing on the line said
    which RANKING policy chose the winner, and the only way to answer "was V2
    on for this settlement" was to read the deploy's environment — inference
    from configuration, which is exactly what a canary may not do.

    ⭐ THE FUNCTION ALREADY EXISTED AND NOTHING EMITTED IT.
    `v2_gate.ranking_policy_version()` was written for this question — "the
    ranking regime a winner was produced under. Recorded rather than assumed,
    because 'which policy picked this row' is exactly the question the
    mode-divergence finding showed nobody could answer." It was never put on
    the trace. This puts it there.

    Both rows matter: a field that said `rank_v2` for everyone would satisfy a
    single positive case and be a fleet rollout wearing a canary's name.
    """
    import types

    import core.turns.factory as F
    from core import food_trace

    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    monkeypatch.delenv("NUTRITION_AS_EATEN_PREFERENCE", raising=False)
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")
    monkeypatch.setenv("FOOD_TRACE", "1")
    monkeypatch.setenv("FOOD_TRACE_SALT", "test")

    lines = []

    class _Coordinator:
        route_stage = types.SimpleNamespace(decision=None)

        async def run(self, req):
            with food_trace.stage(food_trace.Stage.INTERPRET):
                pass
            lines.append(food_trace.current().log_line())
            return types.SimpleNamespace(
                error=None, execution=types.SimpleNamespace(response="ok"),
                response=None, request=req, health_flags=(), snapshot=None,
                validation=None)

    async def _build(req, **kwargs):
        return _Coordinator()

    monkeypatch.setattr(F, "build_coordinator", _build)
    await EP.run_turn(request=_request(uid, f"ios:POLICY{uid}"))

    assert lines, "the coordinator turn opened no food trace at all"
    assert f"ranking_policy={expected}" in lines[0], (
        f"user {uid} should have priced under {expected}; the trace says: "
        f"{lines[0][:200]!r} — V2 state is not readable from durable evidence, "
        "so a canary cannot prove which policy produced a settlement")
