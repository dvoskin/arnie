"""One idempotency contract for every direct-write surface (invariant I18).

Arnie already had several partial duplicate-protections, each keyed
differently: iOS in-process locks, `ConversationLog.idempotency_key` (per
outbound SEND, not per write), text-window collapsing, the structured
`ProcessedTurn` claim, executor dedup. None of them covered the tap-log REST
endpoints, so `api/quick_log.py` wrote a duplicate row for every retried
delivery — measured on deployed 433cdf39f2d0: two identical taps, two food
rows, and both ledger events stamped `turn_id = NULL`.

This module is the single contract those surfaces share.

    claim = await claim_request(db, channel="ios", command="log_food",
                                user_id=user.id, client_key=key, payload=body)
    if claim.replay:
        return claim.stored_result          # the ORIGINAL commit, not a new one
    ...write the domain rows...
    await complete_claim(db, claim, entry_id=entry.id, daily_log_id=log.id)

Three rules make it safe:

  * ABSENT client key → no claim, no deduplication. Only the client can tell a
    retry from a second helping; guessing costs the user a real meal either
    way, and dropping food is the worse failure. The turn id is still minted,
    so traceability does not depend on the client.
  * The unique index on `key` is the enforcement. `claim_request` inserts
    FIRST and lets the database reject the loser, so two workers resolve
    against Postgres rather than against a select-then-insert window.
  * A key replayed with a different payload raises `IdempotencyConflict`.
    Returning the first result would hide a client bug that is losing food.

A claim that never completed (the process died mid-write) is taken over after
`STALE_CLAIM_SECONDS` — otherwise one crash would wedge that key forever. A
claim still in flight inside that window reports `in_progress`, and the caller
turns that into a retryable 409 rather than a second write.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

logger = logging.getLogger(__name__)

# How long a claim may sit unfinished before a retry may take it over. Longer
# than the slowest write path (a food log with enrichment), short enough that
# a crashed request does not block the user's next tap for a whole minute.
STALE_CLAIM_SECONDS = 90


class IdempotencyConflict(Exception):
    """Same key, different payload — a client bug, not a retry."""


class IdempotencyInProgress(Exception):
    """The original request is still running; this delivery must not write."""


@dataclass
class Claim:
    """The caller's ticket. `replay` means the work is already committed."""
    key: str
    turn_id: str
    replay: bool = False
    record_id: Optional[int] = None
    stored_result: Optional[dict] = None


def fingerprint_of(payload: Any) -> str:
    """Stable hash of a request body. Sorted keys so field order never makes
    an identical request look like a conflicting one."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def build_key(channel: str, command: str, user_id: int, client_key: str) -> str:
    """Scope the client's opaque id so two surfaces can never collide on it."""
    return f"{channel}:{command}:{user_id}:{client_key}"


def _result_of(record) -> dict:
    return {
        "entry_id": record.result_entry_id,
        "daily_log_id": record.result_daily_log_id,
    }


#: Which ledger domain a command's write lands in, and which event types are
#: proof that write committed. Only commands whose write commits its event
#: ATOMICALLY with the row belong here — the event is then proof the row
#: reached durable storage, which is what makes reconciliation sound.
#:
#: Weight joined once it gained a ledger event of its own; before that there
#: was nothing to reconcile against and guessing would have been worse than
#: declining. Its event is `created` on first write and `updated` on a
#: same-day correction, so reconciliation accepts either.
#:
#: THE EVENT TYPES ARE PER COMMAND, not shared. A delete's proof is a
#: `deleted` event, and accepting `created` for it would let the ORIGINAL log
#: of a row stand as evidence that a later delete of that row committed —
#: which would report a delete as already done when it never ran. Each
#: command names only the events its own write can produce.
_COMMAND_DOMAIN = {
    "log_food": ("food", ("created",)),
    "log_exercise": ("exercise", ("created",)),
    "log_weight": ("weight", ("created", "updated")),
    "log_water": ("water", ("created",)),
    "update_food": ("food", ("updated",)),
    "delete_food": ("food", ("deleted",)),
    "update_exercise": ("exercise", ("updated",)),
    "delete_exercise": ("exercise", ("deleted",)),
    "update_water": ("water", ("updated",)),
    "delete_water": ("water", ("deleted",)),
}


