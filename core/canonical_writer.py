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

NOT WIRED. `run_turn` still uses the legacy path.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal
from typing import Optional

from core.meal_commit import MealCommitResult
from core.semantics import CanonicalEvent, ResolutionStatus

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

    @property
    def name(self) -> str:
        return self.event.surface_text or self.event.entity_id or "unnamed"


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

    user_id = int(getattr(operation, "user_id", 0) or 0)
    if not user_id:
        raise ValueError("a meal commit needs a user")
    items = list(resolved_meal or ())
    if not items:
        raise MealNotResolved(
            "refusing to commit an empty meal — an operation that reaches the "
            "ledger with nothing to write is a bug upstream, and writing "
            "nothing successfully is how a turn reports a log it never made")
    for item in items:
        if not isinstance(item, ResolvedFood):
            raise MealNotResolved(
                f"every item must be a ResolvedFood, got "
                f"{type(item).__name__} — the check that it is priced and "
                f"resolved lives in that type")

    day = getattr(operation, "logging_day", None) or _date.today()
    log = await _log_for(db, user_id, day)

    written = []
    for item in items:
        entry = await add_food_entry(
            db, log.id,
            commit=False,                 # the meal is ONE mutation
            ledger_source="structured_food",
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
            source_type=item.source_type,
            meal_type=item.meal_type,
            from_photo=bool(item.from_photo),
            processing_level=item.processing_level,
            **{m: getattr(item, m) for m in _MACROS})
        written.append((item, entry))

    await db.flush()
    committed, meal_totals = await _read_back(db, written)
    day_totals = await _day_totals(db, log.id)

    logger.info(
        "event=canonical_meal_written operation=%s items=%d cal=%s",
        getattr(operation, "id", "?"), len(committed),
        meal_totals.get("calories"))

    return MealCommitResult(
        committed_items=tuple(committed),
        meal_totals=meal_totals,
        day_totals=day_totals,
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

    committed, totals = [], {"calories": 0.0,
                             **{m: 0.0 for m in _MACROS}}
    for item, entry in written:
        row = rows.get(entry.id)
        if row is None:                                # pragma: no cover
            raise RuntimeError(
                f"{item.name!r} was written as entry {entry.id} and cannot be "
                f"read back in the same transaction")
        committed.append({
            "entry_id": row.id,
            "name": row.parsed_food_name,
            "entity_id": item.event.entity_id or "",
            "quantity": row.quantity or "",
            "calories": float(row.calories or 0.0),
            "estimated": bool(row.estimated_flag),
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
