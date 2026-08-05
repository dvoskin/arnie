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
#: OUR failure, not the user's — an operation nobody can settle.
FAILED = "failed"

#: Ledger events that qualify as a CORRECTION of what B-1 committed. Not every
#: later event on a row is one — a rollup or a restore says something else, and
#: counting those would inflate the single metric that means "we got it wrong".
#: An edit and a deletion are both evidence; `event_type` is recorded so they
#: stay separable.
CORRECTION_EVENT_TYPES = frozenset({"updated", "deleted"})


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
    def asked_at(self):
        """When the QUESTION was sent. Latency and abandonment are properties
        of the gap between two turns, and only the row spans it — deriving
        either from anything the answer turn holds would measure the answer
        turn instead."""
        return self.row.created_at

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

    from datetime import timedelta

    from core.clock import now as _now

    operation_id = operation_id_for("chat_quantity", user.id, turn_id)
    await repo.create_operation(
        db, operation_id=operation_id, user_id=user.id, status=AWAITING,
        storage_status="active", domain=DOMAIN, source_turn_id=turn_id,
        payload=_encode(interaction, interpreter_item, locale or "en"),
        # AN UNANSWERED QUESTION MUST NOT LIVE FOREVER. Without this the row
        # stays `awaiting_answer` indefinitely and a message weeks later is
        # read as an answer to a meal the user has long forgotten.
        expires_at=_now() + timedelta(minutes=ASK_TTL_MINUTES))
    from core import b1_metrics
    b1_metrics.shown(operation_id=operation_id, user_id=user.id, cohort=cohort,
                     locale=locale or "en",
                     field=interaction.groups[0].fields[0])
    return operation_id


#: How long an unanswered question stays answerable. Past it the operation
#: expires rather than lingering as an open row a later turn trips over.
ASK_TTL_MINUTES = 180


#: HOW A CHANNEL CAN CARRY AN ANSWER BACK. These are not equivalent and must
#: never be described as equivalent — the difference is what the answer is
#: BOUND to.
#:
#:   ID_ADDRESSED   the reply carries operation_id + revision + field_id +
#:                  option_id. The answer is bound to the exact question, and
#:                  a stale or foreign one is detectable.
#:
#:   LABEL_TEXT     the reply carries the option's rendered words and nothing
#:                  else. RESTRICTED, because binding is inferred: we match
#:                  the text against the open operation's stored options. Two
#:                  identical labels on two live operations are
#:                  indistinguishable, a label typed by hand is
#:                  indistinguishable from a press, and staleness cannot be
#:                  detected at all — the text of last turn's chip looks
#:                  exactly like this turn's.
#:
#: B-1 accepts LABEL_TEXT deliberately: it is what proves the wire on real
#: traffic without shipping Swift. It is not the chip path, its production
#: evidence does not substitute for the chip path's, and B-1b exists because
#: of that.
ID_ADDRESSED = "id_addressed"
LABEL_TEXT = "label_text"

#: Channels whose chips the SERVER renders. Telegram and iMessage have no
#: client-side chip parser at all, so the canonical payload is readable by
#: construction — but their reply carries only the label.
_CHANNEL_CAPABILITY = {
    "telegram": LABEL_TEXT,
    "imessage": LABEL_TEXT,
    "bluebubbles": LABEL_TEXT,
    "sms": LABEL_TEXT,
    # ios: absent until B-1b ships a build that renders fields/options and
    # submits ids. Naming it here before then would be a capability claim
    # about software that does not exist.
}


def channel_capability(source: Optional[str]) -> Optional[str]:
    """How this channel can answer, or None if it cannot."""
    return _CHANNEL_CAPABILITY.get(str(source or "").strip().lower())


def client_renders_interactions(source: Optional[str]) -> bool:
    """Can this client read the canonical payload at all?

    AN EXCLUSION, NOT A DOWNGRADE. A client that cannot is ineligible for B-1
    and stays wholly legacy. The alternative — sending it the canonical
    question rendered as prose — would keep the sentence parser alive INSIDE
    the replacement, which is the exact defect B-1 exists to delete, and it
    would block deleting `QuickReplyEngine.swift` at promotion.
    """
    return channel_capability(source) is not None


