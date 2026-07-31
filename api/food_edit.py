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

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import resolve_user, update_food_entry, delete_food_entry
from skills.nutrition.food_write import (
    snapshot_food_entry, build_food_update_message, record_food_change,
)

router = APIRouter(prefix="/api/v1/food", tags=["food"])


class FoodUpdateBody(BaseModel):
    parsed_food_name: Optional[str] = None
    quantity: Optional[str] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    meal_type: Optional[str] = None


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

        before = await snapshot_food_entry(db, entry_id, user.id)
        if before is None:
            raise HTTPException(status_code=404, detail="food entry not found")

        changes = body.model_dump(exclude_none=True)
        updated = await update_food_entry(db, entry_id, user.id, **changes)
        if updated is None:
            # Ownership already enforced by the snapshot above; a None here means
            # the row vanished between reads. 404 (not 403) so this endpoint never
            # discloses "exists but not yours" vs "doesn't exist".
            raise HTTPException(status_code=404, detail="food entry not found")

        # Arnie-voice confirmation → transcript. Shared writer with the web
        # dashboard so both surfaces record an identically-shaped edit.
        arnie_message = build_food_update_message(before, updated, changes)
        await record_food_change(db, user, arnie_message, kind="edit", platform="ios")

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

        before = await snapshot_food_entry(db, entry_id, user.id)
        if before is None:
            raise HTTPException(status_code=404, detail="food entry not found")

        ok = await delete_food_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="food entry not found")

        name = before.get("name") or "that entry"
        arnie_message = f"Removed {name} from today's log."
        await record_food_change(db, user, arnie_message, kind="delete", platform="ios")

        return {"status": "ok", "arnie_message": arnie_message}


# Snapshot / message-builder / transcript-writer live in
# skills.nutrition.food_write so the iOS editor and the web dashboard share one
# implementation and can't drift apart again.
