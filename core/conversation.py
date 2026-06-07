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
from core.prompts.onboarding import format_completion_facts
from core.turn_health import (
    looks_like_stall as _looks_like_stall,
    looks_like_dead_end as _looks_like_dead_end,
    detect_turn_flags,
)
from handlers.tool_executor import execute_tool_calls, deterministic_confirmation

logger = logging.getLogger(__name__)

_LOGGING_TOOLS = frozenset({
    "log_food", "log_exercise", "update_food_entry",
    "delete_food_entry", "update_exercise_entry",
    "log_body_weight", "log_water", "clear_day_log",
})

# Tools whose raw result MUST be re-voiced — the facts live ONLY in the tool
# result, so a follow-up is forced even when the first pass already wrote text
# (otherwise the search facts would never reach the user). Sibling of
# _LOGGING_TOOLS, NOT an overload: search must take the generic re-voice path,
# never the coach-unmute/deterministic_confirmation fallback (which is for
# logging totals and is wrong for search).
_VOICED_RESULT_TOOLS = frozenset({"web_search"})


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
    health_flags: list = dataclasses.field(default_factory=list)  # turn-health telemetry


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
    completion_facts: Optional[dict] = None,  # ephemeral TDEE/goal for the just-completed reflection
) -> TurnResult:
    """
    Core pipeline: LLM call → tool execution → coach-unmute / follow-up /
    deterministic fallback → Response assembly (detect_moment, dashboard-link-once).

    Returns a TurnResult so each handler can apply its own delivery layer.
    """
    _source = source_type or platform
    _tag = f"{platform}:{user.id}"
    _retried = False  # turn-health: did the self-heal fire this turn?
    _messages_for_followup = messages
    _first_stop_reason = None
    _user_text = next((m.get("content", "") for m in reversed(messages)
                       if m.get("role") == "user"), "")

    # ── LLM first pass ───────────────────────────────────────────────────────
    # Generous token budget on purpose: a user can dump a whole day of food in one
    # message, which becomes one log_food tool_use block per item (~130 tokens each).
    # Token cost is NOT the constraint here — a complete, correct log is. At 1024 the
    # response truncated mid-turn: it logged ~1 item, the rest were cut off, and the
    # dangling preamble ("Now logging everything:") got sent raw. 4096 fits ~30 items.
    try:
        result = await chat(messages, system, tools=True, max_tokens=4096)

        # Self-heal an incomplete turn. Two failure modes, both seen in prod:
        #   • truncated  — model ran out of budget mid-tool-call (stop_reason)
        #   • stalled    — model promised an action but emitted NO tool calls. Catches
        #                  both the colon preamble ("Now logging everything:") and the
        #                  period-ending narration ("Let me do that now.", "On it —
        #                  clearing today and relogging…") that slipped past the old
        #                  colon-only check.
        # Either way the user sees a broken promise and nothing happens. Retry ONCE with
        # a bigger budget and an explicit "finish it now" nudge.
        _txt = (result.get("text") or "").rstrip()
        _first_stop_reason = result.get("stop_reason")
        _truncated = _first_stop_reason == "max_tokens"
        _stalled = (not result["tool_calls"]) and _looks_like_stall(_txt)
        if _truncated or _stalled:
            logger.warning(
                f"Incomplete first pass for {_tag} "
                f"(truncated={_truncated}, stalled={_stalled}) — retrying with nudge"
            )
            _retried = True
            retry_messages = messages + [
                {"role": "assistant", "content": _txt or "(started but didn't finish)"},
                {"role": "user", "content": (
                    "Finish that now, in ONE message: actually CALL the tools for every "
                    "item you listed, then confirm with the running total. Don't narrate, "
                    "don't stop on a colon, don't promise to do it next."
                )},
            ]
            result = await chat(retry_messages, system, tools=True, max_tokens=8192)
            _messages_for_followup = retry_messages
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
        if today_log is None:
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

    async def _try_follow_up(system_override: Optional[str] = None,
                             max_tokens: int = 700) -> Optional[str]:
        """One chat_follow_up call + the shared try/except + logger.error.
        Returns the text, or None on failure (callers own their own fallbacks)."""
        try:
            return await chat_follow_up(
                _messages_for_followup, raw_content, tool_calls, tool_results,
                system_override or system, max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error(f"Follow-up failed for {_tag}: {e}")
            return None

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
            _followup_tried = True
            _reflect_line = format_completion_facts(completion_facts)
            _reflect_system = (
                system + "\n\n" + _reflect_line if _reflect_line else system
            )
            response_text = await _try_follow_up(system_override=_reflect_system)
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
            response_text = await _try_follow_up()
            if not response_text:
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences
                )
        else:
            # A voiced-result tool (web_search) forces a follow-up EVEN when the
            # first pass already wrote text — its facts live only in the tool result
            # and must be re-voiced. The generic _try_follow_up() re-voices via
            # chat_follow_up using the full system (which includes SEARCH_RULES when
            # enabled). This is NOT a third branch — just a data-driven term added to
            # the existing need_followup predicate.
            has_voiced_result = any(
                tc["name"] in _VOICED_RESULT_TOOLS for tc in tool_calls
            )
            need_followup = (
                tool_calls and raw_content
                and (in_onboarding or not response_text or has_voiced_result)
            )
            if need_followup:
                _followup_tried = True
                response_text = await _try_follow_up()

    if not response_text:
        # Last-resort follow-up — only if we haven't already tried
        if tool_calls and raw_content and not _followup_tried:
            response_text = await _try_follow_up()
        if not response_text:
            # Never a bare "done." — real confirmation or keep-alive
            if tool_calls:
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences
                )
            else:
                response_text = "Still here. What's the move?"

    # ── Anti-dead-end guard ────────────────────────────────────────────────────
    # "done" / "got it" / "logged" as the WHOLE reply is banned — it kills the
    # conversation, and it's especially wrong right after the user ANSWERED a question
    # (that should continue, not close). The model still does it despite the prompt
    # rule, so enforce it in code: if a tool ran, confirm with the authoritative total;
    # otherwise retry once for a substantive reply.
    _dead_ended = False
    try:
        if _looks_like_dead_end(response_text):
            _dead_ended = True
            logger.warning(f"Dead-end reply for {_tag}: {response_text[:60]!r} — repairing")
            if tool_calls:
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences
                )
            else:
                _retry = await chat(
                    messages + [
                        {"role": "assistant", "content": response_text},
                        {"role": "user", "content": (
                            "that's a dead-end reply. don't answer with just "
                            "'done'/'got it'/'logged'. react to what i actually said and "
                            "give a read or a next step."
                        )},
                    ],
                    system, tools=False, max_tokens=700,
                )
                if (_retry.get("text") or "").strip():
                    response_text = _retry["text"]
    except Exception as e:
        logger.debug(f"dead-end guard failed for {_tag}: {e}")

    # ── Build the platform-agnostic Response ──────────────────────────────────
    # CONTRACT: response_text is FROZEN after this line. All further mutations
    # (bubble injection, dashboard URL, intro prepend) happen on resp.bubbles.
    # The only legitimate post-split read of response_text is sync_pending_questions,
    # which needs the raw LLM string for hook detection. If you ever join resp.bubbles
    # back into a string, derive it from the pre-dashboard slice, not after URL append.
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
                from core.urls import dashboard_url
                from db.queries import get_or_create_webhook_token
                token = await get_or_create_webhook_token(db, user.id)
                dash_url = dashboard_url(token)
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
        # INVARIANT: pass `response_text` (raw LLM reply), NOT a string rebuilt
        # from resp.bubbles. Dashboard-link bubbles are appended above and must
        # not reach hook detection.
        await sync_pending_questions(db, user, llm_reply_text=response_text)

    # ── Turn-health telemetry ─────────────────────────────────────────────────
    # Cheap deterministic detectors so deviations are self-evident (in logs + the
    # admin audit view) instead of needing a screenshot. Fully wrapped — telemetry
    # must NEVER affect the reply the user already got.
    health_flags: list = []
    try:
        _tool_error = any(
            isinstance(v, str) and v.startswith("Error:") for v in tool_results.values()
        )
        health_flags = detect_turn_flags(
            user_text=_user_text if isinstance(_user_text, str) else "",
            response_text=response_text,
            has_tool_calls=bool(tool_calls),
            stop_reason=result.get("stop_reason"),
            retried=_retried,
            tool_error=_tool_error,
        )
        if _retried and "retried" not in health_flags:
            health_flags.append("retried")
        if _dead_ended:
            health_flags.append("dead_end")
        # Wall-of-text: the cap is "5+ bubbles only when a plan/breakdown is asked for".
        # Flag turns that blew past it so verbosity is visible in /admin/flagged.
        if len(resp.bubbles) > 5:
            health_flags.append("wall_of_text")
        if health_flags:
            logger.warning(f"TURN_HEALTH {_tag} flags={','.join(health_flags)}")
    except Exception as e:
        logger.debug(f"turn-health detection failed for {_tag}: {e}")

    return TurnResult(
        response=resp,
        tool_calls=tool_calls,
        just_completed=just_completed,
        in_onboarding=in_onboarding,
        onboarding_field_saved=onboarding_field_saved,
        today_log=today_log,
        user=user,
        health_flags=health_flags,
    )
