"""
Executes the tool calls returned by the LLM, writes to DB, and returns
a human-readable result string per tool (used in multi-turn follow-ups).
"""
import logging
from typing import Dict, List, Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, DailyLog, MemoryUpdate
from db.queries import (
    add_food_entry, add_exercise_entry, add_body_metric,
    close_daily_log, reopen_daily_log, reload_user,
    update_food_entry as q_update_food_entry,
    delete_food_entry as q_delete_food_entry,
    update_exercise_entry as q_update_exercise_entry,
    delete_exercise_entry as q_delete_exercise_entry,
    get_or_create_log_for_date,
)
from handlers.onboarding import is_onboarding_complete
from memory.memory_manager import append_memory_update, init_memory

logger = logging.getLogger(__name__)


def _parse_log_date(date_str: str | None, user_timezone: str = "UTC"):
    """
    Parse a natural or explicit date string into a date object.
    Returns None if date_str is None (meaning use today's log).
    Supports: "yesterday", "2 days ago", "3 days ago", "YYYY-MM-DD"
    """
    if not date_str:
        return None
    import pytz
    from datetime import date, timedelta, datetime as dt
    try:
        tz = pytz.timezone(user_timezone or "UTC")
        today = dt.now(tz).date()
    except Exception:
        from datetime import date
        today = date.today()

    s = date_str.strip().lower()
    if s == "yesterday":
        return today - timedelta(days=1)
    if s in ("2 days ago", "two days ago"):
        return today - timedelta(days=2)
    if s in ("3 days ago", "three days ago"):
        return today - timedelta(days=3)
    # Try YYYY-MM-DD
    try:
        from datetime import date as dclass
        return dclass.fromisoformat(date_str.strip())
    except ValueError:
        pass
    return None


def deterministic_confirmation(tool_calls, log, prefs) -> str:
    """
    Build a meaningful confirmation from what was actually logged, used when the
    LLM returns no text after a tool call. Never a bare "done." — the user always
    learns what happened and where they stand. Returns ||| multi-bubble text.
    """
    names = {tc.get("name") for tc in (tool_calls or [])}
    cal = round(getattr(log, "total_calories", 0) or 0)
    pro = round(getattr(log, "total_protein", 0) or 0)
    cal_t = getattr(prefs, "calorie_target", None) if prefs else None
    pro_t = getattr(prefs, "protein_target", None) if prefs else None

    if names & {"log_food", "update_food_entry"}:
        if cal_t:
            tail = f"you're at {cal}/{cal_t} cal today."
        else:
            tail = f"that's {cal} cal so far today."
        # surface protein if they have a target and are notably behind
        if pro_t and pro < pro_t * 0.85:
            return f"logged.|||{tail}|||protein's at {pro}/{pro_t}g — keep it coming."
        return f"logged.|||{tail}"

    if "log_exercise" in names:
        return "logged your workout. 💪"
    if "log_body_weight" in names:
        return "got your weight down. 📉"
    if "log_water" in names:
        return "water logged. 💧"
    if names & {"delete_food_entry", "delete_exercise_entry"}:
        return "removed it."
    if "update_profile" in names:
        return "updated. 👍"
    if "close_day" in names:
        return "day closed. nice work today."
    return "got it."


async def execute_tool_calls(
    tool_calls: List[Dict[str, Any]],
    user: User,
    today_log: DailyLog,
    db: AsyncSession,
    source_type: str = "text",
) -> Dict[str, Any]:
    """
    Execute each tool call and return {tool_name: result}.
    Result is usually a string (description for follow-up LLM context), but
    can be a dict like {"_type": "image", "url": ..., "caption": ...} which
    the pipeline detects and sends as a photo to the user.
    """
    results = {}

    for tc in tool_calls:
        name = tc["name"]
        inp = tc["input"]
        try:
            results[name] = await _dispatch(
                name, inp, user, today_log, db, source_type
            )
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            results[name] = f"Error: {e}"

    return results


