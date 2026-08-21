"""One owner per responsibility, per turn (architecture review item 7).

    Every inbound turn has exactly one route owner, one execution owner,
    one committed snapshot, one response owner, and one final delivery.

The reason this is a test and not a design note: every violation the review
found had the same shape, and none of them looked wrong at the call site.

  * Two entrypoints. `run_chat_turn()` called `run_turn()` directly and never
    built a coordinator, so the coordinator predicted what it would have done
    while the procedural path did it.
  * Two routers. The shadow observation ran `RouteStage` itself, which was
    harmless while nothing else routed and became a second opinion the moment
    the coordinator became the entrypoint.
  * Two progress events for one dispatch, so the client showed two actions.
  * Two policy decisions, one of which nothing consulted.

Each was introduced by adding a correct thing beside an existing correct thing.
That is why the invariant has to be asserted rather than observed: nobody adds
a second owner on purpose.
"""
import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _qualname(func) -> str:
    """`run_turn` or `_turns.run_turn` — the call as written.

    The qualifier is the whole point here: `_turns.run_turn` is the
    coordinator's entrypoint and a bare `run_turn` is the legacy pipeline, and
    matching on the attribute alone cannot tell one from the other.
    """
    if isinstance(func, ast.Attribute):
        return f"{_qualname(func.value)}.{func.attr}".lstrip(".")
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _calls_in(path: pathlib.Path, name: str) -> list:
    """Every call written exactly as `name` in a module, as (lineno, source).

    Read from the AST rather than by grepping, so a mention in a docstring or a
    comment — of which these modules have many, deliberately — is not evidence
    of a call.
    """
    tree = ast.parse(path.read_text())
    lines = path.read_text().splitlines()
    return [(n.lineno, lines[n.lineno - 1].strip())
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _qualname(n.func) == name]


# ── One route owner ─────────────────────────────────────────────────────────

def test_the_route_is_decided_once_per_turn():
    """The coordinator routes for real. Anything downstream that wants the
    route reads the decision it made, rather than computing a second one that
    could disagree with the one the turn actually took."""
    from core.turns.observe import CURRENT_ROUTE
    assert CURRENT_ROUTE.get() is None      # nothing leaks between turns

    source = (REPO / "core/turns/observe.py").read_text()
    # The fallback is legitimate — observation can be invoked with no
    # coordinator above it — but the published decision has to win.
    assert "CURRENT_ROUTE.get() or await RouteStage().run" in source


@pytest.mark.asyncio
async def test_the_published_route_is_the_one_observation_reports():
    from core.turns.models import RouteDecision, TurnLane, TurnRequest
    from core.turns import observe

    decided = RouteDecision(lane=TurnLane.LEDGER_UNDO, reason_code="fixed")
    token = observe.CURRENT_ROUTE.set(decided)
    try:
        prediction = await observe.observe_turn(
            TurnRequest(turn_id="t", user_id=1, platform="ios",
                        source_type="ios", text="had two eggs"),
            actual_route=TurnLane.LEDGER_UNDO.value)
    finally:
        observe.CURRENT_ROUTE.reset(token)

    # "had two eggs" would route to structured food on its own. It does not,
    # because the turn already routed and this is a report, not a re-decision.
    if prediction is not None:          # None when observation is switched off
        assert prediction["lane"] == TurnLane.LEDGER_UNDO.value


# ── One execution owner ─────────────────────────────────────────────────────

def test_the_service_entrypoint_does_not_call_the_legacy_pipeline_itself():
    """The review's first finding. `run_chat_turn` invoked `run_turn` directly,
    so the coordinator was never in the path — the caller was choosing, and it
    always chose legacy."""
    assert _calls_in(REPO / "core/chat_service.py", "run_turn") == []
    # ...and it reaches the turn through the coordinator instead.
    assert _calls_in(REPO / "core/chat_service.py", "_turns.run_turn")


