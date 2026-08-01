"""
Native-client exercise entry edits — the iOS Daily tab calls these when the
user swipes a logged exercise row and adjusts it or removes it.

Mirrors `api/food_edit.py`: thin endpoints over `update_exercise_entry` /
`delete_exercise_entry`, with an Arnie-voice confirmation written to the chat
log and echoed back in the response so the client can append it live.

THE MUTATION CONTRACT (B2)
──────────────────────────
Both handlers carry the four parts — canonical turn id, idempotency claim,
ONE transaction holding the row + its ledger event + the claim completion,
and a request trace.

These already recorded history, via `record_surface_mutation` AFTER the write
had committed. Two commits with a crash window between them: the process dies
and the row is changed while the record of what it used to be exists nowhere,
so the edit is neither invertible nor auditable. `record_surface_mutation`
also minted a SYNTHETIC turn id from `(surface, event_type, entry_id)`, which
is stable rather than unique — every edit of entry 41 shared one id, so the
turn↔operation join could not tell one from another. The event now rides
inside the write's own transaction and carries the request's real turn id.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import current_identity
from api.quick_log import _claim_failed, _client_key, _turn_scope
from core.idempotency import (
    IdempotencyConflict,
    IdempotencyInProgress,
    claim_request,
)
from core.request_trace import RequestTrace
from core.turn_identity import make_turn_id
from db.database import AsyncSessionLocal
from db.models import ExerciseEntry
from db.queries import (
    resolve_user, update_exercise_entry, delete_exercise_entry, log_conversation,
)

router = APIRouter(prefix="/api/v1/exercise", tags=["exercise"])

CHANNEL = "ios"
LEDGER_SOURCE = "ios_edit"


class ExerciseUpdateBody(BaseModel):
    exercise_name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight: Optional[float] = None      # iOS sends lbs; DB stores kg → convert before update
    # Per-set load as a CSV string in lbs (e.g. "225,235,245"). Converted to
    # CSV-in-kg before storage so it stays parallel to `weight`.
    weights: Optional[str] = None
    duration_minutes: Optional[float] = None
    cardio_type: Optional[str] = None
    rir: Optional[int] = None
    notes: Optional[str] = None


@router.patch("/{entry_id}")
async def update_exercise(
    entry_id: int,
    body: ExerciseUpdateBody,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        client_key = _client_key(client_request_id)
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               f"ex_edit:{entry_id}")
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="update_exercise", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key), entry=entry_id)
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="update_exercise",
                        user_id=user.id, client_key=client_key,
                        payload=body, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "update_exercise")

            if claim.replay:
                # The edit is already applied; report the row as it stands
                # rather than applying it a second time.
                trace.note(idempotency="replay")
                trace.done()
                current = await db.get(ExerciseEntry, entry_id)
                if current is None:
                    raise HTTPException(status_code=404,
                                        detail="exercise entry not found")
                return {"status": "ok", "idempotent_replay": True,
                        "turn_id": claim.turn_id, "arnie_message": None,
                        "entry": _client_entry(current)}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            before = await _snapshot_entry(db, entry_id)
            if before is None:
                trace.done(outcome="not_found")
                raise HTTPException(status_code=404,
                                    detail="exercise entry not found")

            changes = body.model_dump(exclude_none=True)
            # iOS sends lbs; the DB stores weight in kg. Convert before the helper.
            if "weight" in changes:
                changes["weight"] = float(changes["weight"]) / 2.20462
            # CSV in lbs → CSV in kg (same pattern, per-set). Blank tokens dropped.
            if "weights" in changes:
                lbs_parts = [p.strip() for p in str(changes["weights"]).split(",") if p.strip()]
                kg_parts: list[str] = []
                for p in lbs_parts:
                    try:
                        kg_parts.append(str(round(float(p) / 2.20462, 2)))
                    except ValueError:
                        continue
                changes["weights"] = ",".join(kg_parts) if kg_parts else None

            with trace.stage("write"), _turn_scope(turn_id):
                # `ledger_source` folds the `updated` event into the row's own
                # transaction and stamps it with the turn id above, replacing
                # the post-commit `record_surface_mutation` call and its
                # synthetic id.
                updated = await update_exercise_entry(
                    db, entry_id, user.id,
                    ledger_source=LEDGER_SOURCE, claim_id=claim.record_id,
                    **changes)
            if updated is None:
                trace.done(outcome="forbidden")
                raise HTTPException(status_code=403, detail="not your entry")

            arnie_message = _build_update_message(before, updated, changes)
            if arnie_message:
                await log_conversation(
                    db, user.id,
                    raw_message="[edit_exercise_entry]",
                    response=arnie_message,
                    parsed_intent="dashboard_edit",
                    source_type="dashboard_edit",
                    platform="ios",   # iOS inline editor — without this it defaults to telegram
                )

            trace.note(entry=updated.id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {
                "status": "ok",
                "arnie_message": None,  # context-only; chat never re-narrates dashboard edits
                "turn_id": turn_id,
                "entry": _client_entry(updated),
            }


@router.delete("/{entry_id}")
async def delete_exercise(
    entry_id: int,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        client_key = _client_key(client_request_id)
        turn_id = make_turn_id(CHANNEL, client_key, user.id,
                               f"ex_delete:{entry_id}")
        with RequestTrace(turn_id=turn_id, channel=CHANNEL,
                          command="delete_exercise", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key), entry=entry_id)
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="delete_exercise",
                        user_id=user.id, client_key=client_key,
                        payload={"entry_id": entry_id}, turn_id=turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "delete_exercise")

            if claim.replay:
                # The row is already gone — the outcome the caller asked for.
                # A 404 here would report a retry of a success as a failure.
                trace.note(idempotency="replay")
                trace.done()
                return {"status": "ok", "idempotent_replay": True,
                        "turn_id": claim.turn_id, "arnie_message": None}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            before = await _snapshot_entry(db, entry_id)
            if before is None:
                trace.done(outcome="not_found")
                raise HTTPException(status_code=404,
                                    detail="exercise entry not found")

            with trace.stage("write"), _turn_scope(turn_id):
                ok = await delete_exercise_entry(
                    db, entry_id, user.id,
                    ledger_source=LEDGER_SOURCE, claim_id=claim.record_id)
            if not ok:
                trace.done(outcome="forbidden")
                raise HTTPException(status_code=403, detail="not your entry")

            name = before.get("name") or "that exercise"
            arnie_message = f"Removed {name} from today's training log."
            await log_conversation(
                db, user.id,
                raw_message="[delete_exercise_entry]",
                response=arnie_message,
                parsed_intent="dashboard_delete",
                source_type="dashboard_edit",
                platform="ios",   # iOS inline editor — without this it defaults to telegram
            )
            trace.note(entry=entry_id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            # context-only
            return {"status": "ok", "arnie_message": None, "turn_id": turn_id}


# ── helpers ─────────────────────────────────────────────────────────────────

def _client_entry(row) -> dict:
    """The row in the client's units — kg back to lbs, per-set CSV included.

    Shared by the write path and the replay path so a retried edit describes
    the row exactly the way the original response did.
    """
    weights_lbs: Optional[str] = None
    if row.weights:
        parts = []
        for tok in row.weights.split(","):
            tok = tok.strip()
            if not tok: continue
            try:
                parts.append(str(round(float(tok) * 2.20462, 1)))
            except ValueError:
                continue
        weights_lbs = ",".join(parts) if parts else None
    return {
        "id": row.id,
        "name": row.exercise_name or "",
        "sets": row.sets,
        "reps": row.reps,
        "weight": round((row.weight or 0) * 2.20462, 1) if row.weight else None,
        "weights": weights_lbs,
        "duration_minutes": int(row.duration_minutes) if row.duration_minutes else None,
        "cardio_type": row.cardio_type,
        "rir": row.rir,
        "notes": row.notes,
    }

async def _snapshot_entry(db, entry_id: int) -> Optional[dict]:
    row = (await db.execute(
        select(ExerciseEntry).where(ExerciseEntry.id == entry_id)
    )).scalar_one_or_none()
    if row is None:
        return None
    return {
        "name":     row.exercise_name,
        "sets":     row.sets,
        "reps":     row.reps,
        "weight_lbs": round((row.weight or 0) * 2.20462, 1) if row.weight else None,
        "duration_minutes": int(row.duration_minutes) if row.duration_minutes else None,
        "cardio_type": row.cardio_type,
        "rir":      row.rir,
        # Restore-shaped keys (mirror the executor's deleted-event payload).
        "exercise_name": row.exercise_name,
        "weight":        row.weight,
        "daily_log_id":  row.daily_log_id,
    }


def _build_update_message(before: dict, updated, changes: dict) -> str:
    name = updated.exercise_name or before.get("name") or "that exercise"
    deltas: list[str] = []
    if "sets" in changes and updated.sets != before.get("sets"):
        deltas.append(f"sets {before.get('sets')} → {updated.sets}")
    if "reps" in changes and updated.reps != before.get("reps"):
        deltas.append(f"reps {before.get('reps')} → {updated.reps}")
    if "weight" in changes:
        new_lbs = round((updated.weight or 0) * 2.20462, 1) if updated.weight else 0
        if new_lbs != (before.get("weight_lbs") or 0):
            deltas.append(f"weight {before.get('weight_lbs') or 0}lb → {new_lbs}lb")
    if "duration_minutes" in changes and updated.duration_minutes != before.get("duration_minutes"):
        deltas.append(f"duration → {int(updated.duration_minutes or 0)} min")
    if "rir" in changes and updated.rir != before.get("rir"):
        deltas.append(f"RIR → {updated.rir}")
    if not deltas:
        return f"Updated {name}."
    return f"Updated {name}: " + ", ".join(deltas) + "."
