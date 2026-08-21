"""⛔⛔⛔ ONE REQUEST IS ONE TOP-LEVEL TURN.

Tranche D, investigation 1. From production 2026-08-20, build `76076b69aea5`,
turn `ios:5F861208-9AA2-477C-A4E9-D36A897C94A4`:

    turn_metrics 1911  command=turn  9523 ms  end 18:18:18.864921
    turn_metrics 1912  command=turn  6293 ms  end 18:18:25.161854

One inbound message, **two** `turn_metrics` rows, two LLM calls (llm=6601 then
llm=6140), one reply.

⭐ WHAT THE EVIDENCE RULED OUT, so this test does not chase it:

  * NOT concurrency. The windows do not overlap — the second execution starts
    **3.9 ms after the first ends** (overlap −0.004 s). The same −0.004 s
    appears on `ios:853B5889` and `ios:E618D57E`: three for three, with the
    start delta equal to the first execution's duration. That constant is
    mechanical, not a client retry.
  * NOT multiple workers. `main.py` builds `uvicorn.Config(...)` with no
    `workers`, and the Render service has a disk attached, which disables
    horizontal scaling outright ("Scaling is not supported for servers with
    disks"). One process, one instance.
  * NOT a missing client key. A real client UUID was present on both.
  * NOT a duplicated write. The turn wrote nothing: entry 3038's `created`
    event belongs to a DIFFERENT turn (`ios:92A54E10…`).

⛔ TWO WAYS TO BREAK ONE INVARIANT, and the first canary hit the wrong one.

  SEQUENTIAL (production, `ios:5F861208…`) — the canonical lane is ON, the
  native turn produces no plan, and the delegation at `entrypoint.py:420`
  runs AFTER the `finally` closed and persisted the first trace. Reachable
  only with `TURN_COORDINATOR_MODE=new_execute` and the lane enabled; the
  suite defaults to legacy-only, so a canary without those flags cannot
  reach it. Measured order:

      enter:entrypoint.run_turn
      persist:turn                  <- ROW 1
      enter:conversation.run_turn   <- begins after the trace closed
      persist:turn                  <- ROW 2

  NESTED (legacy-only mode) — the legacy pipeline runs INSIDE the
  coordinator and BOTH scopes persist anyway, because the guard is
  one-sided. Measured order:

      enter:entrypoint.run_turn
      enter:conversation.run_turn   <- nested, legitimate
      persist:turn                  <- ROW 1, the INNER scope
      persist:turn                  <- ROW 2, the OUTER scope

⭐ THE DURATIONS TELL THEM APART. `total_ms` runs from construction to
persist, so a nested OUTER must be longer than its inner. Production's
second-persisted row is SHORTER (6293 < 9523) — which nesting cannot
produce, and which is how the sequential variant was identified as the
production one before it could be reproduced.

⛔ THE SEQUENTIAL SHAPE:

    entrypoint.run_turn
      └─ coordinator.run(request)          under `_trace_active(_rt)`
      └─ finally: _rt.done(); persist()    <- ROW 1, trace CLOSED
      └─ native produced no plan
      └─ LegacyExecutionStage(...).run()   <- OUTSIDE the closed trace
           └─ conversation.run_turn          opens its OWN trace -> ROW 2

`core/turns/entrypoint.py` already carries the guard and names the symptom
exactly — "two traces for one turn means two rows, and a duplicated turn reads
as extra traffic rather than as double counting" — but the guard is
`_outer = current_trace()`, which only holds while the second scope runs
NESTED. The delegation at `entrypoint.py:420` runs after the `finally` has
already closed and persisted the first.

⭐ THE RULE IS NOT "ONE MODEL CALL". A composer or follow-up call nested inside
the turn is legitimate work and must stay legal; `test_a_nested_follow_up_is_not
_a_second_turn` pins that. The rule is ONE TOP-LEVEL EXECUTION — one scope that
opens a trace, one terminal owner of the reply.
"""
from __future__ import annotations

import pytest

from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, client, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say, operations, commits, vague, B1_ELIGIBLE,
)


