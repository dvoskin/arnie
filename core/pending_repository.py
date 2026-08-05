"""Durable pending operations, with every write conditional on the revision.

`conversation.payload_json` is a question's payload on a `pending_questions`
row. This is the OPERATION — its own lifecycle, its own revision, and its own
concurrency control — and it is deliberately not built on that column.

OPTIMISTIC CONCURRENCY IS THE POINT. Every write carries the revision the
writer READ:

    UPDATE pending_operations SET ... , revision = :expected + 1
    WHERE operation_id = :id AND revision = :expected

A stale writer matches no row and is told so. Without that, two turns arriving
seconds apart both read revision 3, both write revision 4, and the second
silently erases the first — which is the same class as the read-then-write race
the commit boundary exists to close, one table over.

SHADOW ONLY. `PENDING_OPERATION_PERSIST_SHADOW` gates writing, and nothing
reads these rows for a live decision yet. The legacy path stays authoritative.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

#: The serialized payload's shape. An unknown FUTURE field must not break a
#: read, so unknown keys are preserved rather than rejected; a payload whose
#: version we cannot interpret fails closed instead of being guessed at.
SCHEMA_VERSION = 1


class StaleRevision(RuntimeError):
    """A write was attempted against a revision that is no longer current."""

    def __init__(self, operation_id: str, expected: int, actual=None):
        super().__init__(
            f"{operation_id}: expected revision {expected}, "
            f"found {actual if actual is not None else 'a different one'}")
        self.operation_id, self.expected, self.actual = (
            operation_id, expected, actual)


class UnreadablePayload(ValueError):
    """A persisted payload that cannot be interpreted. Fails closed."""


# ── flags ────────────────────────────────────────────────────────────────────
# SEPARATE, so persistence, reads and commit enforcement can be disabled
# independently. One flag for every phase means a problem in any of them costs
# all three.

def _on(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in (
        "1", "true", "yes", "on")


def persist_shadow_enabled() -> bool:
    return _on("PENDING_OPERATION_PERSIST_SHADOW")


def read_shadow_enabled() -> bool:
    return _on("PENDING_OPERATION_READ_SHADOW")


def commit_shadow_enabled() -> bool:
    return _on("COMMIT_COORDINATOR_SHADOW")


def commit_enforce_enabled() -> bool:
    return _on("COMMIT_COORDINATOR_ENFORCE")


# ── serialization ────────────────────────────────────────────────────────────

def encode_payload(*, items=(), unresolved_fields=(), assumptions=()) -> str:
    """Canonical JSON, versioned. Never a Python repr — a persisted
    `dataclasses.asdict` string is unreadable by any other language and
    unversioned by construction."""
    return json.dumps({
        "schema_version": SCHEMA_VERSION,
        "items": list(items),
        "unresolved_fields": list(unresolved_fields),
        "assumptions": list(assumptions),
    }, default=str)


def decode_payload(raw: Optional[str]) -> dict:
    """Read a payload, or fail closed.

    A malformed payload raises rather than returning an empty operation: an
    empty one looks like "nothing was pending", which is how a held meal
    disappears. Unknown keys are KEPT, so a row written by a newer build
    round-trips through an older one without losing what it does not
    understand.
    """
    if not raw:
        return {"schema_version": SCHEMA_VERSION, "items": [],
                "unresolved_fields": [], "assumptions": []}
    try:
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("event=pending_payload_unreadable reason=json_error")
        raise UnreadablePayload("payload is not valid JSON") from exc
    if not isinstance(data, dict):
        logger.warning("event=pending_payload_unreadable reason=not_an_object")
        raise UnreadablePayload("payload is not an object")
    version = data.get("schema_version")
    if version is None or int(version) > SCHEMA_VERSION:
        logger.warning(
            "event=pending_payload_unreadable reason=unknown_version "
            "version=%s known=%s", version, SCHEMA_VERSION)
        raise UnreadablePayload(f"unknown payload schema_version {version!r}")
    data.setdefault("items", [])
    data.setdefault("unresolved_fields", [])
    data.setdefault("assumptions", [])
    return data


# ── repository ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SaveOutcome:
    """A typed result rather than a bare bool: "it did not save" and "somebody
    else got there first" need different handling and used to look alike."""
    ok: bool
    revision: int
    conflict: bool = False