async def _dispatch(name, inp, user, today_log, db, source_type):  # noqa: C901
    # Guard: log_food/log_exercise/log_water/close_day require a real daily log
    if name in ("log_food", "log_exercise", "log_water", "close_day"):
        if not getattr(today_log, "id", None):
            return "Skipped — day log not yet created (onboarding incomplete)"

    if name == "log_food":
        # Support logging to a past date
        past_date = _parse_log_date(inp.get("date"), getattr(user, "timezone", "UTC"))
        if past_date:
            target_log = await get_or_create_log_for_date(db, user.id, past_date)
        else:
            target_log = today_log

        await add_food_entry(
            db,
            target_log.id,
            raw_input=str(inp),
            parsed_food_name=inp.get("food_name"),
            quantity=inp.get("quantity"),
            calories=inp.get("calories"),
            protein=inp.get("protein"),
            carbs=inp.get("carbs"),
            fats=inp.get("fats"),
            fiber=inp.get("fiber"),
            estimated_flag=inp.get("estimated", False),
            confidence_score=inp.get("confidence", 0.8),
            source_type=source_type,
        )
        await db.refresh(target_log)
        date_label = f" (for {past_date})" if past_date else ""
        return (
            f"Logged {inp.get('food_name')}: {inp.get('calories')} cal{date_label}. "
            f"Day total: {target_log.total_calories:.0f} cal, "
            f"{target_log.total_protein:.0f}g protein"
        )

    elif name == "log_exercise":
        past_date = _parse_log_date(inp.get("date"), getattr(user, "timezone", "UTC"))
        if past_date:
            target_log = await get_or_create_log_for_date(db, user.id, past_date)
        else:
            target_log = today_log

        weight = inp.get("weight")
        weight_unit = inp.get("weight_unit", "lbs")
        weight_kg = (weight * 0.453592) if (weight and weight_unit == "lbs") else weight

        is_cardio = inp.get("is_cardio", False) or bool(inp.get("cardio_type"))
        await add_exercise_entry(
            db,
            target_log.id,
            exercise_name=inp.get("exercise_name"),
            sets=inp.get("sets"),
            reps=str(inp.get("reps", "")) if inp.get("reps") else None,
            weight=weight_kg,
            rir=inp.get("rir"),
            duration_minutes=inp.get("duration_minutes"),
            cardio_type=inp.get("cardio_type"),
            source_type=source_type,
            is_cardio=is_cardio,
        )
        await db.refresh(target_log)
        date_label = f" (for {past_date})" if past_date else ""
        return f"Logged {inp.get('exercise_name')}{date_label}"

    elif name == "log_body_weight":
        weight = inp["weight"]
        unit = inp.get("unit", "lbs")
        weight_kg = weight * 0.453592 if unit == "lbs" else weight
        await add_body_metric(db, user.id, weight_kg)
        return f"Logged weight: {weight} {unit} ({weight_kg:.1f} kg)"

    elif name == "update_food_entry":
        if not getattr(today_log, "id", None):
            return "Skipped — no log to update"
        entry_id = inp.get("entry_id")
        if not entry_id:
            return "Missing entry_id"
        changes = {k: v for k, v in inp.items() if k != "entry_id" and v is not None}
        # Map external name → DB column
        if "food_name" in changes:
            changes["parsed_food_name"] = changes.pop("food_name")
        entry = await q_update_food_entry(db, entry_id, user.id, **changes)
        if not entry:
            return f"No food entry #{entry_id} found in today's log."
        await db.refresh(today_log)
        return f"Updated entry #{entry_id}: {entry.parsed_food_name} → {entry.calories:.0f}cal"

    elif name == "delete_food_entry":
        if not getattr(today_log, "id", None):
            return "Skipped — no log to update"
        entry_id = inp.get("entry_id")
        if not entry_id:
            return "Missing entry_id"
        ok = await q_delete_food_entry(db, entry_id, user.id)
        if not ok:
            return f"No food entry #{entry_id} found."
        await db.refresh(today_log)
        return f"Removed food entry #{entry_id}"

    elif name == "update_exercise_entry":
        if not getattr(today_log, "id", None):
            return "Skipped — no log to update"
        entry_id = inp.get("entry_id")
        if not entry_id:
            return "Missing entry_id"
        changes = {k: v for k, v in inp.items() if k != "entry_id" and v is not None}
        # Convert weight from lbs to kg for storage
        if "weight" in changes:
            changes["weight"] = changes["weight"] * 0.453592
        entry = await q_update_exercise_entry(db, entry_id, user.id, **changes)
        if not entry:
            return f"No exercise entry #{entry_id} found in today's log."
        await db.refresh(today_log)
        return f"Updated exercise #{entry_id}: {entry.exercise_name}"

    elif name == "delete_exercise_entry":
        if not getattr(today_log, "id", None):
            return "Skipped — no log to update"
        entry_id = inp.get("entry_id")
        if not entry_id:
            return "Missing entry_id"
        ok = await q_delete_exercise_entry(db, entry_id, user.id)
        if not ok:
            return f"No exercise entry #{entry_id} found."
        await db.refresh(today_log)
        return f"Removed exercise entry #{entry_id}"

    elif name == "log_water":
        ml = inp.get("amount_ml") or (inp.get("amount_oz", 0) * 29.5735)
        if ml:
            today_log.total_water_ml = (today_log.total_water_ml or 0) + ml
            await db.commit()
        return f"Logged {ml:.0f} ml water"

    elif name == "close_day":
        await close_daily_log(db, today_log.id)
        return "Day closed"

    elif name == "reopen_day":
        if not getattr(today_log, "id", None):
            return "Skipped — no log to reopen"
        await reopen_daily_log(db, today_log.id)
        today_log.status = "open"
        return "Day reopened"

    elif name == "generate_image":
        from core.llm import generate_image
        url = await generate_image(inp["prompt"])
        if not url:
            return "Image generation failed (no API key or rate limited)."
        # Return a special dict the pipeline can detect and send as a photo
        return {
            "_type": "image",
            "url": url,
            "caption": inp.get("caption", ""),
        }

    elif name == "update_memory":
        await append_memory_update(
            user.telegram_id,
            inp.get("updates", ""),
            inp.get("reasoning", ""),
        )
        db.add(MemoryUpdate(
            user_id=user.id,
            update_summary=inp.get("updates", "")[:500],
            reasoning=inp.get("reasoning", ""),
        ))
        await db.commit()
        return "Memory updated"

    elif name == "update_profile":
        fields = inp.get("fields", {})

        # Normalize common LLM field name variations to actual DB column names
        _aliases = {
            "first_name": "name",
            "biological_sex": "sex",
            "gender": "sex",
            "weight_kg": "current_weight_kg",
            "current_weight": "current_weight_kg",
            "weight": "current_weight_kg",
            "goal": "primary_goal",
            "goal_type": "primary_goal",
            "experience": "training_experience",
            "experience_level": "training_experience",
            "dietary_restrictions": "dietary_preferences",
            "restrictions": "dietary_preferences",
        }
        fields = {_aliases.get(k, k): v for k, v in fields.items()}

        # Always capitalize names properly — store "Danny" not "danny"
        if "name" in fields and isinstance(fields["name"], str):
            fields["name"] = fields["name"].strip().title()

        _user_fields = {
            "name", "age", "sex", "height_cm", "current_weight_kg",
            "goal_weight_kg", "primary_goal", "training_experience",
            "dietary_preferences", "injuries", "timezone",
        }
        _pref_fields = {
            "coaching_style", "accountability_level", "pacing_enabled",
            "reminder_frequency", "preferred_response_length",
            "profanity_tolerance", "proactive_messaging_enabled",
            "wake_time", "sleep_time", "calorie_target", "protein_target",
            "preferred_language",
        }
        for field, value in fields.items():
            # Never let null/empty values overwrite already-saved fields.
            # onboarding_completed is a boolean flag — always allow it.
            if field != "onboarding_completed" and (value is None or value == ""):
                logger.warning(f"update_profile: skipping null/empty value for field '{field}'")
                continue
            if field == "onboarding_completed":
                user.onboarding_completed = bool(value)
            elif field in _user_fields:
                setattr(user, field, value)
            elif field in _pref_fields and user.preferences:
                setattr(user.preferences, field, value)

        await db.commit()
        user = await reload_user(db, user.id)

        # SERVER-SIDE AUTO-COMPLETION — onboarding now needs only the minimal
        # essentials (name, weight, goal). age/sex/height + targets come later
        # via proactive collection. Flip onboarding_completed the moment the
        # essentials are in.
        if not user.onboarding_completed and is_onboarding_complete(user):
            logger.info(f"Server-side auto-completing onboarding for user {user.id}")
            user.onboarding_completed = True
            await db.commit()
            user = await reload_user(db, user.id)

        # AUTO-CALC TARGETS — the moment all stats are present (weight, height,
        # age, sex, goal) and no targets are set yet, compute them automatically.
        # This fires when the post-onboarding nudges finish collecting age/sex/height.
        _targets_msg = ""
        prefs_check = user.preferences
        if prefs_check and prefs_check.calorie_target is None:
            from core.targets import calc_targets
            t = calc_targets(user)
            if t:
                prefs_check.calorie_target = t["calories"]
                prefs_check.protein_target = t["protein"]
                await db.commit()
                user = await reload_user(db, user.id)
                logger.info(f"Auto-calculated targets for user {user.id}: "
                            f"{t['calories']}cal/{t['protein']}p")
                _targets_msg = (
                    f" | TARGETS JUST CALCULATED: {t['calories']} cal, {t['protein']}g protein. "
                    f"Tell the user you now have their full picture and these are their daily "
                    f"targets — briefly and naturally, in your voice."
                )

        # When onboarding completes, set sensible preference defaults + init memory
        if user.onboarding_completed and user.preferences:
            p = user.preferences
            if not p.coaching_style:
                p.coaching_style = "balanced"
            if not p.accountability_level:
                p.accountability_level = "medium"
            if not p.wake_time:
                p.wake_time = "07:00"
            if not p.sleep_time:
                p.sleep_time = "23:00"
            if p.proactive_messaging_enabled is None:
                p.proactive_messaging_enabled = True
            await db.commit()
            user = await reload_user(db, user.id)
            # Seed both the legacy memory and the adaptive Profile Matrix
            await init_memory(user)
            try:
                from memory.profile_manager import ensure_profile
                await ensure_profile(user)
            except Exception as e:
                logger.warning(f"ensure_profile failed: {e}")

        return f"Profile updated: {list(fields.keys())}{_targets_msg}"

    return "Unknown tool"