@pytest.fixture()
def native_lane(monkeypatch):
    """Turn the canonical lane ON, as production has it.

    ⛔⛤ WITHOUT THIS THE FALLTHROUGH IS UNREACHABLE. `lane_executes_natively()`
    requires `TURN_COORDINATOR_MODE=new_execute` and the lane enabled; the
    suite defaults to legacy-only, so every message delegates from INSIDE the
    coordinator and `entrypoint.py:420` never runs. A canary written without
    these flags reproduces a different variant and reads as if it had
    reproduced this one — which is exactly what happened on the first
    attempt."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_execute")
    monkeypatch.setenv("TURN_COORDINATOR_LANES", "structured_food,ledger_undo")
    monkeypatch.setenv("TURN_COORDINATOR_ALLOWLIST", "")


#: A plan the native lane can PARSE but cannot EXECUTE: no operation, no
#: response. The production shape recorded at `entrypoint.py:355` — "I had a
#: corn on the cob" reached the native lane, the interpreter produced no log
#: operation, and there was nothing committed to narrate.
NO_PLAN = {"action": "none", "items": [], "ready": [], "points": []}

#: The control: the same lane, a plan it CAN execute — measured as one scope
#: with no delegation. An EMPTY `log` plan is NOT this: it carries no item, so
#: the lane produces nothing and falls through exactly like `NO_PLAN`. The
#: control has to differ from the subject in the one way under test.
def _executable():
    return {"action": "log", "items": [item("Corn on the cob", cal=120)],
            "ready": [], "points": []}


@pytest.fixture()
def scopes(monkeypatch):
    """Record every TOP-LEVEL turn scope and the order the owners were entered.

    A "top-level scope" is one that persists its own `turn_metrics` row —
    `RequestTrace.persist_isolated`. Counting persists rather than
    constructions is deliberate: the entrypoint CONSTRUCTS a trace it may not
    own (`_outer or RequestTrace(...)`), and only the owner persists. The row
    count is also exactly what production showed, so the test and the incident
    are measuring the same thing."""
    from core import request_trace as RT

    log = {"persists": [], "order": []}

    real_persist = RT.RequestTrace.persist_isolated

    async def spy_persist(self):
        log["persists"].append({"command": self.command,
                                "turn_id": self.turn_id})
        log["order"].append(f"persist:{self.command}")
        return await real_persist(self)

    monkeypatch.setattr(RT.RequestTrace, "persist_isolated", spy_persist)

    # The two functions that can each begin a top-level execution.
    import core.conversation as CONV
    import core.turns.entrypoint as EP

    real_ep = EP.run_turn
    real_legacy = CONV.run_turn

    async def spy_ep(*a, **k):
        log["order"].append("enter:entrypoint.run_turn")
        try:
            return await real_ep(*a, **k)
        finally:
            log["order"].append("exit:entrypoint.run_turn")

    async def spy_legacy(*a, **k):
        log["order"].append("enter:conversation.run_turn")
        try:
            return await real_legacy(*a, **k)
        finally:
            log["order"].append("exit:conversation.run_turn")

    monkeypatch.setattr(EP, "run_turn", spy_ep)
    monkeypatch.setattr(CONV, "run_turn", spy_legacy)
    return log


def _nested(order) -> bool:
    """Did the legacy pipeline run INSIDE the entrypoint's trace?

    Nested is legal — that is the delegating lane, and its work belongs to the
    one top-level turn. What is not legal is the legacy pipeline beginning
    AFTER the entrypoint has already persisted, which is the fallthrough."""
    try:
        first_persist = order.index(next(o for o in order
                                         if o.startswith("persist:")))
    except StopIteration:
        return True
    return not any(o == "enter:conversation.run_turn"
                   for o in order[first_persist:])


@pytest.mark.asyncio
async def test_one_request_is_one_top_level_turn(client, edges, seeded, scopes):
    """⛔⛔ THE NESTED VARIANT, over the real iOS endpoint — legacy-only mode,
    which is the suite default and a real production configuration for any
    lane not in `TURN_COORDINATOR_LANES`.

    Here the legacy pipeline runs INSIDE the coordinator and both scopes
    persist anyway, because the nesting guard is ONE-SIDED: the entrypoint
    takes `_outer = current_trace()` and persists only what it opened, while
    `core/conversation.py:731` constructs and persists a trace with no such
    check.

    ⭐ This is NOT the production turn's door — that one is
    `test_the_native_fallthrough_is_still_one_top_level_turn`. Same invariant,
    two different ways to break it, and the first canary I wrote hit this one
    while claiming the other."""
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Chicken breast", "q": "How much?"}],
        "items": [vague("Chicken breast", cal=280, amount=6, unit="oz")],
        "ready": [],
    })

    await client.post("/api/v1/chat", json={"message": "I had some chicken breast"})

    persists = scopes["persists"]
    assert len(persists) == 1, (
        "one inbound request opened %d top-level turn scopes, so it wrote %d "
        "turn_metrics rows: %r — order was %r"
        % (len(persists), len(persists),
           [p["command"] for p in persists], scopes["order"]))


@pytest.mark.asyncio
async def test_the_legacy_pipeline_never_begins_after_the_trace_closed(
        client, edges, seeded, scopes):
    """⛔⛔ THE CALL ORDER, which is the defect itself.

    Delegation is legitimate and must stay legal — but it has to happen INSIDE
    the top-level scope. Beginning it after the first trace has persisted is
    what turns one turn into two, and it is why the second execution found no
    replayable ConversationLog to short-circuit on: the first never wrote one."""
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Chicken breast", "q": "How much?"}],
        "items": [vague("Chicken breast", cal=280, amount=6, unit="oz")],
        "ready": [],
    })

    await client.post("/api/v1/chat", json={"message": "I had some chicken breast"})

    assert _nested(scopes["order"]), (
        "the legacy pipeline began AFTER the entrypoint had already persisted "
        "its trace — a second top-level execution under one turn id. Order: %r"
        % (scopes["order"],))


@pytest.mark.asyncio
async def test_a_terminal_canonical_result_returns_without_delegating(
        client, edges, seeded, b1_live, scopes):
    """⭐ THE POSITIVE HALF. When the canonical lane OWNS the turn and produces
    a terminal result, it must return there — never fall through to legacy.

    Without this the fix could be "always delegate" or "never delegate"; this
    pins the side that must keep working, so the guard cannot be satisfied by
    disabling the lane."""
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Chicken breast", "q": "How much?"}],
        "items": [vague("Chicken breast", cal=280, amount=6, unit="oz")],
        "ready": [],
    })

    body = (await client.post(
        "/api/v1/chat",
        json={"message": "I had some chicken breast"})).json()

    assert body.get("interaction"), (
        "the canonical lane produced no owned ask, so this test is not "
        "exercising the terminal path it claims to")
    assert "enter:conversation.run_turn" not in scopes["order"], (
        "a terminal canonical result still fell through to the legacy "
        "pipeline. Order: %r" % (scopes["order"],))


# ══════════════════════════════════════════════════════════════════════════
# THE SEQUENTIAL VARIANT — the production shape, through native_no_plan
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_native_fallthrough_is_still_one_top_level_turn(
        client, edges, seeded, native_lane, scopes):
    """⛔⛔⛔ THE PRODUCTION SHAPE, REPRODUCED. Canonical lane on, a plan the
    native lane cannot execute, so `entrypoint.py:380` is true and the
    delegation at line 420 runs — AFTER the `finally` at 220-233 has already
    closed and persisted the first trace.

    Measured order, identical to turn `ios:5F861208…`:

        enter:entrypoint.run_turn
        persist:turn                  <- ROW 1, the entrypoint's own trace
        enter:conversation.run_turn   <- begins after the trace closed
        persist:turn                  <- ROW 2
        exit:conversation.run_turn
        exit:entrypoint.run_turn

    Both rows `command='turn'`, as production had them. And the durations
    agree: `total_ms` runs from construction to persist, so the FIRST row
    covers the whole native attempt and the second only the legacy run —
    which is why production's second row is SHORTER (6293 < 9523), a
    relationship nesting cannot produce."""
    edges.plans.append(dict(NO_PLAN))

    await client.post("/api/v1/chat", json={"message": "I had a corn on the cob"})

    order = scopes["order"]
    assert len(scopes["persists"]) == 1, (
        "the native fallthrough opened %d top-level turn scopes for one "
        "request: %r — order was %r"
        % (len(scopes["persists"]),
           [p["command"] for p in scopes["persists"]], order))


@pytest.mark.asyncio
async def test_the_fallthrough_delegates_inside_the_scope_not_after_it(
        client, edges, seeded, native_lane, scopes):
    """⛔⛔ THE ORDER ITSELF, which is the defect.

    Delegating is CORRECT here — `entrypoint.py:355` records why: a native
    turn with no plan and nothing to say must not be swallowed into an empty
    reply. The defect is only WHEN: the trace is closed and persisted in the
    `finally` before the delegation runs, so legitimate rescue work is
    recorded as a second top-level turn."""
    edges.plans.append(dict(NO_PLAN))

    await client.post("/api/v1/chat", json={"message": "I had a corn on the cob"})

    assert _nested(scopes["order"]), (
        "the legacy pipeline began AFTER the entrypoint persisted its trace — "
        "one request, two top-level executions. Order: %r" % (scopes["order"],))


@pytest.mark.asyncio
async def test_a_native_turn_that_executes_does_not_delegate_at_all(
        client, edges, seeded, native_lane, scopes):
    """⭐ THE CONTROL, and it must pass BEFORE the fix as well as after.

    It proves the fixture genuinely reaches the native lane: with a plan the
    lane can execute, there is one scope and no delegation. Without this, a
    red above could mean "the lane never ran" rather than "the lane fell
    through", and the two are opposite diagnoses."""
    edges.plans.append(_executable())

    await client.post("/api/v1/chat", json={"message": "I had a corn on the cob"})

    assert "enter:conversation.run_turn" not in scopes["order"], (
        "a native turn that executed still delegated: %r" % (scopes["order"],))
    assert len(scopes["persists"]) == 1, (
        "an executing native turn wrote %d turn_metrics rows"
        % len(scopes["persists"]))


@pytest.mark.asyncio
async def test_a_nested_follow_up_is_not_a_second_turn(client, edges, seeded,
                                                       scopes):
    """⭐ THE GUARD ON THE FIX. The rule is one top-level EXECUTION, not one
    model call. A composer or follow-up running inside the turn is legitimate
    work; a fix that counted model calls, or that forbade the legacy pipeline
    outright, would break the delegating lane this product still runs on.

    So: however many nested calls a turn makes, it stays ONE scope."""
    edges.plans.append({
        "action": "log",
        "points": [],
        "items": [item("Chicken breast", cal=280)],
        "ready": [item("Chicken breast", cal=280)],
    })

    await client.post("/api/v1/chat", json={"message": "I had chicken breast"})

    assert len(scopes["persists"]) == 1, (
        "a delegating turn must still be ONE top-level scope; got %r"
        % ([p["command"] for p in scopes["persists"]],))
