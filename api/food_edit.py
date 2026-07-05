"""
Native-client food entry edits — the iOS Daily tab calls these endpoints when
the user taps a logged food row and adjusts macros or removes it.

The day's totals are always recomputed server-side (via the existing
`update_food_entry` / `delete_food_entry` helpers, which call
`recompute_log_totals`), so the dashboard can never drift from the underlying
entry rows. Every successful edit also writes a short Arnie-voice confirmation
to `conversation_logs` so the chat thread reflects the change next time the
user opens the transcript — the same "Arnie acknowledges" loop the user gets
when logging through chat.

The Arnie confirmation text is also returned in the HTTP response so the iOS
client can append it to the in-memory chat transcript immediately (live
"Arnie said" feel without needing a persistent WebSocket broadcast).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.models import FoodEntry
from db.queries import (
    resolve_user, update_food_entry, delete_food_entry, log_conversation,
)

router = APIRouter(prefix="/api/v1/food", tags=["food"])


class FoodUpdateBody(BaseModel):
    parsed_food_name: Optional[str] = None
    quantity: Optional[str] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None


@router.patch("/{entry_id}")
async def update_food(
    entry_id: int,
    body: FoodUpdateBody,
    identity: str = Depends(current_identity),
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        before = await _snapshot_entry(db, entry_id)
        if before is None:
            raise HTTPException(status_code=404, detail="food entry not found")

        changes = body.model_dump(exclude_none=True)
        updated = await update_food_entry(db, entry_id, user.id, **changes)
        if updated is None:
            raise HTTPException(status_code=403, detail="not your entry")

        # Arnie-voice confirmation. Keep it short and factual — this is a
        # passive notification, not coaching. The "before" snapshot lets us
        # spell out what actually moved when nutrition fields changed.
        arnie_message = _build_update_message(before, updated, changes)
        if arnie_message:
            await log_conversation(
                db, user.id,
                raw_message="[edit_food_entry]",
                response=arnie_message,
                parsed_intent="dashboard_edit",
                source_type="dashboard_edit",
                platform="ios",   # iOS inline editor — without this it defaults to telegram
            )

        return {
            "status": "ok",
            "arnie_message": arnie_message,
            "entry": {
                "id": updated.id,
                "name": updated.parsed_food_name or "",
                "quantity": updated.quantity or "",
                "calories": round(updated.calories or 0),
                "protein": round(updated.protein or 0),
                "carbs":   round(updated.carbs or 0),
                "fats":    round(updated.fats or 0),
            },
        }


@router.delete("/{entry_id}")
async def delete_food(
    entry_id: int,
    identity: str = Depends(current_identity),
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        before = await _snapshot_entry(db, entry_id)
        if before is None:
            raise HTTPException(status_code=404, detail="food entry not found")

        ok = await delete_food_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=403, detail="not your entry")

        name = before.get("name") or "that entry"
        arnie_message = f"Saw you removed {name}. Today's totals are updated."
        await log_conversation(
            db, user.id,
            raw_message="[delete_food_entry]",
            response=arnie_message,
            parsed_intent="dashboard_delete",
            source_type="dashboard_edit",
            platform="ios",   # iOS inline editor — without this it defaults to telegram
        )

        return {"status": "ok", "arnie_message": arnie_message}


# ── helpers ─────────────────────────────────────────────────────────────────

async def _snapshot_entry(db, entry_id: int) -> Optional[dict]:
    """Snapshot the BEFORE state so the Arnie confirmation can spell out the
    delta ('protein 31 → 28'). Returns None if no entry exists."""
    row = (await db.execute(
        select(FoodEntry).where(FoodEntry.id == entry_id)
    )).scalar_one_or_none()
    if row is None:
        return None
    return {
        "name":     row.parsed_food_name,
        "quantity": row.quantity,
        "calories": round(row.calories or 0),
        "protein":  round(row.protein  or 0),
        "carbs":    round(row.carbs    or 0),
        "fats":     round(row.fats     or 0),
    }


def _build_update_message(before: dict, updated, changes: dict) -> str:
    """Pick the smallest line that actually communicates the change."""
    name = updated.parsed_food_name or before.get("name") or "that entry"
    deltas: list[str] = []
    after_macros = {
        "calories": round(updated.calories or 0),
        "protein":  round(updated.protein  or 0),
        "carbs":    round(updated.carbs    or 0),
        "fats":     round(updated.fats     or 0),
    }
    units = {"calories": "cal", "protein": "g protein", "carbs": "g carbs", "fats": "g fat"}
    for field, unit in units.items():
        if field in changes:
            old = before.get(field)
            new = after_macros[field]
            if old != new:
                deltas.append(f"{unit} {old} → {new}")
    if "quantity" in changes and changes["quantity"] != before.get("quantity"):
        deltas.append(f"quantity → {changes['quantity']}")
    if not deltas:
        return f"Saw your edit to {name}. All synced."
    return f"Saw you edited {name}: " + ", ".join(deltas) + "."
