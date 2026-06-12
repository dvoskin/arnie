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
    get_recent_weights,
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
    weight = float(weight)
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


# ─────────────────────────────────────────────────────────────────────────────
# RECOVERY MESSAGES — short user-facing fallback lines for failure / dead-end
# paths. The user should NEVER be left staring at silence or a confusing reply
# when the pipeline trips. Every recovery line:
#   • acknowledges the snag honestly (no system-blaming, no pretending)
#   • gives ONE concrete next move ("resend", "say it again simpler")
#   • is short (1-2 bubbles, |||-split)
#   • is in Arnie's voice (sentence case, no em dashes, no helpdesk filler)
# This is a retention play: the user knows what happened and what to do,
# instead of wondering whether Arnie is broken.
#
# Variance is deterministic (seed-length index) so the same input always
# yields the same line — resume-safe, testable, and avoids the same bubble
# firing back-to-back when seeds differ.
# ─────────────────────────────────────────────────────────────────────────────

_RECOVERY_BUBBLES = {
    # A tool call returned Error:/Skipped/Failed to — the action did NOT land.
    "tool_error": (
        "That didn't go through.|||resend and it usually catches the second try.",
        "Something hiccupped saving that.|||try once more, should land cleanly.",
        "That one didn't save right.|||resend it and I'll get it.",
    ),
    # The whole LLM turn errored out (exception in chat()). Pipeline can't
    # produce a coached reply — fall back to an honest "try again" line.
    "llm_error": (
        "Something went sideways on my end.|||resend that and I'll catch it.",
        "Hit a snag on that one.|||send it again, I'll be back on track.",
        "Wires crossed for a sec.|||resend it and I'll get it cleanly.",
    ),
    # Degenerate fallback: model produced no text AND no tool calls (or every
    # repair attempt failed). We have nothing to coach on — admit confusion
    # and ask for a simpler restate.
    "stall": (
        "Got a bit confused on that one.|||say it again, simpler if you can.",
        "Didn't quite land for me.|||resend it, shorter is fine.",
        "Lost the thread there.|||try one more time and I'll catch it.",
    ),
}


def recovery_message(kind: str, seed: str = "") -> str:
    """Short user-facing recovery line for failure / dead-end fallbacks.

    Acknowledges the snag in Arnie's voice + gives one concrete recovery
    action (resend, simplify, try again). Helps retention — the user knows
    what went wrong and what to do, instead of staring at silence or a
    confusing reply.

    kind: 'tool_error' (a save failed), 'llm_error' (the whole turn errored),
          'stall' (no usable response_text). Unknown kinds fall back to
          'stall' so a typo can't return empty.
    seed: text the deterministic index keys off — same input maps to the
          same variant. Pass the user's message or a tool-input string.
    """
    pool = _RECOVERY_BUBBLES.get(kind) or _RECOVERY_BUBBLES["stall"]
    idx = (len(seed or "") + len(kind)) % len(pool)
    return pool[idx]


def deterministic_confirmation(tool_calls, log, prefs, tool_results=None) -> str:
    """
    Build a meaningful confirmation from what was actually logged, used when the
    LLM returns no text after a tool call. Never a bare "done." — the user always
    learns what happened and where they stand. Returns ||| multi-bubble text.

    tool_results (optional) is the name→result-string map from execute_tool_calls,
    used to surface real data (e.g. USDA macros from search_food_database) when the
    model produced no text — so a macro lookup never dead-ends on a generic line.
    """
    names = {tc.get("name") for tc in (tool_calls or [])}
    tool_results = tool_results or {}

    # If the tool result for the active logging call is an error, surface that
    # honestly instead of confirming a success that didn't happen. This is the
    # silent-failure mode: user sees "logged it ✅", dashboard is empty.
    # Route through recovery_message for varied phrasing — same seed (tool name
    # + first 32 chars of error) always returns the same line for resume safety.
    for k in ("log_food", "log_exercise", "log_water", "log_body_weight"):
        if k in names:
            r = tool_results.get(k)
            if isinstance(r, str) and (
                r.startswith("Error:") or r.startswith("Skipped")
                or r.startswith("Failed to")
            ):
                return recovery_message("tool_error", seed=f"{k}:{r[:32]}")

    # A macro lookup that produced no model text — surface the actual numbers from
    # the USDA result rather than a content-free "all set." The user asked about a
    # food's macros (or to log it); they must leave with the numbers, never a blank.
    # Only when the SEARCH was the action — if a log also ran, fall through to the
    # logged-confirmation branch below (the food is already on the board).
    if "search_food_database" in names and not (
        names & {"log_food", "update_food_entry"}
    ):
        macro = _macros_from_search(tool_results.get("search_food_database", ""))
        food = next(
            ((tc.get("input") or {}).get("food_name", "").strip()
             for tc in (tool_calls or []) if tc.get("name") == "search_food_database"),
            "",
        )
        if macro:
            head = f"{food[:1].upper() + food[1:]}: {macro}" if food else macro
            return f"{head}|||want me to log it?"
        # No parseable macros (USDA miss) — still don't dead-end.
        return (f"Couldn't pin exact macros on {food or 'that'}.|||"
                "tell me roughly what it was and I'll log my best estimate.")
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
        # Pull the item name from the tool call so the confirmation names what changed.
        up_names = [
            ((tc.get("input") or {}).get("food_name") or
             (tc.get("input") or {}).get("exercise_name") or "").strip()
            for tc in (tool_calls or [])
            if tc.get("name") in ("update_food_entry", "update_exercise_entry")
        ]
        up_names = [n for n in up_names if n]
        if cal_t:
            up_tail = f"You're at {cal} / {cal_t} calories now."
        else:
            up_tail = f"That's {cal} calories now."
        if up_names:
            item = up_names[0][:1].upper() + up_names[0][1:]
            return f"{item} fixed. ✅|||{up_tail}"
        return f"Fixed. ✅|||{up_tail}"

    if names & {"log_food", "update_food_entry"}:
        # Dedup-aware fallback: if the LAST log_food tool result starts
        # with "Already on the board:", the Phase 1.2 guard fired and
        # the model tried to re-log a prior-turn food. Don't claim a
        # fresh log — acknowledge the dup. Same shape as the parallel
        # log_exercise branch below.
        last_food_result = str(tool_results.get("log_food", "") or "")
        if last_food_result.startswith("Already on the board"):
            tail = (f"You're at {cal} / {cal_t} calories today." if cal_t
                    else f"That's {cal} calories so far today." if cal
                    else "Send the next meal.")
            return f"Got it — already on the board. 🍳|||{tail}"
        if len(foods) == 1:
            head = f"{foods[0][:1].upper() + foods[0][1:]} logged."
        elif foods:
            head = "Logged: " + ", ".join(foods) + "."
        else:
            head = "Meal logged."
        if cal_t:
            if cal >= cal_t:
                tail = f"You're at {cal} / {cal_t} calories today — keep the rest controlled."
            elif cal >= cal_t * 0.85:
                tail = f"You're at {cal} / {cal_t} calories today, tight finish."
            else:
                tail = f"You're at {cal} / {cal_t} calories today, good room left."
        else:
            tail = f"That's {cal} calories so far today."
        if pro_t and pro < pro_t * 0.85:
            return f"{head}|||{tail}|||Protein's at {pro} / {pro_t}g — go protein-first next."
        if pro_t:
            return f"{head}|||{tail}|||{pro} / {pro_t}g protein so far. What's next?"
        return f"{head}|||{tail}|||Send the next meal."

    if "log_exercise" in names:
        # Dedup-aware fallback: if the LAST log_exercise tool result starts with
        # "Already on the board" (the prefix format_dedup_result emits), the
        # guard fired and the model tried to re-log an already-saved set. Don't
        # claim a fresh log in that case — the existing entries are already on
        # the board. tool_results is name→last-result, so when MULTIPLE
        # log_exercise calls fire in one turn we only see the last one; this
        # check is conservative (we may under-claim) but never false-positive.
        last_ex_result = str(tool_results.get("log_exercise", "") or "")
        if last_ex_result.startswith("Already on the board"):
            return "Got it — already on the board. 💪|||What's next?"
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
                return _weight_fallback(_bw)
            # fall through to the generic net rather than claim a weigh-in happened
    if "log_water" in names:
        # Same dedup-aware shape as log_food / log_exercise above.
        last_water_result = str(tool_results.get("log_water", "") or "")
        if last_water_result.startswith("Already on the board"):
            return "Got it — already on the board. 💧|||Keep sipping."
        return "Water logged. 💧|||Keep sipping."
    if names & {"delete_food_entry", "delete_exercise_entry"}:
        tail = (f"You're at {cal} / {cal_t} calories now." if cal_t
                else f"That's {cal} calories now.")
        return f"Done, removed it.|||{tail}"
    if "update_profile" in names:
        # Make the response contextual to what was actually changed — "send me your
        # food" is a non-sequitur if the user just toggled reminders or changed mode.
        up_tc = next((tc for tc in (tool_calls or []) if tc.get("name") == "update_profile"), None)
        fields = ((up_tc.get("input") or {}).get("fields") or {}) if up_tc else {}
        if "food_logging_mode" in fields:
            mode = str(fields["food_logging_mode"]).lower()
            if mode == "quick":
                return "Got it — logging on best estimate from now.|||Send me what you've eaten."
            if mode == "strict":
                return "Got it — confirming details before every log.|||Send me what you've eaten."
            return "Logging mode updated.|||Send me what you've eaten."
        if "proactive_messaging_enabled" in fields:
            on = fields["proactive_messaging_enabled"]
            return ("Reminders on. I'll check in.|||What's today looking like?" if on
                    else "Reminders off. I'll be here when you log.|||Send me what you've eaten.")
        if "reminder_frequency" in fields:
            freq = str(fields.get("reminder_frequency", "")).lower()
            return ("Noted, dialing back.|||I'll be here when you log." if freq == "less"
                    else "Got it, checking in more.|||What's today looking like?")
        if any(k in fields for k in ("calorie_target", "protein_target")):
            return "Targets locked in. ✅|||Send me what you've eaten and we'll track against them."
        # Generic profile update (timezone, language, attributes, etc.)
        return "Got it, locked in. ✅|||Send me what you've eaten today."
    # Generic net — only hit for tool turns with no specific branch above. Never a
    # content-free "all set"; keep the ball in their court with the day's standing.
    tail = (f"You're at {cal} / {cal_t} calories today." if cal_t
            else f"That's {cal} calories so far today." if cal
            else "What do you want to log next?")
    return f"Got that.|||{tail}"