@dataclass(frozen=True)
class CanonicalAsk:
    """A question B-1 owns, with the durable state already written."""
    operation_id: str
    revision: int
    interaction: Any
    locale: str
    cohort: str

    def wire_payload(self) -> dict:
        """What the client receives. IDs, not meanings (C11)."""
        field = self.interaction.groups[0].fields[0]
        return {
            "operation_id": self.operation_id,
            "revision": self.revision,
            "interaction_id": self.interaction.interaction_id,
            "locale": self.locale,
            "groups": [{
                "event_id": g.event_id,
                "label": g.label,
                "fields": [{
                    "field_id": f.field_id,
                    "attribute": f.attribute.value,
                    "response_type": f.response_type.value,
                    # C15's FREE-TEXT ROUTE, ON THE WIRE. Without it a
                    # `single_select` tells the client "three chips and
                    # nothing else", and a user whose portion is not among
                    # them has no visible way to say so — the exact
                    # forced-"Other" failure the rollout metric exists to
                    # detect, shipped as a design instead of a bug. It is
                    # also what makes that metric measurable at all: "Other
                    # usage" is answers that arrived as text rather than as a
                    # stored option.
                    "allows_free_text": True,
                    # LABELS ONLY. The patch stays on the server; a tap sends
                    # `option_id` back and the meaning is loaded from storage,
                    # so the label can never travel as semantics.
                    "options": [{"option_id": o.option_id, "label": o.label}
                                for o in f.options],
                } for f in g.fields],
            } for g in self.interaction.groups],
        }

    def legacy_questions(self) -> list:
        """The same field, in the shape today's clients already read.

        A PROJECTION of the canonical interaction, not a second producer:
        both rows come from one field, so they cannot disagree. It exists so
        an older client keeps working during the rollout — and it dies with
        `QuickReplyEngine.swift` at B-1 promotion.
        """
        field = self.interaction.groups[0].fields[0]
        return [{"item": self.interaction.groups[0].label or None,
                 "text": self.interaction.introduction,
                 "options": [o.label for o in field.options]}]


async def try_take_ownership(db, *, user, material: dict, turn_id: str,
                             client_capable: bool,
                             locale: str = "en") -> Optional[CanonicalAsk]:
    """Decide whether B-1 owns this turn, and if so, take ownership durably.

    THE ONE PLACE THE PREDICATE IS EVALUATED. `food_turn` carries the material
    here rather than judging half of it, because a predicate with two owners
    drifts — and the half it could not see (client capability, locale, the
    rollout cohort) is the half that decides whether owning this turn is safe.

    ORDER MATTERS AND IS NOT INCIDENTAL:

        eligibility  ->  rollout gate  ->  candidates  ->  PERSIST  ->  return

    The gate is asked ONCE, here, before the row exists. Everything before the
    write may decline freely: nothing has been taken, so the turn simply
    proceeds as it does today. Everything after the write is owned, and
    `owning()` will find it no matter what the gate later says.

    Returning None is always safe. Raising is not, which is why the persist
    step is the last thing that can fail: a question sent with no durable row
    behind it is a question the user answers into a void.
    """
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition import quantity_rollout as qr

    decision = _MaterialDecision(material)
    verdict = qc.is_eligible(decision, message=material.get("message") or "",
                             client_capable=client_capable)
    if not verdict.ok:
        from core import b1_metrics
        b1_metrics.declined(user_id=getattr(user, "id", None),
                            reason=verdict.reason.value)
        return None

    cohort = qr.cohort_label(user.id)
    if not qr.may_take_ownership(user.id):
        from core import b1_metrics
        b1_metrics.declined(user_id=user.id, reason="not_in_cohort",
                            cohort=cohort)
        return None

    item = verdict.item
    interpreter_item = _interpreter_item_for(material, item)
    if not interpreter_item:
        from core import b1_metrics
        b1_metrics.declined(user_id=user.id, reason="no_interpreter_item",
                            cohort=cohort)
        return None

    operation_id = _operation_id_for(user, turn_id)
    field = qc.quantity_field(operation_id=operation_id, revision=0, item=item)
    candidates = await qc.candidates(db, user_id=user.id, item=item,
                                     message=material.get("message") or "")
    options = qc.select(candidates, field=field,
                        food_name=str(item.identity.canonical_name or ""))
    if not options:
        # No evidence, so no chips. B-1 declines rather than shipping a select
        # with nothing in it — the legacy ask is still a better question than
        # an empty canonical one, and C15 forbids the blank row either way.
        from core import b1_metrics
        b1_metrics.declined(user_id=user.id, reason="no_candidates",
                            cohort=cohort)
        return None

    interaction = qc.build_interaction(
        operation_id=operation_id, revision=0, item=item, options=options,
        introduction=_introduction(item))

    await open_operation(db, user=user, interpreter_item=interpreter_item,
                         interaction=interaction, turn_id=turn_id,
                         cohort=cohort, locale=locale)
    return CanonicalAsk(operation_id=operation_id, revision=0,
                        interaction=interaction, locale=locale, cohort=cohort)


