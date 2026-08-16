"""Turn a resolved meal into rows, as ONE mutation, inside the caller's
transaction.

This is the `writer` the commit coordinator injects, and the whole point is
that it does not commit. `add_food_entry` commits per row by default, which is
precisely why a three-food turn can leave two foods on the board and lose the
third: with each row in its own transaction there is no state in which the meal
as a whole either has or has not landed, so a failure half way through is
indistinguishable from a meal that was only ever half spoken.

    CanonicalMeal -> write_canonical_meal -> commit_or_load_existing
                  -> FoodEntry rows -> MealCommitResult -> rendering

TOTALS ARE READ BACK FROM THE ROWS, never summed from the inputs. A row can be
written with a different value than it was handed — clamping, sanity limits,
a column's own coercion — and a total computed from inputs would then describe
a meal that is not on the board. The card and the prose have disagreed with the
ledger before; totals derived from the rows cannot.

PROVENANCE IS TWO FIELDS, NOT ONE. `ledger_source` names the mutation LANE and
its owner (`canonical:create`, matching the existing `structured_food:*` /
`legacy:ios` / `quick_log:ios` convention); `source_type` names the user's
input MODALITY. They answer different questions and must never be collapsed —
the canonical lane's own prefix is what makes adoption measurable during the
shadow phase.

NOT WIRED. `run_turn` still uses the legacy path.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as _date
from enum import Enum
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from core.meal_commit import MealCommitResult
from core.semantics import (CanonicalEvent, NutritionProvenance,
                            ResolutionStatus)

logger = logging.getLogger(__name__)

#: Columns copied straight through to the row. Named explicitly rather than
#: passed as **kwargs so a typo becomes an error here instead of a silently
#: dropped macro — `FoodEntry(**kwargs)` accepts nothing it does not recognise
#: and would raise, but a field the resolver renames would simply stop being
#: written.
_MACROS = ("protein", "carbs", "fats", "fiber", "sugar", "sodium")


class MealNotResolved(ValueError):
    """A meal item that is not ready to be written.

    RAISED AT CONSTRUCTION, not at write time. An item that reached the ledger
    unpriced is how a food gets logged at 1 calorie, and an item that reached
    it unresolved is how a clarification answer is applied to the wrong food.
    Both are cheap to refuse while the caller that built it is still on the
    stack, and expensive to detect afterwards.
    """


@dataclass(frozen=True)
class ResolvedFood:
    """A food that is BOTH understood and priced.

    Those two are separate facts and the codebase has repeatedly conflated
    them: `resolution_status` says the interpreter knows what the food is,
    `calories` says the resolver knows what it costs. A meal is writable only
    when both are true for every item, so the pair travels together and is
    checked once, here.
    """
    event: CanonicalEvent
    calories: float
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None

    quantity_text: str = ""
    meal_type: Optional[str] = None
    source_type: str = "structured_food"
    estimated: bool = False
    confidence_score: Optional[float] = None
    micros: Optional[dict] = None
    micros_estimated: bool = False
    from_photo: bool = False
    processing_level: Optional[str] = None
    raw_input: str = ""
    attributes: dict = field(default_factory=dict)
    #: WHO SUPPLIED THE NUMBERS — a different fact from who chose the food.
    #: Defaults to UNKNOWN, never SERVER_RESOLVED: an unset field claiming the
    #: resolver priced it is a lie the row cannot be audited out of later.
    nutrition_provenance: NutritionProvenance = NutritionProvenance.UNKNOWN

    def __post_init__(self):
        if not isinstance(self.event, CanonicalEvent):
            raise MealNotResolved(
                f"a resolved food needs a CanonicalEvent, not "
                f"{type(self.event).__name__} — identity is an id, and a name "
                f"is only evidence for one")
        if not self.event.resolution_status.is_actionable:
            raise MealNotResolved(
                f"{self.name!r} is {self.event.resolution_status.value}, not "
                f"resolved — writing it would commit a guess as a fact")
        if self.calories is None:
            raise MealNotResolved(
                f"{self.name!r} has no calories — it was understood but never "
                f"priced, which is how a food lands on the board at 1 cal")
        # Decimal is what CanonicalQuantity carries; the row's columns are
        # floats. Converted HERE, deliberately, in one place.
        for name in ("calories",) + _MACROS:
            value = getattr(self, name)
            if isinstance(value, Decimal):
                object.__setattr__(self, name, float(value))
        if self.calories < 0:
            raise MealNotResolved(f"{self.name!r} has negative calories")
        # Coerce a string at the boundary so callers may pass either, but an
        # invalid one fails HERE rather than reaching storage as free text.
        try:
            object.__setattr__(self, "nutrition_provenance",
                               NutritionProvenance(self.nutrition_provenance))
        except ValueError as exc:
            raise MealNotResolved(
                f"{self.nutrition_provenance!r} is not a NutritionProvenance — "
                f"who priced a row is a closed set, not free text") from exc

    @property
    def name(self) -> str:
        return self.event.surface_text or self.event.entity_id or "unnamed"


def operation_id_for(lane: str, user_id: int, turn_id: str) -> str:
    """A GLOBALLY unique operation id.

    `meal_commits` is unique on (operation_id, operation_revision) and
    deliberately does NOT include user_id — operation identity is meant to be
    global, and widening the constraint would weaken exactly the guarantee it
    exists to give. So the id itself has to carry the scope.

    It cannot simply be the turn id. `make_turn_id` returns `f"{channel}:{cid}"`
    verbatim when the client supplies an Idempotency-Key, with NO user in it —
    so two users sending the same key would share an operation, and the second
    would be handed the first's committed result. The idempotency layer is not
    exposed to this (`build_key` includes the user id); the turn id is.
    """
    return f"{lane}:{int(user_id)}:{turn_id}"


class DirectOperation:
    """The operation for a mutation that HAS no pending operation.

    A tap or an edit is one user action, one mutation, one revision — the meal
    itself is the operation. Chat turns that pass through clarification get a
    real persisted PendingOperation instead; this is for the surfaces that
    commit in the same request they arrive in.
    """

    def __init__(self, meal):
        self.id = meal.operation_id
        self.revision = meal.revision
        self.user_id = meal.user_id


class MealIntent(str, Enum):
    """WHICH LANE owns this mutation, which is not the same question as which
    modality the user typed it in.

    Two provenance fields must not disagree:

        `ledger_source` — the mutation lane and its owner
        `source_type`   — the user's input modality (text, voice, image)

    The database already follows that convention — `structured_food:
    food_interpreter_v2`, `legacy:ios`, `quick_log:ios`, `dashboard:food_log` —
    and the first version of this writer broke it by hardcoding a bare
    `"structured_food"` with no owner. The canonical lane gets its own prefix
    so adoption is MEASURABLE: `ledger_events.source LIKE 'canonical:%'` is the
    query that says how much traffic this path actually owns, which is exactly
    what the shadow phase needs and what a shared label would have destroyed.
    """
    CREATE = "create"
    CORRECTION = "correction"
    REPLACEMENT = "replacement"

    @property
    def ledger_source(self) -> str:
        return f"canonical:{self.value}"


@dataclass(frozen=True)
class ResolvedMeal:
    """One meal, validated as a whole, with the context a meal actually has.

    The first version took an arbitrary iterable of `ResolvedFood` and pieced
    the meal-level facts together from the operation — which left the day, the
    intent, the assumptions and the warnings outside the type, and a default of
    `date.today()` standing in for the one of them that decides which day the
    food lands on.

    LOGGING DAY IS REQUIRED. It has no safe default: the application server's
    local calendar date is not the user's, so around midnight — and for "that
    was dinner last night" — a fallback misfiles the meal silently, onto a day
    the user will not think to look at. It must be resolved upstream from the
    user's timezone and the source turn's timestamp, and this refuses to guess.
    """
    operation_id: str
    revision: int
    user_id: int
    logging_day: _date
    user_timezone: str
    items: tuple = ()
    intent: MealIntent = MealIntent.CREATE
    source_turn_id: str = ""
    meal_type: Optional[str] = None
    assumptions: tuple = ()
    warnings: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "items", tuple(self.items or ()))
        object.__setattr__(self, "assumptions", tuple(self.assumptions or ()))
        object.__setattr__(self, "warnings", tuple(self.warnings or ()))
        object.__setattr__(self, "intent", MealIntent(self.intent))

        if not self.operation_id:
            raise MealNotResolved("a meal commit needs an operation id")
        if not self.user_id:
            raise MealNotResolved("a meal commit needs a user")
        if not isinstance(self.logging_day, _date):
            raise MealNotResolved(
                "a canonical meal commit requires an explicit logging_day: "
                "the server's local date is not the user's, so a default "
                "misfiles the meal around midnight and for any historical log "
                "('that was dinner last night') — resolve it upstream from the "
                "user's timezone and the source turn's timestamp")
        # THE ZONE THE DAY WAS COMPUTED IN, carried so the day is auditable
        # rather than merely asserted, and VALIDATED rather than degraded.
        #
        # `_user_today` resolves through `safe_timezone`, which turns junk into
        # UTC — correct at read time, where a bad row must not 500 every chat
        # turn, and wrong here. A user in Naples whose stored timezone is free
        # text ("Naples, USA" really shipped) would silently have their meals
        # filed on UTC days, off by hours in the one direction nobody checks.
        # The mutation boundary refuses what the read path tolerates.
        if not self.user_timezone:
            raise MealNotResolved(
                "a canonical meal commit requires the timezone its logging_day "
                "was computed in — without it the day is an assertion nobody "
                "can check")
        try:
            ZoneInfo(self.user_timezone)
        except Exception as exc:
            raise MealNotResolved(
                f"{self.user_timezone!r} is not a real IANA timezone — "
                f"safe_timezone() degrades junk to UTC at read time, which "
                f"would silently file this meal on the wrong day") from exc
        if not self.items:
            raise MealNotResolved(
                "refusing to commit an empty meal — writing nothing "
                "successfully is how a turn reports a log it never made")
        for item in self.items:
            if not isinstance(item, ResolvedFood):
                raise MealNotResolved(
                    f"every item must be a ResolvedFood, got "
                    f"{type(item).__name__} — the checks that it is priced and "
                    f"resolved live in that type")


async def _log_for(db, user_id: int, day: _date):
    """The day's container, resolved WITHOUT touching the caller's transaction.

    `get_or_create_log_for_date` cannot be used here: it calls `db.commit()`,
    and on a create race `db.rollback()`. Inside the coordinator a rollback
    would discard the commit claim and everything the turn had staged — the
    meal would vanish and the operation would look untouched, which is the
    exact failure this architecture exists to remove, reintroduced by a helper
    that looks harmless.

    The create rides a SAVEPOINT instead, the same way `claim_commit` absorbs
    its unique violation: on Postgres a constraint violation aborts the whole
    transaction, so the loser of the race must be contained rather than
    handled.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from db.models import DailyLog

    async def _read():
        return (await db.execute(
            select(DailyLog).where(DailyLog.user_id == user_id,
                                   DailyLog.date == day))).scalar_one_or_none()

    log = await _read()
    if log is not None:
        return log
    try:
        async with db.begin_nested():
            log = DailyLog(user_id=user_id, date=day)
            db.add(log)
            await db.flush()
        return log
    except IntegrityError:
        # uq_daily_log_user_date — somebody else created it. The savepoint took
        # the failure, so the outer transaction is still usable.
        log = await _read()
    if log is None:                                   # pragma: no cover
        raise RuntimeError(
            f"could not resolve a daily log for user {user_id} on {day}")
    return log


