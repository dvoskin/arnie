"""Native execution (P0.2 Phase 5).

The first stage that can own a write. It executes ONLY the operations the
validation stage approved — never the plan's raw operations — so a policy
refusal cannot be bypassed by a stage reaching one layer further back.

Two guarantees carried over from the structured food lane, because they are
the reason that lane is trustworthy:

  • exactly-once. A durable claim on (user, idempotency key) absorbs resends,
    double-taps, cross-device races and post-restart redelivery. The claim is
    taken BEFORE the writes, so a crash between claim and commit fails closed
    (no write) rather than open (a double write).
  • typed results. The executor publishes an ExecutionResult; this stage
    returns it. Nothing downstream scrapes a shared results dict, which
    collapses a multi-item batch to its last call.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _food_inputs(ops) -> list:
    """The `log_food` inputs among the approved operations, in order.

    ⚠ `log_food` ONLY. `update_food_entry` and deletions are corrections, and
    canonical rows cannot be corrected through this path yet (B-1.8, §6). A
    turn carrying one is not this slice and routes to legacy whole.
    """
    return [dict(op.get("input") or {}) for op in (ops or [])
            if (op or {}).get("name") == "log_food"]


class ExactlyOnceRefusal(RuntimeError):
    """The turn was already executed. Not an error the user should see — the
    renderer replays the prior answer."""


class NativeExecutionStage:
    """Runs approved operations through the existing executor.

    The executor stays shared with the legacy lane deliberately: enrichment,
    dedup guards, card building and ledger events all live there, and forking
    them would mean two definitions of what a write is."""

    def __init__(self, executor=None):
        self._executor = executor

    async def run(self, request, route=None, validation=None):
        ops = list(getattr(validation, "approved_operations", ()) or ())
        if not ops:
            return None
        meta = request.metadata or {}
        db, user, today_log = meta.get("db"), meta.get("user"), meta.get("today_log")
        if db is None or user is None:
            raise RuntimeError("native execution requires db and user")

        # ⭐ A1/A11 — ROUTING HAPPENS BEFORE THE CLAIM, AND IT IS PURE.
        # `Unsupported` must reach the UNTOUCHED legacy path: not a canonical
        # attempt that falls back, not a claim taken and released — untouched.
        # So the decision is made here, before anything mutates.
        settlement = await self._canonical_route(db, user, ops)

        if not await self._claim(db, user, request, ops):
            raise ExactlyOnceRefusal(request.turn_id)

        if settlement is not None:
            # ⛔⛔ NO FALLBACK PAST THIS LINE (A8). Once canonical settlement
            # owns the turn, `PricingRefused` PROPAGATES — catching it here to
            # run the legacy executor would put one turn under two settlement
            # owners, which is the dual authority this slice exists to delete.
            # A refusal is non-mutating by construction: it is raised before
            # any write, so there is no row and no ledger event to undo.
            owner, coverage = settlement
            items = _food_inputs(ops)
            result = await owner.settle(db, user=user, items=items,
                                        source_turn_id=request.turn_id,
                                        coverage=coverage)
            # ⛔⛔ PUBLISH, OR THE USER SEES NOTHING. The snapshot and the
            # renderer read the execution view; the legacy executor is the only
            # thing that has ever published one. Measured on a real turn before
            # this line existed: row written, totals correct, CARDS = 0.
            from core.execution_result import LAST_EXECUTION
            from core.general_settlement import execution_view

            view = execution_view(result, items)
            LAST_EXECUTION.set(view)
            return view

        executor = self._executor
        if executor is None:
            from handlers.tool_executor import execute_tool_calls as executor
        await executor(ops, user, today_log, db,
                       source_type=request.source_type or request.platform,
                       user_message=request.text or "")
        return self._published()

    async def _canonical_route(self, db, user, ops):
        """`(owner, coverage)` when canonical settlement owns this turn, else None.

        ⛔ FOUR CONDITIONS, ALL EXPLICIT. The cohort, the shape (every approved
        operation is a food log — a turn that also updates or deletes is not
        this slice), and the coverage predicate. Any of them declining routes
        to legacy untouched.

        ⚠ AND A ROUTING FAILURE ROUTES TO LEGACY, LOUDLY. An exception while
        DECIDING must not take down a turn that legacy could have served; an
        exception while SETTLING must propagate, and does — this try covers
        only the decision.
        """
        from core.general_settlement import (GeneralSettlementOwner, Supported,
                                             coverage_for, settlement_cohort)

        if not settlement_cohort(getattr(user, "id", None)):
            return None
        calls = _food_inputs(ops)
        if not calls or len(calls) != len(ops):
            return None
        try:
            coverage = await coverage_for(db, user_id=int(user.id), items=calls)
        except Exception:                              # noqa: BLE001
            logger.warning("coverage predicate failed; routing to legacy",
                           exc_info=True)
            return None
        logger.info("event=settlement_route user=%s decision=%s reason=%s",
                    user.id, type(coverage).__name__,
                    getattr(coverage, "reason", ""))
        if not isinstance(coverage, Supported):
            return None
        return GeneralSettlementOwner(), coverage

    # ── helpers ───────────────────────────────────────────────────────────────
    async def _claim(self, db, user, request, ops) -> bool:
        """True when this turn is first. A claim that cannot be taken (table
        missing, DB hiccup) must not block the write — the in-memory and
        interpreter-level dedup layers still apply, and refusing every write
        on an infrastructure fault is worse than a rare double."""
        try:
            from core.food_ledger import turn_idempotency_key
            from db.queries import claim_processed_turn
            key = turn_idempotency_key(user.id, request.text or "", ops)
            return await claim_processed_turn(db, user.id, key)
        except Exception as e:
            logger.warning(f"idempotency claim unavailable, proceeding: {e}")
            return True

    def _published(self) -> Optional[object]:
        try:
            from core.execution_result import LAST_EXECUTION
            return LAST_EXECUTION.get()
        except Exception:
            return None
