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
import math
from dataclasses import dataclass, field
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
    #: A `MealCommitResult` when the winner recorded one — the SAME type the
    #: winner holds, so both callers answer the same question with the same
    #: object. None means the claim exists with no result yet, which is the
    #: crash window and must stay distinguishable from an empty result.
    result: Optional["MealCommitResult"] = None

    @property
    def is_duplicate(self) -> bool:
        return not self.won


# ── the result ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OutboxEvent:
    """One piece of durable post-commit work, typed BEFORE any producer exists.

    Introduced while `outbox_events` had zero producers, so an untyped
    `{"kind": ..., "payload": ...}` dict never acquires one — retrofitting
    types onto a populated queue means migrating rows; refusing dicts on an
    empty one costs nothing.

    `dedup_key` is REQUIRED. The coordinator's winner-only enqueue already
    stops a flaky network multiplying jobs, but a stable key also protects
    against the paths that arrive later and are never load-tested: manual
    replays, coordinator retries, migration bugs. A job type that genuinely
    tolerates duplicates says so explicitly with `allow_duplicates=True` —
    opting OUT of safety is a decision someone signs, not a field they forgot.

    `version` is the payload's schema version, present from day one because a
    consumer reading v1 rows after v2 ships needs to know which it holds —
    the same lesson `meal_commits.result_payload` already encodes.
    """
    kind: str
    payload: dict = field(default_factory=dict)
    dedup_key: str = ""
    version: int = 1
    allow_duplicates: bool = False

    def __post_init__(self):
        if not self.kind or not isinstance(self.kind, str):
            raise UnserializableResult(
                "an outbox event needs a kind — durable work that cannot say "
                "what it is cannot be swept")
        if not isinstance(self.payload, dict):
            raise UnserializableResult(
                f"outbox payload for {self.kind!r} is "
                f"{type(self.payload).__name__}, not a dict")
        _json_safe(self.payload, f"outbox[{self.kind}].payload")
        if not self.dedup_key and not self.allow_duplicates:
            raise UnserializableResult(
                f"outbox event {self.kind!r} has no dedup_key and does not "
                f"declare allow_duplicates — duplicate tolerance is a "
                f"decision, not a default")

    def to_payload(self) -> dict:
        return {"kind": self.kind, "payload": self.payload,
                "dedup_key": self.dedup_key, "version": self.version,
                "allow_duplicates": self.allow_duplicates}