class IdempotencyCorrupt(Exception):
    """A ledger event exists for this turn but its domain row does not."""


async def committed_result(db, record) -> Optional[dict]:
    """Did the original delivery's write actually land? Ask the ledger.

    A TIMER CANNOT ANSWER THIS. `STALE_CLAIM_SECONDS` answers "is the original
    process probably dead", which is a different fact from "did its operation
    commit" — and taking a claim over on the first while assuming the second is
    exactly how a retry writes the meal twice.

    Food and exercise commit their `created` event in the same transaction as
    the row, so an event stamped with this claim's `turn_id` IS proof the write
    happened. Returns the committed result, or None when nothing landed.

    Raises `IdempotencyCorrupt` when an event exists but its row does not. That
    is not a replay and not a fresh request; reporting either would be a lie
    about the user's data, so it fails loudly instead.
    """
    mapped = _COMMAND_DOMAIN.get(record.command or "")
    if not mapped or not record.turn_id:
        return None
    domain, event_types = mapped
    from db.models import FoodEntry, LedgerEvent

    ev = (await db.execute(
        select(LedgerEvent)
        .where(LedgerEvent.turn_id == record.turn_id,
               LedgerEvent.domain == domain,
               LedgerEvent.event_type.in_(event_types))
        .order_by(LedgerEvent.id)
    )).scalars().first()
    if ev is None or ev.entry_id is None:
        return None

    # The row-existence cross-check only applies where the write was supposed
    # to LEAVE a row. For a delete the row being gone is the success case, and
    # demanding it exist would report every completed delete as corrupt.
    if domain == "food" and "deleted" not in event_types:
        row = await db.get(FoodEntry, ev.entry_id)
        if row is None:
            logger.error(
                f"event=idempotency_corrupt turn={record.turn_id} "
                f"domain={domain} entry_id={ev.entry_id} — a created event "
                f"exists but its row does not")
            raise IdempotencyCorrupt(record.key)

    return {"entry_id": ev.entry_id, "daily_log_id": ev.daily_log_id}


