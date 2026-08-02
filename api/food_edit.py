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
import logging

logger = logging.getLogger(__name__)

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
from db.database import AsyncSessionLocal
from db.models import DailyLog, FoodEntry
from db.queries import (
    resolve_user, update_food_entry, delete_food_entry, log_conversation,
)

router = APIRouter(prefix="/api/v1/food", tags=["food"])

CHANNEL = "ios_edit"
LEDGER_SOURCE = "ios_edit"


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
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        client_key = _client_key(client_request_id)
        # Same id for the ledger event and the conversation row (I1) — see
        # `_edit_turn_id`. A client key is used when sent; without one the
        # content-hash fallback is unchanged, so existing builds keep the
        # exact turn ids they have today.
        _turn_id = _edit_turn_id(user.id, entry_id,
                                 body.model_dump(exclude_none=True), client_key)
        with RequestTrace(turn_id=_turn_id, channel=CHANNEL,
                          command="update_food", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key), entry=entry_id)
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="update_food",
                        user_id=user.id, client_key=client_key,
                        payload=body, turn_id=_turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "update_food")

            if claim.replay:
                trace.note(idempotency="replay")
                trace.done()
                current = await db.get(FoodEntry, entry_id)
                if current is None:
                    raise HTTPException(status_code=404,
                                        detail="food entry not found")
                return {"status": "ok", "idempotent_replay": True,
                        "turn_id": claim.turn_id, "arnie_message": None,
                        "receipt": await _fresh_receipt(db, user, current),
                        "entry": _client_entry(current)}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            before = await _snapshot_entry(db, entry_id)
            if before is None:
                trace.done(outcome="not_found")
                raise HTTPException(status_code=404, detail="food entry not found")

            changes = _reconcile_macros(before, body.model_dump(exclude_none=True))
            with trace.stage("write"), _turn_scope(_turn_id):
                # LEDGER EVENT (P0.6): a dashboard edit is a ledger mutation
                # like any other — same history, same undo reach, `before`
                # makes it invertible. `ledger_source` moves it INSIDE the
                # row's transaction; it used to commit separately, so a crash
                # between the two left a rescaled entry whose original macros
                # existed nowhere.
                #
                # The contextvar is set by `_turn_scope`, which resets it in
                # `finally`. The bare `CURRENT_TURN_ID.set(...)` this replaces
                # never did, so the id leaked into every later write in the
                # request.
                updated = await update_food_entry(
                    db, entry_id, user.id,
                    ledger_source=LEDGER_SOURCE, claim_id=claim.record_id,
                    **changes)
            if updated is None:
                trace.done(outcome="forbidden")
                raise HTTPException(status_code=403, detail="not your entry")

            # Context-only record of the edit. The diff text is stored so the
            # model's recent-conversation window knows the board changed, but
            # it is NEVER shown: chat history skips dashboard_edit rows and
            # arnie_message returns None so the client appends nothing (Danny
            # 2026-07-23: "don't reiterate edited foods in the chat").
            context_note = _build_update_message(before, updated, changes)
            receipt = await _fresh_receipt(db, user, updated)
            _bust_briefing(user.id)
            if context_note:
                await log_conversation(
                    db, user.id,
                    raw_message="[edit_food_entry]",
                    response=context_note,
                    parsed_intent="dashboard_edit",
                    source_type="dashboard_edit",
                    platform="ios",   # iOS inline editor — without this it defaults to telegram
                    # The same id the ledger event above carries, which is what
                    # makes this edit's operation joinable to this edit's turn.
                    turn_id=_turn_id,
                )

            trace.note(entry=updated.id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {
                "status": "ok",
                "arnie_message": None,
                "turn_id": _turn_id,
                "receipt": receipt,
                "entry": _client_entry(updated),
            }


@router.delete("/{entry_id}")
async def delete_food(
    entry_id: int,
    identity: str = Depends(current_identity),
    client_request_id: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        client_key = _client_key(client_request_id)
        # One id, both writes — see the update path above.
        _turn_id = _edit_turn_id(user.id, entry_id, {"delete": True}, client_key)
        with RequestTrace(turn_id=_turn_id, channel=CHANNEL,
                          command="delete_food", user_id=user.id) as trace:
            trace.note(keyed=bool(client_key), entry=entry_id)
            try:
                with trace.stage("claim"):
                    claim = await claim_request(
                        db, channel=CHANNEL, command="delete_food",
                        user_id=user.id, client_key=client_key,
                        payload={"entry_id": entry_id}, turn_id=_turn_id)
            except (IdempotencyConflict, IdempotencyInProgress) as e:
                trace.note(idempotency=type(e).__name__)
                trace.done(outcome="conflict")
                raise _claim_failed(e, "delete_food")

            if claim.replay:
                # The row is already gone — the outcome the caller asked for.
                trace.note(idempotency="replay")
                trace.done()
                return {"status": "ok", "idempotent_replay": True,
                        "turn_id": claim.turn_id, "arnie_message": None}
            trace.note(idempotency="claimed" if claim.key else "unkeyed")

            before = await _snapshot_entry(db, entry_id)
            if before is None:
                trace.done(outcome="not_found")
                raise HTTPException(status_code=404, detail="food entry not found")

            with trace.stage("write"), _turn_scope(_turn_id):
                ok = await delete_food_entry(
                    db, entry_id, user.id,
                    ledger_source=LEDGER_SOURCE, claim_id=claim.record_id)
            if not ok:
                trace.done(outcome="forbidden")
                raise HTTPException(status_code=403, detail="not your entry")

            name = before.get("name") or "that entry"
            _bust_briefing(user.id)
            await log_conversation(
                db, user.id,
                raw_message="[delete_food_entry]",
                response=f"Removed {name} from today's log.",  # context-only, never rendered
                parsed_intent="dashboard_delete",
                source_type="dashboard_edit",
                platform="ios",   # iOS inline editor — without this it defaults to telegram
                turn_id=_turn_id,
            )

            trace.note(entry=entry_id, claim="completed_in_txn")
            trace.done()
            await trace.persist(db)
            return {"status": "ok", "arnie_message": None, "turn_id": _turn_id}


# ── helpers ─────────────────────────────────────────────────────────────────

def _client_entry(row) -> dict:
    """The entry as the iOS editor renders it. Shared by the write path and
    the replay path so a retried edit describes the row identically."""
    return {
        "id": row.id,
        "name": row.parsed_food_name or "",
        "quantity": row.quantity or "",
        "calories": round(row.calories or 0),
        "protein": round(row.protein or 0),
        "carbs":   round(row.carbs or 0),
        "fats":    round(row.fats or 0),
    }


def _edit_turn_id(user_id: int, entry_id: int, changes: dict,
                  client_key: Optional[str] = None) -> str:
    """The canonical turn id for one dashboard edit, shared by both writes.

    Built with `make_turn_id` rather than by hand so this path cannot invent a
    fourth id format — the audit already had three, none of which joined.

    ONE ID, BOTH WRITES (I1). This used to be `ios_edit:update:{entry_id}`, an
    id derived from the ENTRY, which no conversation row has ever carried, so
    the operation could never be joined to the turn that caused it — worse
    than a null, because it looks joined. Measured over 7 days, all 28
    `ios_edit` operations were unjoinable: the single largest hole in the
    turn⋈operation join. Being entry-derived it also collided with itself —
    the dashboard's double-edit produced two `ios_edit:update:2587` rows 18s
    apart.

    A client `Idempotency-Key` is used when the caller sends one. Without it
    the content-hash fallback is unchanged: an immediate retry of the SAME
    edit collapses onto one turn, while a genuinely different edit (or the
    same one an hour later) is its own. Existing builds send no key and keep
    exactly the ids they have today.
    """
    from core.turn_identity import make_turn_id
    fields = ",".join(sorted(str(k) for k in (changes or {})))
    return make_turn_id("ios_edit", client_key, user_id, f"{entry_id}|{fields}")

def _bust_briefing(user_id: int) -> None:
    """A dashboard/card edit changes the day the coach brief describes — drop
    the cached briefing so the next Coach open (and chat context block)
    rebuilds from the corrected log. Never raises."""
    try:
        from api.insights import invalidate_briefing
        invalidate_briefing(user_id)
    except Exception:
        pass


def _reconcile_macros(before: dict, changes: dict) -> dict:
    """Keep every stored row internally coherent: calories must roughly equal
    4P + 4C + 9F. The iOS editor lets a quantity rescale and a direct calorie
    edit land in one PATCH, which can ship a row like 80 cal / P5 C25 F27
    (~363 implied — Danny's truffle fries, 2026-07-23). Resolution order:

      • calories explicitly edited → calories are the user's intent anchor;
        scale the macros (sent or stored) onto it.
      • macros edited without calories → recompute calories from the macros.
      • neither/only cosmetic fields → pass through untouched.

    Rows within ±30% are left exactly as sent — normal rounding and fiber/
    alcohol slack must not trigger silent rewrites."""
    result_cal = changes.get("calories", before.get("calories"))
    p = changes.get("protein", before.get("protein")) or 0
    c = changes.get("carbs", before.get("carbs")) or 0
    f = changes.get("fats", before.get("fats")) or 0
    implied = 4 * p + 4 * c + 9 * f
    if not result_cal or result_cal <= 0 or implied <= 0:
        return changes
    ratio = result_cal / implied
    if 0.7 <= ratio <= 1.3:
        return changes
    fixed = dict(changes)
    if "calories" in changes:
        fixed["protein"] = round(p * ratio, 1)
        fixed["carbs"] = round(c * ratio, 1)
        fixed["fats"] = round(f * ratio, 1)
    elif any(k in changes for k in ("protein", "carbs", "fats")):
        fixed["calories"] = round(implied)
    return fixed


async def _snapshot_entry(db, entry_id: int) -> Optional[dict]:
    """Snapshot the BEFORE state so the Arnie confirmation can spell out the
    delta ('protein 31 → 28') AND so the ledger event is restorable (P0.6:
    REST edits leave the same history as chat edits). Returns None if no
    entry exists."""
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
        # Restore-shaped keys (mirror the executor's deleted-event payload).
        "food_name":    row.parsed_food_name,
        "meal_type":    row.meal_type,
        "daily_log_id": row.daily_log_id,
    }


async def _fresh_receipt(db, user, entry):
    """Re-run the deterministic receipt engine against the edited entry and the
    recomputed day so the chat card's coach read stays true after an edit.
    Additive response key — older clients never look for it. Never raises."""
    try:
        import pytz
        from datetime import datetime as _dtt
        from core.receipt import build_receipt
        log = (await db.execute(
            select(DailyLog).where(DailyLog.id == entry.daily_log_id)
        )).scalar_one_or_none()
        if log is None:
            return None
        prefs = getattr(user, "preferences", None)
        try:
            local_hour = _dtt.now(
                pytz.timezone(getattr(user, "timezone", None) or "UTC")).hour
        except Exception:
            local_hour = None
        return build_receipt(
            calories=float(entry.calories or 0),
            protein=float(entry.protein or 0),
            total_cal=float(log.total_calories or 0),
            total_protein=float(log.total_protein or 0),
            cal_target=getattr(prefs, "calorie_target", None) if prefs else None,
            protein_target=getattr(prefs, "protein_target", None) if prefs else None,
            local_hour=local_hour,
            confidence=getattr(entry, "confidence_score", None),
            estimated=bool(getattr(entry, "estimated_flag", False)),
            total_fats=float(log.total_fats or 0),
            fat_target=getattr(prefs, "fat_target", None) if prefs else None,
            trained_today=bool(getattr(log, "workout_completed", False)),
            carbs=float(entry.carbs) if entry.carbs is not None else None,
        )
    except Exception:
        return None


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
        return f"Updated {name}."
    return f"Updated {name}: " + ", ".join(deltas) + "."
