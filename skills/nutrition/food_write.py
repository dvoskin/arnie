"""
Shared food-entry write path.

Before this module, only the chat `log_food` tool ran USDA/web/memory
enrichment + macro reconciliation before writing a FoodEntry. The two REST
create surfaces — iOS quick-log (`api/quick_log.py`) and the web dashboard
(`api/app.py` `POST /api/food/log`) — wrote the client's raw numbers straight
through, leaving `fiber` / `sugar` / `sodium` / `micronutrients_json` /
`meal_time` NULL and disagreeing on `estimated_flag`. That made "the same food"
a structurally different row depending on which surface logged it.

This module is the ONE place enrichment + row-shape consistency lives, so every
surface produces an identically-shaped row:

  * `build_enriched_food_kwargs()` — run the same enrichment the chat path uses
    and return the full kwargs dict for `db.queries.add_food_entry`.
  * `find_recent_duplicate()` — tight idempotency guard so a double-tapped "+
    Add" button or a double-submitted dashboard form doesn't write two rows.

The user's calories/protein still anchor the portion — enrichment never
overrides the numbers the user typed; it only fills the micronutrient
side-fields, reconciles internally-inconsistent macros, and sets a consistent
confidence + estimated flag.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


async def build_enriched_food_kwargs(
    db,
    user,
    *,
    food_name: str,
    quantity: Optional[str] = None,
    calories: float = 0,
    protein: float = 0,
    carbs: float = 0,
    fats: float = 0,
    fiber: Optional[float] = None,
    meal_type: Optional[str] = None,
    meal_time: Optional[datetime] = None,
    source_type: str = "text",
    from_photo: bool = False,
    is_packaged: bool = False,
    confidence: Optional[float] = None,
    estimated: Optional[bool] = None,
) -> dict:
    """Return the kwargs for `add_food_entry`, enriched exactly like the chat path.

    `confidence` / `estimated`: pass explicit values to override; otherwise both
    are derived from the enrichment result so a manual API log matches a chat log.
    """
    import json as _json

    # Lazy import — tool_executor imports api.* lazily inside functions, so this
    # avoids any module-load cycle when api modules import this helper.
    from handlers.tool_executor import _analyze_food

    inp = {
        "food_name": food_name,
        "quantity": quantity,
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fats": fats,
        "fiber": fiber,
        "is_packaged": is_packaged,
        "from_photo": from_photo,
    }
    analysis = await _analyze_food(db, user, food_name, inp)

    # Confidence — mirror the chat path's posture. Photos always cap at 0.75.
    if confidence is None:
        conf = {
            "user-confirmed": 0.95,
            "exact": 0.9,
            "likely": 0.8,
        }.get(analysis.confidence, 0.6)
    else:
        conf = confidence
    if from_photo:
        conf = min(conf, 0.75)

    if estimated is None:
        est = (analysis.confidence == "estimated") or from_photo
    else:
        est = estimated

    micros = getattr(analysis, "micronutrients", None)
    return dict(
        raw_input=str(inp),
        parsed_food_name=food_name,
        quantity=quantity,
        calories=analysis.calories,
        protein=analysis.protein,
        carbs=analysis.carbs,
        fats=analysis.fat,
        fiber=analysis.fiber if analysis.fiber is not None else fiber,
        sugar=analysis.sugar,
        sodium=analysis.sodium,
        micronutrients_json=_json.dumps(micros) if micros else None,
        estimated_flag=est,
        confidence_score=conf,
        source_type=source_type,
        meal_type=meal_type,
        meal_time=meal_time or datetime.utcnow(),
    )


# ── Shared edit side-effects ────────────────────────────────────────────────
# Editing a food row happens on two surfaces — the iOS native editor
# (api/food_edit.py) and the web dashboard (api/app.py). They used to diverge:
# iOS wrote an Arnie-voice confirmation to the transcript but sent no push; the
# web path fired a push but wrote nothing to the transcript. So the SAME logical
# edit produced different persisted history depending on where it happened.
# These helpers are the single source of truth for the transcript side of that,
# so both surfaces write an identically-shaped confirmation. (Push/notify stays
# surface-appropriate — the web edit notifies the user's phone; the in-app edit
# doesn't push the user a notification about their own in-app tap.)


async def snapshot_food_entry(db, entry_id: int, user_id: int):
    """Ownership-scoped BEFORE-state snapshot so a confirmation can spell out the
    delta ('protein 31 → 28'). Scoped via a join to DailyLog.user_id: an entry
    that isn't the caller's reads as None (same as not-found), so an edit
    endpoint can't be used to probe which entry IDs exist. Returns dict or None.
    """
    from sqlalchemy import select
    from db.models import FoodEntry, DailyLog
    row = (await db.execute(
        select(FoodEntry)
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(FoodEntry.id == entry_id, DailyLog.user_id == user_id)
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


def build_food_update_message(before: dict, updated, changes: dict) -> str:
    """The smallest line that actually communicates a food edit, delta-aware.
    Shared by every edit surface so the transcript wording is identical no matter
    where the edit came from."""
    name = updated.parsed_food_name or before.get("name") or "that entry"
    deltas: list[str] = []
    after_macros = {
        "calories": round(updated.calories or 0),
        "protein":  round(updated.protein  or 0),
        "carbs":    round(updated.carbs    or 0),
        "fats":     round(updated.fats     or 0),
    }
    units = {"calories": "cal", "protein": "g protein",
             "carbs": "g carbs", "fats": "g fat"}
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


async def record_food_change(db, user, message: str, *,
                             kind: str = "edit", platform: str = "ios") -> None:
    """Persist an Arnie-voice confirmation of a food edit/delete to the
    transcript so chat history reflects the change regardless of which surface
    made it. ONE writer → both surfaces produce identically-shaped rows.
    `platform` marks the origin ('ios' native editor, 'web' dashboard)."""
    if not message:
        return
    from db.queries import log_conversation
    raw = "[delete_food_entry]" if kind == "delete" else "[edit_food_entry]"
    intent = "dashboard_delete" if kind == "delete" else "dashboard_edit"
    await log_conversation(
        db, user.id,
        raw_message=raw,
        response=message,
        parsed_intent=intent,
        source_type="dashboard_edit",
        platform=platform,
    )


async def find_recent_duplicate(
    db,
    daily_log_id: int,
    food_name: str,
    quantity: Optional[str],
    calories: Optional[float],
    window_sec: int = 90,
):
    """Idempotency guard for the REST create surfaces.

    A double-tapped "+ Add" or a double-submitted dashboard form fires the same
    payload twice within a second or two. Reuse the pure `is_duplicate_food`
    matcher (normalized name + quantity + ±15% calories) over a TIGHT window so
    an accidental resend collapses to the existing row, while a legitimate
    re-add minutes later still writes a new entry. Returns the existing entry or
    None. Never raises — on any error it returns None so a lookup hiccup can't
    block a real log.
    """
    try:
        from sqlalchemy import select, desc
        from db.models import FoodEntry
        from skills.nutrition.food_dedup import is_duplicate_food

        rows = (await db.execute(
            select(FoodEntry)
            .where(FoodEntry.daily_log_id == daily_log_id)
            .order_by(desc(FoodEntry.timestamp))
            .limit(15)
        )).scalars().all()
        return is_duplicate_food(
            food_name=food_name,
            quantity=quantity,
            calories=calories,
            existing_entries=rows,
            now_utc=datetime.utcnow(),
            window_sec=window_sec,
        )
    except Exception:
        return None