def _weight_fallback(weight_seed: Any = "") -> str:
    """Last-resort body-weight confirmation, varied so one phrase doesn't haunt users."""
    fallbacks = (
        "Weigh-in logged.|||Same conditions next time gives us the cleanest trend.",
        "Weight logged.|||One point is noise, the trend is the signal.",
        "Scale check logged.|||We'll judge it by the rolling trend, not one reading.",
    )
    seed = str(weight_seed or "")
    idx = sum(ord(c) for c in seed) % len(fallbacks)
    return fallbacks[idx]


def _macros_from_search(result: str) -> str:
    """Pull a short macro summary from a search_food_database result string.
    Prefers the per-quantity 'For X' totals line, falls back to per-100g.
    Returns '' if neither is present (USDA miss / error result)."""
    if not result:
        return ""
    import re as _re
    # "For 1 bar (~50g): 180 cal, 20g P, 4g C, 9g F"
    m = _re.search(r"For .+?:\s*(\d[\d.]*\s*cal[^\n]*)", result)
    if m:
        return m.group(1).strip()
    # "Per 100g: 360 cal | 40g protein | 8g carbs | 18g fat"
    m = _re.search(r"Per 100g:\s*([^\n]+)", result)
    if m:
        return f"{m.group(1).strip()} (per 100g)"
    return ""


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

