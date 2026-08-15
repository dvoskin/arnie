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
                                           ResolvedMeal, write_canonical_meal)
        from core.commit_coordinator import commit_or_load_existing
        from core.semantics import (CanonicalEvent, Confidence,
                                    NutritionProvenance, ResolutionStatus)

        resolved = [await self._price(db, user=user, item=item)
                    for item in items]

        meal = ResolvedMeal(
            operation_id=f"turn:{source_turn_id}", revision=0,
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
                    attributes={"pricing": {
                        "rung": priced.analysis.rung.value,
                        "evidence_id": priced.analysis.evidence_id or "",
                        "confidence": float(
                            getattr(priced.analysis, "confidence", 0.0) or 0.0),
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