def test_chat_service_holds_no_alias_to_the_legacy_entrypoint():
    """A module-level `run_turn` here is a second door into the turn — one a
    test can patch and pass against while nothing calls it. That is exactly how
    the idempotency tests kept passing over the seam."""
    tree = ast.parse((REPO / "core/chat_service.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.conversation":
            assert "run_turn" not in [a.name for a in node.names]


def test_only_the_adapter_reaches_the_legacy_pipeline():
    """Exactly one module may call `run_turn()` — the adapter that exists to.

    `core.turns.entrypoint` defines a function of the same name; that is the
    coordinator's entrypoint, not a call to the legacy one.
    """
    callers = []
    for path in (REPO / "core").rglob("*.py"):
        if path.name in ("conversation.py", "entrypoint.py"):
            continue
        if _calls_in(path, "run_turn"):
            callers.append(path.relative_to(REPO).as_posix())
    assert callers == ["core/turns/legacy_adapter.py"], callers


# ── One response owner, one delivery ────────────────────────────────────────

def test_a_turn_yields_exactly_one_result():
    """Persistence and delivery run once per turn because there is one result
    to run them on. Two entrypoints meant two candidate results and no rule for
    which one the user saw."""
    import inspect
    from core.turns import entrypoint
    # ⭐ THE WHOLE MODULE, NOT ONE FUNCTION *(Tranche D, D1)*. This read
    # `getsource(entrypoint.run_turn)` until `run_turn` was split so that ONE
    # scope owns the trace across the native-no-plan delegation — which moved
    # the coordinator call into `_run_coordinated` and left this counting zero.
    #
    # Counting the module is what the invariant actually means and is strictly
    # stronger: a second `coordinator.run(` anywhere in the entrypoint is the
    # two-entrypoints defect regardless of which function it hides in.
    source = inspect.getsource(entrypoint)
    # One coordinator run, one thing returned from it.
    assert source.count("await coordinator.run(") == 1


@pytest.mark.asyncio
async def test_a_native_turn_still_produces_a_result_the_caller_can_deliver():
    """A native lane has no legacy TurnResult. If that produced None, the
    caller's persistence and delivery would silently not run — the failure mode
    where a turn succeeds and the user sees nothing."""
    from core.platform import Response
    from core.turns.entrypoint import _result_from_state
    from core.turns.models import TurnRequest, TurnState

    state = TurnState(request=TurnRequest(
        turn_id="t", user_id=1, platform="ios", source_type="ios", text="hi",
        metadata={"user": object(), "today_log": None, "in_onboarding": False}))
    state.response = Response.from_text("logged.")

    result = _result_from_state(state, {})
    assert result is not None
    # The B6 seam sentence-cases the lead; the invariant is that a deliverable
    # result exists, and it does.
    assert result.response.bubbles == ["Logged."]


@pytest.mark.asyncio
async def test_a_native_turn_with_no_response_still_returns_a_result():
    """A hold is a legitimate outcome. It must not look like a crash."""
    from core.turns.entrypoint import _result_from_state
    from core.turns.models import TurnRequest, TurnState

    state = TurnState(request=TurnRequest(
        turn_id="t", user_id=1, platform="ios", source_type="ios", text="hi"))
    result = _result_from_state(state, {"user": None})
    assert result is not None and result.response is not None


# ── One committed snapshot ──────────────────────────────────────────────────

def test_execution_and_render_cannot_both_own_the_committed_state():
    """The phase machine is what makes this structural rather than a
    convention: a render before a commit is not a bug to catch, it is a
    transition that does not exist."""
    from core.turns.models import TurnPhase
    from core.turns.coordinator import transition, TurnState, TurnRequest

    state = TurnState(request=TurnRequest(
        turn_id="t", user_id=1, platform="ios", source_type="ios", text="hi"))
    with pytest.raises(Exception):
        transition(state, TurnPhase.RENDERED)


# ── One progress announcement ───────────────────────────────────────────────

def test_a_tool_is_announced_once_per_turn():
    """Two `on_tool_start` calls for one dispatch made the client restart its
    indicator, so one log read as two backend actions."""
    source = (REPO / "core/conversation.py").read_text()
    assert "_announced" in source
    assert "_announced.add(\"log_food\")" in source
    assert "n not in _announced" in source


# ── One clarification renderer ──────────────────────────────────────────────

def test_no_clarification_bypasses_the_response_contract():
    """Review item 4. `_format_question` rendered clarifications directly, so
    the response contract governed the staged engine's questions and not the
    interpreter's — two meals with near-identical uncertainty could get
    different conversational treatment depending on which one noticed it, and
    the retired system vocabulary survived in the path nothing was checking.

    It stays defined for the gate evals that assert on its exact strings. It
    may not be CALLED from the turn.
    """
    live = [(lineno, src) for lineno, src
            in _calls_in(REPO / "core/food_turn.py", "_format_question")]
    assert live == [], live


def test_the_retired_clarification_copy_cannot_be_emitted():
    """Checked against the string literals the live renderer could EMIT, not
    against its source text — the docstring quotes the retired copy on purpose,
    to say what was removed and why, and a check that cannot tell an example
    from an output would forbid explaining the fix."""
    tree = ast.parse((REPO / "core/food_turn.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "clarify_text_from_points")
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    emitted = [n.value for stmt in body for n in ast.walk(stmt)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for retired in ("Quick one so it's clean", "locked in ✅",
                    "Nothing hits the board till then"):
        assert not any(retired in e for e in emitted), retired