# EMERGENCY FALLBACK ONLY. The model is instructed to ALWAYS write its own
# in-voice heads-up before a slow-tool call. These deterministic lines fire
# ONLY when the model skipped text entirely (just emitted the tool_use
# block with no preceding text) — a rare degenerate case. They still need to
# sound like Arnie, not a customer-service rep: "one sec." reads as a
# helpdesk holding pattern. Use short, in-voice phrasings tied to what's
# actually being looked up (food/history/image), so when this fallback
# DOES fire the user just sees a slightly terser Arnie, not a different bot.
#
# VARIANCE: each tool has 6 short generic variants. The deterministic index
# (seed length % len(bubbles)) maps different tool inputs to different
# bubbles, so two consecutive lookups don't always emit the same line. Each
# stays ≤30 chars / no "lemme"/"real quick"/"hang tight"/"hang on" filler —
# pinned by test_deterministic_fallback_is_intentionally_generic. The wit
# and personality lives in the model-written heads-up (see SLOW TOOLS in
# core/prompts/arnie.py), NOT in these emergency strings.
_TOOL_HEADS_UP_BUBBLES = {
    "web_search": (
        "checking that.",
        "looking it up.",
        "checking the source.",
        "finding it.",
        "looking that up.",
        "checking it now.",
    ),
    "search_food_database": (
        "pulling the macros.",
        "grabbing the numbers.",
        "checking the macros.",
        "looking those up.",
        "finding the macros.",
        "macro check.",
    ),
    "query_history": (
        "checking your log.",
        "pulling that up.",
        "scrolling back.",
        "checking the log.",
        "digging it up.",
        "finding it.",
    ),
    "generate_image": (
        "working on it.",
        "rendering that.",
        "drawing it up.",
        "putting it together.",
        "drawing it now.",
        "rendering now.",
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


_BRANDED_RE = __import__("re").compile(
    r"\b(?:[A-Z][a-z']+\s+){1,4}(?:bar|shake|drink|protein|yogurt|cereal|"
    r"oats|granola|sauce|spread|butter|milk|powder|chips|cookies|crackers)\b"
)


def _looks_branded(food_name: str) -> bool:
    """Safety-net heuristic when the model forgot to set is_packaged=True.

    Targets ProperNoun-Brand + common-package-noun patterns (e.g. "Quest Bar",
    "Elmhurst Clean Protein", "Liquid IV"). Conservative — only matches when at
    least one capitalized brand-like token precedes a known package word.
    Never matches "chicken breast" / "white rice" — those are lowercase generics.
    """
    if not food_name or len(food_name) < 6:
        return False
    return bool(_BRANDED_RE.search(food_name))


async def _web_lookup_packaged(food_name: str, quantity) -> dict | None:
    """Tavily lookup for label-accurate macros on a branded packaged product.

    Returns a candidate dict shaped like USDA's (`per100g`, `_match`) on success,
    or None on miss / outage. NEVER raises — Tavily already returns graceful
    empty results, and any parse failure falls through to None so the existing
    USDA → LLM cascade still runs.
    """
    try:
        from core.search import search as _search
        q = f"{food_name} nutrition facts label calories protein carbs fat"
        if quantity:
            q += f" per {quantity}"
        result = await _search(q)
        text = (result.answer or "") + "\n" + "\n".join(
            (r.get("content") or "")[:600] for r in (result.results or [])[:3]
        )
        if not text.strip():
            return None
        import re as _re
        # Look for "X calories ... Yg protein ... Zg carbs ... Wg fat" near each other
        cal_m = _re.search(r"(\d{2,4})\s*(?:cal(?:ories)?|kcal)\b", text, _re.I)
        pro_m = _re.search(r"(\d{1,3})\s*g\s*(?:of\s*)?protein\b", text, _re.I)
        if not (cal_m and pro_m):
            return None
        cal = float(cal_m.group(1))
        pro = float(pro_m.group(1))
        carb_m = _re.search(r"(\d{1,3})\s*g\s*(?:of\s*)?(?:carb|carbohydrate)", text, _re.I)
        fat_m = _re.search(r"(\d{1,3})\s*g\s*(?:of\s*)?(?:fat|total fat)\b", text, _re.I)
        carbs = float(carb_m.group(1)) if carb_m else 0.0
        fat = float(fat_m.group(1)) if fat_m else 0.0
        # Estimate serving grams from calorie density. Most packaged foods sit
        # at 100-500 cal/100g; assume ~200 for the back-out (rough — used only
        # for fiber/sugar scaling, not the primary macros).
        per100 = {
            "calories": 200.0,
            "protein": (pro / cal) * 200.0 if cal else None,
            "carbs": (carbs / cal) * 200.0 if cal else None,
            "fat": (fat / cal) * 200.0 if cal else None,
            "fiber": None, "sugar": None, "sodium": None,
        }
        return {"fdc_id": None, "per100g": per100, "_match": "likely"}
    except Exception as e:
        logger.warning(f"web packaged lookup failed: {e}")
        return None


async def _check_recent_duplicate(db, target_log_id, food_name: str, quantity, window_min: int = 5):
    """Idempotency check: same (food_name, quantity) logged on the same daily_log
    within the last `window_min` minutes is almost always a retry, not a second
    portion. Returns the existing entry (with id/calories/etc.) on a hit, or None.

    Catches the shake re-confirmation cascade from the screenshots — when the
    model keeps promising to "log the shake", the second attempt collapses to
    a no-op instead of producing a duplicate row.
    """
    try:
        from datetime import datetime as _dt, timedelta as _td
        from sqlalchemy import select as _select, desc as _desc
        from db.models import FoodEntry
        cutoff = _dt.utcnow() - _td(minutes=window_min)
        qn = (food_name or "").strip().lower()
        if not qn or target_log_id is None:
            return None
        stmt = (_select(FoodEntry)
                .where(FoodEntry.daily_log_id == target_log_id)
                .order_by(_desc(FoodEntry.timestamp))
                .limit(10))
        rows = (await db.execute(stmt)).scalars().all()
        for r in rows:
            ts = getattr(r, "timestamp", None)
            if (ts is not None and ts >= cutoff
                    and (r.parsed_food_name or "").strip().lower() == qn
                    and (str(r.quantity or "").strip().lower()
                         == str(quantity or "").strip().lower())):
                return r
        return None
    except Exception as e:
        logger.warning(f"duplicate check failed: {e}")
        return None


async def _analyze_food(db, user, food_name, inp):
    """
    Enrich a logged food with the right data source, returning a FoodAnalysis.

    Routing:
      memory (recurring user food) → highest priority for both branded & generic.
      Branded packaged products (is_packaged=True or _looks_branded heuristic):
          web search FIRST (label-accurate), USDA as backup.
      Generic foods / meals:
          USDA FIRST (unchanged), web as backup for items USDA misses.
      LLM estimate is always the final fallback.
    """
    from core.food_intelligence import (
        analyze, normalize_name, best_candidate, is_generic_food_name,
    )
    from db.queries import get_user_food_match, upsert_user_food_match

    llm = (inp.get("calories"), inp.get("protein"), inp.get("carbs"), inp.get("fats"))
    name_norm = normalize_name(food_name)
    generic = is_generic_food_name(food_name)
    is_packaged = bool(inp.get("is_packaged")) or _looks_branded(food_name)

    # 1) Recurring memory — user's known staples (highest priority for any type)
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

    # 2) Branched enrichment — branded goes web-first; generics go USDA-first.
    usda = None
    web = None
    if memory is None and name_norm and not generic:
        if is_packaged:
            web = await _web_lookup_packaged(food_name, inp.get("quantity"))
            if web is None:
                # USDA does carry some branded items (Quest bars, etc.) — try as backup.
                try:
                    from api.usda import search_food
                    candidates = await search_food(food_name, page_size=8)
                    best, conf = best_candidate(food_name, candidates)
                    if best:
                        best["_match"] = conf
                        usda = best
                except Exception as e:
                    logger.warning(f"USDA backup enrichment failed: {e}")
            # Cache a confident web hit so the same product is instant next time.
            if web is not None:
                try:
                    await upsert_user_food_match(
                        db, user.id, name_norm, food_name,
                        web.get("fdc_id"), web.get("per100g", {}), web.get("_match") or "likely",
                    )
                except Exception as e:
                    logger.warning(f"memory cache write failed: {e}")
        else:
            try:
                from api.usda import search_food
                candidates = await search_food(food_name, page_size=8)
                best, conf = best_candidate(food_name, candidates)
                if best:
                    best["_match"] = conf
                    usda = best
                    if conf in ("exact", "likely"):
                        await upsert_user_food_match(
                            db, user.id, name_norm, food_name,
                            best.get("fdc_id"), best.get("per100g", {}), conf,
                        )
            except Exception as e:
                logger.warning(f"USDA enrichment failed: {e}")
            # USDA missed AND it's a packaged-looking text mention → try web.
            if usda is None and _looks_branded(food_name):
                web = await _web_lookup_packaged(food_name, inp.get("quantity"))
                if web is not None:
                    try:
                        await upsert_user_food_match(
                            db, user.id, name_norm, food_name,
                            web.get("fdc_id"), web.get("per100g", {}),
                            web.get("_match") or "likely",
                        )
                    except Exception:
                        pass

    return analyze(food_name, inp.get("quantity"), *llm,
                   usda_candidate=usda, memory_match=memory,
                   web_candidate=web)


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
    # Track per-call outcomes so the batch coaching can name individual
    # failures (otherwise the name-keyed `results` dict only retains the LAST
    # log_food's tool result and partial-failure detail is lost).
    per_call: list[tuple[str, str, bool]] = []  # (name, food_name, succeeded)

    # Snapshot entry IDs that existed BEFORE this tool batch ran. The
    # log_* dedup guards filter their match candidates to ONLY these IDs —
    # so bulk post-factum pastes (model fires the same tool multiple times
    # in one batch) are NOT self-blocked. The guards still catch re-logs
    # that reference entries created in a PRIOR turn (the re-log-on-
    # context-shift bug). Phase 1 covered exercise; Phase 1.2/1.3 extend
    # the pattern to food + water, both of which exhibit the same bug
    # surfaced live by Danny on 2026-06-12 (chicken+rice double-log).
    pre_existing_exercise_ids: set[int] = {
        e.id for e in (getattr(today_log, "exercise_entries", None) or [])
        if getattr(e, "id", None) is not None
    }
    pre_existing_food_ids: set[int] = {
        e.id for e in (getattr(today_log, "food_entries", None) or [])
        if getattr(e, "id", None) is not None
    }
    # Water entries aren't on today_log via relationship in the same way;
    # the snapshot is collected from a defensive getattr so we don't crash
    # on test stubs that omit the field. Pre-existing IDs are filtered in
    # the log_water branch by looking them up in db at dispatch time when
    # the kwarg is None (back-compat for direct _dispatch test callers).
    pre_existing_water_ids: Optional[set[int]] = None
    try:
        water_entries = getattr(today_log, "water_entries", None)
        if water_entries is not None:
            pre_existing_water_ids = {
                e.id for e in water_entries
                if getattr(e, "id", None) is not None
            }
    except Exception:
        pre_existing_water_ids = None

    # Per-turn telemetry counters: how many of each log_* tool call fired,
    # how many were skipped by a dedup guard. Greppable in Render logs as
    # `event=tool_log_turn` for monitoring re-log-on-context-shift rates
    # across the user base without manual log inspection.
    log_calls = {"food": 0, "water": 0, "exercise": 0, "body_weight": 0}
    log_skipped = {"food": 0, "water": 0, "exercise": 0, "body_weight": 0}

    for tc in tool_calls:
        name = tc["name"]
        inp = tc["input"] or {}
        food_name = (inp.get("food_name") or "").strip() if isinstance(inp, dict) else ""
        try:
            r = await _dispatch(
                name, inp, user, today_log, db, source_type,
                pre_existing_exercise_ids=pre_existing_exercise_ids,
                pre_existing_food_ids=pre_existing_food_ids,
                pre_existing_water_ids=pre_existing_water_ids,
            )
            # Increment telemetry counters for log_* tools. "Already on the
            # board:" prefix indicates the dedup guard fired and a write
            # was skipped — count separately.
            _tool_key = {
                "log_food": "food", "log_water": "water",
                "log_exercise": "exercise", "log_body_weight": "body_weight",
            }.get(name)
            if _tool_key:
                log_calls[_tool_key] += 1
                if isinstance(r, str) and r.startswith("Already on the board"):
                    log_skipped[_tool_key] += 1
            results[name] = r
            ok = not (isinstance(r, str) and (
                r.startswith("Error:") or r.startswith("Skipped")
                or r.startswith("Failed to")
            ))
            per_call.append((name, food_name, ok))
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            results[name] = f"Error: {e}"
            per_call.append((name, food_name, False))

    # Emit one structured telemetry line per turn that had any log_* call.
    # Greppable as `event=tool_log_turn` in Render logs. Measures the
    # dedup guards' effectiveness across the user base without manual
    # per-user inspection — see Phase 4 plan in project_arnie_live_workout.
    if any(log_calls.values()):
        try:
            _u = getattr(user, "id", None)
            _p = getattr(user, "channel_preference", None) or "?"
            _fc, _fs = log_calls["food"], log_skipped["food"]
            _wc, _ws = log_calls["water"], log_skipped["water"]
            _xc, _xs = log_calls["exercise"], log_skipped["exercise"]
            _bc, _bs = log_calls["body_weight"], log_skipped["body_weight"]
            logger.info(
                f"event=tool_log_turn user_id={_u} platform={_p} "
                f"food={_fc}/{_fs} water={_wc}/{_ws} "
                f"exercise={_xc}/{_xs} body_weight={_bc}/{_bs}"
            )
        except Exception:
            pass  # never let telemetry break the turn

    # Multi-item batch: when several log_food calls fire in one turn, the
    # single-item coaching ("name the food and its macros") is wrong — it makes
    # the model recap one item, ignoring the rest. Swap to batch coaching so the
    # model confirms the whole batch in 1-2 bubbles with the combined total.
    return _apply_multi_item_batch_coaching(results, tool_calls, per_call=per_call)


def _apply_multi_item_batch_coaching(
    results: Dict[str, Any],
    tool_calls: List[Dict[str, Any]],
    per_call: List[tuple] = None,
) -> Dict[str, Any]:
    """If 2+ log_food calls fired in one turn, replace the single-item coaching
    section of the log_food tool result with a batch-summary directive. Pure
    helper so it's unit-testable without spinning up a DB session.

    per_call: optional [(tool_name, food_name, succeeded), ...] capturing each
    individual log_food's outcome (the name-keyed `results` dict loses this
    because last-write-wins). When supplied and any log_food failed, the
    coaching branches into partial-failure mode.
    """
    log_food_calls = [tc for tc in (tool_calls or []) if tc.get("name") == "log_food"]
    if len(log_food_calls) <= 1 or "log_food" not in results:
        return results
    food_names = [
        ((tc.get("input") or {}).get("food_name") or "").strip()
        for tc in log_food_calls
    ]
    food_names = [n for n in food_names if n]
    existing = results.get("log_food")
    if not isinstance(existing, str) or "Scale the reply" not in existing:
        return results
    head, _, _ = existing.partition("Scale the reply")
    n_items = len(food_names) or len(log_food_calls)

    # Detect partial failure from per_call status, if provided.
    failed_names: list[str] = []
    succeeded_names: list[str] = []
    if per_call:
        for nm, fn, ok in per_call:
            if nm != "log_food":
                continue
            (succeeded_names if ok else failed_names).append(fn or "(unnamed)")
    n_failed = len(failed_names)
    n_success = n_items - n_failed if per_call else n_items

    if n_failed > 0:
        # Partial-failure mode: name the failures, name what succeeded.
        succ_preview = ", ".join(succeeded_names[:3]) + (
            f" + {len(succeeded_names) - 3} more" if len(succeeded_names) > 3 else ""
        ) if succeeded_names else "nothing"
        fail_preview = ", ".join(failed_names)
        batch_coaching = (
            f"MULTI-ITEM BATCH WITH FAILURES ({n_success} of {n_items} succeeded). "
            f"Succeeded: {succ_preview}. FAILED: {fail_preview}. "
            f"Tell the user honestly: confirm the {n_success} that went in (combined "
            f"macros + day total from DAY TOTAL above, verbatim) and CALL OUT the "
            f"failures by name ('{failed_names[0]} didn't go through — resend?'). "
            f"NEVER say 'all logged' or 'got everything' when some failed. NEVER "
            f"invent a day total that includes the failed items. 2-3 short bubbles. "
            f"Spell 'calories' not 'cal'. No emoji."
        )
    else:
        preview = ", ".join(food_names[:3]) + (
            f" + {n_items - 3} more" if n_items > 3 else ""
        )
        second = food_names[1] if len(food_names) > 1 else ""
        batch_coaching = (
            f"MULTI-ITEM BATCH ({n_items} foods just logged this turn: {preview}). "
            f"Confirm the WHOLE batch in 1-2 short bubbles — do NOT list each item "
            f"line by line. Combined macros, day total (from DAY TOTAL above, "
            f"verbatim — never recompute), one short next step. Spell 'calories' "
            f"not 'cal'. Examples of the shape: "
            f"\"all logged — bowl, shake, bar came to ~780.|||you're at 1,560 / 2,100 calories.\" "
            f"or \"{food_names[0] if food_names else 'item'}, {second} and the rest "
            f"came to ~X. that's A / B calories today.\" "
            f"Never mention items NOT in this turn's batch. Never restore foods the "
            f"user deleted from the dashboard. One emoji max."
        )
    results["log_food"] = head.rstrip() + " " + batch_coaching
    return results


async def _dispatch(name, inp, user, today_log, db, source_type,
                    pre_existing_exercise_ids=None,
                    pre_existing_food_ids=None,
                    pre_existing_water_ids=None):  # noqa: C901
    # Guard: log_food/log_exercise/log_water require a real daily log
    if name in ("log_food", "log_exercise", "log_water"):
        if not getattr(today_log, "id", None):
            return "Skipped — day log not yet created (onboarding incomplete)"

    if name == "log_food":
        target_log, past_date = await _resolve_log(inp, user, today_log, db)

        food_name = inp.get("food_name") or ""

        # Re-log-on-context-shift guard (Phase 1.2). The model occasionally
        # re-fires log_food for a prior-turn food when the user pivots
        # topic — Danny 2026-06-12 01:01 chicken+rice re-logged at 01:59
        # while answering an Apple Health question. The existing 5-min
        # idempotency check was too tight (58 min gap). 90-min snapshot-
        # aware window catches the model-pivot case without false-positives
        # on legitimate next-meal repeats (typically 3+ hours apart).
        #
        # Bulk-paste safety: when execute_tool_calls passes the snapshot
        # of food entry IDs that existed BEFORE this batch ran, the dedup
        # candidate set is filtered to ONLY those IDs. So a bulk post-
        # factum food paste ("had eggs, then chicken, then rice") with
        # multiple log_food calls in one batch is never self-blocked.
        # When pre_existing_food_ids is None (tests calling _dispatch
        # directly), the filter is bypassed.
        if not past_date:
            from datetime import datetime as _dt_now
            from skills.nutrition.food_dedup import (
                is_duplicate_food, format_dedup_result as _format_food_dedup,
            )
            now_utc = _dt_now.utcnow()
            # Defensive: target_log.food_entries can raise MissingGreenlet
            # if the relationship wasn't selectinloaded (rare — get_today_log
            # always loads it, but past-date logs and some test fixtures
            # don't). When access fails, skip the dedup gracefully rather
            # than crashing the log. The snapshot guard from
            # execute_tool_calls still applies if pre_existing_food_ids is
            # supplied; if neither path can see the prior entries, the dup
            # gets through but the existing entry stays intact.
            try:
                candidate_food_entries = (
                    getattr(target_log, "food_entries", None) or []
                )
                # Force-trigger any lazy load BEFORE the helper runs so the
                # error path here, not downstream.
                _ = len(candidate_food_entries)
            except Exception:
                candidate_food_entries = []
            if pre_existing_food_ids is not None:
                candidate_food_entries = [
                    e for e in candidate_food_entries
                    if getattr(e, "id", None) in pre_existing_food_ids
                ]
            _dup_food = is_duplicate_food(
                food_name=food_name,
                quantity=inp.get("quantity"),
                calories=inp.get("calories"),
                existing_entries=candidate_food_entries,
                now_utc=now_utc,
            )
            if _dup_food is not None:
                return _format_food_dedup(_dup_food, now_utc=now_utc)

        # Capture raw LLM-submitted macros before _analyze_food runs
        # reconcile_macros, so we can flag corrections in the tool result.
        _raw_cal = inp.get("calories")
        _raw_protein = inp.get("protein")
        _raw_carbs = inp.get("carbs")
        _raw_fat = inp.get("fats")
        analysis = await _analyze_food(db, user, food_name, inp)

        # T2.3 — capture meal timing / alcohol / photo provenance.
        # Photos are inherently noisier than text: force estimated=True and cap
        # confidence at 0.75 — UNLESS the enrichment source is a label-accurate
        # web hit, in which case we have the actual numbers from the packaging
        # and the cap would unfairly downgrade trend math.
        from_photo = bool(inp.get("from_photo"))
        _conf = inp.get("confidence", 0.8)
        if from_photo:
            if getattr(analysis, "enrichment_source", None) == "web_label":
                _conf = max(_conf, 0.90)
            else:
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

        # Item-scoped auto-resolve: close only the food_clarification rows whose
        # item_referenced matches THIS logged food. A log of item A must NOT
        # silently close an open question about item B (cross-item collision).
        # Generic-item questions ("protein bar") still close on any specific log —
        # the user named the specific item, that's the answer.
        try:
            from db.queries import resolve_pending_questions_for_logged_items
            await resolve_pending_questions_for_logged_items(db, user.id, [food_name])
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

        # Surface macro-reconciliation corrections so the model uses the
        # reconciled numbers in its reply (not the LLM-input it remembers).
        # We flag when ANY macro shifted by >=5% — small rounding differences
        # don't deserve the noise.
        reconciled_note = ""
        try:
            def _pct_off(orig, new):
                if not orig or orig == 0:
                    return 0.0
                return abs(float(new) - float(orig)) / float(orig)

            def _abs_off(orig, new):
                return abs(float(new) - float(orig)) if orig is not None else 0.0
            # Absolute-floor guard so tiny rounding shifts (10g → 11g protein)
            # don't generate a reconciliation correction the user doesn't care
            # about. Both the relative AND absolute threshold must be met.
            shifted = []
            if (_raw_protein is not None
                    and _pct_off(_raw_protein, analysis.protein) >= 0.05
                    and _abs_off(_raw_protein, analysis.protein) >= 3):
                shifted.append(f"protein {float(_raw_protein):.0f}g→{analysis.protein:.0f}g")
            if (_raw_carbs is not None
                    and _pct_off(_raw_carbs, analysis.carbs) >= 0.05
                    and _abs_off(_raw_carbs, analysis.carbs) >= 5):
                shifted.append(f"carbs {float(_raw_carbs):.0f}g→{analysis.carbs:.0f}g")
            if (_raw_fat is not None
                    and _pct_off(_raw_fat, analysis.fat) >= 0.05
                    and _abs_off(_raw_fat, analysis.fat) >= 2):
                shifted.append(f"fat {float(_raw_fat):.0f}g→{analysis.fat:.0f}g")
            if shifted:
                reconciled_note = (
                    f" RECONCILED: your submitted macros didn't add up to your "
                    f"submitted calories ({', '.join(shifted)} after rebalance). "
                    f"USE THE RECONCILED VALUES from 'Logged X:' above — those are "
                    f"what's in the DB. Don't mention the rebalance to the user."
                )
        except Exception as _e:
            logger.warning(f"reconciliation diff failed: {_e}")

        return (
            f"Logged {food_name}: {analysis.calories} cal, {analysis.protein:.0f}g protein"
            f"{date_label}. ANALYSIS: {analysis.coach_note}.{reconciled_note} "
            f"DAY TOTAL: {target_log.total_calories:.0f} cal, {target_log.total_protein:.0f}g protein"
            f"{(' (' + remaining.strip() + ')') if remaining else ''}. "
            f"Scale the reply to the log. Meaningful meal: name the food and its macros "
            f"(from 'Logged X:' above — NEVER from your input, ALWAYS from the tool "
            f"result), day total from DAY TOTAL (verbatim — never recompute), "
            f"protein standing if a target exists, one short next step. "
            f"Small item (coffee, condiment, drink under ~150 cal): 2 lines max — confirm the food "
            f"and a brief day note, skip the full macro breakdown. "
            f"Protein-heavy meal: lead with protein progress. "
            f"Near or over calorie target: brief control nudge, no shame. "
            f"Sentence case. One emoji if it fits naturally. "
            f"Spell 'calories' not 'cal' — '1,340 / 2,200 calories', not '1,340/2,200 cal'. "
            f"Never skip the day total when a target exists. Never invent numbers."
        )

    elif name == "log_exercise":
        target_log, past_date = await _resolve_log(inp, user, today_log, db)

        weight = inp.get("weight")
        weight_unit = inp.get("weight_unit", "lbs")
        weight_kg = _lbs_to_kg(weight, weight_unit)

        # Canonicalize the exercise name BEFORE dedup so two distinct user
        # phrasings of the same movement ("Crunches (Cable/Machine)" vs
        # "cable crunch") collide on the same dedup key. Unresolved names
        # pass through unchanged.
        from skills.fitness.exercise_catalog import canonicalize as _canon
        raw_name = inp.get("exercise_name")
        canonical_name, _catalog_entry = _canon(raw_name)

        # Re-log-on-context-shift guard. The model occasionally re-fires
        # log_exercise for already-logged sets when the user pivots exercises
        # or asks an open mid-session question. Catch the exact-payload dup
        # within a 120s window and surface it back to the model so it doesn't
        # emit a fresh log line. Only applies to TODAY's log — past-date edits
        # via date= are legitimate corrections, not dups.
        #
        # Bulk-paste safety: when execute_tool_calls passes the snapshot of
        # exercise entry IDs that existed BEFORE this tool batch ran, the
        # dedup candidate set is filtered to ONLY those IDs. This means a
        # user pasting a bulk post-factum workout (model fires log_exercise
        # several times in one batch for sets with identical payloads) is
        # NOT self-blocked. The guard still catches dups against prior turns.
        # When pre_existing_exercise_ids is None (e.g. tests calling _dispatch
        # directly), the filter is bypassed — the full live exercise_entries
        # list is the candidate set, preserving the legacy behavior.
        if not past_date:
            from datetime import datetime as _dt_now
            from skills.fitness.exercise_dedup import (
                is_duplicate_of_recent, format_dedup_result,
            )
            now_utc = _dt_now.utcnow()
            candidate_entries = target_log.exercise_entries or []
            if pre_existing_exercise_ids is not None:
                candidate_entries = [
                    e for e in candidate_entries
                    if getattr(e, "id", None) in pre_existing_exercise_ids
                ]
            dup = is_duplicate_of_recent(
                exercise_name=canonical_name,
                sets=inp.get("sets"),
                reps=str(inp.get("reps", "")) if inp.get("reps") else None,
                weight_kg=weight_kg,
                existing_entries=candidate_entries,
                now_utc=now_utc,
            )
            if dup is not None:
                return format_dedup_result(dup, now_utc=now_utc)

        is_cardio = inp.get("is_cardio", False) or bool(inp.get("cardio_type"))
        await add_exercise_entry(
            db,
            target_log.id,
            exercise_name=canonical_name,
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

        # Echo back the canonical name so the log line the model emits uses
        # the same string we stored (avoids "you said X, we logged Y" drift).
        exercise_name = canonical_name or "exercise"
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

        # Unit-mix-up sanity check — classic bug: user enters 14 (meant 140 lbs
        # or 14 stone), no unit, gets logged as 14 kg = ~31 lbs. That corrupts
        # weight trends for days. If the resulting kg reading is >20% off the
        # user's stored current_weight_kg, return a clarifying tool result
        # instead of writing the entry — the model will re-ask cleanly.
        cur_kg = getattr(user, "current_weight_kg", None)
        if cur_kg and weight_kg > 0:
            ratio = weight_kg / cur_kg
            if ratio < 0.8 or ratio > 1.25:
                # Suggest the most likely intended units so the model can ask
                # specifically rather than vaguely.
                cur_lb = cur_kg * 2.20462
                return (f"Skipped weight log — {weight} {unit} reads as "
                        f"{weight_kg:.1f} kg ({weight_kg*2.20462:.1f} lb), "
                        f"but their current weight is ~{cur_kg:.1f} kg "
                        f"({cur_lb:.1f} lb). YOUR REPLY: ask them to confirm "
                        f"the unit — 'was that {weight} kg or {weight} lb?' "
                        f"— before logging. One short bubble.")

        # T2.5 — context (morning_fasted / post_meal / evening / post_workout)
        # is captured for trend interpretation. A morning_fasted reading is
        # the gold standard; anything else carries noise the coach should
        # weight accordingly.
        context_val = inp.get("context")
        metric = await add_body_metric(db, user.id, weight_kg, context=context_val)
        recent = await get_recent_weights(db, user.id, days=14)
        ordered = sorted(
            [w for w in recent if getattr(w, "weight_kg", None) is not None],
            key=lambda w: w.timestamp,
        )
        previous = next(
            (w for w in reversed(ordered)
             if getattr(w, "id", None) != getattr(metric, "id", None)),
            None,
        )

        logged_lbs = weight_kg * 2.20462
        if previous:
            delta_lbs = (weight_kg - previous.weight_kg) * 2.20462
            delta_note = f"Change vs previous weigh-in: {delta_lbs:+.1f}lb."
        else:
            delta_note = "No prior weigh-in in the last 14 days."

        if len(ordered) >= 2:
            first = ordered[0]
            trend_lbs = (weight_kg - first.weight_kg) * 2.20462
            trend_note = (
                f"14-day trend window: {len(ordered)} weigh-ins, "
                f"{trend_lbs:+.1f}lb from first to now."
            )
        else:
            trend_note = "Trend status: first point only; do not over-read it."

        goal_kg = getattr(user, "goal_weight_kg", None)
        if goal_kg:
            goal_lbs = goal_kg * 2.20462
            remaining_lbs = (weight_kg - goal_kg) * 2.20462
            if abs(remaining_lbs) < 0.25:
                goal_note = f"Goal: {goal_lbs:.1f}lb; essentially at goal."
            elif remaining_lbs > 0:
                goal_note = f"Goal: {goal_lbs:.1f}lb; {remaining_lbs:.1f}lb above goal."
            else:
                goal_note = f"Goal: {goal_lbs:.1f}lb; {abs(remaining_lbs):.1f}lb below goal."
        else:
            goal_note = "Goal weight: not set; do not invent one."

        context_notes = {
            "morning_fasted": "Context: morning fasted, best signal for trend comparison.",
            "post_meal": "Context: post-meal, noisier reading; mention food/water can move it.",
            "evening": "Context: evening, noisier reading; compare cautiously.",
            "post_workout": "Context: post-workout, hydration shifts can distort scale weight.",
            "unknown": "Context: unknown; avoid strong conclusions from one point.",
        }
        context_note = context_notes.get(context_val or "unknown", context_notes["unknown"])

        return (
            f"Logged body weight: {float(weight):.1f} {unit} "
            f"({weight_kg:.1f}kg / {logged_lbs:.1f}lb). "
            f"{delta_note} {trend_note} {goal_note} {context_note} "
            f"YOUR REPLY: 1-2 short bubbles max. Confirm the weigh-in, then give one "
            f"specific read from the delta/trend/goal above. Do not use the canned "
            f"weight-down or consistency slogans from the old fallback. "
            f"Do not moralize; same-time weigh-ins and rolling trend are the coaching frame."
        )

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

        # Recurring-memory correction backfill: when a correction notably shifts
        # macros on a named non-generic food, update the user_food_match so the
        # next log of the same item primes from the corrected profile. Reuses
        # existing upsert_user_food_match. Skip on generics, partial updates,
        # and entries with no calories to anchor the per-100g profile.
        try:
            from core.food_intelligence import normalize_name, is_generic_food_name
            from db.queries import upsert_user_food_match
            fn = entry.parsed_food_name or ""
            if fn and entry.calories and not is_generic_food_name(fn):
                name_norm = normalize_name(fn)
                # Use entry.quantity to derive per-100g IF we can read grams.
                # Fall back to direct cal as cal100 only when the entry is
                # explicitly 100g — otherwise skip (don't taint memory).
                qty = str(entry.quantity or "").lower()
                if "100g" in qty or "100 g" in qty:
                    per100 = {
                        "calories": float(entry.calories),
                        "protein": float(entry.protein or 0),
                        "carbs": float(entry.carbs or 0),
                        "fat": float(entry.fats or 0),
                        "fiber": float(entry.fiber) if entry.fiber is not None else None,
                        "sugar": float(entry.sugar) if entry.sugar is not None else None,
                        "sodium": float(entry.sodium) if entry.sodium is not None else None,
                    }
                    await upsert_user_food_match(
                        db, user.id, name_norm, fn,
                        None, per100, "user-confirmed",
                    )
        except Exception as _e:
            logger.warning(f"recurring-memory backfill on update failed: {_e}")

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

        # Re-log-on-context-shift guard (Phase 1.3). Mirrors Phase 1.2 food
        # dedup. The model can carry a prior-turn water log forward across
        # context shifts; the dup inflates total_water_ml on DailyLog.
        # 60-min window — water is sipped more often than food is eaten,
        # so the legit-second-drink false-positive risk is higher than for
        # food. Bulk-paste safety via the same snapshot pattern.
        if not past_date and ml:
            from datetime import datetime as _dt_now
            from skills.nutrition.water_dedup import (
                is_duplicate_water, format_dedup_result as _format_water_dedup,
            )
            now_utc = _dt_now.utcnow()
            # Defensive lazy-load guard, same shape as food_dedup above.
            try:
                candidate_water = (
                    getattr(target_log, "water_entries", None) or []
                )
                _ = len(candidate_water)
            except Exception:
                candidate_water = []
            if pre_existing_water_ids is not None:
                candidate_water = [
                    e for e in candidate_water
                    if getattr(e, "id", None) in pre_existing_water_ids
                ]
            _dup_water = is_duplicate_water(
                amount_ml=ml,
                context=inp.get("context"),
                existing_entries=candidate_water,
                now_utc=now_utc,
            )
            if _dup_water is not None:
                return _format_water_dedup(_dup_water, now_utc=now_utc)

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

    elif name == "coach_on_photo":
        # Structured DECISION on a photo (menu, fridge, grocery, delivery app,
        # prepared meal needing verdict, body progress). The preprocessor has
        # already classified + extracted items; the LLM has decided what to
        # advise. We just package the structured result so the renderer can
        # show a rich card. No DB writes — this is purely advisory.
        photo_type = (inp.get("photo_type") or "").strip().lower()
        decision = (inp.get("decision") or "").strip()
        reasoning = (inp.get("reasoning") or "").strip()
        items = inp.get("items_identified") or []
        macros = inp.get("macros_estimate") or {}
        bf_range = inp.get("bf_range") or {}

        # Confidence caps — vision estimates are inherently noisy.
        # Body fat photo estimates cap tighter than other photo decisions.
        try:
            conf = float(inp.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        if photo_type == "body_progress":
            conf = max(0.0, min(0.75, conf))
        else:
            conf = max(0.0, min(0.85, conf))

        if not decision:
            return "Error: coach_on_photo requires a non-empty decision."

        logger.info(
            f"event=coach_on_photo user_id={getattr(user, 'id', None)} "
            f"type={photo_type} confidence={conf:.2f} items={len(items)}"
        )

        return {
            "_type": "photo_coaching",
            "photo_type": photo_type,
            "decision": decision,
            "reasoning": reasoning,
            "items_identified": list(items)[:12],  # cap for display sanity
            "macros_estimate": {
                "calories": macros.get("calories"),
                "protein": macros.get("protein"),
                "carbs": macros.get("carbs"),
                "fats": macros.get("fats"),
            } if macros else {},
            "bf_range": {
                "low": bf_range.get("low"),
                "high": bf_range.get("high"),
            } if bf_range else {},
            "confidence": conf,
            "caption": decision,  # short version for notification text
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
            "non_training_activity",  # NOT yet wired to compute_macro_targets,
                                       # but allow conversational capture so the
                                       # data is there when the math switches over.
            "dietary_preferences", "injuries", "timezone", "city",
            "channel_preference",
        }
        _pref_fields = {
            "coaching_style", "accountability_level", "pacing_enabled",
            "reminder_frequency", "preferred_response_length",
            "profanity_tolerance", "proactive_messaging_enabled",
            "wake_time", "sleep_time", "calorie_target", "protein_target",
            "carb_target", "fat_target",
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
        # Uses the canonical compute_macro_targets() so all 4 macros land
        # (most existing users had only calories/protein populated; this fix
        # fills carb_target + fat_target too for new auto-calc events).
        _targets_msg = ""
        prefs_check = user.preferences
        if prefs_check and prefs_check.calorie_target is None:
            from core.targets import compute_macro_targets
            t = compute_macro_targets(user)
            if t:
                prefs_check.calorie_target = t["calorie_target"]
                prefs_check.protein_target = t["protein_target"]
                prefs_check.carb_target    = t["carb_target"]
                prefs_check.fat_target     = t["fat_target"]
                await db.commit()
                user = await reload_user(db, user.id)
                logger.info(
                    f"Auto-calculated targets for user {user.id}: "
                    f"{t['calorie_target']} kcal · "
                    f"{t['protein_target']}g P / {t['carb_target']}g C / {t['fat_target']}g F "
                    f"(BMR {t['bmr']}, TDEE {t['tdee']}, {t['deficit_pct']:+.1f}%)"
                )
                _targets_msg = (
                    f" | TARGETS JUST CALCULATED: {t['calorie_target']} cal, "
                    f"{t['protein_target']}g protein, {t['carb_target']}g carbs, "
                    f"{t['fat_target']}g fat. Tell the user you now have their full "
                    f"picture and these are their daily targets — briefly and "
                    f"naturally, in your voice."
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

    elif name == "set_macro_targets":
        # Direct write path for calorie + macro targets — used when the
        # user agrees to Arnie's recommended targets (from the
        # [COACH NOTE — targets_unset] block) or names specific values.
        # Mirrors the dashboard POST /api/profile/{token}/auto-targets
        # behavior: same fields, same persistence, same audit log.
        #
        # CLASSIFICATION (matches update_profile — instant prefs write):
        #   · NOT in NEEDS_HEADS_UP_TOOLS / _TOOL_HEADS_UP_BUBBLES — the
        #     write is microseconds, a heads-up bubble would feel jarring
        #     ("setting your targets..." → immediate confirmation). Heads-
        #     ups are for slow I/O only (web_search, search_food_database,
        #     query_history, generate_image).
        #   · NOT in _LOGGING_TOOLS (core/conversation.py) — not a log
        #     entry. That set triggers the coach-unmute path with
        #     deterministic_confirmation as fallback, which reads totals
        #     from today_log + user.preferences and is the wrong shape
        #     for a 4-macro prefs write.
        #   · NOT in _VOICED_RESULT_TOOLS — the recommended values live
        #     in the [COACH NOTE — targets_unset] block already injected
        #     into the system prompt, so the model can voice them in its
        #     first pass before calling the tool. Nothing to re-voice.
        #
        # Streaming behavior falls through to the standard inline path:
        # Arnie writes his confirmation in the first pass, the tool fires
        # silently, and the existing need_followup safety net (line ~443
        # in core/conversation.py) generates a follow-up confirmation if
        # the model fired the tool with no text.
        prefs = user.preferences
        if not prefs:
            from db.models import UserPreferences
            prefs = UserPreferences(user_id=user.id)
            db.add(prefs)

        # Accept either the documented arg names or a few sensible
        # aliases (some models emit synonyms — be liberal in what we
        # take, strict in what we save).
        _aliases = {
            "calorie_target": "calories", "kcal": "calories", "cals": "calories",
            "protein_target": "protein", "p": "protein",
            "carb_target":    "carbs",   "carbohydrates": "carbs", "c": "carbs",
            "fat_target":     "fat",     "fats": "fat",            "f": "fat",
        }
        normed = {_aliases.get(k, k): v for k, v in (inp or {}).items()}

        _field_for_arg = {
            "calories": "calorie_target", "protein": "protein_target",
            "carbs":    "carb_target",    "fat":     "fat_target",
        }
        written = []
        if normed.get("calories") is not None:
            prefs.calorie_target = int(normed["calories"]); written.append("calories")
        if normed.get("protein") is not None:
            prefs.protein_target = int(normed["protein"]);  written.append("protein")
        if normed.get("carbs") is not None:
            prefs.carb_target    = int(normed["carbs"]);    written.append("carbs")
        if normed.get("fat") is not None:
            prefs.fat_target     = int(normed["fat"]);      written.append("fat")

        if not written:
            return (
                "set_macro_targets called with no values — pass at least one of "
                "calories, protein, carbs, fat. If accepting the recommended "
                "targets from context, pass all four."
            )

        # If the LLM passed exactly ONE macro (e.g. user said "set my
        # calories to 2800"), auto-sync the other three using the same
        # rules as the dashboard PATCH path. When the LLM passes the full
        # 4-macro recommendation (the targets_unset accept-flow), trust
        # its coherent set and skip the sync.
        if len(written) == 1:
            from core.targets import sync_macros_after_change
            sync_macros_after_change(user, prefs, _field_for_arg[written[0]])

        await db.commit()
        user = await reload_user(db, user.id)
        logger.info(
            f"Macro targets set via tool for user {user.id}: "
            f"cals={prefs.calorie_target} P={prefs.protein_target}g "
            f"C={prefs.carb_target}g F={prefs.fat_target}g"
        )
        return (
            f"Macro targets saved: {prefs.calorie_target} kcal, "
            f"{prefs.protein_target}g protein, {prefs.carb_target}g carbs, "
            f"{prefs.fat_target}g fat. Confirm briefly to the user in your voice."
        )

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
        # ── NEW PER-ENTRY METRICS ───────────────────────────────────────────
        if metric == "food_entries" and "rows" in data:
            rows = data["rows"]
            lines.append(f"FOOD ENTRIES ({data.get('entries', 0)} items across "
                         f"{data.get('days_with_data', 0)} days):")
            current_date = None
            for r in rows:
                if r["date"] != current_date:
                    current_date = r["date"]
                    lines.append(f"  {current_date}:")
                est = "~" if r.get("estimated") else ""
                qty = f" ({r['quantity']})" if r.get("quantity") else ""
                lines.append(
                    f"    • {r['food_name']}{qty} — {est}{r['calories']} calories, "
                    f"{r['protein']}g protein"
                )
        if metric == "exercise_entries" and "rows" in data:
            lines.append(f"EXERCISE ENTRIES ({data.get('entries', 0)} entries across "
                         f"{data.get('days_with_data', 0)} days):")
            current_date = None
            for r in data["rows"]:
                if r["date"] != current_date:
                    current_date = r["date"]
                    lines.append(f"  {current_date}:")
                if r.get("sets") and r.get("reps"):
                    w = f" @ {r['weight_lbs']}lb" if r.get("weight_lbs") else ""
                    lines.append(f"    • {r['exercise_name']}: {r['sets']}×{r['reps']}{w}")
                elif r.get("duration_minutes"):
                    ct = f" {r['cardio_type']}" if r.get("cardio_type") else ""
                    lines.append(f"    • {r['exercise_name']}:{ct} {r['duration_minutes']:.0f} min")
                else:
                    lines.append(f"    • {r['exercise_name']}")
        if metric == "water":
            lines.append(f"WATER (period={period}):")
            for d in data.get("daily_totals", []):
                lines.append(f"  {d['date']}: {d['total_water_ml']} ml total")
            if data.get("rows"):
                lines.append(f"  individual entries: {data['entries']}")
                for r in data["rows"][-10:]:
                    ctx = f" ({r['context']})" if r.get("context") else ""
                    lines.append(f"    {r['date']}: {r['amount_ml']} ml{ctx}")
        if metric == "body_metrics" and "rows" in data:
            lines.append(f"BODY METRICS / RECOVERY ({data.get('entries', 0)} days):")
            for r in data["rows"]:
                parts = [r["date"] + ":"]
                if r.get("sleep_hours") is not None:
                    parts.append(f"sleep {r['sleep_hours']:.1f}h")
                if r.get("hrv") is not None:
                    parts.append(f"HRV {r['hrv']:.0f}")
                if r.get("resting_hr") is not None:
                    parts.append(f"RHR {r['resting_hr']:.0f}")
                if r.get("recovery_score") is not None:
                    parts.append(f"recovery {r['recovery_score']}")
                if r.get("strain") is not None:
                    parts.append(f"strain {r['strain']:.1f}")
                if r.get("steps") is not None:
                    parts.append(f"{r['steps']} steps")
                if r.get("source"):
                    parts.append(f"[{r['source']}]")
                lines.append("  " + " | ".join(parts))
        if metric == "day_detail" and "days" in data:
            lines.append(f"DAY DETAIL — {data.get('days_with_data', 0)} day(s) with data:")
            for d in data["days"]:
                t = d["totals"]
                lines.append(f"  {d['date']}: {t['calories']} cal, {t['protein']}g P, "
                             f"{t['carbs']}g C, {t['fats']}g F | water {t['water_ml']}ml | "
                             f"workout={'✓' if d['workout_completed'] else '✗'} "
                             f"cardio={'✓' if d['cardio_completed'] else '✗'}")
                if d["food"]:
                    lines.append("    FOOD:")
                    for f in d["food"]:
                        est = "~" if f.get("estimated") else ""
                        qty = f" ({f['quantity']})" if f.get("quantity") else ""
                        lines.append(
                            f"      • {f['food_name']}{qty} — {est}{f['calories']} cal, "
                            f"{f['protein']}g protein"
                        )
                if d["exercise"]:
                    lines.append("    EXERCISE:")
                    for e in d["exercise"]:
                        if e.get("sets") and e.get("reps"):
                            w = f" @ {e['weight_lbs']}lb" if e.get("weight_lbs") else ""
                            lines.append(f"      • {e['exercise_name']}: {e['sets']}×{e['reps']}{w}")
                        elif e.get("duration_minutes"):
                            ct = f" {e['cardio_type']}" if e.get("cardio_type") else ""
                            lines.append(f"      • {e['exercise_name']}:{ct} {e['duration_minutes']:.0f} min")
                        else:
                            lines.append(f"      • {e['exercise_name']}")
        return (
            "\n".join(lines) + "\n\n"
            "COACH INSTRUCTION: present this data conversationally — give the read, not a table. "
            "Highlight the trend, flag anything notable, then give one concrete next step. "
            "For per-entry food/exercise/day_detail recaps the user asked for, list every "
            "entry verbatim with the EXACT names and macros from the data above (this is the "
            "DB source of truth — same data they see on the dashboard). Use 'calories' not 'cal'. "
            "Never paraphrase entries or skip items."
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
                f"No data found for '{food_name}'. "
                f"Use your best training-data estimate. "
                f"NEVER mention USDA, database, or that you looked anything up."
            )
        best, conf = best_candidate(food_name, candidates)
        if not best:
            return (
                f"No strong match for '{food_name}'. Closest: {candidates[0]['description']}. "
                f"Use your best estimate. "
                f"NEVER mention USDA, database, or that you looked anything up."
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
            f"COACH INSTRUCTION: answer the user's macro question using these numbers. "
            f"NEVER mention USDA, database, match confidence, data sources, or that you looked "
            f"anything up — fold the numbers into your coaching voice as if you already knew them. "
            f"If confidence is 'estimated', just give your best read on the numbers without flagging uncertainty."
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
                f"Don't say anything about saving it — just ask the question naturally. "
                f"If the user's original turn mentioned OTHER foods too (multi-item batch), "
                f"hold those as well: log ALL of them together once the user answers, "
                f"not just '{food_item}'."
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
