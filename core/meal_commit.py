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
"not committed", both proceed, both write. The uniqueness is enforced where the
serialisation happens, so the failure to insert IS the answer.

THE RESULT IS IMMUTABLE ONCE WRITTEN. A duplicate must receive what the FIRST
attempt produced, and "first" has to keep meaning something — a second
`record_result` that overwrote the payload would make the duplicate contract
return whatever was written most recently. The transition is
`claimed -> committed` exactly once, guarded in SQL rather than in Python.

NOT WIRED. The claim, the result and their guards are proven here; routing food
writes through them is the next commit, in that order deliberately.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The stored result's shape. Versioned so a payload written by a newer build
#: is refused rather than misread by an older one.
RESULT_SCHEMA_VERSION = 1


class MissingCommitClaim(RuntimeError):
    """A result was recorded against a claim that is absent, or in a state that
    may not accept one.

    Raised rather than returned: the caller is mid-transaction, and the correct
    response is to abort the whole thing. Food rows without an authoritative
    result is the one outcome this module exists to prevent.
    """

    def __init__(self, operation_id: str, revision: int, why: str):
        super().__init__(f"{operation_id}@{revision}: {why}")
        self.operation_id, self.revision, self.why = (
            operation_id, revision, why)


class UnserializableResult(TypeError):
    """A result containing a value that cannot be stored faithfully."""


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


# ── serialization ────────────────────────────────────────────────────────────

def _plain(value: Any, path: str = "result") -> Any:
    """A JSON-safe copy, or an exception naming what could not be stored.

    NO `default=str`. That silently turns a Decimal, a datetime or a domain
    object into a string, so a duplicate receives something structurally
    different from what the original caller got — and nothing fails at the
    moment it happens. For an authoritative replay result, a lossy conversion
    is worse than a refusal.

    Decimal and datetime ARE converted, because both have a lossless canonical
    text form and both appear in real totals. Everything else must be made
    plain by the caller, which is where the meaning lives.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)                    # exact; float() would not be
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, f"{path}[{i}]") for i, v in enumerate(value)]
    raise UnserializableResult(
        f"{path} is {type(value).__name__}, which cannot be stored without "
        "losing its shape — convert it before recording the result")


def encode_result(result: Any) -> str:
    """Versioned, validated, and lossless or refused."""
    return json.dumps({"schema_version": RESULT_SCHEMA_VERSION,
                       "result": _plain(result)})


def decode_result(raw: Optional[str]) -> Optional[Any]:
    """The stored result, or None when there is none.

    Fails closed on a version it cannot interpret: answering a duplicate with a
    partially-understood payload would hand it something the original caller
    never saw.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning("event=commit_result_unreadable reason=json_error")
        return None
    if not isinstance(data, dict):
        logger.warning("event=commit_result_unreadable reason=not_an_object")
        return None
    version = data.get("schema_version")
    if version is None or int(version) > RESULT_SCHEMA_VERSION:
        logger.warning("event=commit_result_unreadable reason=unknown_version "
                       "version=%s known=%s", version, RESULT_SCHEMA_VERSION)
        return None
    return data.get("result")


# ── the claim ────────────────────────────────────────────────────────────────

async def claim_commit(db, *, operation_id: str, revision: int = 0,
                       user_id: int) -> CommitClaim:
    """Try to become the one caller allowed to write this meal.

    Returns `won=True` exactly once per (operation_id, revision). Every later
    attempt gets `won=False` and the winner's stored result.

    THE INSERT IS THE CLAIM. There is no read-then-write, because a read cannot
    see a row another worker is about to insert.

    THE FAILED INSERT UNWINDS TO A SAVEPOINT, not to the session. A plain
    `db.rollback()` discards everything the caller staged in the same
    transaction — and a duplicate is a NORMAL outcome, so losing a caller's
    prior work on it is a defect waiting for the first composite caller.
    """
    if not operation_id:
        raise ValueError("a commit claim needs an operation id")
    from sqlalchemy.exc import IntegrityError

    from db.models import MealCommit

    try:
        async with db.begin_nested():        # SAVEPOINT
            db.add(MealCommit(operation_id=operation_id,
                              operation_revision=int(revision),
                              user_id=int(user_id), status="claimed"))
            await db.flush()
    except IntegrityError:
        # Lost, and that is a normal outcome. Only the savepoint unwound;
        # whatever the caller staged before this is intact.
        existing = await _load(db, operation_id, revision)
        logger.info(
            "event=meal_commit outcome=duplicate operation=%s revision=%d "
            "— the write already happened; returning the original result",
            operation_id, revision)
        return CommitClaim(won=False, operation_id=operation_id,
                           revision=revision,
                           result=decode_result(
                               getattr(existing, "result_payload", None)))
    logger.info("event=meal_commit outcome=claimed operation=%s revision=%d",
                operation_id, revision)
    return CommitClaim(won=True, operation_id=operation_id, revision=revision)


async def record_result(db, *, operation_id: str, revision: int = 0,
                        result: Any) -> None:
    """Store what the winning write produced. Exactly once, or raise.

    Called INSIDE the same transaction as the ledger write. If the two commit
    separately, a crash between them leaves a claim with no result — and a
    retry reading it would report a commit whose rows do not exist.

    GUARDED IN SQL, NOT IN PYTHON. The update matches only a row still
    `claimed` with no payload, and any rowcount other than 1 raises:

      * no row, because the claim is missing or the ids are wrong — food would
        exist with no authoritative result, which is the invariant this module
        is for. Previously this UPDATE matched zero rows, raised nothing, and
        the transaction committed;
      * no row, because it is already committed — a second result write, which
        would quietly redefine "the original result" as "the most recent one".
    """
    from sqlalchemy import update

    from db.models import MealCommit

    payload = encode_result(result)          # refuses lossy values first
    outcome = await db.execute(
        update(MealCommit)
        .where(MealCommit.operation_id == operation_id,
               MealCommit.operation_revision == int(revision),
               MealCommit.status == "claimed",
               MealCommit.result_payload.is_(None))
        .values(result_payload=payload, status="committed"))
    if (outcome.rowcount or 0) != 1:
        existing = await _load(db, operation_id, revision)
        why = ("no claim exists" if existing is None
               else "already has a result" if existing.result_payload
               else f"claim is {existing.status!r}")
        logger.error(
            "event=meal_commit outcome=result_not_recorded operation=%s "
            "revision=%d why=%s — the ledger write must not stand",
            operation_id, revision, why)
        raise MissingCommitClaim(operation_id, int(revision), why)
    logger.info("event=meal_commit outcome=recorded operation=%s revision=%d",
                operation_id, revision)


async def existing_result(db, *, operation_id: str,
                          revision: int = 0) -> Optional[Any]:
    """What a previous commit of this (operation, revision) produced, if any."""
    row = await _load(db, operation_id, revision)
    return decode_result(getattr(row, "result_payload", None))


async def _load(db, operation_id: str, revision: int):
    from sqlalchemy import select

    from db.models import MealCommit

    res = await db.execute(
        select(MealCommit).where(
            MealCommit.operation_id == operation_id,
            MealCommit.operation_revision == int(revision)))
    return res.scalar_one_or_none()
