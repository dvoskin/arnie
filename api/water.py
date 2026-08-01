"""
Water-log REST endpoints for the iOS native app.

These wrap the same query helpers the chat-side `log_water_entry` tool
uses (`add_water_entry` / `update_water_entry` / `delete_water_entry` +
`recompute_water_total`), so a row logged via tap-the-glass UI is
indistinguishable from one logged via chat. The cached
`DailyLog.total_water_ml` aggregate stays in sync on every mutation.

Out of scope:
- Server-side oz/cup → ml conversion. iOS converts to ml before POSTing.
- Reading the day's water — that's already in /api/v1/day (via the
  `total_water_ml` field surfaced through `_build_stats_for_user`).

THE MUTATION CONTRACT (B2)
──────────────────────────
Every handler here now carries the same four parts as `api/quick_log.py`:
a canonical turn id, an idempotency claim, ONE transaction holding the row +
its ledger event + the claim completion, and a request trace on that turn id.

Water was the widest gap of the three iOS logging surfaces. A pour logged by
tap wrote a `WaterEntry` and NOTHING else: no ledger event (so `ledger_undo`
reached past it to a row the user had not mentioned — the same defect audit
O-1 found for food), no turn id (so the write could not be joined to the
request that caused it), and no claim (so a double tap on the Today tile, or
a retry on a flaky network, logged the glass twice).

A tap is a turn here too.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from api.auth import current_identity
from core.idempotency import (
    IdempotencyConflict,
    IdempotencyInProgress,
    claim_request,
)
from core.request_trace import RequestTrace
from core.turn_identity import make_turn_id
# ONE implementation of the contract's plumbing, imported rather than
# re-declared. `_turn_scope` leaking its contextvar and `_client_key` folding
# every keyless request onto one turn id are both real past incidents; a
# second copy of either is a second chance to reintroduce them.
from api.quick_log import _claim_failed, _client_key, _turn_scope
from db.database import AsyncSessionLocal
from db.queries import (
    add_water_entry,
    delete_water_entry,
    get_or_create_today_log,
    recompute_water_total,
    resolve_user,
    update_water_entry,
)

router = APIRouter(prefix="/api/v1/water", tags=["water"])

CHANNEL = "ios"
LEDGER_SOURCE = "water_api:ios"


class WaterLogBody(BaseModel):
    """Quick-log payload from the iOS Today tile. `amount_ml` is the SI
    canonical — iOS converts ounces / cups client-side. `context` is
    optional free-form ("after workout", "with lunch") — surfaced to the
    coach for timing-aware nudges."""
    amount_ml: float = Field(gt=0, le=5000, description="Quantity in milliliters")
    context: Optional[str] = None


class WaterUpdateBody(BaseModel):
    """PATCH payload — same shape as log but no context (edits only change
    the amount; context stays whatever was originally logged)."""
    amount_ml: float = Field(gt=0, le=5000)


@router.post("")
async def log_water(
    payload: WaterLogBody,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    """Add a single water entry for the authenticated user. Materializes
    today's `DailyLog` if it doesn't exist yet (first log of the day) and
    keeps `total_water_ml` in sync. Returns the new entry id, day-log id,
    and the post-write cached total so the client can update the tile
    without a re-fetch."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        client_key = _client_key(client_request_id)
        # The dedup signature must be per-request-meaningful: two DIFFERENT
        # pours a minute apart are not a retry of each other, and folding
        # them onto one turn id would make the second look like a replay.
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               f"water:{payload.amount_ml}")
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="log_water", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key))
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="log_water",
                        user_id=user.id, client_key=client_key,
                        payload=payload, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "log_water")

            if claim.replay:
                trace.note(idempotency="replay",
                           entry=claim.stored_result.get("entry_id"))
                # The total is read fresh rather than stored on the claim: a
                # replay answers "which row did the original write", and the
                # day's total may legitimately have moved since.
                total = None
                if claim.stored_result.get("daily_log_id"):
                    total = await recompute_water_total(
                        db, claim.stored_result["daily_log_id"])
                return {"ok": True, "idempotent_replay": True,
                        "turn_id": claim.turn_id, "total_water_ml": total,
                        **claim.stored_result}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            with trace.stage("write"), _turn_scope(turn_id):
                log = await get_or_create_today_log(db, user.id,
                                                    user.timezone or "UTC")
                # `ledger_source` makes `add_water_entry` the ONE writer of
                # the created event, inside the row's own transaction, and
                # `claim_id` completes the claim in that same transaction.
                # This surface previously wrote no event at all.
                entry = await add_water_entry(
                    db,
                    user_id=user.id,
                    daily_log_id=log.id,
                    amount_ml=payload.amount_ml,
                    context=payload.context,
                    source_type="ios",
                    ledger_source=LEDGER_SOURCE,
                    claim_id=claim.record_id,
                )
                total = await recompute_water_total(db, log.id)

            trace.note(entry=entry.id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {
                "ok": True,
                "entry_id": entry.id,
                "daily_log_id": log.id,
                "total_water_ml": total,
                "turn_id": turn_id,
            }


@router.patch("/{entry_id}")
async def update_water(
    entry_id: int,
    payload: WaterUpdateBody,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    """Update a single water entry's amount. Scoped by user — a token can
    only touch its own rows. Returns 404 if the entry doesn't exist or
    belongs to another user (uniform shape so token leakage doesn't
    expose entry existence)."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        client_key = _client_key(client_request_id)
        # Keyed on the ROW as well as the amount — editing entry 7 and
        # entry 9 to the same value are different requests.
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               f"water_edit:{entry_id}:{payload.amount_ml}")
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="update_water", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key), entry=entry_id)
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="update_water",
                        user_id=user.id, client_key=client_key,
                        payload=payload, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "update_water")

            if claim.replay:
                trace.note(idempotency="replay")
                total = None
                if claim.stored_result.get("daily_log_id"):
                    total = await recompute_water_total(
                        db, claim.stored_result["daily_log_id"])
                return {"ok": True, "idempotent_replay": True,
                        "turn_id": claim.turn_id, "total_water_ml": total,
                        **claim.stored_result}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            with trace.stage("write"), _turn_scope(turn_id):
                updated = await update_water_entry(
                    db, entry_id=entry_id, user_id=user.id,
                    amount_ml=payload.amount_ml,
                    ledger_source=LEDGER_SOURCE,
                    claim_id=claim.record_id,
                )
            if updated is None:
                # A 404 leaves the claim `in_progress` deliberately: nothing
                # was written, so there is no result to replay, and the next
                # delivery should be free to retry rather than be told it
                # already succeeded.
                trace.done(outcome="not_found")
                raise HTTPException(status_code=404,
                                    detail="water entry not found")
            total = None
            if updated.daily_log_id:
                total = await recompute_water_total(db, updated.daily_log_id)

            trace.note(entry=updated.id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {
                "ok": True,
                "entry_id": updated.id,
                "daily_log_id": updated.daily_log_id,
                "total_water_ml": total,
                "turn_id": turn_id,
            }


@router.delete("/{entry_id}")
async def delete_water(
    entry_id: int,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    """Delete a water entry. Same ownership scoping as PATCH."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        client_key = _client_key(client_request_id)
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               f"water_delete:{entry_id}")
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="delete_water", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key), entry=entry_id)
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="delete_water",
                        user_id=user.id, client_key=client_key,
                        payload={"entry_id": entry_id}, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "delete_water")

            if claim.replay:
                # A replayed delete reports the ORIGINAL success rather than
                # the 404 a second real delete would produce. The row being
                # gone is the outcome the caller asked for; answering "not
                # found" to a network retry would read as a failure.
                trace.note(idempotency="replay")
                trace.done()
                return {"ok": True, "idempotent_replay": True,
                        "turn_id": claim.turn_id}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            with trace.stage("write"), _turn_scope(turn_id):
                removed = await delete_water_entry(
                    db, entry_id=entry_id, user_id=user.id,
                    ledger_source=LEDGER_SOURCE,
                    claim_id=claim.record_id,
                )
            if not removed:
                trace.done(outcome="not_found")
                raise HTTPException(status_code=404,
                                    detail="water entry not found")

            trace.note(entry=entry_id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {"ok": True, "turn_id": turn_id}
