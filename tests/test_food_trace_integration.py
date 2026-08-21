"""One food turn, one trace, all the way through (review fix, PR #29).

The unit tests around `food_trace` prove the record accumulates correctly. What
they could not prove is the thing the review actually caught: WHERE the trace
opens and closes. It used to wrap `core.food_turn.run()`, which returns the
structured action and the tool calls and nothing else — so the nutrient
resolution during execution, the database writes, the failed writes, the card
render and the final coaching line were all outside it. Every unit test still
passed, because each stage records correctly when something is listening; the
defect was that nothing was listening by the time the writes happened.

So this drives the real `run_turn` with a stubbed model and a stubbed executor
and asserts the shape of the ONE line that comes out: that it reached execute
and render, and that its commit counts came from the executor rather than from
the clarifier's approval.
"""
import logging

import pytest
from types import SimpleNamespace

import core.conversation as C
import db.queries as Q
import reminders.lifecycle as RL
from core import food_trace
from core.conversation import run_turn
from core.execution_result import CallResult, ExecutionResult


def _user():
    return SimpleNamespace(
        id=413, onboarding_completed=True, timezone="UTC", name="Danny",
        primary_goal="recomp", nudges_sent="", log_unlocked_at="seeded",
        preferences=SimpleNamespace(calorie_target=2165, protein_target=180),
    )


class _DB:
    """The peripheral reads in run_turn are all wrapped, so no-ops suffice."""
    async def refresh(self, *a, **k): pass
    async def commit(self, *a, **k): pass
    async def rollback(self, *a, **k): pass

    async def execute(self, *a, **k):
        class _R:
            def scalar_one_or_none(self): return None
            def scalars(self): return self
            def all(self): return []
            def first(self): return None
            def scalar(self): return None
        return _R()


def _today_log():
    return SimpleNamespace(
        id=None, total_calories=0, total_protein=0, total_carbs=0,
        total_fats=0, total_water_ml=0, workout_completed=False,
        cardio_completed=False, food_entries=[], exercise_entries=[],
    )


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs):
        return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)

    async def _reload(db, uid):
        return _user()
    monkeypatch.setattr(Q, "reload_user", _reload)

    monkeypatch.setenv("FOOD_TRACE", "true")
    food_trace.CURRENT_TRACE.set(None)
    yield
    food_trace.CURRENT_TRACE.set(None)


def _structured_plan(*names):
    """What the food lane hands back: an ordered plan of writes."""
    return {
        "action": "log",
        "tool_calls": [{"name": "log_food", "input": {"food_name": n}}
                       for n in names],
        "kinds": ["new"] * len(names),
        "say": "",
        "note": "",
        "follow_up": "",
    }


def _trace_lines(caplog):
    """The TURN lines, and only those.

    ⛔ `"event=food_trace" in message` is a PREFIX of
    `event=food_trace_config`, which `core/food_trace.py` emits once per
    process when `FOOD_TRACE_SALT` is unset. Whichever test happened to run
    first in a shuffled session captured it as a second "trace line" and
    failed — `expected exactly one trace line, got 2`, or `KeyError: 'user'`
    when a field lookup then parsed the config line instead of the turn.

    Order-dependent, so it passed on most seeds and on most full runs:
    measured here on seeds 1 and 3 failing while seed 2 passed. The same
    substring family as every other grep trap in this repo — an event NAME
    needs its boundary, not a prefix match."""
    return [r.message for r in caplog.records
            if r.message.startswith("event=food_trace ")]


def _fields(line):
    out = {}
    for token in line.split():
        key, _, value = token.partition("=")
        if key and value:
            out[key] = value
    return out


#: Every turn needs its own id: the exactly-once guard keys on it, and a reused
#: one makes the second test a duplicate delivery that correctly writes nothing.
_TURN_SEQ = iter(range(1, 10_000))


async def _drive(monkeypatch, caplog, *, plan, execution, results):
    """Run one turn through the real coordinator."""
    turn_id = f"turn-{next(_TURN_SEQ)}"
    async def fake_sft_run(*a, **k):
        # Stands in for the interpreter pass. Records the stages the real
        # pipeline would, so the assertions below are about the LIFETIME of the
        # trace rather than about the planner, which has its own tests.
        from core.food_trace import Stage
        with food_trace.span(mode="moderate", cohort="canary"):
            food_trace.record(Stage.INTERPRET, duration_ms=5)
            food_trace.record(Stage.STAGE, duration_ms=1)
            food_trace.record(Stage.CLARIFY, duration_ms=1)
            food_trace.note(items_staged=len(plan["tool_calls"]),
                            items_ready=len(plan["tool_calls"]))
        return dict(plan)

    import core.food_turn as FT
    monkeypatch.setattr(FT, "run", fake_sft_run)
    monkeypatch.setattr(FT, "structured_food_enabled", lambda: True)
    # `applies` is the gate that decides the food lane runs at all. Forced here
    # so the test is about the trace lifetime rather than about phrase matching,
    # which food_turn's own tests cover.
    monkeypatch.setattr(FT, "applies", lambda text: True)

    async def fake_exec(*a, **k):
        from core.execution_result import LAST_EXECUTION
        LAST_EXECUTION.set(execution)
        return results
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def fake_voice(*a, **k):
        return "Logged."
    monkeypatch.setattr(C, "voice_log", fake_voice)

    with caplog.at_level(logging.INFO):
        await run_turn(
            _user(), _DB(), [{"role": "user", "content": "100g chicken breast"}],
            "SYS", "imessage", in_onboarding=False, was_onboarding=False,
            today_log=_today_log(), turn_id=turn_id,
        )
    return _trace_lines(caplog)


