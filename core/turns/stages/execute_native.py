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

        if not await self._claim(db, user, request, ops):
            raise ExactlyOnceRefusal(request.turn_id)

        executor = self._executor
        if executor is None:
            from handlers.tool_executor import execute_tool_calls as executor
        await executor(ops, user, today_log, db,
                       source_type=request.source_type or request.platform,
                       user_message=request.text or "")
        return self._published()

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