@dataclass(frozen=True)
class MealCommitResult:
    """What one meal mutation produced, in a shape that survives storage.

    THE WINNER AND THE DUPLICATE RECEIVE THE SAME TYPE. The previous version
    stored whatever the caller passed and handed a duplicate the decoded JSON —
    so a `Decimal` became a string and a tuple became a list, and the two
    callers got structurally different answers to the same question. Text
    preserves a VALUE; it does not preserve a TYPE.

    Fixing that by tagging types would make the payload harder to read for
    every consumer in order to serve one. The simpler answer is that this IS
    the representation: both callers get a `MealCommitResult`, built from the
    same JSON, so there is nothing to reconcile.

    TOTALS ARE FINITE FLOATS KEYED BY STRINGS. That is a property of the
    RESULT, enforced at construction — not a property of serialization. A
    `Decimal` is converted here, deliberately, in one place; a generic walker
    doing it silently everywhere is what the previous version got wrong.

    Converting at `to_payload` time instead would leave a winner holding
    `Decimal("0.1")` where the duplicate rebuilt from JSON holds `0.1`. Those
    are not equal, and they are not the same type to any consumer — the exact
    winner/duplicate asymmetry this class exists to remove, moved one layer up.
    So a total that cannot be a finite float is refused at the moment it is
    built, where the caller that supplied it is still on the stack.
    """
    committed_items: tuple = ()
    updated_items: tuple = ()
    removed_items: tuple = ()
    meal_totals: dict = None
    day_totals: dict = None
    assumptions: tuple = ()
    warnings: tuple = ()
    #: BEST-EFFORT, POST-COMMIT, IN-PROCESS. Cache invalidation and the like:
    #: losing one costs a stale read that self-heals. Runs AFTER the caller
    #: commits, and a failure must never turn a committed mutation into an
    #: error.
    render_actions: tuple = ()
    #: DURABLE, IN-TRANSACTION. Work that must not be lost — memory updates,
    #: analytics, coaching analysis. The coordinator enqueues these into
    #: `background_jobs` inside the SAME transaction as the rows, so either
    #: both are durable or neither happened. Never re-enqueued on a duplicate:
    #: the original delivery already owns them.
    outbox_events: tuple = ()

    def __post_init__(self):
        # NORMALISED AT CONSTRUCTION, so the type does not depend on how the
        # object was built. Without this a winner built from lists compared
        # UNEQUAL to the duplicate rebuilt from JSON as tuples — the exact
        # winner/duplicate asymmetry this class exists to remove, reintroduced
        # one layer down and caught by its own test.
        for name in ("committed_items", "updated_items", "removed_items",
                     "assumptions", "warnings", "render_actions",
                     "outbox_events"):
            object.__setattr__(self, name, tuple(getattr(self, name) or ()))
        # REHYDRATED AT CONSTRUCTION — the third recurrence of the same
        # asymmetry (tuples vs lists, Decimal vs float, now OutboxEvent vs
        # dict): allowing storage-shaped dicts to stay dicts made a winner
        # holding OutboxEvent compare UNEQUAL to the duplicate rebuilt from
        # JSON, which breaks C6 the moment a producer exists. Dicts from
        # from_payload become the type again; the five fields are the v1
        # schema, and a shape change bumps `version` rather than growing keys
        # v1 code would silently drop.
        def _event_of(e):
            if isinstance(e, OutboxEvent):
                return e
            if isinstance(e, dict):
                return OutboxEvent(
                    kind=e.get("kind", ""),
                    payload=e.get("payload") or {},
                    dedup_key=e.get("dedup_key", "") or "",
                    version=int(e.get("version", 1)),
                    allow_duplicates=bool(e.get("allow_duplicates", False)))
            raise UnserializableResult(
                f"outbox_events entries must be OutboxEvent, got "
                f"{type(e).__name__}")
        object.__setattr__(self, "outbox_events",
                           tuple(_event_of(e) for e in self.outbox_events))
        object.__setattr__(self, "meal_totals",
                           _totals(self.meal_totals, "meal_totals"))
        object.__setattr__(self, "day_totals",
                           _totals(self.day_totals, "day_totals"))

    def to_payload(self) -> dict:
        """The canonical JSON form. Validated, not coerced."""
        return {
            "committed_items": _json_safe(list(self.committed_items),
                                          "committed_items"),
            "updated_items": _json_safe(list(self.updated_items),
                                        "updated_items"),
            "removed_items": _json_safe(list(self.removed_items),
                                        "removed_items"),
            "meal_totals": _totals(self.meal_totals, "meal_totals"),
            "day_totals": _totals(self.day_totals, "day_totals"),
            "assumptions": _json_safe(list(self.assumptions), "assumptions"),
            "warnings": _json_safe(list(self.warnings), "warnings"),
            "render_actions": _json_safe(list(self.render_actions),
                                         "render_actions"),
            "outbox_events": [e.to_payload() for e in self.outbox_events],
        }

    @classmethod
    def from_payload(cls, data) -> "MealCommitResult":
        if not isinstance(data, dict):
            raise UnserializableResult("a commit result must be an object")
        return cls(
            committed_items=tuple(data.get("committed_items") or ()),
            updated_items=tuple(data.get("updated_items") or ()),
            removed_items=tuple(data.get("removed_items") or ()),
            meal_totals=dict(data.get("meal_totals") or {}),
            day_totals=dict(data.get("day_totals") or {}),
            assumptions=tuple(data.get("assumptions") or ()),
            warnings=tuple(data.get("warnings") or ()),
            render_actions=tuple(data.get("render_actions") or ()),
            outbox_events=tuple(data.get("outbox_events") or ()),
        )


