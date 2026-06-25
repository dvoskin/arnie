"""
Native-client exercise entry edits — the iOS Daily tab calls these when the
user swipes a logged exercise row and adjusts it or removes it.

Mirrors `api/food_edit.py`: thin endpoints over `update_exercise_entry` /
`delete_exercise_entry`, with an Arnie-voice confirmation written to the chat
log and echoed back in the response so the client can append it live.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.models import ExerciseEntry
from db.queries import (
    resolve_user, update_exercise_entry, delete_exercise_entry, log_conversation,
)

router = APIRouter(prefix="/api/v1/exercise", tags=["exercise"])


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
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        before = await _snapshot_entry(db, entry_id)
        if before is None:
            raise HTTPException(status_code=404, detail="exercise entry not found")

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

        updated = await update_exercise_entry(db, entry_id, user.id, **changes)
        if updated is None:
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

        # Convert stored kg-CSV back to lbs-CSV for the client.
        weights_lbs: Optional[str] = None
        if updated.weights:
            parts = []
            for tok in updated.weights.split(","):
                tok = tok.strip()
                if not tok: continue
                try:
                    parts.append(str(round(float(tok) * 2.20462, 1)))
                except ValueError:
                    continue
            weights_lbs = ",".join(parts) if parts else None

        return {
            "status": "ok",
            "arnie_message": arnie_message,
            "entry": {
                "id": updated.id,
                "name": updated.exercise_name or "",
                "sets": updated.sets,
                "reps": updated.reps,
                "weight": round((updated.weight or 0) * 2.20462, 1) if updated.weight else None,
                "weights": weights_lbs,
                "duration_minutes": int(updated.duration_minutes) if updated.duration_minutes else None,
                "cardio_type": updated.cardio_type,
                "rir": updated.rir,
                "notes": updated.notes,
            },
        }


@router.delete("/{entry_id}")
async def delete_exercise(
    entry_id: int,
    identity: str = Depends(current_identity),
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        before = await _snapshot_entry(db, entry_id)
        if before is None:
            raise HTTPException(status_code=404, detail="exercise entry not found")

        ok = await delete_exercise_entry(db, entry_id, user.id)
        if not ok:
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
        return {"status": "ok", "arnie_message": arnie_message}


# ── helpers ─────────────────────────────────────────────────────────────────

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