async def claim_request(
    db, *, channel: str, command: str, user_id: int,
    client_key: Optional[str], payload: Any, turn_id: str,
) -> Claim:
    """Claim this logical request, or report that it is already served.

    Returns a `Claim`. `claim.replay is True` means the caller must NOT write
    and should return `claim.stored_result` verbatim.

    Raises `IdempotencyConflict` when the key was used for a different payload,
    and `IdempotencyInProgress` when the original delivery is still running.
    """
    from db.models import IdempotencyRecord

    # No client key: traceable, but not deduplicated. See the module docstring —
    # this is the deliberate branch, not an oversight.
    if not client_key:
        return Claim(key="", turn_id=turn_id, replay=False)

    key = build_key(channel, command, user_id, client_key)
    fp = fingerprint_of(payload)

    record = IdempotencyRecord(
        key=key, user_id=user_id, command=command, channel=channel,
        turn_id=turn_id, fingerprint=fp, status="in_progress",
    )
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except (OperationalError, ProgrammingError) as e:
        # The table is not there. That means `idem001` has not run — and the
        # pre-deploy migration is a Render dashboard setting this repo cannot
        # guarantee (render.yaml is reference-only), so this is a real state,
        # not a hypothetical.
        #
        # Degrade to no deduplication rather than failing the request. A
        # missing bookkeeping table must never cost the user the meal they
        # just logged; the write itself, and its turn id, do not depend on
        # this row. Duplicates become possible again until the migration runs,
        # which is strictly better than losing food.
        logger.error(
            f"event=idempotency_unavailable key={key} command={command} "
            f"err={type(e).__name__} — idem001 has not been applied; writing "
            f"WITHOUT duplicate protection")
        # NO session-level rollback. `begin_nested()` has already released the
        # savepoint on its way out, and a full `db.rollback()` here expires
        # every object loaded in this session — the next attribute access on
        # `user` then attempts IO from a sync context and dies with
        # MissingGreenlet. That is the same trap `record_ledger_event`
        # documents, and the soft-fail would have reintroduced it: the request
        # would fail anyway, just further along and with a stranger error.
        return Claim(key="", turn_id=turn_id, replay=False)
    except IntegrityError:
        # The unique index rejected us: someone else owns this key. Read what
        # they committed and answer from it.
        existing = (await db.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        )).scalar_one_or_none()
        if existing is None:
            # Rejected by the index but not visible to this transaction — the
            # winner has not committed yet. Treat as in flight.
            raise IdempotencyInProgress(key)

        if existing.fingerprint != fp:
            logger.warning(
                f"event=idempotency_conflict key={key} command={command} "
                f"— same key, different payload; refusing to serve the wrong "
                f"result")
            raise IdempotencyConflict(key)

        if existing.status == "completed":
            # A completed claim with no result reference cannot answer the one
            # question a replay exists to answer — "which row was written?" —
            # and handing back `entry_id: None` reads as success while telling
            # the client nothing. Rebuild it from the ledger and heal the row.
            if existing.result_entry_id is None:
                landed = await committed_result(db, existing)
                if landed is not None:
                    logger.warning(
                        f"event=idempotency_healed key={key} command={command} "
                        f"entry={landed.get('entry_id')} — completed claim was "
                        f"missing its result reference")
                    existing.result_entry_id = landed.get("entry_id")
                    existing.result_daily_log_id = landed.get("daily_log_id")
                    await db.commit()
            logger.info(f"event=idempotency_replay key={key} command={command}")
            return Claim(key=key, turn_id=existing.turn_id or turn_id,
                         replay=True, record_id=existing.id,
                         stored_result=_result_of(existing))

        # RECONCILE BEFORE ANYTHING ELSE. An unfinished claim does not mean the
        # work did not happen — a process can die after the write commits and
        # before the claim is marked, and older claims were completed by a
        # separate commit that had exactly that window. Ask the ledger whether
        # the operation landed; a claim whose work is committed is a REPLAY, no
        # matter how it looks or how old it is.
        landed = await committed_result(db, existing)
        if landed is not None:
            logger.warning(
                f"event=idempotency_reconciled key={key} command={command} "
                f"entry={landed.get('entry_id')} — the original delivery "
                f"committed but never completed its claim; healing it rather "
                f"than re-executing")
            existing.status = "completed"
            existing.result_entry_id = landed.get("entry_id")
            existing.result_daily_log_id = landed.get("daily_log_id")
            existing.completed_at = datetime.utcnow()
            await db.commit()
            return Claim(key=key, turn_id=existing.turn_id or turn_id,
                         replay=True, record_id=existing.id,
                         stored_result=_result_of(existing))

        # Nothing committed. Only now does the question "is the original still
        # running" matter, and only now can a takeover be safe.
        started = existing.created_at or datetime.utcnow()
        if datetime.utcnow() - started < timedelta(seconds=STALE_CLAIM_SECONDS):
            raise IdempotencyInProgress(key)

        logger.warning(
            f"event=idempotency_takeover key={key} age_s="
            f"{(datetime.utcnow() - started).total_seconds():.0f} — the "
            f"original delivery never completed")
        existing.turn_id = turn_id
        existing.created_at = datetime.utcnow()
        await db.commit()
        return Claim(key=key, turn_id=turn_id, record_id=existing.id)

    await db.commit()
    return Claim(key=key, turn_id=turn_id, record_id=record.id)


async def complete_claim(db, claim: Claim, *, entry_id: Optional[int] = None,
                         daily_log_id: Optional[int] = None) -> None:
    """Record where the committed result lives, so a replay can return it.

    Best-effort by design: the domain rows are already committed at this point,
    and failing the user's request because the bookkeeping row would not update
    would turn a successful log into an error. A claim left `in_progress` is
    recoverable — the next delivery takes it over after STALE_CLAIM_SECONDS.
    """
    if not claim.key or claim.record_id is None:
        return
    from db.models import IdempotencyRecord
    try:
        record = await db.get(IdempotencyRecord, claim.record_id)
        if record is None:
            return
        record.status = "completed"
        record.result_entry_id = entry_id
        record.result_daily_log_id = daily_log_id
        record.completed_at = datetime.utcnow()
        await db.commit()
    except Exception as e:      # pragma: no cover — bookkeeping must not throw
        logger.warning(f"event=idempotency_complete_failed key={claim.key}: {e}")