def _totals(values, path: str) -> dict:
    """Totals, as finite floats keyed by strings.

    The ONE place a Decimal is converted, and it is converted deliberately
    because totals cross a JSON boundary and both sides of that boundary agree
    they are numbers.

    Called from `__post_init__`, so this is the CONTRACT for the field rather
    than a step in writing it: an int stays an int (JSON round-trips it
    exactly), a Decimal becomes a float, and anything else is refused before a
    result carrying it can exist.
    """
    out = {}
    for key, value in (values or {}).items():
        if not isinstance(key, str):
            raise UnserializableResult(
                f"{path} key {key!r} is {type(key).__name__}, not a string")
        if isinstance(value, Decimal):
            value = float(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UnserializableResult(
                f"{path}.{key} is {type(value).__name__}, not a number")
        if isinstance(value, float) and not math.isfinite(value):
            raise UnserializableResult(f"{path}.{key} is {value}, not finite")
        out[key] = value
    return out


def _json_safe(value: Any, path: str = "result") -> Any:
    """VALIDATE, do not convert. Anything not already JSON-native is refused.

    The previous version converted — Decimal to string, datetime to string,
    tuple to list — which is why a duplicate received a different shape from
    the winner. Conversion belongs in `to_payload`, where the field is known
    and the choice is explicit.

    Three things this refuses that the converting version accepted:

      * NON-STRING DICT KEYS. `str(k)` collapsed {1: "a", "1": "b"} into one
        entry — genuine silent data loss.
      * NON-FINITE FLOATS. NaN and Infinity are not JSON, and `json.dumps`
        emits them anyway unless told not to.
      * every domain object, with the path named so the caller can fix it.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise UnserializableResult(
                f"{path} is {value}, which is not valid JSON")
        return value
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise UnserializableResult(
                    f"{path} key {key!r} is {type(key).__name__}, not a "
                    "string — stringifying it can collapse distinct keys")
        return {k: _json_safe(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v, f"{path}[{i}]") for i, v in enumerate(value)]
    raise UnserializableResult(
        f"{path} is {type(value).__name__}, which is not JSON — convert it in "
        "MealCommitResult.to_payload(), where the field is known")


def encode_result(result) -> str:
    """Versioned canonical JSON. Accepts a `MealCommitResult` or a payload."""
    payload = (result.to_payload() if isinstance(result, MealCommitResult)
               else _json_safe(result))
    return json.dumps({"schema_version": RESULT_SCHEMA_VERSION,
                       "result": payload}, allow_nan=False)


def decode_result(raw: Optional[str]) -> Optional[Any]:
    """The stored result, or None when there is none or it cannot be read.

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
                           result=_result_of(existing))
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


async def existing_result(db, *, operation_id: str, revision: int = 0
                          ) -> Optional["MealCommitResult"]:
    """What a previous commit of this (operation, revision) produced, if any."""
    return _result_of(await _load(db, operation_id, revision))


def _result_of(row) -> Optional["MealCommitResult"]:
    """The stored result as the SAME TYPE the winner held.

    Returning raw JSON here is what made the duplicate contract asymmetric: the
    winner had a result object and the duplicate got a dict.
    """
    data = decode_result(getattr(row, "result_payload", None))
    if data is None:
        return None
    try:
        return MealCommitResult.from_payload(data)
    except UnserializableResult:
        logger.warning("event=commit_result_unreadable reason=bad_shape")
        return None


async def _load(db, operation_id: str, revision: int):
    from sqlalchemy import select

    from db.models import MealCommit

    res = await db.execute(
        select(MealCommit).where(
            MealCommit.operation_id == operation_id,
            MealCommit.operation_revision == int(revision)))
    return res.scalar_one_or_none()
