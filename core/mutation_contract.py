"""One implementation of the mutation contract, for every route that owes it.

`api/quick_log.py` worked out the shape; six more routes were migrated by
copying it. Forty-three remain, and copying a forty-line block that many times
would guarantee the drift this codebase keeps paying for — the audit already
found three turn-id formats, none of which joined, because each surface grew
its own. So the shape lives here once.

    async with mutation_turn(db, channel="dashboard", command="log_food",
                             user_id=user.id, client_key=key, payload=body,
                             dedup=f"{body.name}", claim=True) as turn:
        if turn.replay:
            return {"status": "ok", **turn.stored}
        entry = await add_food_entry(db, ..., ledger_source="dashboard",
                                     claim_id=turn.claim_id)
        turn.note(entry=entry.id)
    return {"status": "ok", "id": entry.id, "turn_id": turn.turn_id}

What the context manager owns:

  * the canonical turn id (`make_turn_id`, never hand-rolled)
  * the ambient `CURRENT_TURN_ID` for its whole body, reset in `finally` —
    the leak that stamps the NEXT write with this turn is a real incident
  * the `RequestTrace`, its `claim` / `write` stages, and persisting it, which
    is what carries build attribution (`TurnMetric.build_sha`)
  * the idempotency claim when `claim=True`, and turning both failure modes
    into the 409 the clients already understand

What the CALLER still owns, deliberately:

  * passing `ledger_source=` and `claim_id=turn.claim_id` INTO the domain
    write, so the row, its ledger event and the claim completion land in one
    transaction. That cannot move in here without this module taking over the
    write itself, and a helper that owns the transaction would be the thing
    every one of these routes is trying to stop having.
  * deciding what a replay returns. Only the route knows whether the answer is
    a row, a total, or a bare ok.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import HTTPException

from core.idempotency import (
    Claim,
    IdempotencyConflict,
    IdempotencyInProgress,
    claim_request,
)
from core.request_trace import RequestTrace, active
from core.turn_identity import CURRENT_TURN_ID, make_turn_id


def client_key(raw) -> Optional[str]:
    """The client's idempotency key, or None.

    FastAPI resolves `Header(...)` before calling the handler, but a DIRECT
    call — tests, and any internal caller reusing a handler — receives the
    unresolved `FieldInfo` default instead. Stringifying that produced a turn
    id of `ios:annotation=Union[str, NoneType]...`, which is worse than the
    null it replaced: a unique-looking id that is really the same for every
    keyless request, so two unrelated taps collide on it.
    """
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def claim_failed(exc: Exception, command: str) -> HTTPException:
    """Both failures are 409, and clients treat them differently: a conflict
    is a bug to report, an in-flight claim is a retry to repeat."""
    if isinstance(exc, IdempotencyConflict):
        return HTTPException(
            status_code=409,
            detail={"error": "idempotency_conflict", "command": command,
                    "message": "This Idempotency-Key was already used for a "
                               "different request."})
    return HTTPException(
        status_code=409,
        detail={"error": "request_in_progress", "command": command,
                "retryable": True,
                "message": "The original delivery of this request is still "
                           "running."})


class MutationTurn:
    """The handle a route gets inside `mutation_turn`."""

    def __init__(self, turn_id: str, trace: RequestTrace, user_id: int):
        self.turn_id = turn_id
        self.trace = trace
        self.user_id = user_id
        self.claim: Optional[Claim] = None

    @property
    def replay(self) -> bool:
        """True when this delivery has already been served. The route must NOT
        write; it returns the original result."""
        return bool(self.claim and self.claim.replay)

    @property
    def stored(self) -> dict:
        """What the original delivery committed."""
        return dict(self.claim.stored_result or {}) if self.claim else {}

    @property
    def claim_id(self) -> Optional[int]:
        """Pass into the domain write so the claim completes in ITS
        transaction. Completing it afterwards leaves a window where the write
        is durable and the claim is not, and a retry takes the stale claim
        over and executes the command a second time."""
        return self.claim.record_id if self.claim else None

    def note(self, **fields: Any) -> None:
        self.trace.note(**fields)

    async def complete(self, db, *, entry_id: Optional[int] = None,
                       daily_log_id: Optional[int] = None) -> None:
        """Complete the claim in a SEPARATE commit. The weaker option.

        Prefer `claim_id=turn.claim_id` on the domain write, which completes
        the claim in the same transaction as the row. Use this only where the
        write cannot take it — a helper this module does not own, or a route
        whose effect is not a single row.

        The difference is a real failure, not a style preference: between the
        write committing and this call, a process that dies leaves the work
        durable and the claim `in_progress`, and the next delivery either
        re-executes it or 409s at a user who did nothing wrong. Reconciliation
        (`core.idempotency.committed_result`) recovers that for commands
        listed in `_COMMAND_DOMAIN`; for anything else the window is real.

        A claim that is never completed at all is worse than both: every retry
        inside STALE_CLAIM_SECONDS is refused.
        """
        if self.claim is None:
            return
        from core.idempotency import complete_claim
        await complete_claim(db, self.claim, entry_id=entry_id,
                             daily_log_id=daily_log_id)

    async def audit(self, db, event_type: str, *, domain: str,
                    entry_id: Optional[int] = None,
                    payload: Optional[dict] = None,
                    surface: Optional[str] = None) -> None:
        """The Class B audit record: what changed, when, and on whose turn.

        A settings change owes an audit trail rather than a ledger event —
        the question asked of it later is "when did this change and to what",
        not "how do I undo it". `record_surface_mutation` keeps the canonical
        turn id already bound by this context manager (it only mints a
        synthetic one when nothing else has), so the audit row joins the turn.
        """
        from db.queries import record_surface_mutation
        await record_surface_mutation(
            db, self.user_id, event_type, domain=domain, entry_id=entry_id,
            payload=payload, surface=surface or domain)


@asynccontextmanager
async def mutation_turn(
    db, *, channel: str, command: str, user_id: int,
    client_key: Optional[str] = None, payload: Any = None,
    dedup: str = "", claim: bool = False, persist: bool = True,
):
    """Bind one request's identity, trace and (optionally) idempotency claim.

    `dedup` is the per-request-meaningful signature the turn id falls back to
    when the client sends no key. It must distinguish two genuinely different
    requests — food uses `name|quantity` — or two distinct taps collapse onto
    one turn.

    `claim=True` is Class A. Class B and C pass `claim=False`: their policy is
    declared in `core/mutation_policy.py` as naturally idempotent, and a claim
    there would add a failure mode without removing one.
    """
    turn_id = make_turn_id(channel, client_key, user_id, dedup)
    with RequestTrace(turn_id=turn_id, channel=channel, command=command,
                      user_id=user_id) as trace:
        turn = MutationTurn(turn_id, trace, user_id)
        trace.note(keyed=bool(client_key))
        if claim:
            try:
                with trace.stage("claim"):
                    turn.claim = await claim_request(
                        db, channel=channel, command=command, user_id=user_id,
                        client_key=client_key, payload=payload,
                        turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise claim_failed(e, command)
            trace.note(idempotency=("replay" if turn.claim.replay
                                    else "claimed" if turn.claim.key
                                    else "unkeyed"))

        # Bound for the whole body, reset in `finally`. The endpoint runs on a
        # shared worker task and a leaked contextvar stamps the next request's
        # writes with this turn.
        token = CURRENT_TURN_ID.set(turn_id)
        try:
            # ⭐ AND THE TRACE ITSELF IS BOUND, which it never was.
            #
            # `request_trace` has always exposed `timed()` / `time_stage()` for
            # leaf instrumentation — "a NO-OP when none is [active]" — and
            # NOTHING in the codebase ever called `active()`. So every leaf
            # that thought it was reporting was reporting nothing: `llm` on
            # every model call (core/llm.py:166, :234) and `tools`
            # (tool_executor:3328) have been decorated and dead. That is why
            # every row in `turn_metrics.stages_json` shows exactly two stages,
            # `claim` and `write` — the only two set directly on the object.
            #
            # Measured 2026-08-07: a chip tap took 11,053 ms and the trace
            # attributed all of it to `write`. True, and useless. Binding the
            # ambient trace is what makes the existing instrumentation mean
            # something, and it is a prerequisite for measuring the settle
            # path rather than inferring it.
            with active(trace):
                with trace.stage("write"):
                    yield turn
        except HTTPException as e:
            # An expected refusal (404/403) is an outcome, not a crash. Recorded
            # so the trace says what happened, and re-raised unchanged.
            trace.done(outcome=f"http_{e.status_code}")
            raise
        finally:
            CURRENT_TURN_ID.reset(token)

        trace.done()
        if persist:
            await trace.persist(db)
