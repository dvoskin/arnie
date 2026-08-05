"""B-1's operation lifecycle: open ownership, hold it, settle it canonically.

Three calls, and between them the meal belongs to the canonical path:

    open()      the ask turn takes ownership — ONCE, after the rollout gate
    owning()    the answer turn asks "does a canonical operation own this?"
    settle()    the answer applies, the food is priced, ONE canonical commit

WHY `owning()` DOES NOT CONSULT THE ROLLOUT GATE
------------------------------------------------
It answers a question about STORED STATE, not about configuration: a row
exists, therefore this meal is ours. Re-asking the gate here is the mid-flight
fallback the directive forbids, and every way of acting on a newly-False gate
loses the meal — the answer becomes a second meal, or the pending row is
dropped, or the user answers twice. Narrowing the cohort stops new operations
and strands nothing.

WHY PRICING GOES THROUGH `_analyze_food`
-----------------------------------------
"No legacy writer is reached" is a claim about WRITES. `_analyze_food` is the
enrichment half of the legacy path — it decides what a food costs and returns
a `FoodAnalysis`; it writes nothing. Reusing it means B-1 prices food exactly
as production does today, so a divergence in the numbers can only come from
the quantity the user just gave us, which is the one thing B-1 changed.
Writing our own pricing would make every parity comparison meaningless.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

DOMAIN = "food"

#: The pending payload's B-1 section. Versioned separately from the operation
#: payload because it is a different contract with a different owner.
B1_PAYLOAD_VERSION = 1

#: Operation statuses. `awaiting_answer` is the only one `owning()` claims.
AWAITING = "awaiting_answer"
COMMITTED = "committed"
CANCELLED = "cancelled"


@dataclass(frozen=True)
class OwnedOperation:
    """A canonical operation that owns a meal — in flight, or already settled.

    Settled ones are returned too, deliberately. "The user taps the chip again
    after it committed" is a real delivery, and an owner that forgot the meal
    the moment it wrote it would hand that tap to the interpreter, which is
    where a duplicate meal comes from. Ownership ends when the operation is
    terminal AND stale, not the instant it commits.
    """
    row: Any
    interaction: Any
    #: The interpreter's own reading of the food, carried across the turn
    #: boundary so the answer turn PRICES rather than re-interprets. Losing it
    #: is how a clarified meal came back as a different food thirteen hours
    #: later.
    item: dict
    #: The language the QUESTION was asked in. Read back rather than
    #: re-detected, so a later answer cannot be judged by a different lexicon
    #: than the one that produced the chips.
    locale: str = "en"

    @property
    def operation_id(self) -> str:
        return self.row.operation_id

    @property
    def revision(self) -> int:
        return int(self.row.revision or 0)

    @property
    def status(self) -> str:
        return str(self.row.status or "")

    @property
    def awaiting(self) -> bool:
        return self.status == AWAITING

    @property
    def readable(self) -> bool:
        """False when the stored payload could not be decoded. The operation
        still OWNS the meal — the turn repairs, it does not fall back."""
        return self.interaction is not None


class _AnswerOperation:
    """The operation identity a settling commit claims.

    The row carries the revision it is AT; the commit belongs to the revision
    the answer PRODUCES, and the claim is `(operation_id, revision)`. Passing
    the row unchanged would claim the pre-answer revision, so a second, later
    answer to the same operation would collide with the first instead of
    forming its own claim.
    """

    def __init__(self, row, revision: int):
        self.id = row.operation_id
        self.revision = int(revision)
        self.user_id = int(row.user_id)
        self.source_turn_id = row.source_turn_id or ""


def _encode(interaction, interpreter_item: dict, locale: str) -> str:
    if not isinstance(interpreter_item, dict):
        # NAMED, not coerced. `build_interaction` takes the STAGED item and
        # this takes the INTERPRETER's dict; they are different objects about
        # the same food, and a silent str() here would store a repr that the
        # answer turn could not price from.
        raise TypeError(
            f"the pending payload carries the interpreter's item dict, got "
            f"{type(interpreter_item).__name__} — the staged item goes to "
            f"build_interaction, not here")
    return json.dumps({
        "schema_version": B1_PAYLOAD_VERSION,
        "slice": "b1_quantity",
        "interaction": interaction.to_payload(),
        "item": interpreter_item,
        # THE LANGUAGE THE QUESTION WAS ASKED IN, pinned to the operation.
        # The answer arrives on a later turn, possibly a later day, and must
        # be read under the same language context — re-detecting it from a
        # two-word reply ("6 oz") is a guess with a destructive command
        # behind it.
        "locale": locale,
    })


async def open_operation(db, *, user, interpreter_item: dict, interaction,
                         turn_id: str, cohort: str = "",
                         locale: str = "en") -> str:
    """Take ownership of this meal. Call ONLY after the rollout gate said yes.

    `interpreter_item` is the interpreter's own reading — the food name and
    its per-portion macros — stored so the ANSWER turn prices instead of
    re-interpreting. That re-interpretation is the 16-second cheesecake
    re-priced a turn later, and the sopressata that came back as "Dollar pizza
    slices" thirteen hours on.

    `locale` is RESOLVED BY THE CALLER, not read from `user` here. Reaching
    for `user.preferences` inside this module triggers a lazy relationship
    load in a sync context (MissingGreenlet), and more importantly it makes
    this module a second place that decides what language a user writes in.
    `core.language.command_locale` owns that; the turn that already holds the
    loaded preferences calls it and passes the answer.

    Persisted before the reply is sent, because ownership that exists only in
    the reply is ownership a restart loses — and the user would then answer a
    question no row remembers.
    """
    from core import pending_repository as repo
    from core.canonical_writer import operation_id_for

    operation_id = operation_id_for("chat_quantity", user.id, turn_id)
    await repo.create_operation(
        db, operation_id=operation_id, user_id=user.id, status=AWAITING,
        storage_status="active", domain=DOMAIN, source_turn_id=turn_id,
        payload=_encode(interaction, interpreter_item, locale or "en"))
    logger.info(
        "event=b1_interaction_shown operation=%s user=%s cohort=%s "
        "options=%d sources=%s", operation_id, user.id, cohort,
        len(interaction.groups[0].fields[0].options),
        ",".join(sorted({(o.source.value if o.source else "none")
                         for o in interaction.groups[0].fields[0].options})))
    return operation_id


#: How long a settled operation still answers for its meal. A tap that arrives
#: after the commit inside this window is a REPLAY; outside it, the user is
#: plausibly talking about a new meal. Generous, because the failure it
#: prevents (a duplicate meal) is worse than the one it causes (a replay
#: answer to a genuinely new, identical meal, which idempotency also absorbs).
SETTLED_OWNERSHIP_MINUTES = 30


async def owning(db, user) -> Optional[OwnedOperation]:
    """The canonical operation that owns this user's meal, if any.

    A ROW, NOT A FLAG — and the rollout gate is deliberately not consulted
    here. This answers a question about stored state: an operation exists,
    therefore this meal is ours. Re-asking the gate would be the mid-flight
    fallback the directive forbids.

    Fails CLOSED in the opposite direction from the rest of this module: a
    payload that cannot be decoded still comes back, with `readable=False`,
    because pretending nothing is pending is how a held meal disappears.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from core.clock import now as _now
    from db.models import PendingOperation

    try:
        cutoff = _now() - timedelta(minutes=SETTLED_OWNERSHIP_MINUTES)
        rows = (await db.execute(
            select(PendingOperation)
            .where(PendingOperation.user_id == user.id,
                   PendingOperation.domain == DOMAIN)
            .order_by(PendingOperation.id.desc()).limit(5))).scalars().all()
    except Exception:
        logger.warning("b1 pending lookup failed", exc_info=True)
        return None

    for row in rows:
        status = str(row.status or "")
        if status not in (AWAITING, COMMITTED):
            continue
        if status == COMMITTED:
            updated = row.updated_at or row.created_at
            if updated is not None and updated < cutoff:
                continue          # stale; this is a new meal, not a replay
        try:
            data = json.loads(row.canonical_payload or "{}")
        except Exception:
            data = {}
        if data.get("slice") != "b1_quantity":
            continue
        try:
            from core.semantics import ClarificationInteraction
            interaction = ClarificationInteraction.from_payload(
                data.get("interaction") or {})
        except Exception:
            logger.error(
                "event=b1_payload_unreadable operation=%s — the operation "
                "still owns this meal; the turn repairs rather than falling "
                "back", row.operation_id, exc_info=True)
            return OwnedOperation(row=row, interaction=None, item={},
                                  locale=str(data.get("locale") or "en"))
        return OwnedOperation(row=row, interaction=interaction,
                              item=dict(data.get("item") or {}),
                              locale=str(data.get("locale") or "en"))
    return None