async def write_canonical_meal(db, *, operation, resolved_meal
                               ) -> MealCommitResult:
    """Write every item of one meal, or leave the transaction for the caller to
    unwind. Returns what was actually written.

    Called by `commit_or_load_existing`, which owns the claim and the result;
    this owns only the rows. Nothing here commits or rolls back.
    """
    from db.queries import add_food_entry

    if not isinstance(resolved_meal, ResolvedMeal):
        raise MealNotResolved(
            f"the writer takes a validated ResolvedMeal, not "
            f"{type(resolved_meal).__name__} — meal-level facts (the logging "
            f"day, the intent, the assumptions, the warnings) belong inside "
            f"the type rather than reassembled at the mutation boundary")
    meal = resolved_meal

    # THE MEAL AND THE OPERATION MUST BE THE SAME MUTATION. The coordinator
    # claims under the operation's id and revision while the rows are written
    # from the meal, so a mismatch commits one meal under another's claim —
    # and the duplicate that follows would then be handed a result describing
    # food it never asked for.
    for field_name, from_op, from_meal in (
            ("operation", getattr(operation, "id", None), meal.operation_id),
            ("revision", int(getattr(operation, "revision", 0) or 0),
             int(meal.revision)),
            ("user", int(getattr(operation, "user_id", 0) or 0),
             int(meal.user_id))):
        if from_op != from_meal:
            raise MealNotResolved(
                f"{field_name} mismatch: the coordinator claimed "
                f"{from_op!r} and the meal describes {from_meal!r}")

    user_id, items = meal.user_id, meal.items
    log = await _log_for(db, user_id, meal.logging_day)

    written = []
    for item in items:
        entry = await add_food_entry(
            db, log.id,
            commit=False,                 # the meal is ONE mutation
            ledger_source=meal.intent.ledger_source,
            user_id=user_id,
            raw_input=item.raw_input or item.name,
            parsed_food_name=item.name,
            quantity=item.quantity_text or None,
            calories=item.calories,
            micronutrients_json=(json.dumps(item.micros)
                                 if item.micros else None),
            micros_estimated=bool(item.micros_estimated),
            estimated_flag=bool(item.estimated or item.from_photo),
            confidence_score=item.confidence_score,
            source_type=item.source_type,        # the user's INPUT MODALITY
            meal_type=item.meal_type or meal.meal_type,
            from_photo=bool(item.from_photo),
            processing_level=item.processing_level,
            **{m: getattr(item, m) for m in _MACROS})
        written.append((item, entry))

    await db.flush()
    committed, meal_totals = await _read_back(db, written)
    day_totals = await _day_totals(db, log.id)

    logger.info(
        "event=canonical_meal_written operation=%s revision=%d lane=%s "
        "items=%d cal=%s day=%s", meal.operation_id, meal.revision,
        meal.intent.ledger_source, len(committed),
        meal_totals.get("calories"), meal.logging_day.isoformat())

    return MealCommitResult(
        committed_items=tuple(committed),
        meal_totals=meal_totals,
        day_totals=day_totals,
        # DISCLOSURE IS PART OF THE RESULT, not of the turn that produced it.
        # The stored result must be enough to reproduce the exact user-facing
        # confirmation, because a duplicate delivery is answered from it and
        # never re-runs the interpretation. Dropping these here would let the
        # ledger be right while the second confirmation quietly omits the
        # assumptions the first one disclosed.
        assumptions=meal.assumptions,
        warnings=meal.warnings,
        # POST-COMMIT WORK, RETURNED AS DATA. Dropping the briefing cache while
        # these rows are still invisible would let a concurrent Coach open
        # repopulate it from pre-write state, and it would outlive a rollback
        # that removed them. The caller performs this after its commit.
        render_actions=({"action": "invalidate_briefing",
                         "user_id": user_id},),
    )