@pytest.mark.asyncio
async def test_one_turn_emits_one_trace_that_reaches_render(monkeypatch,
                                                            caplog):
    """The whole point of the fix: the trace is still open when the writes and
    the render happen, so the line carries all seven stages' worth of turn."""
    execution = ExecutionResult(calls=(
        CallResult(name="log_food", raw_input={"food_name": "Fairlife"},
                   status="committed", entry_id=1),))
    lines = await _drive(monkeypatch, caplog, plan=_structured_plan("Fairlife"),
                         execution=execution,
                         results={"log_food": "Logged: Fairlife, 150 cal"})

    assert len(lines) == 1, f"expected exactly one trace line, got {len(lines)}"
    fields = _fields(lines[0])
    timings = fields.get("timings", "")
    assert "execute:" in timings, (
        "the trace closed before the writes — this is the defect the review "
        f"found; timings={timings}")
    assert "render:" in timings, f"render fell outside the trace; {timings}"
    assert fields["stopped_at"] == "render"
    assert fields["turn"].startswith("turn-")


@pytest.mark.asyncio
async def test_the_channel_is_populated(monkeypatch, caplog):
    """It was always blank: nothing passed it, because the trace began inside
    the interpreter, which does not know how the message arrived. The coordinator
    does — it is the parameter it was called with."""
    execution = ExecutionResult(calls=(
        CallResult(name="log_food", raw_input={"food_name": "Fairlife"},
                   status="committed", entry_id=1),))
    lines = await _drive(monkeypatch, caplog, plan=_structured_plan("Fairlife"),
                         execution=execution, results={"log_food": "Logged"})
    assert _fields(lines[0])["channel"] == "imessage"


@pytest.mark.asyncio
async def test_the_trace_does_not_outlive_the_turn(monkeypatch, caplog):
    execution = ExecutionResult(calls=(
        CallResult(name="log_food", raw_input={"food_name": "Fairlife"},
                   status="committed", entry_id=1),))
    await _drive(monkeypatch, caplog, plan=_structured_plan("Fairlife"),
                 execution=execution, results={"log_food": "Logged"})
    assert food_trace.current() is None, "the trace outlived the turn"


@pytest.mark.asyncio
async def test_a_blocked_write_does_not_count_as_committed(monkeypatch,
                                                           caplog):
    """The clarifier approved one item; the executor refused it. The funnel used
    to read the approval, so a turn that wrote nothing reported a full commit."""
    execution = ExecutionResult(calls=(
        CallResult(name="log_food", raw_input={"food_name": "Fairlife"},
                   status="blocked",
                   result_text="Couldn't log that - no match found"),))
    lines = await _drive(monkeypatch, caplog, plan=_structured_plan("Fairlife"),
                         execution=execution,
                         results={"log_food": "Couldn't log that"})

    fields = _fields(lines[0])
    assert fields["ready"] == "1", "the approval should still be recorded"
    assert fields["committed"] == "0", (
        "a blocked write was counted as a commit")
    assert fields["failed"] == "1"


@pytest.mark.asyncio
async def test_a_partial_commit_reports_both_halves(monkeypatch, caplog):
    """Two items approved, one written. Both numbers have to survive — the
    commit rate and the failure rate are read off the same line."""
    execution = ExecutionResult(calls=(
        CallResult(name="log_food", raw_input={"food_name": "Fairlife"},
                   status="committed", entry_id=1),
        CallResult(name="log_food", raw_input={"food_name": "mystery casserole"},
                   status="blocked", result_text="Couldn't log that"),))
    lines = await _drive(
        monkeypatch, caplog,
        plan=_structured_plan("Fairlife", "mystery casserole"),
        execution=execution, results={"log_food": "Logged one of two"})

    fields = _fields(lines[0])
    assert fields["ready"] == "2"
    assert fields["attempted"] == "2"
    assert fields["committed"] == "1"
    assert fields["failed"] == "1"


@pytest.mark.asyncio
async def test_the_line_carries_no_account_id(monkeypatch, caplog):
    execution = ExecutionResult(calls=(
        CallResult(name="log_food", raw_input={"food_name": "Fairlife"},
                   status="committed", entry_id=1),))
    lines = await _drive(monkeypatch, caplog, plan=_structured_plan("Fairlife"),
                         execution=execution, results={"log_food": "Logged"})
    assert _fields(lines[0])["user"] != "413"
    assert _fields(lines[0])["user"].startswith("u")
