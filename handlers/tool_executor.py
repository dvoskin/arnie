"""
Executes the tool calls returned by the LLM, writes to DB, and returns
a human-readable result string per tool (used in multi-turn follow-ups).
"""
import logging
from typing import Dict, List, Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, DailyLog, MemoryUpdate
from db.queries import (
    add_food_entry, add_exercise_entry, add_body_metric, add_water_entry,
    reload_user,
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
        parsed = dclass.fromisoformat(date_str.strip())
        # Reject future dates — the LLM should never log forward in time.
        # Also reject implausibly old dates (>2 years back) to catch year-confusion
        # bugs (e.g. "January 1" → 2099-01-01 instead of the past Jan 1).
        if parsed > today:
            logger.warning(f"_parse_log_date: rejected future date {parsed} (today={today})")
            return None
        if (today - parsed).days > 730:
            logger.warning(f"_parse_log_date: rejected implausibly old date {parsed} (today={today})")
            return None
        return parsed
    except ValueError:
        pass
    return None


def _lbs_to_kg(weight, unit: str = "lbs"):
    """Convert a weight value to kg. Returns None for None input, passes kg through."""
    if weight is None:
        return None
    return weight * 0.453592 if (unit or "lbs").lower().strip() == "lbs" else weight


async def _resolve_log(inp: dict, user, today_log, db):
    """
    Determine which DailyLog to write to and return (target_log, past_date).

    If inp contains a parseable 'date' field pointing to a past date, get/create
    that day's log. Otherwise use today_log. Days have no open/closed state —
    every day is editable, today or past.
    """
    past_date = _parse_log_date(inp.get("date"), getattr(user, "timezone", "UTC"))
    if past_date:
        target = await get_or_create_log_for_date(db, user.id, past_date)
    else:
        target = today_log
    return target, past_date


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

    foods = [
        ((tc.get("input") or {}).get("food_name") or "").strip()
        for tc in (tool_calls or [])
        if tc.get("name") in ("log_food", "update_food_entry")
    ]
    foods = [f for f in foods if f]

    # Standalone day-clear (no re-log in the same turn) — a clean slate, ask for the rebuild.
    if "clear_day_log" in names and not (names & {"log_food", "log_exercise", "update_food_entry"}):
        return "Wiped today clean ✅|||send me what you actually had and I'll rebuild it."

    if names & {"update_food_entry", "update_exercise_entry"} and not (names & {"log_food", "log_exercise"}):
        return "Updated. ✅|||totals are resynced."

    if names & {"log_food", "update_food_entry"}:
        head = (f"{foods[0][:1].upper() + foods[0][1:]} logged." if len(foods) == 1 else "Logged.")
        tail = (f"You're at {cal}/{cal_t} cal today." if cal_t
                else f"That's {cal} cal so far today.")
        if pro_t and pro < pro_t * 0.85:
            return f"{head}|||{tail}|||Protein's at {pro}/{pro_t}g, keep it coming."
        if pro_t:
            return f"{head}|||{tail}|||{pro}/{pro_t}g protein so far. What's next?"
        return f"{head}|||{tail}|||What's next?"

    if "log_exercise" in names:
        # Mid-workout detection: if more than one exercise logged today (including this
        # turn) the user is still in session — don't imply "workout done."
        # We check the log totals: workout_completed is set after any exercise entry,
        # but we can't easily count prior entries here without a DB query. Use the tool
        # call count as a proxy — multiple log_exercise calls this turn = mid-session.
        ex_names = [
            ((tc.get("input") or {}).get("exercise_name") or "").strip()
            for tc in (tool_calls or [])
            if tc.get("name") == "log_exercise"
        ]
        ex_names = [n for n in ex_names if n]
        if len(ex_names) > 1:
            # Multi-exercise turn — stay in session mode
            return f"Logged {len(ex_names)} exercises. 💪|||What's next?"
        ex_label = ex_names[0] if ex_names else "exercise"
        # Single exercise logged — neutral, keeps workout open
        return f"{ex_label.capitalize()} logged. 💪|||What's the next set?"
    if "log_body_weight" in names:
        # Guard 1: if an exercise was also logged this turn, log_body_weight is
        # almost certainly a false positive (exercise weight mis-routed as body weight).
        # Skip the weigh-in confirmation and fall through to the generic net.
        if names & {"log_exercise"}:
            pass  # fall through — don't claim a weigh-in happened
        else:
            # Guard 2: only confirm a real numeric weigh-in. A bare log_body_weight
            # with no value (e.g. "barbells bar" mis-routed) shouldn't fabricate a
            # weigh-in message. Weight must be a positive number.
            _bw = next((tc.get("input", {}).get("weight")
                        for tc in (tool_calls or [])
                        if tc.get("name") == "log_body_weight"), None)
            try:
                _has_weight = _bw is not None and float(_bw) > 0
            except (TypeError, ValueError):
                _has_weight = False
            if _has_weight:
                return "Got your weight down. 📉|||Consistency is the whole game."
            # fall through to the generic net rather than claim a weigh-in happened
    if "log_water" in names:
        return "Water logged. 💧|||Keep sipping."
    if names & {"delete_food_entry", "delete_exercise_entry"}:
        tail = (f"You're at {cal}/{cal_t} cal now." if cal_t else f"That's {cal} cal now.")
        return f"Done, removed it.|||{tail}"
    if "update_profile" in names:
        return "Got it, locked in. 👍|||Send me what you've eaten today and we'll keep building."
    return "All set. What's next?"


# ─────────────────────────────────────────────────────────────────────────────
# INTERIM HEADS-UP BUBBLES — for tools where the typing indicator alone can't
# bridge the latency. Sent BEFORE the slow tool runs so the user gets an
# immediate "let me check that" bubble instead of dead air. Hybrid wording:
# the model's own first-pass in-voice line is preferred when present; this
# deterministic set fills in when the first pass left no text.
#
# Deterministic by design — index keyed off input length, so the same input
# always yields the same bubble. No Math/random (resume-safe + testable).
# Each line: one short bubble, in voice, no trailing answer, no promise of a
# specific finding. Lives here with deterministic_confirmation (SoC).
#
# Adding a tool: drop one entry in _TOOL_HEADS_UP_BUBBLES and add the tool
# name to NEEDS_HEADS_UP_TOOLS. The conversation pipeline picks it up.
# ─────────────────────────────────────────────────────────────────────────────

_TOOL_HEADS_UP_BUBBLES = {
    "web_search": (
        "good q — let me look that up 🔎",
        "hang on, let me check that 🔎",
        "lemme look that up real quick 🔎",
        "one sec, pulling that up 🔎",
    ),
    "search_food_database": (
        "lemme pull those macros 🩻",
        "one sec on the macros 🩻",
        "checking the database real quick",
        "give me a sec, looking that up",
    ),
    "query_history": (
        "let me pull your history 📊",
        "checking the trend, one sec 📊",
        "give me a sec to scan your data",
        "lemme look back at your numbers",
    ),
    "generate_image": (
        "drawing that up 🎨",
        "give me a sec to sketch this 🎨",
        "putting that together now",
        "one sec, working on the image",
    ),
}

# The wider set: tools that get a heads-up. Imported by the conversation
# pipeline as the gate. Distinct from _VOICED_RESULT_TOOLS (in conversation.py),
# which is the NARROWER subset whose result MUST be re-voiced — every voiced-
# result tool also needs a heads-up, but not every slow tool needs re-voicing
# (e.g. search_food_database returns macros the model logs directly).
NEEDS_HEADS_UP_TOOLS = frozenset(_TOOL_HEADS_UP_BUBBLES.keys())


def tool_heads_up(tool_name: str, seed: str | None = None) -> str:
    """One short in-voice heads-up line for a slow-tool turn. Deterministic:
    line is chosen by stable index off the seed length, so a given input
    always maps to the same bubble. Unknown tool name falls through to the
    web_search set as a safe default. Never empty."""
    bubbles = _TOOL_HEADS_UP_BUBBLES.get(tool_name) or _TOOL_HEADS_UP_BUBBLES["web_search"]
    idx = len(seed or tool_name) % len(bubbles)
    return bubbles[idx]


def search_heads_up(query: str | None = None) -> str:
    """Backward-compatible shim — pre-T1.5 callers and tests reference this name.
    Equivalent to tool_heads_up('web_search', query)."""
    return tool_heads_up("web_search", query)


def _heads_up_seed(tc: dict) -> str:
    """Pull the most relevant text field from a tool call's input for the
    deterministic heads-up index. Falls back to str(input) for unknown tools."""
    inp = tc.get("input") or {}
    name = tc.get("name")
    if name == "web_search":
        return inp.get("query") or ""
    if name == "search_food_database":
        return inp.get("food_name") or ""
    if name == "query_history":
        return f"{inp.get('metric','')}-{inp.get('period','')}"
    if name == "generate_image":
        return (inp.get("prompt") or "")[:60]
    return str(inp)[:60]


async def _analyze_food(db, user, food_name, inp):
    """
    Enrich a logged food with USDA data + recurring-food memory, returning a
    FoodAnalysis. Always falls back to the LLM's estimate if USDA/memory miss.
    """
    from core.food_intelligence import (
        analyze, normalize_name, best_candidate, is_generic_food_name,
    )
    from db.queries import get_user_food_match, upsert_user_food_match

    llm = (inp.get("calories"), inp.get("protein"), inp.get("carbs"), inp.get("fats"))
    name_norm = normalize_name(food_name)

    # A bare generic name ("protein bar", "shake") must NOT silently resolve to a
    # previously-logged specific item or a USDA guess — the coach should have asked
    # which one. Skip memory + USDA and just use the LLM's stated estimate.
    generic = is_generic_food_name(food_name)

    # 1) Recurring memory — the user's known staples (highest priority)
    memory = None
    try:
        m = (await get_user_food_match(db, user.id, name_norm)
             if (name_norm and not generic) else None)
        if m:
            memory = {
                "fdc_id": m.fdc_id, "user_confirmed": m.user_confirmed,
                "confidence": m.confidence,
                "per100g": {"calories": m.cal_100, "protein": m.protein_100,
                            "carbs": m.carbs_100, "fat": m.fat_100,
                            "fiber": m.fiber_100, "sugar": m.sugar_100,
                            "sodium": m.sodium_100},
            }
            await upsert_user_food_match(db, user.id, name_norm, food_name,
                                         m.fdc_id, memory["per100g"], m.confidence)
    except Exception as e:
        logger.warning(f"food memory lookup failed: {e}")

    # 2) USDA search (only if no memory match — saves an API call on staples).
    # Skip for generic names too: a USDA "protein bar" row is a meaningless average.
    usda = None
    if memory is None and name_norm and not generic:
        try:
            from api.usda import search_food
            candidates = await search_food(food_name, page_size=8)
            best, conf = best_candidate(food_name, candidates)
            if best:
                best["_match"] = conf
                usda = best
                # Store confident matches as recurring memory for next time
                if conf in ("exact", "likely"):
                    await upsert_user_food_match(
                        db, user.id, name_norm, food_name,
                        best.get("fdc_id"), best.get("per100g", {}), conf,
                    )
        except Exception as e:
            logger.warning(f"USDA enrichment failed: {e}")

    return analyze(food_name, inp.get("quantity"), *llm,
                   usda_candidate=usda, memory_match=memory)


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
    # Guard: log_food/log_exercise/log_water require a real daily log
    if name in ("log_food", "log_exercise", "log_water"):
        if not getattr(today_log, "id", None):
            return "Skipped — day log not yet created (onboarding incomplete)"

    if name == "log_food":
        target_log, past_date = await _resolve_log(inp, user, today_log, db)

        food_name = inp.get("food_name") or ""
        analysis = await _analyze_food(db, user, food_name, inp)

        # T2.3 — capture meal timing / alcohol / photo provenance. Photos are
        # inherently noisier than text: force estimated=True and cap confidence
        # at 0.75 regardless of what the model passed, so trend-tracking treats
        # photo logs with appropriate skepticism.
        from_photo = bool(inp.get("from_photo"))
        _conf = inp.get("confidence", 0.8)
        if from_photo:
            _conf = min(_conf, 0.75)
        # meal_time defaults to "now" so we capture WHEN, not just WHAT
        from datetime import datetime as _dt
        _meal_time = _dt.utcnow()

        await add_food_entry(
            db,
            target_log.id,
            raw_input=str(inp),
            parsed_food_name=food_name,
            quantity=inp.get("quantity"),
            calories=analysis.calories,
            protein=analysis.protein,
            carbs=analysis.carbs,
            fats=analysis.fat,
            fiber=analysis.fiber if analysis.fiber is not None else inp.get("fiber"),
            sugar=analysis.sugar,
            sodium=analysis.sodium,
            estimated_flag=(analysis.confidence == "estimated") or from_photo,
            confidence_score=_conf,
            source_type=source_type,
            meal_type=inp.get("meal_type"),
            meal_time=_meal_time,
            alcohol_units=inp.get("alcohol_units"),
            from_photo=from_photo,
        )
        await db.refresh(target_log)

        # T2.2 — auto-resolve any open food_clarification rows. The user's
        # answer arrived and the log fired; the clarification is satisfied.
        # Closing ALL open food_clarification rows is intentional: if multiple
        # are pending, the model may be answering one specific question with a
        # log, and stale ones from earlier turns shouldn't linger either.
        try:
            from db.queries import resolve_pending_questions
            await resolve_pending_questions(db, user.id, kinds=["food_clarification"])
        except Exception as e:
            logger.warning(f"food_clarification auto-resolve failed: {e}")

        date_label = f" (for {past_date})" if past_date else ""

        # Rich result so the follow-up LLM coaches on the food, not just logs it
        prefs = user.preferences
        cal_t = prefs.calorie_target if prefs else None
        pro_t = prefs.protein_target if prefs else None
        remaining = ""
        if cal_t:
            remaining += f" {cal_t - target_log.total_calories:.0f} cal left"
        if pro_t:
            remaining += f", {pro_t - target_log.total_protein:.0f}g protein to go"
        return (
            f"Logged {food_name}: {analysis.calories} cal, {analysis.protein:.0f}g protein"
            f"{date_label}. ANALYSIS: {analysis.coach_note}. "
            f"DAY TOTAL: {target_log.total_calories:.0f} cal, {target_log.total_protein:.0f}g protein"
            f"{(' (' + remaining.strip() + ')') if remaining else ''}. "
            f"Confirm what was logged: state the food, its exact cal + protein, and the day total "
            f"from DAY TOTAL above — use those numbers verbatim. Then coach on quality or goal fit. "
            f"Never skip the numbers."
        )

    elif name == "log_exercise":
        target_log, past_date = await _resolve_log(inp, user, today_log, db)

        weight = inp.get("weight")
        weight_unit = inp.get("weight_unit", "lbs")
        weight_kg = _lbs_to_kg(weight, weight_unit)

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

        exercise_name = inp.get("exercise_name") or "exercise"
        sets_val = inp.get("sets")
        reps_val = inp.get("reps")
        weight_val = inp.get("weight")
        weight_unit_val = inp.get("weight_unit", "lbs")
        cardio_type_val = inp.get("cardio_type")
        duration_val = inp.get("duration_minutes")

        # Build a concise log descriptor the LLM can echo back in the log line format
        if cardio_type_val or inp.get("is_cardio"):
            desc = f"{exercise_name}: {duration_val:.0f}min" if duration_val else exercise_name
        elif sets_val and reps_val and weight_val:
            desc = f"{exercise_name}: {sets_val}×{reps_val} @ {weight_val}{weight_unit_val}"
        elif sets_val and reps_val:
            desc = f"{exercise_name}: {sets_val}×{reps_val}"
        else:
            desc = exercise_name

        # Count how many exercise entries are now in this log (including this one)
        ex_count = len(target_log.exercise_entries or [])
        mid_workout = ex_count > 1

        mid_note = (
            "MID-WORKOUT: user is actively in session. Do NOT say 'how was the workout' or "
            "imply the session is done. Give the log line, then a short cue for the next set "
            "or next exercise. Be directive and brief — they're between sets."
            if mid_workout else
            "FIRST EXERCISE: if you have [EXERCISE HISTORY] for this movement, compare to "
            "last time and give one specific target for the next set."
        )

        return (
            f"Logged {desc}{date_label}. "
            f"Exercises in session so far: {ex_count}. "
            f"YOUR REPLY: (1) log line in format '🏋️ Bench · 3×8 @135lb' (plain text on iMessage), "
            f"(2) coaching note from history if relevant — compare weight/reps to last time. "
            f"{mid_note} "
            f"Keep it to 2 bubbles max. Never fabricate history numbers."
        )

    elif name == "log_body_weight":
        weight = inp["weight"]
        unit = inp.get("unit", "lbs")
        weight_kg = _lbs_to_kg(weight, unit)
        # T2.5 — context (morning_fasted / post_meal / evening / post_workout)
        # is captured for trend interpretation. A morning_fasted reading is
        # the gold standard; anything else carries noise the coach should
        # weight accordingly.
        context_val = inp.get("context")
        await add_body_metric(db, user.id, weight_kg, context=context_val)
        ctx_note = f" ({context_val})" if context_val else ""
        return f"Logged weight: {weight} {unit} ({weight_kg:.1f} kg){ctx_note}"

    elif name == "update_food_entry":
        if not getattr(today_log, "id", None):
            return "Skipped — no log to update"
        entry_id = inp.get("entry_id")
        if not entry_id:
            return "Missing entry_id"
        changes = {k: v for k, v in inp.items()
                   if k not in ("entry_id", "date") and v is not None}
        # Map external name → DB column
        if "food_name" in changes:
            changes["parsed_food_name"] = changes.pop("food_name")
        # date= moves the entry to another day's log — same primitive as editing a value.
        if inp.get("date"):
            move_log, target_date = await _resolve_log(inp, user, today_log, db)
            if target_date:
                changes["new_daily_log_id"] = move_log.id
        else:
            target_date = None
        entry = await q_update_food_entry(db, entry_id, user.id, **changes)
        if not entry:
            return f"No food entry #{entry_id} found in today's log."
        await db.refresh(today_log)
        moved = f", moved to {target_date}" if target_date else ""
        return (f"Updated entry #{entry_id}: {entry.parsed_food_name} → "
                f"{entry.calories:.0f}cal{moved}")

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

    elif name == "clear_day_log":
        # Wipe today's food/exercise for a clean rebuild. reset_today_log mutates the
        # same session-cached DailyLog row, so any log_food calls dispatched AFTER this
        # in the same turn accumulate correctly from zero.
        from db.queries import reset_today_log
        existed = await reset_today_log(db, user.id, getattr(user, "timezone", "UTC"))
        if getattr(today_log, "id", None):
            await db.refresh(today_log)
        return ("Today's log wiped clean — totals back to zero. Now re-log whatever they "
                "gave you." if existed else "Nothing was logged today — clean slate already.")

    elif name == "update_exercise_entry":
        if not getattr(today_log, "id", None):
            return "Skipped — no log to update"
        entry_id = inp.get("entry_id")
        if not entry_id:
            return "Missing entry_id"
        changes = {k: v for k, v in inp.items()
                   if k not in ("entry_id", "date") and v is not None}
        # Convert weight from lbs to kg for storage
        if "weight" in changes:
            changes["weight"] = _lbs_to_kg(changes["weight"])
        # date= moves the entry to another day's log (same primitive as editing it).
        if inp.get("date"):
            move_log, target_date = await _resolve_log(inp, user, today_log, db)
            if target_date:
                changes["new_daily_log_id"] = move_log.id
        else:
            target_date = None
        entry = await q_update_exercise_entry(db, entry_id, user.id, **changes)
        if not entry:
            return f"No exercise entry #{entry_id} found in today's log."
        await db.refresh(today_log)
        moved = f", moved to {target_date}" if target_date else ""
        return f"Updated exercise #{entry_id}: {entry.exercise_name}{moved}"

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
        # T2.4 — resolve to target log (today by default; supports date= for
        # past-day correction same as food/exercise).
        target_log, past_date = await _resolve_log(inp, user, today_log, db)
        ml = inp.get("amount_ml") or (inp.get("amount_oz", 0) * 29.5735)
        if ml:
            target_log.total_water_ml = (target_log.total_water_ml or 0) + ml
            await db.commit()
            # Canonical timestamped row alongside the aggregate. Failure here
            # is logged but doesn't bubble up — the aggregate is still updated
            # so the user sees their hydration progress.
            try:
                await add_water_entry(
                    db, user.id, target_log.id,
                    amount_ml=ml, context=inp.get("context"),
                    source_type=source_type,
                )
            except Exception as e:
                logger.warning(f"WaterEntry write failed (aggregate already updated): {e}")
        total_ml = target_log.total_water_ml or 0
        oz_this = round((ml or 0) / 29.5735)
        total_oz = round(total_ml / 29.5735)
        # Hydration status relative to a common ~2400ml daily target
        if total_ml >= 2000:
            hydration = "solid — well hydrated for the day"
        elif total_ml >= 1200:
            hydration = "on track"
        else:
            hydration = "still building — nudge them to keep drinking"
        return (
            f"Logged {round(ml or 0)}ml water (~{oz_this}oz). "
            f"Water total today: {round(total_ml)}ml (~{total_oz}oz). "
            f"Hydration status: {hydration}. "
            f"YOUR REPLY: 1-2 short bubbles max. Quick read on their hydration and keep moving. "
            f"Water is a low-friction log — don't over-coach it. "
            f"If they're well-hydrated, one line and done. If still low, a brief nudge."
        )

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

    elif name == "web_search":
        # GATED upstream (web_search is only in the tool list when SEARCH_ENABLED=true).
        # This path NEVER sends and NEVER returns user-facing prose — it returns only
        # an instruction-wrapped result string for the follow-up to re-voice in Arnie's
        # voice. Inherits the per-tool try/except envelope, so a Tavily outage degrades
        # to a normal tool failure ("Error: ...") instead of breaking the turn.
        from core.search import search as web_search

        sr = await web_search(inp.get("query", ""), inp.get("context", "") or "")
        if sr.error or (not sr.answer and not sr.results):
            # No usable facts — tell the model to fall back honestly, not fabricate.
            return (
                f"WEB SEARCH for '{sr.query}' returned nothing usable "
                f"({sr.error or 'no results'}). Don't fabricate a number or a source. "
                f"Give your best honest coaching read from what you already know, and say "
                f"plainly if you couldn't confirm the specific fact."
            )

        # Fold in logged injuries so anything surfaced stays safe for this user.
        injuries = (getattr(user, "injuries", None) or "").strip()
        injury_note = (
            f" The user has these logged injuries: {injuries} — bias anything you "
            f"surface toward what's safe for them, applying your usual injury/medical "
            f"caution."
            if injuries else ""
        )

        # Compact the raw facts (kept verbatim in the string — the G4 persistence seam).
        lines = []
        if sr.answer:
            lines.append(f"ANSWER: {sr.answer}")
        for i, r in enumerate(sr.results[:5], 1):
            snippet = (r.get("content") or "").strip().replace("\n", " ")
            if snippet:
                lines.append(f"[{i}] {r.get('title', '')}: {snippet[:300]}")
        facts = "\n".join(lines) if lines else "(no detail returned)"

        return (
            f"WEB SEARCH RESULTS for query '{sr.query}':\n{facts}\n\n"
            f"COACH INSTRUCTION: re-voice this in YOUR coaching voice — fold the fact "
            f"into your normal bubbles as if you already knew it. Cite nothing verbatim, "
            f"no links, no quoted blobs; the user should never see the seams of a lookup."
            f"{injury_note} If results are uncertain or conflicting, say so plainly and "
            f"give your best honest read rather than faking precision."
        )

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
            "location": "city",
            "hometown": "city",
            "home_city": "city",
            "notification_channel": "channel_preference",
            "preferred_channel": "channel_preference",
            "reminder_channel": "channel_preference",
        }
        fields = {_aliases.get(k, k): v for k, v in fields.items()}

        # Always capitalize names properly — store "Danny" not "danny"
        if "name" in fields and isinstance(fields["name"], str):
            fields["name"] = fields["name"].strip().title()

        # Normalize channel preference to exactly "telegram" or "imessage"
        if "channel_preference" in fields and isinstance(fields["channel_preference"], str):
            _v = fields["channel_preference"].strip().lower()
            if "imessage" in _v or "imsg" in _v or "iphone" in _v or "text" in _v or "message" in _v:
                fields["channel_preference"] = "imessage"
            elif "telegram" in _v or "tg" in _v:
                fields["channel_preference"] = "telegram"
            else:
                fields.pop("channel_preference")  # unrecognized → don't store junk

        _user_fields = {
            "name", "age", "sex", "height_cm", "current_weight_kg",
            "goal_weight_kg", "primary_goal", "training_experience",
            "dietary_preferences", "injuries", "timezone", "city",
            "channel_preference",
        }
        _pref_fields = {
            "coaching_style", "accountability_level", "pacing_enabled",
            "reminder_frequency", "preferred_response_length",
            "profanity_tolerance", "proactive_messaging_enabled",
            "wake_time", "sleep_time", "calorie_target", "protein_target",
            "preferred_language", "food_logging_mode",
        }
        # Separate attr: prefixed keys (→ user_attributes table) from profile fields
        attr_fields = {k[5:]: v for k, v in fields.items() if k.startswith("attr:")}
        profile_fields = {k: v for k, v in fields.items() if not k.startswith("attr:")}

        # Persist user-stated attributes immediately (confirmed, user_stated)
        if attr_fields:
            try:
                from memory.attribute_store import upsert_attribute
                for attr_key, attr_value in attr_fields.items():
                    if attr_value is not None and str(attr_value).strip():
                        await upsert_attribute(
                            db, user.id,
                            attribute_key=attr_key,
                            value=str(attr_value),
                            source="user_stated",
                            confidence="confirmed",
                        )
            except Exception as e:
                logger.error(f"Attribute upsert via update_profile failed: {e}")

        for field, value in profile_fields.items():
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
                if field == "reminder_frequency":
                    from reminders.eligibility import normalize_reminder_frequency
                    value = normalize_reminder_frequency(
                        value, user.preferences.reminder_frequency
                    )
                elif field == "food_logging_mode":
                    from core.food_intelligence import normalize_food_logging_mode
                    value = normalize_food_logging_mode(
                        value, getattr(user.preferences, "food_logging_mode", "moderate")
                    )
                setattr(user.preferences, field, value)

        # If a city was provided (and the LLM didn't explicitly set a timezone),
        # resolve it to an IANA timezone so proactive check-ins fire in local time.
        if "city" in fields and "timezone" not in fields and fields.get("city"):
            try:
                from core.timezones import resolve_timezone
                tz = resolve_timezone(str(fields["city"]))
                if tz:
                    user.timezone = tz
                    logger.info(f"Resolved city '{fields['city']}' → timezone {tz} for user {user.id}")
                else:
                    logger.info(f"Could not resolve city '{fields['city']}' to a timezone for user {user.id}")
            except Exception as e:
                logger.warning(f"City→timezone resolution failed: {e}")

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
            # Native check-in enable: every onboarding finisher gets proactive check-ins
            # on (the global PROACTIVE_MESSAGING_ENABLED switch still gates real sends).
            from db.queries import enable_check_ins
            await enable_check_ins(db, user.id)
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

    elif name == "query_history":
        from db.queries import query_history_stats
        metric = inp.get("metric", "all")
        period = inp.get("period", "last_30")
        exercise_name = inp.get("exercise_name")
        data = await query_history_stats(
            db, user.id, period, metric, exercise_name,
            getattr(user, "timezone", "UTC"),
        )
        if "error" in data:
            return f"History query error: {data['error']}"

        # Format a compact, coach-readable summary
        lines = [f"HISTORY QUERY — metric={metric}, period={period}"]
        if metric in ("calories", "all") and "avg_calories" in data:
            lines.append(
                f"Calories: avg {data['avg_calories']}/day "
                f"(range {data.get('min_calories','?')}–{data.get('max_calories','?')}) "
                f"over {data['days_with_data']} days with data"
            )
        if metric in ("protein", "all") and "avg_protein" in data:
            lines.append(f"Protein: avg {data['avg_protein']}g/day")
        if metric in ("workouts", "all") and "workout_days" in data:
            lines.append(
                f"Workouts: {data['workout_days']} strength days, "
                f"{data.get('cardio_days', 0)} cardio days out of {data['days_with_data']} days logged"
            )
        if metric == "weight" and "data" in data:
            d = data
            if d["entries"] > 1:
                lines.append(
                    f"Weight: {d['start_kg']}kg → {d['end_kg']}kg "
                    f"({d['delta_kg']:+.2f}kg) over {d['entries']} entries"
                )
                for w in d["data"][-5:]:
                    lines.append(f"  {w['date']}: {w['weight_kg']}kg")
            else:
                lines.append(f"Only {d['entries']} weight entry in this period")
        if metric == "exercise" and "data" in data:
            d = data
            lines.append(f"Exercise '{exercise_name}': {d['sessions']} sessions logged")
            for s in d["data"][-8:]:
                w = f" @ {s['weight_lbs']}lb" if s.get("weight_lbs") else ""
                lines.append(f"  {s['date']}: {s.get('sets','?')}×{s.get('reps','?')}{w}")
        if metric == "all" and "rows" in data:
            lines.append("Recent days:")
            for r in data["rows"][-7:]:
                w = "💪" if r.get("workout") else "  "
                lines.append(
                    f"  {r['date']} {w}: {r.get('calories','?')} cal, {r.get('protein','?')}g P"
                )
        return (
            "\n".join(lines) + "\n\n"
            "COACH INSTRUCTION: present this data conversationally — give the read, not a table. "
            "Highlight the trend, flag anything notable, then give one concrete next step."
        )

    elif name == "search_food_database":
        from api.usda import search_food
        from core.food_intelligence import best_candidate
        food_name = inp.get("food_name", "")
        quantity = inp.get("quantity")
        if not food_name:
            return "Missing food_name"
        try:
            candidates = await search_food(food_name, page_size=8)
        except Exception as e:
            return f"USDA search failed: {e}"
        if not candidates:
            return (
                f"USDA SEARCH: no results found for '{food_name}'. "
                f"Use your best training-data estimate and flag it as approximate."
            )
        best, conf = best_candidate(food_name, candidates)
        if not best:
            return (
                f"USDA SEARCH: found results for '{food_name}' but none matched well. "
                f"Top result: {candidates[0]['description']}. "
                f"Use your best estimate and flag it as approximate."
            )
        p100 = best.get("per100g", {})
        cal100 = p100.get("calories", "?")
        pro100 = p100.get("protein", "?")
        carb100 = p100.get("carbs", "?")
        fat100 = p100.get("fat", "?")

        # Calculate totals for the user's quantity if provided
        totals_str = ""
        if quantity and isinstance(cal100, (int, float)):
            try:
                import re as _re
                # Extract a gram weight from the quantity string (e.g. '200g', '1.5 oz')
                g_match = _re.search(r"([\d.]+)\s*g\b", quantity, _re.IGNORECASE)
                oz_match = _re.search(r"([\d.]+)\s*oz\b", quantity, _re.IGNORECASE)
                grams = None
                if g_match:
                    grams = float(g_match.group(1))
                elif oz_match:
                    grams = float(oz_match.group(1)) * 28.3495
                if grams:
                    factor = grams / 100.0
                    t_cal = round(cal100 * factor)
                    t_pro = round((pro100 or 0) * factor, 1)
                    t_carb = round((carb100 or 0) * factor, 1)
                    t_fat = round((fat100 or 0) * factor, 1)
                    totals_str = (
                        f"\nFor {quantity} (~{round(grams)}g): "
                        f"{t_cal} cal, {t_pro}g P, {t_carb}g C, {t_fat}g F"
                    )
            except Exception:
                pass

        return (
            f"USDA SEARCH RESULT for '{food_name}' (match confidence: {conf}):\n"
            f"Matched: {best.get('description', food_name)}"
            f"{' — ' + best.get('brand', '') if best.get('brand') else ''}\n"
            f"Per 100g: {cal100} cal | {pro100}g protein | {carb100}g carbs | {fat100}g fat"
            f"{totals_str}\n\n"
            f"COACH INSTRUCTION: use these numbers when logging this food. "
            f"If the match confidence is 'estimated' or 'likely', mention the number might be "
            f"slightly off but it's the best available data."
        )

    elif name == "store_attribute":
        from memory.attribute_store import upsert_attribute
        key = inp.get("key", "")
        value = inp.get("value", "")
        if not key or not value:
            return "Missing key or value"
        try:
            await upsert_attribute(
                db, user.id,
                attribute_key=key,
                value=str(value),
                unit=inp.get("unit"),
                category=inp.get("category"),
                source="conversation",
                confidence="confirmed",
            )
            display_key = key.replace("_", " ").title()
            unit_str = f" {inp['unit']}" if inp.get("unit") else ""
            return f"Stored attribute '{display_key}': {value}{unit_str}"
        except Exception as e:
            logger.error(f"store_attribute failed: {e}")
            return f"Failed to store attribute: {e}"

    elif name == "track_metric":
        from db.queries import upsert_user_metric
        metric_name = inp.get("metric_name", "")
        value = inp.get("value")
        if not metric_name or value is None:
            return "Missing metric_name or value"
        unit = inp.get("unit")
        # Resolve date
        recorded_at = None
        if inp.get("date"):
            past = _parse_log_date(inp["date"], getattr(user, "timezone", "UTC"))
            if past:
                from datetime import datetime as _dt
                recorded_at = _dt.combine(past, _dt.min.time())
        try:
            await upsert_user_metric(db, user.id, metric_name, float(value), unit, recorded_at)
            unit_str = f" {unit}" if unit else ""
            display_name = metric_name.replace("_", " ")
            return (
                f"Tracked {display_name}: {value}{unit_str}. "
                f"COACH INSTRUCTION: acknowledge the metric briefly (1 bubble), "
                f"give context if relevant (e.g. if resting HR or HRV, relate to recovery/training), "
                f"then keep moving. Don't over-explain."
            )
        except Exception as e:
            logger.error(f"track_metric failed: {e}")
            return f"Failed to track metric: {e}"

    elif name == "note_food_clarification":
        # T2.2 — record an open clarifying question so the model SEES it next
        # turn (via [PENDING CLARIFICATION] context block) and doesn't re-ask.
        # Auto-resolves on log_food / update_food_entry below.
        question = (inp.get("question") or "").strip()
        food_item = (inp.get("food_item") or "").strip()
        if not question or not food_item:
            return "Missing question or food_item"
        try:
            from db.queries import record_pending_question, get_open_pending_question
            # Use kind="food_clarification" — invisible to reminders module
            # (which only re-asks profile_stats + conversation_hook).
            existing = await get_open_pending_question(db, user.id, "food_clarification")
            if existing and existing.item_referenced == food_item:
                # Already pending for this item — update the question text in place.
                existing.question = question
                existing.item_referenced = food_item
                await db.commit()
            else:
                # Either no pending or a DIFFERENT item — create new (the existing
                # row from another item stays open; the executor's log_food auto-
                # resolve will close it when its item lands).
                pq = await record_pending_question(
                    db, user.id, kind="food_clarification",
                    question=question, tier="casual", hook_style="question",
                )
                pq.item_referenced = food_item
                # Carry kind metadata in tier? No — separate field.
                if inp.get("kind"):
                    pq.tier = inp["kind"]  # piggyback metadata on tier field
                await db.commit()
            return (
                f"Recorded pending clarification: '{question}' about '{food_item}'. "
                f"Don't say anything about saving it — just ask the question naturally."
            )
        except Exception as e:
            logger.error(f"note_food_clarification failed: {e}")
            return f"Failed to record clarification: {e}"

    elif name == "schedule_check_in":
        send_at = (inp.get("send_at") or "").strip()
        directive = (inp.get("directive") or "").strip()
        if not send_at or not directive:
            return "Missing send_at or directive"
        try:
            from scheduler.proactive_scheduler import schedule_one_shot_checkin
            from db.queries import resolve_send_target
            target_id = await resolve_send_target(db, user)
            ok = schedule_one_shot_checkin(
                user_id=user.id,
                telegram_id=target_id,
                directive=directive,
                send_at_local=send_at,
                user_timezone=getattr(user, "timezone", "UTC"),
            )
            if ok:
                return (
                    f"Check-in scheduled for {send_at} (user local time). "
                    f"COACH INSTRUCTION: confirm the check-in naturally in 1 short bubble — "
                    f"'I'll check back in at {send_at}' or similar. Don't repeat the full directive."
                )
            else:
                return (
                    f"Could not schedule check-in for {send_at} — time may be in the past "
                    f"or scheduler not running. "
                    f"COACH INSTRUCTION: tell the user you weren't able to set the reminder "
                    f"and ask them to log the result manually when they're done."
                )
        except Exception as e:
            logger.error(f"schedule_check_in failed: {e}")
            return f"Scheduling failed: {e}"

    return "Unknown tool"