async def _read_back(db, written) -> tuple:
    """What is ON THE BOARD, not what was asked for.

    Re-reading is the difference between a receipt and a promise: if a column
    coerced a value, or a sanity clamp changed one, the totals and the card
    must describe the row rather than the request.
    """
    from sqlalchemy import select

    from db.models import FoodEntry

    ids = [entry.id for _, entry in written]
    rows = {r.id: r for r in (await db.execute(
        select(FoodEntry).where(FoodEntry.id.in_(ids)))).scalars().all()}

    # ⭐ THE LEDGER EVENT ID, WHICH IS THE UNDO TOKEN. `add_food_entry` writes
    # the created event internally and returns only the entry, so a canonically
    # settled turn had `ledger_event_ids` EMPTY all the way out to the client —
    # and an undo token is exactly what that tuple carries. Read back here,
    # beside the rows themselves, rather than threaded through the writer:
    # `_read_back` already exists to report what is ON THE BOARD.
    #
    # ⚠ ONE QUERY, NOT ONE PER ITEM, and keyed by entry so a multi-item meal
    # cannot pair a row with another row's event.
    from db.models import LedgerEvent

    events = {}
    for event_id, entry_id in (await db.execute(
            select(LedgerEvent.id, LedgerEvent.entry_id)
            .where(LedgerEvent.entry_id.in_(ids),
                   LedgerEvent.event_type == "created"))).all():
        events.setdefault(int(entry_id), int(event_id))

    committed, totals = [], {"calories": 0.0,
                             **{m: 0.0 for m in _MACROS}}
    for item, entry in written:
        row = rows.get(entry.id)
        if row is None:                                # pragma: no cover
            raise RuntimeError(
                f"{item.name!r} was written as entry {entry.id} and cannot be "
                f"read back in the same transaction")
        pricing = (item.attributes or {}).get("pricing")
        committed.append({
            "entry_id": row.id,
            # Persisted with the result, so a duplicate replay and every later
            # reader can tell client-priced from catalog-priced without a
            # schema change — meal_commits.result_payload is the durable home.
            "nutrition_provenance": item.nutrition_provenance.value,
            # ⭐ A6 — THE RUNG THAT ACTUALLY DECIDED THE PRICE, when the caller
            # recorded one. `food_entries` has no rung column, so this payload
            # is the durable home here too, and it is what makes "read the
            # provenance from the DB, never from reply text" possible at all.
            #
            # ⚠ OMITTED RATHER THAN DEFAULTED when absent: a caller that did
            # not record a rung must not be reported as having priced from one.
            # Callers that never set it (B-1, quick_log) see no payload change.
            **({"pricing": dict(pricing)} if pricing else {}),
            # Where the row LIVES, not just what it is. The quick-log response
            # contract returns daily_log_id, and the idempotency claim stores
            # it so a replay can answer without a join — a result that cannot
            # say which day it landed on cannot honour either.
            "daily_log_id": row.daily_log_id,
            "name": row.parsed_food_name,
            "entity_id": item.event.entity_id or "",
            "quantity": row.quantity or "",
            "calories": float(row.calories or 0.0),
            # ⭐ READ BACK FROM THE ROW, like `calories` beside it. The renderer
            # narrates committed state, and it cannot do that for protein while
            # the only protein figure crossing this seam is the model's
            # proposal — which is how "Mackerel logged, 180 cal" gets said over
            # a row the artifact priced at 305.
            "protein": float(row.protein or 0.0),
            "estimated": bool(row.estimated_flag),
            # The undo token. Omitted rather than defaulted when the event is
            # absent: "no event was recorded" and "event 0" are different facts.
            **({"event_id": events[row.id]} if row.id in events else {}),
        })
        totals["calories"] += float(row.calories or 0.0)
        for m in _MACROS:
            totals[m] += float(getattr(row, m, 0.0) or 0.0)
    return committed, {k: round(v, 2) for k, v in totals.items()}


async def _day_totals(db, daily_log_id: int) -> dict:
    """The day as the ledger now holds it. `add_food_entry` already recomputed
    these from the entries, so this reads rather than re-derives — a fourth
    computation of the day's calories is how the prose and the card came to
    disagree by one."""
    from sqlalchemy import select

    from db.models import DailyLog

    log = (await db.execute(select(DailyLog).where(
        DailyLog.id == daily_log_id))).scalar_one()
    return {
        "calories": float(log.total_calories or 0),
        "protein": float(log.total_protein or 0),
        "carbs": float(log.total_carbs or 0),
        "fats": float(log.total_fats or 0),
    }
