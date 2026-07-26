"""One-tap undo for native clients — the server side of the card's Undo token.

Every food macro_card already carries the `event_id` of the ledger event
behind its write: the executor stashes it, `_logged_entry_card` puts it on the
payload, and the client renders "· Undo" from it. Nothing accepted that token.
The affordance shipped with no endpoint behind it, so a card could offer an
undo it had no way to perform.

The inversion itself is NOT reimplemented here. `core.ledger_undo` already
turns an event into its inverse plan for the conversational path ("undo that",
"bring back the fries"), and this calls the same `_invert` with the same TTLs
through `plan_for_event`. Typing undo and tapping undo have to reach the same
inverse — two ways of taking something back that behave differently is the
exact failure this codebase keeps rediscovering, and a tap is the one the user
will trust least if it surprises them.

The write goes through `execute_tool_calls`, the same executor every other
path uses, so the reversal appends its own ledger event, recomputes totals and
updates the board by the same rules as any other write. Nothing about undo is
a special case downstream.

No chat bubble. Like the dashboard edit endpoints, a direct manipulation is
recorded so the model's context knows the board moved, but does not narrate
itself into the transcript — the user tapped a button and watched it happen;
being told about it afterwards is noise.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import current_identity
from db.database import AsyncSessionLocal
from db.queries import get_or_create_today_log, log_conversation, resolve_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"])

#: Marks the conversation row so chat history skips it (see api/chat.py) while
#: the model's context still sees that the day changed.
UNDO_SOURCE_TYPE = "ledger_undo"


class UndoBody(BaseModel):
    event_id: int


@router.post("/undo")
async def undo_event(body: UndoBody,
                     identity: str = Depends(current_identity)) -> dict:
    """Invert one ledger event, named by the `event_id` its card carries."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        from core.ledger_undo import plan_for_event
        plan = await plan_for_event(db, user, body.event_id)
        if plan is None:
            # One refusal for every reason — not theirs, too old, or no safe
            # inverse. The specific cause is logged server-side by
            # `plan_for_event`; telling an unauthenticated-ish caller WHICH
            # applies would confirm the existence of another user's event.
            raise HTTPException(
                status_code=409,
                detail="that entry can no longer be undone")

        today_log = await get_or_create_today_log(db, user.id,
                                                  user.timezone or "UTC")
        from handlers.tool_executor import execute_tool_calls
        calls = plan.get("tool_calls") or []
        results = await execute_tool_calls(
            calls, user, today_log, db, UNDO_SOURCE_TYPE,
            user_message="[undo]")

        # The board is the truth, not the plan's expectation of it.
        try:
            await db.refresh(today_log)
        except Exception:
            pass

        await log_conversation(
            db, user.id,
            raw_message="[undo_entry]",
            response=(plan.get("say") or "Undone.").split("{")[0].strip()
            or "Undone.",
            parsed_intent=UNDO_SOURCE_TYPE,
            source_type=UNDO_SOURCE_TYPE,
            platform="ios",
        )

        prefs = getattr(user, "preferences", None)
        return {
            "status": "ok",
            "event_id": body.event_id,
            "action": plan.get("action") or "",
            "kinds": list(plan.get("kinds") or ()),
            "results": {k: str(v) for k, v in (results or {}).items()},
            "day": {
                "calories": int(getattr(today_log, "total_calories", 0) or 0),
                "protein": int(getattr(today_log, "total_protein", 0) or 0),
                "calorie_target": int(getattr(prefs, "calorie_target", 0) or 0)
                if prefs else 0,
                "protein_target": int(getattr(prefs, "protein_target", 0) or 0)
                if prefs else 0,
            },
        }