class _MaterialDecision:
    """`is_eligible` reads a decision's `staged_items`; this is that shape,
    rebuilt from what crossed the boundary. Not a mock — the staged items are
    the real objects, only the container is local."""

    def __init__(self, material: dict):
        self.staged_items = tuple(material.get("staged_items") or ())


def _operation_id_for(user, turn_id: str) -> str:
    from core.canonical_writer import operation_id_for

    return operation_id_for("chat_quantity", user.id, turn_id)


def _interpreter_item_for(material: dict, staged) -> dict:
    """The interpreter's row for the food being asked about.

    Matched on the staged item's ORDINAL first, because two servings of the
    same food in one turn share a name and differ only by position — and
    falling back to a name match there would price the wrong one. B-1 is
    single-item, so the fallback is exact-name and then the sole item.
    """
    items = [i for i in (material.get("items") or []) if isinstance(i, dict)]
    if not items:
        return {}
    ordinal = int(getattr(staged, "ordinal", 0) or 0)
    if 0 <= ordinal < len(items):
        return dict(items[ordinal])
    name = str(getattr(getattr(staged, "identity", None), "canonical_name", "")
               or "").strip().lower()
    for raw in items:
        if str(raw.get("food") or "").strip().lower() == name:
            return dict(raw)
    return dict(items[0]) if len(items) == 1 else {}


def _introduction(staged) -> str:
    """Deterministic wording. The renderer owns voice at B-2.8; until then a
    template that cannot drift is better than a model call that can, and the
    question's MEANING lives in the field either way."""
    label = str(getattr(getattr(staged, "identity", None), "canonical_name", "")
                or "").strip() or "that"
    return f"How much {label}?"


#: How long a settled operation still answers for its meal. A tap that arrives
#: after the commit inside this window is a REPLAY; outside it, the user is
#: plausibly talking about a new meal. Generous, because the failure it
#: prevents (a duplicate meal) is worse than the one it causes (a replay
#: answer to a genuinely new, identical meal, which idempotency also absorbs).
SETTLED_OWNERSHIP_MINUTES = 30


class OwnershipUnknown(RuntimeError):
    """THE LOOKUP ITSELF FAILED. Not "no operation owns this meal" — we do not
    know whether one does.

    The distinction is the whole point. `None` means the query ran and found
    nothing, so the turn proceeds legacy exactly as today. A raise means the
    query did not run, and treating that as `None` would hand a possibly-owned
    meal to the broad interpreter on a database blip — turning a transient
    error into a duplicate meal, silently, at exactly the moment nobody is
    watching. Two states cannot express three.

    The caller's only safe response is to log nothing and say so.
    """


