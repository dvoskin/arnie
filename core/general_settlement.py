"""A1–A11 — the GENERAL canonical settlement owner for ordinary food turns.

The ordinary chat food turn is the last lane that still settles through
`handlers.tool_executor`. B-1 (`_AnswerOperation`) and quick_log
(`DirectOperation`) already own their writes canonically; this is their
equivalent for the turn nobody clarified and nobody quick-logged.

    ResolvedMeal -> commit_or_load_existing -> write_canonical_meal

⛔⛔ THIS MODULE MAY NOT IMPORT `handlers.tool_executor` (A2). Not the executor,
not `_analyze_food`, not its enrichment. The canonical spine rented exactly ONE
thing from legacy — `_analyze_food` — and every canonical defect measured in
production was on its far side: 8,171 ms of an 8,225 ms tap, and entry 2932
committed at 0.0 kcal. `assemble()` + `price()` replace it, and `price()` is
SYNCHRONOUS, which is the structural statement that no provider or model call
can occur on this path. The rule is gated by an AST assertion, not by reading.

⛔ AND CANONICAL IDEMPOTENCY REPLACES LEGACY DEDUP HERE. The old executor must
not survive as a hidden second settlement owner: one turn, one claim, one
writer. `commit_or_load_existing` is that claim.

⭐ THE PREDICATE IS DESCRIPTIVE, NOT ASPIRATIONAL *(Danny, 2026-08-16)*. A11
answers "can the current canonical system safely settle this meal?" — never
"should we eventually support this meal?". That distinction is what stops
coverage pressure from turning `Unsupported` into speculative settlement: the
honest answer for a food with no evidence is to leave it on the legacy path,
where retrieval still happens, rather than to commit an estimate and call it
adoption.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional, Union

logger = logging.getLogger(__name__)

#: The rungs whose evidence already exists locally at routing time. ESTIMATE is
#: deliberately absent: `assemble()` retrieves NOTHING, so a food in neither
#: artifact nor memory is WORSE off canonically than on the legacy path, which
#: would have found a live USDA row. That is the measured coverage cliff
#: (§3a.2), and the predicate exists to route around it rather than to hide it.
LOCALLY_EVIDENCED = ("memory", "artifact")


class ExecutionViewMismatch(RuntimeError):
    """The meal SETTLED, but its written rows cannot be mapped back to the
    items that produced them — so the turn must fail BEFORE durability.

    ⛔⛔ AND "SETTLED" IS NOT "COMMITTED". An earlier draft of this docstring
    said the meal was already committed and that retry safety came from the
    durable idempotency claim. **Neither is true on this path.**
    `commit_or_load_existing` states it plainly — *"Nothing here commits or
    rolls it back"* — and the coordinator adds that after the writer flushes,
    *"the rows are flushed, not durable"*. The CALLER owns the transaction, and
    `execution_view` runs inside it.

    ⭐ WHICH MAKES THE INVARIANT STRONGER, NOT WEAKER. The mapping is still part
    of the MUTATION transaction, so a view that cannot be built safely takes
    the meal, the claim and the result down with it: the exception escapes
    before any commit and everything rolls back together. There is no durable
    half-state to reconcile — which is exactly why raising beats returning an
    empty view that would report "nothing was written" while the rows sat
    flushed in an open transaction.

    ⚠ AND THE SCOPE IS *THIS TURN'S* WRITE. On the REPLAY path
    `commit_or_load_existing` returns a result loaded from storage, describing
    a meal that committed in an EARLIER transaction and is durable. Rolling
    this turn back does not and must not undo that one. What rolls back is
    whatever this transaction staged; what an earlier turn made durable stays.
    """


class SettlementIdempotencyConflict(RuntimeError):
    """This operation id already settled DIFFERENT content.

    Separate from `ExecutionViewMismatch` because the remedy is different: a
    mismatch means "cannot map, fail this turn", while this means "the id you
    claimed is already spoken for by another meal". Same count, different
    food — the case a length check waves through and a positional pairing then
    attributes confidently.
    """


# ══ A11 — THE COVERAGE PREDICATE ════════════════════════════════════════════
#
# Split the way `assemble`/`price` is split, and for the same reason: `look()`
# performs local READS, `decide()` is PURE and SYNCHRONOUS. A predicate that
# could reach a provider would be a second settlement path wearing a routing
# costume, and its latency would land on every turn it declined.


@dataclass(frozen=True)
class Supported:
    """This meal can be settled canonically, and here is the rung expected to
    decide it. `expected_source` is a PREDICTION — A6 records what actually
    decided, and the two are compared rather than reconciled."""
    expected_source: str
    reason: str = ""


@dataclass(frozen=True)
class Unsupported:
    """Route to the untouched legacy path. The reason is telemetry from day
    one — a predicate that declines silently cannot have its miss rate
    measured, and the miss rate is the whole risk of this slice."""
    reason: str


Coverage = Union[Supported, Unsupported]


@dataclass(frozen=True)
class ItemFacts:
    """Everything `decide()` is allowed to know, gathered once."""
    identity: str
    entity: str
    preparation: str
    has_identity: bool
    has_quantity: bool
    has_memory: bool
    has_artifact: bool


async def look(db, *, user_id: int, item: dict) -> ItemFacts:
    """The routing facts for one item. LOCAL READS ONLY.

    Permitted (§3a.2 decision D): canonical identity eligibility, local
    artifact availability, eligible memory availability, quantity/identity
    completeness. Forbidden: `assemble()`, USDA, web retrieval, the resolver,
    pricing, writing state, claiming idempotency.

    ⚠ ASKING WHETHER EVIDENCE EXISTS IS NOT PRICING IT. `_memory` and
    `evidence_for` are the same reads `assemble` would perform, called here for
    their EXISTENCE and not for their numbers — nothing below returns a macro.
    """
    from core.canonical_pricing_inputs import _memory
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    identity = str(item.get("food_name") or item.get("food") or "").strip()
    entity, preparation = split_identity(identity)
    entity_id = str(item.get("canonical_entity_id") or "")

    memory = None
    if identity:
        try:
            memory = await _memory(db, user_id, identity, entity_id)
        except Exception:                              # noqa: BLE001
            # An unavailable read is NOT an absence of evidence. Routing on a
            # failed lookup would silently move a covered food to the legacy
            # path and report it as a coverage miss — the instrument lying by
            # silence again. Left as None, which declines, and logged.
            logger.warning("coverage: memory lookup failed for user=%s",
                           user_id, exc_info=True)

    return ItemFacts(
        identity=identity, entity=entity, preparation=preparation,
        has_identity=bool(entity),
        has_quantity=bool(str(item.get("quantity") or "").strip()),
        has_memory=memory is not None,
        has_artifact=(bool(entity)
                      and evidence_for(entity, preparation) is not None),
    )


def decide(facts: ItemFacts) -> Coverage:
    """PURE. SYNCHRONOUS. NO DATABASE, NO CLOCK, NO NETWORK.

    ⭐ AND IT DESCRIBES THE SYSTEM AS IT IS. Each branch answers "can canonical
    settle this safely TODAY", so widening coverage means landing evidence, not
    loosening this function. If a later reader is tempted to return `Supported`
    for a food with no local evidence, the thing to change is the artifact.
    """
    if not facts.has_identity:
        return Unsupported("no canonical identity")
    if not facts.has_quantity:
        return Unsupported("no stated quantity")
    if facts.has_memory:
        return Supported("memory", "this user has priced this food before")
    if facts.has_artifact:
        return Supported("artifact", "the committed artifact covers it")
    # ⛔ THE CLIFF, NAMED. Canonical would price this from the interpreter's own
    # estimate while legacy would have retrieved a row. Declining is the honest
    # answer and the miss is the number A10 owes.
    return Unsupported("no local evidence — estimate would be worse than legacy")


async def coverage_for(db, *, user_id: int, items) -> Coverage:
    """THE MEAL, NOT THE ITEM. One unsupported item declines the whole meal.

    ⛔ PARTIAL OWNERSHIP IS DUAL AUTHORITY. Settling two items canonically and
    handing the third to legacy would put one meal under two settlement owners,
    write it in two transactions, and leave the exactly-once claim describing
    half of it. That is the shape this migration exists to delete.
    """
    if not items:
        return Unsupported("no items")
    expected = []
    for item in items:
        verdict = decide(await look(db, user_id=user_id, item=item))
        if isinstance(verdict, Unsupported):
            return verdict
        expected.append(verdict.expected_source)
    return Supported("+".join(sorted(set(expected))),
                     f"{len(items)} item(s), all locally evidenced")


# ══ THE COHORT ══════════════════════════════════════════════════════════════


def settlement_cohort(user_id=None) -> bool:
    """May THIS user's ordinary food turn be settled canonically?

    ⛔⛔ FAIL CLOSED, for the same reason `_consume_allowlist` does and one
    more: this flag changes WHICH CODE OWNS THE WRITE. An operator who enables
    the lane and forgets the cohort would move every user's food onto a
    settlement path that has never carried their traffic. Unset means NOBODY,
    and a turn with no user id means nobody either.

    ⭐ AND IT IS ITS OWN DIAL. `TURN_COORDINATOR_ALLOWLIST` decides which
    execution PATH runs; this decides who is settled canonically. Neither
    rollout may implicitly widen the other — the lesson `identity_is_consumable`
    was written to encode.
    """
    raw = os.getenv("GENERAL_SETTLEMENT_ALLOWLIST", "") or ""
    allowed = frozenset(int(part) for part in raw.replace(",", " ").split()
                        if part.strip().isdigit())
    if not allowed or user_id is None:
        return False
    try:
        return int(user_id) in allowed
    except (TypeError, ValueError):
        return False


# ══ A1 — THE OWNER ══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class GeneralTurnOperation:
    """One ordinary food turn, as an operation the commit coordinator claims.

    The id IS the turn id, so a resend replays rather than double-writes —
    canonical idempotency replacing legacy dedup (A2), not layered over it.
    """
    operation_id: str
    user_id: int
    revision: int = 0

    @property
    def id(self) -> str:
        return self.operation_id


class GeneralSettlementOwner:
    """Prices and commits an ordinary food turn. The ONLY settlement path the
    native stage invokes for structured_food under the lane flag (A1)."""

    async def settle(self, db, *, user, items, source_turn_id: str,
                     coverage: Optional[Supported] = None):
        """ResolvedMeal -> commit_or_load_existing -> write_canonical_meal.

        ⛔ `PricingRefused` PROPAGATES (A8). It is raised BEFORE any write, so a
        refusal is non-mutating by construction rather than by a handler
        remembering to be careful: no food row, no ledger event. Catching it to
        substitute a number is the failure being deleted; catching it to fall
        back to legacy is the dual-authority failure being prevented.
        """
        from core.canonical_writer import (MealIntent, ResolvedFood,
                                           ResolvedMeal, operation_id_for,
                                           write_canonical_meal)
        from core.commit_coordinator import commit_or_load_existing
        from core.semantics import (CanonicalEvent, Confidence,
                                    NutritionProvenance, ResolutionStatus)

        resolved = [await self._price(db, user=user, item=item)
                    for item in items]

        # ⛔⛔ USER-SCOPED, AND THE REPOSITORY ALREADY SAID SO. This was
        # `f"turn:{source_turn_id}"`, and `operation_id_for`'s docstring
        # describes that exact bug verbatim: `make_turn_id` returns
        # `f"{channel}:{cid}"` when the client supplies an Idempotency-Key,
        # with NO user in it — "so two users sending the same key would share
        # an operation, and the second would be handed the first's committed
        # result". `meal_commits` is unique on (operation_id, revision) and
        # deliberately excludes user_id, and `_load` looks up by id alone, so
        # THE ID ITSELF HAS TO CARRY THE SCOPE.
        #
        # The content guard does not save this: two users logging the same food
        # at the same portion agree on name and quantity, so B silently
        # receives A's stored result — A's entry_id, A's macros — and writes no
        # row of its own.
        meal = ResolvedMeal(
            operation_id=operation_id_for("general", int(user.id),
                                          source_turn_id),
            revision=0,
            user_id=int(user.id),
            logging_day=_logging_day(user),
            user_timezone=_zone(user),
            intent=MealIntent.CREATE, source_turn_id=source_turn_id,
            meal_type=_first(items, "meal_type"),
            items=tuple(
                ResolvedFood(
                    event=CanonicalEvent(
                        id=f"{source_turn_id}:{index}", domain="food",
                        entity_id=priced.entity_id,
                        surface_text=priced.identity,
                        quantity=priced.quantity,
                        resolution_status=ResolutionStatus.RESOLVED,
                        # The user TYPED the food and its portion; the resolver
                        # priced it. Two axes, deliberately not collapsed.
                        provenance=priced.provenance,
                        confidence=Confidence(score=1.0,
                                              basis=priced.provenance.value)),
                    calories=float(priced.analysis.calories or 0.0),
                    protein=priced.analysis.protein,
                    carbs=priced.analysis.carbs, fats=priced.analysis.fats,
                    fiber=priced.analysis.fiber, sugar=priced.analysis.sugar,
                    sodium=priced.analysis.sodium,
                    quantity_text=priced.quantity_text,
                    meal_type=priced.meal_type,
                    source_type="structured_food",
                    estimated=bool(priced.analysis.estimated),
                    micros=getattr(priced.analysis, "micros", None),
                    micros_estimated=bool(
                        getattr(priced.analysis, "micros_estimated", False)),
                    nutrition_provenance=NutritionProvenance.SERVER_RESOLVED,
                    raw_input=priced.identity,
                    # ⭐ A6 — PROVENANCE NAMES THE RUNG THAT ACTUALLY DECIDED.
                    # Whichever rung that is. Persisted with the result so it
                    # is readable from the DB, never scraped from reply text,
                    # and never a claim that the artifact decided when memory
                    # did.
                    # ⛔ `PricedFood` HAS NO `confidence` FIELD, and the first
                    # version of this dict recorded `getattr(..., 0.0)` — which
                    # persisted **confidence: 0.0** on every canonical row. A
                    # default standing in for an absent value is the exact
                    # failure `_CONF_NUM` was written to end: "no confidence
                    # was recorded" and "confidence is zero" are different
                    # facts, and only one of them is true here. Omitted.
                    #
                    # `basis` is recorded instead because it EXISTS: it says
                    # what the numbers were scaled from, which is what a later
                    # correction has to correct against.
                    attributes={"pricing": {
                        "rung": priced.analysis.rung.value,
                        "evidence_id": priced.analysis.evidence_id or "",
                        "basis": getattr(priced.analysis, "basis", "") or "",
                        "expected_source": (coverage.expected_source
                                            if coverage else ""),
                    }})
                for index, priced in enumerate(resolved)),
        )

        result = await commit_or_load_existing(
            db, operation=GeneralTurnOperation(
                operation_id=meal.operation_id, user_id=int(user.id)),
            resolved_meal=meal, writer=write_canonical_meal)
        logger.info(
            "event=general_settled turn=%s user=%s items=%d rungs=%s "
            "expected=%s", source_turn_id, user.id, len(resolved),
            ",".join(p.analysis.rung.value for p in resolved),
            coverage.expected_source if coverage else "-")
        return result

    async def _price(self, db, *, user, item: dict):
        """assemble() then price(). Nothing between them retrieves."""
        from core.canonical_pricing import price
        from core.canonical_pricing_inputs import assemble
        from skills.nutrition.canonical_adapter import to_canonical
        from skills.nutrition.normalize import normalize_quantity
        from skills.nutrition.pricing_artifact import split_identity

        identity = str(item.get("food_name") or item.get("food") or "").strip()
        entity, preparation = split_identity(identity)
        quantity_text = str(item.get("quantity") or "").strip()
        consumed = normalize_quantity(quantity_text, identity)

        inputs = await assemble(
            db, user_id=int(user.id), entity=entity, preparation=preparation,
            identity=identity, item=item,
            basis_grams=getattr(consumed, "grams", None))
        analysis = price(entity=identity, preparation=preparation,
                         consumed=consumed, **inputs)
        return _Priced(
            identity=identity, entity_id=str(
                item.get("canonical_entity_id") or item.get("entity_id") or ""),
            quantity=to_canonical(consumed), quantity_text=quantity_text,
            meal_type=item.get("meal_type") or None, analysis=analysis,
            provenance=_provenance())


def execution_view(result, items) -> object:
    """The committed meal, in the shape EVERY RENDERER ALREADY READS.

    ⛔⛔ WITHOUT THIS THE USER GETS NO CARD, AND THE ROW IS STILL CORRECT.
    Measured 2026-08-16 on a real turn: legacy rendered 1 card, canonical
    rendered ZERO. `LAST_EXECUTION` is published only by `execute_tool_calls`,
    so after a canonical settle `affected_entities(None)` is empty, the
    snapshot has no committed operations, and `render_committed` has nothing to
    narrate. The write succeeded and the turn looked like it did nothing.

    ⭐ TRANSLATED, NOT FORKED. The renderer is not taught about canonical
    settlement; the canonical result is expressed in the type the renderer
    already consumes. Presentation rides behind the slice — it is never the
    next phase, and it is never a second renderer.

    ⚠ AND THE PAIRING IS BY POSITION, WHICH IS ONLY SOUND BECAUSE IT IS BUILT
    THAT WAY: `_read_back` walks `written`, which follows `meal.items`, which
    this module builds by `enumerate(items)`. Stated and CHECKED rather than
    assumed — a length mismatch means the chain changed underneath and is
    logged loudly instead of silently mis-pairing a food with another's row.
    """
    from core.execution_result import CallResult, ExecutionResult

    committed = list(getattr(result, "committed_items", None) or ())
    if len(committed) != len(items):
        # ⛔⛔ RAISE. UNKNOWN IS NOT ZERO.
        #
        # This has now been wrong TWICE, in opposite directions:
        #
        #   v1  logged "positional pairing is unsafe" and then paired anyway,
        #       so [A,B,C] against [A,C] could produce B -> C's entry_id.
        #   v2  returned `ExecutionResult(calls=())` and called it "an empty
        #       view narrates nothing, which is recoverable". It is not
        #       recoverable and it does not narrate nothing: `affected_entities`
        #       derives changes from COMMITTED CALLS ONLY, so an empty view
        #       reports no affected entities, the renderer finds no committed
        #       operations and returns None, and the entrypoint finalises an
        #       empty response — the turn reports that NOTHING WAS WRITTEN over
        #       a meal that is already durable in the database.
        #
        # That is the standing rule broken exactly: AN ABSENT ANSWER MUST NEVER
        # BE REPRESENTABLE AS A NEGATIVE ANSWER. `ExecutionResult` has no
        # "unknown" state to return, so the honest signal is a typed raise the
        # caller cannot mistake for "nothing committed".
        #
        # ⚠ THE ROWS ARE FLUSHED, NOT DURABLE, WHEN THIS FIRES — the caller
        # owns the transaction and `commit_or_load_existing` never commits it.
        # So this raise happens INSIDE the mutation transaction, and the meal,
        # the exactly-once claim and the persisted result all roll back
        # together. Failing before durability is the strong outcome; an empty
        # view would have reported "nothing was written" while the rows sat
        # flushed in an open transaction, which is the worst of both.
        logger.error(
            "event=execution_view_mismatch items=%d written=%d — the meal is "
            "SETTLED BUT NOT DURABLE; failing before commit so it rolls back",
            len(items), len(committed))
        raise ExecutionViewMismatch(
            f"{len(items)} items settled into {len(committed)} written rows; "
            f"the execution view cannot be built, so this turn must fail "
            f"before the transaction commits")
    # ⛔⛔ LENGTH IS NOT IDENTITY, AND THE REPLAY PATH IS WHY.
    #
    # `commit_or_load_existing` returns a STORED result when the claim is a
    # duplicate — a result from a PREVIOUS, already durable transaction — and
    # the caller cannot tell a winner from a replay. Meanwhile `make_turn_id`
    # prefers the CLIENT MESSAGE ID over the text, so the same client id sent
    # with different content produces the same turn_id, and
    # `GeneralTurnOperation` claims `turn:{id}` again.
    #
    #     first   ios:X = mackerel      -> durable, one row
    #     later   ios:X = asparagus     -> replay returns mackerel's row
    #                                      1 == 1, so a length check passes
    #                                      and asparagus takes mackerel's
    #                                      entry_id and macros
    #
    # That is confident wrong attribution rebuilt through the one door the
    # positional guard does not watch. So the COMMAND is checked against what
    # was actually written, and a disagreement is its own typed failure —
    # never a view.
    for index, item in enumerate(items):
        row = committed[index] or {}
        want_name = str(item.get("food_name") or item.get("food") or "").strip()
        got_name = str(row.get("name") or "").strip()
        want_qty = str(item.get("quantity") or "").strip()
        got_qty = str(row.get("quantity") or "").strip()
        # ⚠ CANONICAL IDENTITY TOO, NOT ONLY THE VISIBLE TEXT. Name and
        # quantity are free-text and are the WRONG long-term authority: a
        # genuine retry can arrive as equivalent text formatted differently,
        # and a changed canonical identity could in principle keep the same
        # visible name. `entity_id` is the settlement-defining half that the
        # renderer's two strings cannot see.
        #
        # ⛔ AND THE REAL FIX IS UPSTREAM, STATED SO IT IS NOT FORGOTTEN: bind
        # the CLAIM to a fingerprint of the normalized settlement input and
        # compare it AT THE CLAIM BOUNDARY, so a result is known to belong to
        # this command before anything downstream sees it. This check is a net
        # under that, not a substitute for it — a presentation adapter should
        # not be the idempotency authority.
        want_entity = str(item.get("canonical_entity_id")
                          or item.get("entity_id") or "").strip()
        got_entity = str(row.get("entity_id") or "").strip()
        if (want_name.casefold() != got_name.casefold()
                or want_qty.casefold() != got_qty.casefold()
                or (want_entity and got_entity
                    and want_entity.casefold() != got_entity.casefold())):
            logger.error(
                "event=settlement_idempotency_conflict index=%d command=%r/%r "
                "written=%r/%r — this operation id already settled DIFFERENT "
                "content", index, want_name, want_qty, got_name, got_qty)
            raise SettlementIdempotencyConflict(
                f"item {index} is {want_name!r} ({want_qty}) but the operation "
                f"already settled {got_name!r} ({got_qty}); the same operation "
                f"id was reused for different content")

    calls = []
    for index, item in enumerate(items):
        row = committed[index] or {}
        calls.append(CallResult(
            name="log_food", raw_input=dict(item), status="committed",
            entry_id=row.get("entry_id"),
            # ⭐ THE COMMITTED OUTCOME, CARRIED SEPARATELY FROM THE COMMAND.
            # `raw_input` is the command as executed and stays untouched —
            # mutating it to hold outcome numbers is the command/outcome
            # collapse this migration exists to undo. `receipt` is the field
            # that already means "what actually happened".
            receipt={"calories": float(row.get("calories") or 0.0),
                     "protein": float(row.get("protein") or 0.0),
                     "entry_id": row.get("entry_id")},
            # ⚠ NO event_id. `write_canonical_meal` records the ledger event
            # but does not return its id, so `ledger_event_ids` is empty for a
            # canonically settled turn and an UNDO TOKEN cannot be surfaced
            # from it. Named here rather than left as a surprise: it is a
            # separate gap, and it belongs with B-1.8's correction work.
            event_id=None))
    # ⭐ THE TOTALS TRAVEL WHOLE, from the writer that read them back off the
    # committed rows. Nothing here adds anything up (C3).
    return ExecutionResult(
        calls=tuple(calls),
        meal_totals=dict(getattr(result, "meal_totals", None) or {}) or None)


@dataclass(frozen=True)
class _Priced:
    identity: str
    entity_id: str
    quantity: object
    quantity_text: str
    meal_type: Optional[str]
    analysis: object
    provenance: object


def _provenance():
    from core.semantics import Provenance

    return Provenance.USER_STATED


def _zone(user) -> str:
    from core.timezones import safe_timezone

    return str(getattr(safe_timezone(getattr(user, "timezone", None)), "zone",
                       "UTC"))


def _logging_day(user):
    """The USER'S LOGGING day — `db.queries._user_today`, the same function B-1
    settles through.

    ⛔⛔ NOT `datetime.now(tz).date()`, WHICH THIS FUNCTION ORIGINALLY WAS. The
    logging day rolls over at `LOGGING_DAY_ROLLOVER_HOUR=4`, not at midnight,
    so between 00:00 and 04:00 a calendar date files the meal onto TOMORROW —
    a day the user will not think to look at, for the meal they are most likely
    to be logging late. `ResolvedMeal` refuses to default this precisely so a
    second definition cannot appear here, and one nearly did.
    """
    from db.queries import _user_today

    return _user_today(getattr(user, "timezone", None) or "UTC")


def _first(items, key):
    for item in items:
        value = item.get(key)
        if value:
            return value
    return None