async def settle(db, *, user, owned: OwnedOperation, patch,
                 source_turn_id: str, cohort: str = "") -> Any:
    """Apply the answer, price the food, and commit it ONCE, canonically.

    Everything below happens inside the caller's transaction. `settle` neither
    commits nor rolls back the session — the coordinator's contract, and the
    reason a failure here leaves no partial meal.
    """
    from core.canonical_writer import MealIntent, ResolvedFood, ResolvedMeal
    from core.commit_coordinator import commit_or_load_existing
    from core.semantics import (CanonicalEvent, Confidence,
                                NutritionProvenance, ResolutionStatus)
    from core.timezones import safe_timezone
    from db.queries import _user_today
    from handlers.tool_executor import _analyze_food

    # ALREADY SETTLED — replay, never re-settle.
    #
    # The chip stays on screen after the meal lands, so a second tap is a real
    # delivery. It cannot be answered by re-running this function: `settle`
    # advances the operation's revision, so the second pass would compute a
    # DIFFERENT (operation_id, revision) pair, form its own claim, and write a
    # second meal. The coordinator's idempotency cannot see that — the two
    # claims are genuinely distinct — so the guard belongs here, where the
    # operation's terminal status is known.
    if owned.status == COMMITTED:
        stored = await replay(db, owned)
        if stored is not None:
            logger.info(
                "event=b1_replayed operation=%s user=%s — the chip was tapped "
                "again after the meal landed", owned.operation_id, user.id)
            return stored
        raise RuntimeError(
            f"{owned.operation_id} is committed but has no stored result — "
            f"replaying blind would write the meal twice")

    quantity_text = _quantity_text(patch)
    item = dict(owned.item or {})
    food_name = str(item.get("food") or item.get("name") or "").strip()
    inp = {**item, "quantity": quantity_text}

    # THE SAME PRICING PRODUCTION USES. Writes nothing; decides what it costs.
    analysis = await _analyze_food(db, user, food_name, inp)

    zone = str(getattr(safe_timezone(user.timezone), "zone", "UTC"))
    revision = owned.revision + 1
    operation_id = owned.operation_id
    provenance = patch.provenance

    meal = ResolvedMeal(
        operation_id=operation_id, revision=revision, user_id=user.id,
        logging_day=_user_today(user.timezone or "UTC"), user_timezone=zone,
        intent=MealIntent.CREATE, source_turn_id=source_turn_id,
        meal_type=item.get("meal_type") or None,
        assumptions=tuple(getattr(analysis, "assumptions", ()) or ()),
        items=(ResolvedFood(
            event=CanonicalEvent(
                id=patch.event_id, domain=DOMAIN,
                entity_id=str(item.get("entity_id") or ""),
                surface_text=food_name,
                quantity=patch.quantity,
                resolution_status=ResolutionStatus.RESOLVED,
                # WHO CHOSE THE NUMBER: a tap is USER_SELECTED, typing it is
                # USER_STATED. Collapsing them is the measured 2026-08-04
                # disclosure defect, and this is the last place the
                # distinction can be recorded.
                provenance=provenance,
                confidence=Confidence(score=1.0, basis=provenance.value)),
            calories=float(analysis.calories or 0.0),
            protein=analysis.protein, carbs=analysis.carbs,
            fats=analysis.fat, fiber=analysis.fiber, sugar=analysis.sugar,
            sodium=analysis.sodium,
            quantity_text=quantity_text,
            meal_type=item.get("meal_type") or None,
            source_type="structured_food",
            estimated=_is_estimated(analysis),
            micros=getattr(analysis, "micros", None),
            micros_estimated=bool(getattr(analysis, "micros_estimated", False)),
            # The RESOLVER priced it; the user chose the portion. Two axes,
            # deliberately not collapsed (B-0b).
            nutrition_provenance=NutritionProvenance.SERVER_RESOLVED,
            raw_input=food_name),))

    # THE REAL PENDING OPERATION, at the revision the answer produces. The
    # claim is `(operation_id, revision)`, so a duplicate delivery of the same
    # answer computes the same pair and is answered from storage rather than
    # written again.
    result = await commit_or_load_existing(
        db, operation=_AnswerOperation(owned.row, revision),
        resolved_meal=meal, writer=_writer)

    from core import pending_repository as repo
    outcome = await repo.save_revision(
        db, operation_id=operation_id, expected_revision=owned.revision,
        status=COMMITTED, storage_status="settled")
    if not outcome.ok and not outcome.conflict:
        logger.warning("b1 could not close operation=%s", operation_id)
    logger.info(
        "event=b1_committed operation=%s revision=%d user=%s cohort=%s "
        "answer_provenance=%s grams=%s items=%d",
        operation_id, revision, user.id, cohort, provenance.value,
        getattr(patch.quantity, "grams", None), len(result.committed_items))
    return result