async def create_operation(db, *, operation_id: str, user_id: int,
                           status: str, storage_status: str,
                           domain: str = "food", mode: str = "",
                           source_turn_id: str = "",
                           payload: Optional[str] = None,
                           expires_at: Optional[datetime] = None):
    """Insert a new operation at revision 0."""
    from db.models import PendingOperation

    row = PendingOperation(
        operation_id=operation_id, user_id=int(user_id), domain=domain,
        status=status, storage_status=storage_status, revision=0,
        mode=mode or None, source_turn_id=source_turn_id or None,
        canonical_payload=payload if payload is not None else encode_payload(),
        expires_at=expires_at, updated_at=datetime.utcnow())
    db.add(row)
    await db.flush()
    return row


async def load_operation(db, operation_id: str):
    from sqlalchemy import select

    from db.models import PendingOperation

    res = await db.execute(select(PendingOperation).where(
        PendingOperation.operation_id == operation_id))
    return res.scalar_one_or_none()


async def load_open_for_user(db, user_id: int, domain: str = "food") -> list:
    """Open operations only — `storage_status` is used for the QUERY, never to
    reconstruct `status`, which is read from its own column."""
    from sqlalchemy import select

    from db.models import PendingOperation

    res = await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == int(user_id),
        PendingOperation.domain == domain,
        PendingOperation.storage_status == "active"))
    return list(res.scalars().all())


async def save_revision(db, *, operation_id: str, expected_revision: int,
                        **changes) -> SaveOutcome:
    """Write, but only if nobody else has written since we read.

    The revision is bumped by the same statement that checks it, so the check
    and the write cannot be separated by another worker.
    """
    from sqlalchemy import update

    from db.models import PendingOperation

    values = dict(changes)
    values["revision"] = int(expected_revision) + 1
    values["updated_at"] = datetime.utcnow()
    result = await db.execute(
        update(PendingOperation)
        .where(PendingOperation.operation_id == operation_id,
               PendingOperation.revision == int(expected_revision))
        .values(**values))
    if (result.rowcount or 0) != 1:
        current = await load_operation(db, operation_id)
        actual = getattr(current, "revision", None)
        logger.info(
            "event=pending_revision_conflict operation=%s expected=%d "
            "actual=%s — the write was refused, not applied",
            operation_id, expected_revision, actual)
        return SaveOutcome(ok=False, revision=actual or -1, conflict=True)
    return SaveOutcome(ok=True, revision=int(expected_revision) + 1)


async def mark_committing(db, *, operation_id: str, expected_revision: int,
                          commit_key: str = "") -> SaveOutcome:
    return await save_revision(
        db, operation_id=operation_id, expected_revision=expected_revision,
        status="committing", storage_status="active",
        commit_key=commit_key or None)


async def mark_committed(db, *, operation_id: str, expected_revision: int,
                         commit_key: str) -> SaveOutcome:
    if not commit_key:
        raise ValueError("a committed operation requires a commit_key")
    return await save_revision(
        db, operation_id=operation_id, expected_revision=expected_revision,
        status="committed", storage_status="consumed",
        commit_key=commit_key, committed_at=datetime.utcnow())


async def mark_cancelled(db, *, operation_id: str, expected_revision: int,
                         reason: str) -> SaveOutcome:
    if not reason:
        raise ValueError("a cancelled operation requires a reason")
    return await save_revision(
        db, operation_id=operation_id, expected_revision=expected_revision,
        status="cancelled", storage_status="cancelled",
        terminal_reason=reason)


async def mark_expired(db, *, operation_id: str, expected_revision: int
                       ) -> SaveOutcome:
    return await save_revision(
        db, operation_id=operation_id, expected_revision=expected_revision,
        status="expired", storage_status="expired",
        terminal_reason="expired")


async def record_failure(db, *, operation_id: str, expected_revision: int,
                         error: str, attempt_count: int,
                         max_attempts: int = 3) -> SaveOutcome:
    """Count the attempt and land in the right terminal state in ONE write.

    Mirrors `PendingOperation.record_failure` in `core.semantics`: exhaustion
    is reached by recording the final attempt, never asserted, and a retryable
    failure always carries its error.
    """
    if not error:
        raise ValueError("a recorded failure must carry its error")
    attempts = int(attempt_count) + 1
    exhausted = attempts >= int(max_attempts)
    return await save_revision(
        db, operation_id=operation_id, expected_revision=expected_revision,
        status="failed" if exhausted else "retryable_failure",
        storage_status="cancelled" if exhausted else "active",
        attempt_count=attempts, last_error=error,
        terminal_reason="attempts_exhausted" if exhausted else None)
