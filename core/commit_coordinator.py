"""The one place that sequences claim, ledger write, result and finalisation.

WHAT THIS OWNS AND WHAT IT DOES NOT. It owns the atomic mutation PROTOCOL
inside a transaction the caller provides. It does not own the session, and it
never calls `commit()` or `rollback()`.

Giving the coordinator its own session would split atomicity the wrong way:
the food rows and their result would commit while the rest of the turn later
failed, or the turn would commit while the food transaction did not. That is
precisely the cross-boundary inconsistency this exists to remove, so the food
mutation, the immutable result and the operation transition all ride the
caller's outer transaction.

What "the coordinator owns the boundary" means here is narrower and stronger:
NO CALLER MAY INDEPENDENTLY SEQUENCE claim -> write -> record -> finalise. Only
this function does, and every step's failure unwinds the ones before it because
they share one transaction.

NOT WIRED. `run_turn` does not call this yet.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from core.meal_commit import (CommitClaim, MealCommitResult,  # noqa: F401
                              MissingCommitClaim, claim_commit, record_result)

logger = logging.getLogger(__name__)


class CommitInProgress(RuntimeError):
    """A claim exists with no result.

    NOT a routine duplicate. If the claim, the ledger write and the result all
    ride one transaction, a crash before commit unwinds all three — so a
    DURABLE claim without a result means either another transaction is still
    writing, or something left an invalid partial state. Both deserve a
    caller's attention rather than a silent success.

    Never returned as a value: `commit_or_load_existing` does not return None,
    because a caller receiving nothing cannot tell "already done" from "nothing
    happened".
    """

    def __init__(self, operation_id: str, revision: int):
        super().__init__(
            f"{operation_id}@{revision}: a commit claim exists with no "
            "recorded result — another writer may still be in flight")
        self.operation_id, self.revision = operation_id, revision


async def _enqueue_outbox(db, *, operation, result, user_id: int) -> None:
    """Queue each durable event in the mutation's own transaction.

    A WRITER must supply `OutboxEvent` instances — the type validates kind,
    payload JSON-safety and the dedup decision at construction, where the
    producer is on the stack. A dict here means someone bypassed the type,
    and refusing it now (zero producers exist) is what keeps the untyped
    shape from ever acquiring one.
    """
    events = getattr(result, "outbox_events", ()) or ()
    if not events:
        return
    from core.meal_commit import OutboxEvent
    from db.queries import enqueue_background_job

    for event in events:
        if not isinstance(event, OutboxEvent):
            raise TypeError(
                f"outbox events are OutboxEvent, got {type(event).__name__} — "
                f"the type is where kind, payload and the duplicate decision "
                f"are validated")
        await enqueue_background_job(
            db, user_id=user_id, kind=event.kind,
            payload={"version": event.version, **event.payload},
            dedup_key=event.dedup_key or None,
            turn_id=getattr(operation, "source_turn_id", None) or None,
            commit=False)          # rides THIS transaction; never its own


async def commit_or_load_existing(
        db, *, operation, resolved_meal,
        writer: Callable[..., Any],
        finaliser: Optional[Callable[..., Any]] = None) -> MealCommitResult:
    """Write this meal exactly once, or return what the first write produced.

    `db` is the CALLER'S session, mid-turn, possibly with work already staged.
    Nothing here commits or rolls it back.

    `writer` performs the ledger write and returns a `MealCommitResult`. It is
    injected rather than imported so this module does not depend on the food
    executor — and so the failure paths below can be exercised without one.

    Raises rather than returning None on every abnormal outcome, because a
    caller that receives nothing cannot distinguish "already done" from
    "nothing happened".
    """
    operation_id = getattr(operation, "id", None) or getattr(
        operation, "operation_id", "")
    revision = int(getattr(operation, "revision", 0) or 0)
    user_id = int(getattr(operation, "user_id", 0) or 0)
    if not operation_id:
        raise ValueError("a commit needs an operation id")

    claim = await claim_commit(db, operation_id=operation_id,
                               revision=revision, user_id=user_id)
    if claim.is_duplicate:
        if claim.result is not None:
            logger.info(
                "event=commit_coordinator outcome=duplicate operation=%s "
                "revision=%d — returning the original result",
                operation_id, revision)
            return claim.result
        # A durable claim with no result is abnormal, not routine.
        logger.warning(
            "event=commit_coordinator outcome=in_progress operation=%s "
            "revision=%d", operation_id, revision)
        raise CommitInProgress(operation_id, revision)

    # WON. Everything below is in the caller's transaction, so any failure
    # unwinds the ledger write with it.
    #
    # THE WRITE, ON THE TRACE. `Stage.EXECUTE` and `items_committed` were
    # recorded only by the legacy executor, so a canonical commit left a trace
    # reading `committed=0` — indistinguishable from a turn that wrote nothing.
    # Only the executor may move `items_committed`, which is why it moves here
    # and not at the point settlement decided to write.
    from core import food_trace as _ft
    with _ft.stage(_ft.Stage.EXECUTE) as _writing:
        result = await writer(db, operation=operation, resolved_meal=resolved_meal)
        if not isinstance(result, MealCommitResult):
            raise TypeError(
                "the writer must return a MealCommitResult, so the winner and a "
                f"later duplicate answer with the same type; got {type(result).__name__}")
        _writing.counts["committed"] = len(result.committed_items)
    _ft.note(items_attempted=len(result.committed_items),
             items_committed=len(result.committed_items))

    # DURABLE POST-COMMIT WORK, ENQUEUED INSIDE THIS TRANSACTION.
    #
    # On the WINNER path only. A duplicate is answered from storage, and the
    # original delivery already enqueued these — re-enqueueing on every retry
    # would multiply the work a flaky network causes, which is the opposite of
    # what idempotency is for.
    #
    # Best-effort `render_actions` are NOT handled here: they run after the
    # caller commits, and doing them inside would make a cache invalidation
    # able to roll back a meal.
    await _enqueue_outbox(db, operation=operation, result=result,
                          user_id=user_id)

    await record_result(db, operation_id=operation_id, revision=revision,
                        result=result)
    if finaliser is not None:
        await finaliser(db, operation_id=operation_id,
                        expected_revision=revision,
                        commit_key=f"{operation_id}:{revision}")
    await db.flush()
    logger.info("event=commit_coordinator outcome=committed operation=%s "
                "revision=%d items=%d", operation_id, revision,
                len(result.committed_items))
    return result