async def owning(db, user) -> Optional[OwnedOperation]:
    """The canonical operation that owns this user's meal.

    TRI-STATE, deliberately:

        OwnedOperation   this meal is ours
        None             the query ran; nothing owns it — proceed legacy
        raise            the query FAILED; ownership is unknown

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
    except Exception as exc:
        logger.error("event=b1_ownership_unknown user=%s — refusing to "
                     "proceed as unowned", getattr(user, "id", None),
                     exc_info=True)
        raise OwnershipUnknown(
            f"could not determine B-1 ownership for user "
            f"{getattr(user, 'id', None)}") from exc

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


async def sweep_abandoned(db, *, limit: int = 200) -> int:
    """Expire questions nobody answered, and COUNT them.

    Runs on a timer, not on a turn, because nobody is having a turn when a
    user abandons one — which is exactly why abandonment is the signal most
    likely to be missing from a dashboard that otherwise looks complete. A
    clarification the user walked away from is the loudest possible statement
    that the question was not worth asking, and without this it is invisible.

    It also stops an unanswered row lingering as `awaiting_answer` forever,
    where a message weeks later would be read as an answer to a meal the user
    has long forgotten.
    """
    import json as _json

    from sqlalchemy import select

    from core import b1_metrics
    from core import pending_repository as repo
    from core.clock import now as _now
    from db.models import PendingOperation

    # STARVATION-SAFE, and this was a real defect. `LIMIT` applied before the
    # slice filter means the batch is drawn from ALL expired food operations
    # and only then narrowed to B-1's — so a backlog of expired non-B-1
    # operations fills every page and B-1's are never reached, forever, while
    # the sweep reports success.
    #
    # The slice IS queryable (`"slice": "b1_quantity"` lives in the JSON text),
    # so it is pushed into the WHERE clause as a coarse pre-filter and
    # re-checked properly after decoding — the LIKE narrows the scan, the
    # decode decides. Deterministic ordering by id, and pagination continues
    # until `limit` B-1 operations have been PROCESSED rather than until
    # `limit` rows have been read.
    swept = 0
    seen = 0
    after_id = 0
    page = max(limit, 50)
    while swept < limit and seen < limit * 20:
        rows = (await db.execute(
            select(PendingOperation)
            .where(PendingOperation.domain == DOMAIN,
                   PendingOperation.status == AWAITING,
                   PendingOperation.expires_at.isnot(None),
                   PendingOperation.expires_at < _now(),
                   PendingOperation.id > after_id,
                   # MATCHED ON THE VALUE, not on a serialized key/value
                   # pair. `'%"slice": "b1_quantity"%'` depends on
                   # json.dumps' separator, and if that ever changes the LIKE
                   # silently matches nothing — abandonment stops being
                   # measured and the sweep still reports success. The decode
                   # below is what decides; this only narrows the scan, so it
                   # should be the loosest thing that narrows.
                   PendingOperation.canonical_payload.like('%b1_quantity%'))
            .order_by(PendingOperation.id)
            .limit(page))).scalars().all()
        if not rows:
            break
        after_id = rows[-1].id
        seen += len(rows)
        for row in rows:
            if swept >= limit:
                break
            try:
                data = _json.loads(row.canonical_payload or "{}")
            except Exception:
                data = {}
            if data.get("slice") != "b1_quantity":
                continue          # the LIKE narrowed; the decode decides
            outcome = await repo.mark_expired(
                db, operation_id=row.operation_id,
                expected_revision=int(row.revision or 0))
            if not outcome.ok:
                # Somebody answered between the query and the write. Their
                # answer wins — this is a sweep, not a race to close.
                continue
            b1_metrics.abandoned(operation_id=row.operation_id,
                                 user_id=row.user_id,
                                 asked_at=row.created_at)
            swept += 1
    return swept


async def note_corrections(db, *, limit: int = 200) -> int:
    """Count B-1 rows corrected soon after they landed.

    THE SHARPEST QUALITY SIGNAL IN THE SET: the user saw the number and it was
    wrong enough to fix. A rising rate here invalidates a green corpus, which
    is precisely why it cannot be inferred from anything inside the answer
    turn — the evidence arrives minutes later, from a different turn.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from core import b1_metrics
    from core.clock import now as _now
    from db.models import LedgerEvent, PendingOperation

    # KEYED ON THE ENTRY, not the operation: `ledger_events` records which
    # ROW changed and which turn changed it, and has no operation column. The
    # entry id comes from the operation's own stored result, which is the only
    # thing joining the two.
    window = timedelta(minutes=b1_metrics.CORRECTION_WINDOW_MINUTES)
    since = _now() - (window * 3)
    _ZERO = timedelta(0)
    rows = (await db.execute(
        select(PendingOperation)
        .where(PendingOperation.domain == DOMAIN,
               PendingOperation.status == COMMITTED,
               PendingOperation.updated_at.isnot(None),
               PendingOperation.updated_at >= since)
        .limit(limit))).scalars().all()
    if not rows:
        return 0

    noted = 0
    for row in rows:
        entry_id = await _committed_entry_id(db, row.operation_id)
        if entry_id is None:
            continue
        if await _already_observed(db, row.operation_id, entry_id):
            continue
        events = (await db.execute(
            select(LedgerEvent)
            .where(LedgerEvent.domain == DOMAIN,
                   LedgerEvent.entry_id == entry_id)
            .order_by(LedgerEvent.id))).scalars().all()
        created = next((e for e in events if e.event_type == "created"), None)
        if created is None or created.created_at is None:
            continue
        for event in events:
            if event.id == created.id or event.created_at is None:
                continue
            # QUALIFYING TYPES ONLY. Not every later event on a row is a
            # correction of its numbers — a re-log rollup or a restore says
            # something else — and counting them would inflate the one metric
            # that is supposed to mean "we got it wrong".
            if event.event_type not in CORRECTION_EVENT_TYPES:
                continue
            gap = event.created_at - created.created_at
            # BOTH ENDS. A negative gap is clock skew or a backfilled event,
            # not a correction that happened before the thing it corrects, and
            # letting it through would count an impossible ordering as
            # evidence.
            if gap < _ZERO or gap > window:
                continue
            if await _record_observation(
                    db, operation_id=row.operation_id, entry_id=entry_id,
                    user_id=row.user_id, event_type=event.event_type,
                    minutes=gap.total_seconds() / 60.0):
                b1_metrics.corrected(
                    operation_id=row.operation_id, user_id=row.user_id,
                    entry_id=entry_id, minutes=gap.total_seconds() / 60.0)
                noted += 1
            break
    return noted


