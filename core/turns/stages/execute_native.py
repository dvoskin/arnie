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


def _bind_scanned_product(items: list) -> list:
    """⭐ P17f.5 — BIND THE SCANNED SNAPSHOT, SINGLE-ITEM ONLY, ONE VIEW.

    Called by `_food_inputs`' consumers via the wrapper below so COVERAGE and
    SETTLEMENT see the same items: when P17g asks "is there an authoritative
    path for this item", the product reference must already be on the item the
    predicate reads, or coverage and pricing would judge two different meals.

    A scan names ONE product. A multi-item turn binds nothing rather than
    smearing one product's evidence across foods it does not describe.
    `assemble()` loads the reference locally; nothing here fetches.
    """
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE

    snapshot_id = SCANNED_PRODUCT_EVIDENCE.get()
    if snapshot_id is not None and items:
        if len(items) == 1:
            items[0]["product_evidence_id"] = snapshot_id
        else:
            logger.info(
                "event=scan_binding_skipped items=%d snapshot=%s — a scan "
                "names one product and this turn has several",
                len(items), snapshot_id)
    return items


def _correction_input(ops) -> Optional[dict]:
    """The ONE `update_food_entry` input when the turn is exactly that, else
    None. B-1.8b is deliberately narrow: a single correction naming a row.
    A turn that mixes logs and updates, or corrects several rows, is not this
    slice and routes to legacy whole."""
    if len(ops or []) != 1:
        return None
    op = ops[0] or {}
    if op.get("name") != "update_food_entry":
        return None
    inp = dict(op.get("input") or {})
    return inp if inp.get("entry_id") is not None else None


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

        # ⛔⛔ CLEAR THE AMBIENT EXECUTION FIRST, WHATEVER SETTLES THIS TURN.
        # `execute_tool_calls` documents and honours this: a new batch sets
        # LAST_EXECUTION to None up front, so a batch that dies mid-flight
        # cannot leave the PREVIOUS turn's execution ambient for a renderer to
        # narrate. The canonical branch only ever `set()` a value on success,
        # so a settlement that raised in a reused context left the prior
        # execution standing — the same stale-read class, arriving through the
        # door this slice opened.
        from core.execution_result import LAST_EXECUTION
        LAST_EXECUTION.set(None)

        # ⭐ B-1.8b — A CORRECTION ON A CANONICAL ROW IS THE OWNER'S TO MAKE.
        # Decided BEFORE the legacy claim, like settlement, and for the same
        # reason: a canonically owned row must never reach the legacy executor,
        # whose INFERRED_INTERPRETATION the firewall refuses. `_correction_route`
        # answers a pure ownership question; `correct_quantity` then either
        # writes or RAISES — CorrectionRefused PROPAGATES exactly as
        # PricingRefused does (A8: no handler here, by AST gate), because a
        # canonical refusal that fell through to legacy would be the dual
        # authority this lane exists to delete.
        correction = await self._correction_route(db, user, ops)
        if correction is not None:
            from core.canonical_correction import correct_quantity
            entry_id, new_quantity = correction
            result = await correct_quantity(
                db, user=user, entry_id=entry_id,
                new_quantity_text=new_quantity)
            logger.info("event=canonical_correction_settled entry=%s "
                        "ratio=%.4f", result.entry_id, result.ratio)
            return await self._publish_correction(db, user, result, request)

        # ⭐ A1/A11 — ROUTING HAPPENS BEFORE THE CLAIM, AND IT IS PURE.
        # `Unsupported` must reach the UNTOUCHED legacy path: not a canonical
        # attempt that falls back, not a claim taken and released — untouched.
        # So the decision is made here, before anything mutates.
        settlement = await self._canonical_route(db, user, ops)

        # ⛔⛔ THE CANONICAL BRANCH TAKES NO LEGACY CLAIM. `_claim` calls
        # `claim_processed_turn`, which COMMITS — a durable ProcessedTurn row —
        # and it used to run BEFORE settlement. The sequence that produced:
        #
        #     route canonical -> ProcessedTurn COMMITS (durable)
        #                     -> meal + result merely STAGED
        #                     -> execution_view raises
        #                     -> the meal transaction disappears
        #                     -> the ProcessedTurn SURVIVES
        #
        # and a retry then met that stale claim and was refused before it could
        # ever reach `commit_or_load_existing`. One failed presentation, and the
        # meal becomes unloggable until the window expires.
        #
        # It also contradicted this slice's own A2 contract, in the settlement
        # owner's docstring: "canonical idempotency REPLACES legacy dedup here
        # — one turn, one claim, one writer. `commit_or_load_existing` is that
        # claim." Two claims is exactly the hidden second owner A2 forbids.
        #
        # ⚠ AND MY OWN ROLLBACK GATE HID IT by stubbing `_claim` — removing the
        # single durable write from the path it was written to prove. A test
        # that patches out the thing under test proves the patch.
        if settlement is not None:
            # ⛔⛔ NO FALLBACK PAST THIS LINE (A8). Once canonical settlement
            # owns the turn, `PricingRefused` PROPAGATES — catching it here to
            # run the legacy executor would put one turn under two settlement
            # owners, which is the dual authority this slice exists to delete.
            # A refusal is non-mutating by construction: it is raised before
            # any write, so there is no row and no ledger event to undo.
            owner, coverage = settlement
            items = _bind_scanned_product(_food_inputs(ops))
            # ⭐ THE MESSAGE TRAVELS WITH THE MEAL (A12). Canonical's idempotency
            # is keyed on what the USER TYPED, not on the turn id and not on the
            # model's plan — so `settle` needs the text, and this is the only
            # place that has both it and the routing decision.
            #
            # ⛔⛔ AND `DuplicateMeal` PROPAGATES, exactly like `PricingRefused`.
            # An earlier version of this line caught it here to rename it, and
            # A8's AST gate refused the patch: `NativeExecutionStage.run` may
            # hold NO except handler at all, because a handler around settlement
            # is precisely how a canonical refusal reaches the legacy executor.
            # The gate was right and the rename belongs at the absorption point,
            # not on the settlement path — `core/turns/entrypoint.py` treats the
            # two signals as one, so the user reads "Already logged that one."
            # whichever owner settled the turn.
            result = await owner.settle(db, user=user, items=items,
                                        source_turn_id=request.turn_id,
                                        source_text=request.text or "",
                                        coverage=coverage)
            # ⛔⛔ PUBLISH, OR THE USER SEES NOTHING. The snapshot and the
            # renderer read the execution view; the legacy executor is the only
            # thing that has ever published one. Measured on a real turn before
            # this line existed: row written, totals correct, CARDS = 0.
            from core.general_settlement import execution_view

            view = execution_view(result, items)
            LAST_EXECUTION.set(view)
            return view

        # LEGACY ONLY FROM HERE. The ProcessedTurn claim belongs to the lane
        # that has no claim of its own.
        if not await self._claim(db, user, request, ops):
            raise ExactlyOnceRefusal(request.turn_id)

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
        calls = _bind_scanned_product(_food_inputs(ops))
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

    async def _correction_route(self, db, user, ops):
        """`(entry_id, new_quantity_text)` when this turn is ONE quantity
        correction of a CANONICALLY OWNED row, else None (legacy, untouched).

        ⛔ THREE CONDITIONS, ALL EXPLICIT: the shape (exactly one
        update_food_entry naming a row and a quantity), the ownership (the
        row's `created` ledger event names a canonical writer), and the field
        (quantity only — identity/product-variant repair is B-1.8c). A row
        legacy created keeps its legacy correction path exactly as today.

        ⚠ A ROUTING FAILURE ROUTES TO LEGACY, LOUDLY — this try covers only
        the DECISION. `correct_quantity` itself runs outside it, so its
        refusals propagate.
        """
        inp = _correction_input(ops)
        if not inp or not str(inp.get("quantity") or "").strip():
            return None
        # Quantity-only: a correction that also renames the food or moves the
        # day is not this slice yet.
        if any(inp.get(k) not in (None, "") for k in
               ("food_name", "date", "meal_type", "calories", "protein",
                "carbs", "fats")):
            return None
        try:
            from core.canonical_correction import creating_source_of
            owner = await creating_source_of(db, int(inp["entry_id"]))
        except Exception:                              # noqa: BLE001
            logger.warning("correction ownership check failed; legacy",
                           exc_info=True)
            return None
        if not (owner and str(owner).startswith("canonical:")):
            return None
        logger.info("event=correction_route user=%s entry=%s owner=%s",
                    getattr(user, "id", None), inp["entry_id"], owner)
        return int(inp["entry_id"]), str(inp["quantity"])

    async def _publish_correction(self, db, user, result, request):
        """The execution view for a correction, so the user SEES it. Reuses
        the shared executor's card/snapshot machinery through the same
        ExecutionResult shape the legacy update path publishes."""
        from core.execution_result import (CallResult, ExecutionResult,
                                           LAST_EXECUTION)
        call = CallResult(
            name="update_food_entry",
            raw_input={"entry_id": result.entry_id,
                       "quantity": result.quantity_text},
            status="committed",
            result_text=(f"Updated to {result.quantity_text} "
                         f"({result.changes.get('calories', 0):.0f} kcal)"),
            entry_id=result.entry_id,
            correction={"ratio": result.ratio, "method": result.method,
                        "owner": "canonical", "changes": result.changes})
        view = ExecutionResult(calls=(call,))
        LAST_EXECUTION.set(view)
        return view

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
