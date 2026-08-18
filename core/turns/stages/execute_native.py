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
            # ⛔⛔ EXACTLY ONCE, IN ONE TRANSACTION *(B-1.8b.1, Danny)*. The
            # first cut wired `_claim` -> claim_processed_turn, which COMMITS
            # the claim before the write — the pre-commit lifecycle canonical
            # settlement deliberately abandoned, because a crash or refusal
            # between claim and write leaves a claim guarding nothing and the
            # user's retry is refused. This is the corrected shape:
            #
            #     derive key -> RESERVE claim (flushed, NOT committed)
            #     -> repair -> update row -> totals -> canonical:correction
            #     event -> COMPLETE claim -> ONE COMMIT
            #
            # `update_food_entry(claim_id=...)` already does the tail. A replay
            # of the same turn finds the completed claim and is answered from
            # it — one effective correction, one event, one completed claim.
            # A failure anywhere before that commit rolls claim + mutation +
            # event back TOGETHER, and the retry succeeds. No handler here
            # (A8); refusals propagate and the transaction unwinds with them.
            from core.canonical_correction import (correct_identity,
                                                   correct_quantity,
                                                   restore_recorded_state)
            entry_id, fields = correction
            idem = (request.turn_id, request.text or "")
            if fields.get("replay") is not None:
                # Verbatim restore of the ledger's before-state. The undo
                # plan already carries every restorable field (and explicit
                # None for fields the correction ADDED); nothing is priced.
                before = {k: v for k, v in fields["replay"].items()
                          if k not in ("entry_id", "source", "food_hint")}
                restored = await restore_recorded_state(
                    db, user=user, entry_id=entry_id, before=before,
                    idempotency=idem)
                if restored is None:
                    logger.info("event=canonical_restore_replay entry=%s",
                                entry_id)
                    raise ExactlyOnceRefusal(request.turn_id)
                from core.execution_result import CallResult, ExecutionResult
                from core.execution_result import LAST_EXECUTION
                view = ExecutionResult(calls=(CallResult(
                    name="update_food_entry",
                    raw_input={"entry_id": entry_id, **before},
                    status="committed", entry_id=entry_id,
                    result_text="Rolled it back to how it was.",
                    correction={"owner": "canonical", "restore": True,
                                "fields": sorted(restored)}),))
                LAST_EXECUTION.set(view)
                return view
            if fields.get("food_name"):
                # ⛔⛔ IDENTITY + QUANTITY IS ONE CALL, ONE TRANSACTION *(review
                # P1)*. The first cut chained correct_identity (commit) then
                # correct_quantity (commit): a crash between them left the
                # identity changed, the claim COMPLETED, and the quantity old —
                # and the retry found the completed claim and refused. The
                # quantity now rides INTO the rebind, priced once at that
                # quantity on the rebound evidence: one write, one event, one
                # claim, one commit.
                #
                # ⚠ product_evidence_id is NOT threaded here on purpose: no
                # live producer yields one for a text correction yet
                # (SelectProductVariant has no producer). The primitive accepts
                # it; the LIVE variant path is not production-complete and is
                # labelled so on the board.
                result = await correct_identity(
                    db, user=user, entry_id=entry_id,
                    new_identity=fields["food_name"],
                    new_quantity_text=fields.get("quantity"),
                    idempotency=idem)
            else:
                result = await correct_quantity(
                    db, user=user, entry_id=entry_id,
                    new_quantity_text=fields["quantity"], idempotency=idem)
            if result is None:
                # The claim says this exact turn already corrected the row.
                logger.info("event=canonical_correction_replay user=%s "
                            "entry=%s — already applied", user.id, entry_id)
                raise ExactlyOnceRefusal(request.turn_id)
            logger.info("event=canonical_correction_settled entry=%s kind=%s",
                        result.entry_id, type(result).__name__)
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
            if owner is None:
                # SCAN-BOUND, UNPRICEABLE (P17 scan/binding, CF5): canonical
                # owns the answer and the answer is a refusal. Nothing
                # written, nothing claimed — the user's retry ("2 bars") is a
                # fresh turn with the same scan.
                view = self._publish_bound_refusal(coverage, items, request)
                LAST_EXECUTION.set(view)
                return view
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
            # ⛔⛔ CF5 — A SCAN-BOUND ITEM NEVER FALLS TO LEGACY. Legacy would
            # estimate the food and the scan would be silently inert. The
            # verdict travels back so `run` answers canonically: no write, no
            # claim, and the user is told what is missing in the LABEL'S units.
            from core.general_settlement import BoundUnpriceable
            if isinstance(coverage, BoundUnpriceable):
                return None, coverage
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
        if not inp:
            return None
        # ⛔ B-1.8d — AN UNDO IS A RESTORE, NOT A REPAIR *(review #3)*. The
        # ledger_undo plan lifts to an update_food_entry op stamped
        # source=ledger_undo:*; sending THAT through the repair path would
        # re-price the restored identity instead of putting back the recorded
        # numbers. Detected here, before any kind dispatch.
        replay = str(inp.get("source") or "").startswith("ledger_undo:")
        quantity = str(inp.get("quantity") or "").strip()
        food_name = str(inp.get("food_name") or "").strip()
        # ⭐ B-1.8c — TWO REPAIR KINDS, ONE ROUTE. Quantity-only -> the ratio
        # repair (B-1.8b). Identity (with or without a quantity) -> the rebind
        # repair. Day moves and meal re-slots are not this lane yet.
        if not replay and not quantity and not food_name:
            return None
        if any(inp.get(k) not in (None, "") for k in ("date", "meal_type")):
            return None
        # ⛔⛔ THE INTERPRETER'S NUMBERS ARE IGNORED, NOT ROUTED AWAY. The
        # correction tool hands over calories/protein/... it re-estimated. A
        # canonical repair NEVER accepts them: a quantity repair derives its
        # ratio from the row, an identity repair reprices from local evidence.
        # Their presence must not send the turn to legacy — that would let the
        # very numbers we refuse land on the row through the other door.
        try:
            from core.canonical_correction import creating_source_of
            owner = await creating_source_of(db, int(inp["entry_id"]))
        except Exception:                              # noqa: BLE001
            logger.warning("correction ownership check failed; legacy",
                           exc_info=True)
            return None
        if not (owner and str(owner).startswith("canonical:")):
            return None
        logger.info("event=correction_route user=%s entry=%s owner=%s kind=%s",
                    getattr(user, "id", None), inp["entry_id"], owner,
                    "identity" if food_name else "quantity")
        return (int(inp["entry_id"]),
                {"quantity": quantity or None, "food_name": food_name or None,
                 "replay": dict(inp) if replay else None})

    async def _publish_correction(self, db, user, result, request):
        """The execution view for a correction, so the user SEES it. Reuses
        the shared executor's card/snapshot machinery through the same
        ExecutionResult shape the legacy update path publishes."""
        from core.execution_result import (CallResult, ExecutionResult,
                                           LAST_EXECUTION)
        # The receipt text IS the user's reply now (NativeRenderStage
        # narrates a canonical correction from it — canary #2). Sentence case,
        # the row's committed numbers, no internal rung words.
        kcal = int(round(float(result.changes.get("calories", 0) or 0)))
        if hasattr(result, "ratio"):
            raw = {"entry_id": result.entry_id, "quantity": result.quantity_text}
            name = await self._row_name(db, result.entry_id)
            text = (f"Updated the {name} to {result.quantity_text}, {kcal} cal."
                    if name else
                    f"Updated it to {result.quantity_text}, {kcal} cal.")
            correction = {"ratio": result.ratio, "method": result.method,
                          "owner": "canonical", "changes": result.changes}
        else:
            raw = {"entry_id": result.entry_id, "food_name": result.new_identity}
            qty = str(result.changes.get("quantity") or "").strip()
            same_food = (str(result.new_identity or "").strip().lower()
                         == str(result.old_identity or "").strip().lower())
            if same_food:
                # the interpreter echoed the name; what changed is the amount
                text = (f"Updated the {result.new_identity} to {qty}, {kcal} cal."
                        if qty else f"Updated the {result.new_identity}, {kcal} cal.")
            else:
                text = (f"Updated it to {result.new_identity}, {qty}, {kcal} cal."
                        if qty else f"Updated it to {result.new_identity}, {kcal} cal.")
            correction = {"rebound_from": result.old_identity,
                          "rung": result.rung, "evidence_id": result.evidence_id,
                          "owner": "canonical", "changes": result.changes}
        call = CallResult(
            name="update_food_entry", raw_input=raw, status="committed",
            result_text=text, entry_id=result.entry_id, correction=correction)
        view = ExecutionResult(calls=(call,))
        LAST_EXECUTION.set(view)
        return view

    def _publish_bound_refusal(self, coverage, items, request):
        """The execution view for a scan-bound refusal: ONE blocked call
        carrying user-grade copy in the label's units. Non-mutating by
        construction — nothing here touched the database."""
        from core.execution_result import CallResult, ExecutionResult
        item = (items or [{}])[0]
        food = str(item.get("food_name") or item.get("food") or "").strip()
        unit = str(getattr(coverage, "unit", "") or "").strip()
        qty = str(item.get("quantity") or "").strip()
        what = food or getattr(coverage, "label", "") or "that"
        grams = getattr(coverage, "serving_grams", None)
        # THE ASK IS IN THE LABEL'S OWN TERMS. With a unit noun: count those.
        # Without one but with a stated serving mass (the P17d probe's OFF
        # shape — "55.0g", no noun): the label's serving is a sourced
        # conversion, so "2 servings" or a gram weight prices; "2 bars" does
        # not, because nothing on the record says a bar is a serving.
        if unit:
            how = f"how many {unit}s"
        elif grams:
            how = (f"the label lists a {grams:g} g serving — how many servings, "
                   f"or how many grams")
        else:
            how = "what was the weight"
        if not qty:
            text = f"Got the scanned {what}. How much did you have — {how}?"
        else:
            text = (f"Got the scanned {what}, but I can't price {qty} of it "
                    f"from the label — {how}?")
        logger.info("event=scan_bound_refused turn=%s food=%r quantity=%r "
                    "unit=%r reason=%s", getattr(request, "turn_id", "-"),
                    food, qty, unit, getattr(coverage, "reason", ""))
        call = CallResult(
            name="log_food", raw_input=dict(item), status="blocked",
            result_text=text, entry_id=None,
            correction={"owner": "canonical", "refusal": "scan_bound_unpriceable",
                        "reason": getattr(coverage, "reason", ""),
                        "unit": unit})
        return ExecutionResult(calls=(call,))

    # ── helpers ───────────────────────────────────────────────────────────────
    async def _row_name(self, db, entry_id) -> str:
        """The committed row's food name, for the correction receipt. A read
        after the commit; failure degrades the copy, never the turn."""
        try:
            from sqlalchemy import select
            from db.models import FoodEntry
            name = (await db.execute(select(FoodEntry.parsed_food_name).where(
                FoodEntry.id == int(entry_id)))).scalar_one_or_none()
            return str(name or "").strip()
        except Exception:                              # noqa: BLE001
            return ""

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
