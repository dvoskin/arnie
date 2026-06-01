"""
Shared conversation pipeline — the single orchestration core for all platforms.

Both bot/imessage_handler and bot/telegram_handler delegate to run_turn().
Platform-specific bits (typing indicator, image delivery, adapter.send,
onboarding keyboards, completion text) stay in each handler; this module
owns everything from LLM call through Response assembly.
"""
from __future__ import annotations

import dataclasses
import logging
import os
from typing import Any, Callable, Optional

from core.llm import chat, chat_follow_up
from core.platform import Response, React, FX, onboarding_reaction, detect_moment
from handlers.tool_executor import execute_tool_calls, deterministic_confirmation

logger = logging.getLogger(__name__)

_LOGGING_TOOLS = frozenset({
    "log_food", "log_exercise", "update_food_entry",
    "delete_food_entry", "update_exercise_entry",
    "log_body_weight", "log_water",
})


@dataclasses.dataclass
class TurnResult:
    """Everything a handler needs after run_turn completes."""
    response: Response
    tool_calls: list
    just_completed: bool
    in_onboarding: bool             # final state (after tools may have completed it)
    onboarding_field_saved: Optional[str]
    today_log: Any                  # may have been created/refreshed during the turn
    user: Any                       # refreshed after tool execution


async def run_turn(
    user,
    db,
    messages: list,
    system: str,
    platform: str,                  # "imessage" | "telegram"
    *,
    in_onboarding: bool,
    was_onboarding: bool,
    today_log=None,                 # pre-fetched or None (created lazily if tools run)
    source_type: Optional[str] = None,  # for execute_tool_calls; defaults to platform
    on_image: Optional[Callable] = None,    # async fn(url, caption) → None
    on_completion: Optional[Callable] = None,  # fn(user) → str; defaults to plain welcome
) -> TurnResult:
    """
    Core pipeline: LLM call → tool execution → coach-unmute / follow-up /
    deterministic fallback → Response assembly (detect_moment, dashboard-link-once).

    Returns a TurnResult so each handler can apply its own delivery layer.
    """
    _source = source_type or platform
    _tag = f"{platform}:{user.id}"

    # ── LLM first pass ───────────────────────────────────────────────────────
    try:
        result = await chat(messages, system, tools=True, max_tokens=1024)
    except Exception as e:
        logger.error(f"LLM call failed for {_tag}: {e}")
        resp = Response.from_text(
            "Something went wrong on my end — try again in a moment."
        )
        return TurnResult(
            response=resp, tool_calls=[], just_completed=False,
            in_onboarding=in_onboarding, onboarding_field_saved=None,
            today_log=today_log, user=user,
        )

    response_text = result["text"]
    tool_calls    = result["tool_calls"]
    raw_content   = result["raw_content"]
    onboarding_field_saved: Optional[str] = None

    # ── Execute tools ─────────────────────────────────────────────────────────
    tool_results: dict = {}
    if tool_calls:
        if today_log is None and not in_onboarding:
            from db.queries import get_or_create_today_log
            today_log = await get_or_create_today_log(
                db, user.id, user.timezone or "UTC"
            )

        _log_for_tools = today_log
        if _log_for_tools is None:
            class _FakeLog:
                id = None
                total_calories = 0; total_protein = 0; total_carbs = 0
                total_fats = 0; total_water_ml = 0
                workout_completed = False; cardio_completed = False
                food_entries: list = []; exercise_entries: list = []
            _log_for_tools = _FakeLog()

        tool_results = await execute_tool_calls(
            tool_calls, user, _log_for_tools, db, _source
        )

        # Deliver image results via the platform callback; replace dict with string
        for tname, tresult in list(tool_results.items()):
            if isinstance(tresult, dict) and tresult.get("_type") == "image":
                image_url = tresult.get("url", "")
                caption   = tresult.get("caption", "")
                if on_image and image_url:
                    try:
                        await on_image(image_url, caption)
                    except Exception as e:
                        logger.error(f"Image delivery failed for {_tag}: {e}")
                tool_results[tname] = (
                    f"Image generated and sent. URL: {image_url}. Caption: {caption}"
                )

        from db.queries import reload_user
        user = await reload_user(db, user.id)
        if today_log and hasattr(today_log, "id") and today_log.id:
            await db.refresh(today_log)

        # Track which profile field was saved this turn (for onboarding reaction)
        if was_onboarding:
            for tc in tool_calls:
                if tc["name"] == "update_profile":
                    f = tc.get("input", {}).get("fields", {})
                    for fld in ("name", "current_weight_kg", "height_cm",
                                "primary_goal", "training_experience", "calorie_target"):
                        if fld in f:
                            onboarding_field_saved = fld
                            break

        # Onboarding state may have changed (update_profile can complete it)
        in_onboarding = not user.onboarding_completed

    # ── Detect onboarding completion ──────────────────────────────────────────
    just_completed = was_onboarding and not in_onboarding

    # ── Follow-up after tool calls ────────────────────────────────────────────
    _followup_tried = False

    if just_completed:
        # Onboarding just completed — almost always because the brain dump landed all
        # three essentials at once. The RETENTION moment here is the reflection: an
        # intelligent read of who this person is ("190 now, 175 before Mexico, training's
        # there, food tracking's the lever"), NOT a generic "you're in, start logging"
        # push. The onboarding system prompt (dump stage) already instructs that
        # reflection, so prefer the LLM's text. If the first pass only called
        # update_profile and wrote nothing, generate the reflection via a follow-up.
        # The canned text / on_completion welcome is the LAST resort, not the default.
        if response_text and response_text.strip():
            pass  # LLM reflected alongside the update_profile call — keep it
        else:
            try:
                _followup_tried = True
                response_text = await chat_follow_up(
                    messages, raw_content, tool_calls, tool_results,
                    system, max_tokens=400,
                )
            except Exception as e:
                logger.error(f"Onboarding reflection follow-up failed for {_tag}: {e}")
            if not (response_text and response_text.strip()):
                if on_completion is not None:
                    response_text = on_completion(user)
                else:
                    name = user.name or ""
                    response_text = (
                        f"You're in, {name}. 🎉|||"
                        "Just text me whatever you eat or train and I'll handle the rest.|||"
                        "What've you had today? Let's start there."
                    )
    else:
        has_logging = any(tc["name"] in _LOGGING_TOOLS for tc in tool_calls)
        if has_logging and not in_onboarding:
            # Coach-unmute path: let Arnie coach on a log instead of a template.
            # Authoritative totals come from the tool result; "NUMBERS ARE SACRED"
            # in the system prompt prevents fabrication.
            _followup_tried = True
            try:
                response_text = await chat_follow_up(
                    messages, raw_content, tool_calls, tool_results,
                    system, max_tokens=400,
                )
            except Exception as e:
                logger.error(f"Coaching follow-up failed for {_tag}: {e}")
            if not response_text:
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences
                )
        else:
            need_followup = (
                tool_calls and raw_content and (in_onboarding or not response_text)
            )
            if need_followup:
                _followup_tried = True
                try:
                    response_text = await chat_follow_up(
                        messages, raw_content, tool_calls, tool_results,
                        system, max_tokens=400,
                    )
                except Exception as e:
                    logger.error(f"Follow-up LLM failed for {_tag}: {e}")

    if not response_text:
        # Last-resort follow-up — only if we haven't already tried
        if tool_calls and raw_content and not _followup_tried:
            try:
                response_text = await chat_follow_up(
                    messages, raw_content, tool_calls, tool_results,
                    system, max_tokens=300,
                )
            except Exception as e:
                logger.warning(f"Last-resort follow-up failed for {_tag}: {e}")
        if not response_text:
            # Never a bare "done." — real confirmation or keep-alive
            if tool_calls:
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences
                )
            else:
                response_text = "Still here. What's the move?"

    # ── Build the platform-agnostic Response ──────────────────────────────────
    resp = Response.from_text(response_text)

    if just_completed:
        resp.effect    = FX.CELEBRATE
        resp.effect_idx = 0
        resp.reaction  = React.LOVE
    elif was_onboarding and onboarding_field_saved:
        resp.reaction = onboarding_reaction(onboarding_field_saved)
    elif not in_onboarding:
        moment         = detect_moment(response_text, tool_calls)
        resp.reaction  = moment.reaction
        resp.effect    = moment.effect
        resp.effect_idx = moment.effect_idx

    # ── Dashboard link after FIRST food/workout log (once per account) ────────
    if not in_onboarding and tool_calls:
        logged = any(tc["name"] in ("log_food", "log_exercise") for tc in tool_calls)
        sent = set(s for s in (user.nudges_sent or "").split(",") if s)
        if logged and "dashboard" not in sent:
            try:
                from core.blurbs import dashboard_line
                from db.queries import get_or_create_webhook_token
                token = await get_or_create_webhook_token(db, user.id)
                base = os.getenv(
                    "RENDER_EXTERNAL_URL", "https://arnie.onrender.com"
                ).rstrip("/")
                dash_url = f"{base}/dashboard/{token}"
                intro = await dashboard_line(user.name or "")
                resp.bubbles.append(intro)
                resp.bubbles.append(dash_url)
                sent.add("dashboard")
                user.nudges_sent = ",".join(sorted(sent))
                await db.commit()
            except Exception as e:
                logger.warning(f"Dashboard link failed for {_tag}: {e}")

    # ── Sync open follow-up loops (record needs / resolve answered) ───────────
    # Runs every turn regardless of the proactive flag — recording + resolution
    # are state updates, not sends. The re-ask itself stays gated in the scheduler.
    if not in_onboarding:
        from reminders.lifecycle import sync_pending_questions
        await sync_pending_questions(db, user)

    return TurnResult(
        response=resp,
        tool_calls=tool_calls,
        just_completed=just_completed,
        in_onboarding=in_onboarding,
        onboarding_field_saved=onboarding_field_saved,
        today_log=today_log,
        user=user,
    )