async def replay(db, owned: OwnedOperation):
    """The result this operation already committed, or None.

    Reads the persisted `MealCommitResult` — the SAME object the winner held,
    which is what makes "a duplicate returns the original" a statement about
    types and not just about ids.
    """
    from sqlalchemy import select

    from core.meal_commit import _result_of
    from db.models import MealCommit

    row = (await db.execute(
        select(MealCommit)
        .where(MealCommit.operation_id == owned.operation_id,
               MealCommit.status == "committed")
        .order_by(MealCommit.operation_revision.desc()).limit(1)
    )).scalar_one_or_none()
    # `_result_of`, not a local decode: it rebuilds the SAME TYPE the winner
    # held. Returning raw JSON here is exactly what made the duplicate
    # contract asymmetric once already.
    return None if row is None else _result_of(row)


async def _writer(db, *, operation, resolved_meal):
    from core.canonical_writer import write_canonical_meal
    return await write_canonical_meal(db, operation=operation,
                                      resolved_meal=resolved_meal)


async def cancel(db, *, owned: OwnedOperation, user, reason: str = "") -> None:
    """Close the operation without a write, because the user said so.

    A terminal canonical outcome, not a fallback: nothing is handed to the
    legacy lane, and the meal does not silently persist as an open row that a
    later turn trips over.
    """
    from core import pending_repository as repo

    await repo.save_revision(db, operation_id=owned.operation_id,
                             expected_revision=owned.revision,
                             status=CANCELLED, storage_status="closed",
                             terminal_reason=(reason or "user_cancelled")[:200])
    logger.info("event=b1_cancelled operation=%s user=%s reason=%s",
                owned.operation_id, user.id, reason or "user_cancelled")


def _quantity_text(patch) -> str:
    """The quantity as the pricing path reads it — grams, which is the scaling
    currency. The user's own words are preserved on the patch's quantity
    (`surface_text`) and in the interaction; this is the machine's copy."""
    grams = getattr(patch.quantity, "grams", None)
    if grams:
        return f"{float(grams):g}g"
    amount = getattr(patch.quantity, "amount", None)
    unit = getattr(patch.quantity, "unit_id", "") or ""
    return f"{float(amount):g}{unit}".strip() if amount else ""


def _is_estimated(analysis) -> bool:
    """Derived from the provenance VERDICT, not the display vocabulary.

    Promotion rewrites `confidence` from the tier table, so
    `confidence == "estimated"` is False for every promoted row — prod
    fe#2703/2705 committed `estimated_flag=False` while their own raw_input
    said estimated. The string check remains only for analyses with no
    provenance.
    """
    prov = getattr(analysis, "provenance", None)
    if prov is not None:
        return bool(getattr(prov, "macros_are_estimated", False))
    return getattr(analysis, "confidence", "") == "estimated"
