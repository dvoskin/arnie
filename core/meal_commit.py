"""One ledger mutation per (operation, revision), arbitrated by the database.

`pending_store.claim()` proves exactly one caller consumed the clarification
ANSWER. This proves exactly one caller WRITES the meal, which is a different
promise — and the gap between them is a real sequence:

    worker A claims the answer
    worker A commits food
    worker A crashes before marking the operation consumed
    a retry reconstructs the operation and commits again

WHY A CONSTRAINT AND NOT A CHECK. An application-level
`if not already_committed(key)` cannot arbitrate concurrent workers: both read
"not committed", both proceed, both write. The uniqueness has to be enforced
where the serialisation happens, so it is a UNIQUE constraint and the failure to
insert IS the answer.

WHY THE RESULT IS STORED. A duplicate must return what the FIRST attempt
produced, not merely decline. A caller that gets nothing back cannot tell
"already done" from "nothing happened", and will either re-report the meal or
report a commit that did not occur on this turn — the phantom-log failure in a
new costume.

NOT WIRED. The constraint exists and is proven here; routing the food path
through it is the next commit, in that order deliberately. Consolidating the
mutation sites first would relocate the double-commit rather than close it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitClaim:
    """The outcome of asking to write a meal.

    `won` says whether THIS caller may perform the write. `result` is what the
    winner recorded, present on a duplicate so the loser can answer with it.
    """
    won: bool
    operation_id: str
    revision: int
    result: Optional[dict] = None

    @property
    def is_duplicate(self) -> bool:
        return not self.won


async def claim_commit(db, *, operation_id: str, revision: int = 0,
                       user_id: int) -> CommitClaim:
    """Try to become the one caller allowed to write this meal.

    Returns `won=True` exactly once per (operation_id, revision). Every later
    attempt gets `won=False` and the winner's stored result.

    THE INSERT IS THE CLAIM. There is no read-then-write here, because a read
    cannot see a row another worker is about to insert — checking first and
    inserting second is the race this exists to remove.
    """
    if not operation_id:
        raise ValueError("a commit claim needs an operation id")
    from sqlalchemy.exc import IntegrityError

    from db.models import MealCommit

    row = MealCommit(operation_id=operation_id,
                     operation_revision=int(revision),
                     user_id=int(user_id))
    try:
        db.add(row)
        await db.flush()
    except IntegrityError:
        # LOST, and that is a normal outcome rather than an error. The winner's
        # row is what this caller must answer with.
        await db.rollback()
        existing = await _load(db, operation_id, revision)
        logger.info(
            "event=meal_commit outcome=duplicate operation=%s revision=%d "
            "— the write already happened; returning the original result",
            operation_id, revision)
        return CommitClaim(won=False, operation_id=operation_id,
                           revision=revision,
                           result=_decode(existing))
    logger.info("event=meal_commit outcome=claimed operation=%s revision=%d",
                operation_id, revision)
    return CommitClaim(won=True, operation_id=operation_id, revision=revision)


async def record_result(db, *, operation_id: str, revision: int = 0,
                        result: Any) -> None:
    """Store what the winning write produced, so a duplicate can be answered.

    Called INSIDE the same transaction as the ledger write. If the two are
    committed separately, a crash between them leaves a claim with no result —
    and a retry that reads it would report a commit whose rows do not exist.
    """
    from sqlalchemy import update

    from db.models import MealCommit

    await db.execute(
        update(MealCommit)
        .where(MealCommit.operation_id == operation_id,
               MealCommit.operation_revision == int(revision))
        .values(result_payload=json.dumps(result, default=str),
                status="committed"))


async def existing_result(db, *, operation_id: str,
                          revision: int = 0) -> Optional[dict]:
    """What a previous commit of this (operation, revision) produced, if any."""
    return _decode(await _load(db, operation_id, revision))


async def _load(db, operation_id: str, revision: int):
    from sqlalchemy import select

    from db.models import MealCommit

    res = await db.execute(
        select(MealCommit).where(
            MealCommit.operation_id == operation_id,
            MealCommit.operation_revision == int(revision)))
    return res.scalar_one_or_none()


def _decode(row) -> Optional[dict]:
    raw = getattr(row, "result_payload", None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("meal commit result is unreadable for %s",
                       getattr(row, "operation_id", "?"))
        return None