async def _already_observed(db, operation_id: str, entry_id) -> bool:
    from sqlalchemy import select

    from db.models import B1CorrectionObservation

    return (await db.execute(
        select(B1CorrectionObservation.id)
        .where(B1CorrectionObservation.operation_id == operation_id,
               B1CorrectionObservation.entry_id == entry_id)
        .limit(1))).scalar_one_or_none() is not None


async def _record_observation(db, *, operation_id: str, entry_id, user_id,
                              event_type: str, minutes: float) -> bool:
    """Claim this observation, or discover somebody already did.

    THE INSERT IS THE CLAIM, contained in a savepoint, exactly as
    `claim_commit` does it: a read-then-write cannot see the row another
    worker is inserting, and two schedulers on two workers is the normal
    deployment. Returns False when the observation already exists, which is
    how the metric stays exactly-once rather than once-per-cron-tick.
    """
    from sqlalchemy.exc import IntegrityError

    from db.models import B1CorrectionObservation

    try:
        async with db.begin_nested():
            db.add(B1CorrectionObservation(
                operation_id=operation_id, entry_id=int(entry_id),
                user_id=int(user_id), event_type=str(event_type),
                minutes_after_commit=float(minutes)))
            await db.flush()
        return True
    except IntegrityError:
        return False


async def _committed_entry_id(db, operation_id: str):
    from sqlalchemy import select

    from core.meal_commit import _result_of
    from db.models import MealCommit

    row = (await db.execute(
        select(MealCommit)
        .where(MealCommit.operation_id == operation_id,
               MealCommit.status == "committed")
        .order_by(MealCommit.operation_revision.desc()).limit(1)
    )).scalar_one_or_none()
    result = None if row is None else _result_of(row)
    items = list(getattr(result, "committed_items", ()) or ())
    first = items[0] if items and isinstance(items[0], dict) else {}
    return first.get("entry_id")


async def fail(db, *, owned: OwnedOperation, user, reason: str) -> None:
    """Close an operation WE cannot serve.

    Distinct from `cancel`, which is the user's decision. This is ours: the
    stored interaction cannot be read, so no answer could be applied to it,
    and leaving the row `awaiting_answer` would collect answers into a void
    turn after turn. Terminal, logged as an error, and never dressed up as a
    question to the user.
    """
    from core import pending_repository as repo

    await repo.save_revision(db, operation_id=owned.operation_id,
                             expected_revision=owned.revision,
                             status=FAILED, storage_status="closed",
                             terminal_reason=(reason or "unserviceable")[:200])
    logger.error("event=b1_failed operation=%s user=%s reason=%s",
                 owned.operation_id, getattr(user, "id", None), reason)


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
