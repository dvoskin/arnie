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
from core.platform import (
    Response, React, FX, onboarding_reaction, detect_moment,
    _sanitize_bubble,
)
from core.prompts.onboarding import format_completion_facts
from core.turn_health import (
    looks_like_stall as _looks_like_stall,
    looks_like_dead_end as _looks_like_dead_end,
    looks_like_bare_log_ack as _looks_like_bare_log_ack,
    looks_like_mechanics as _looks_like_mechanics,
    looks_like_empty_praise as _looks_like_empty_praise,
    looks_like_phantom_log_claim as _looks_like_phantom_log_claim,
    detect_turn_flags,
    user_is_signing_off as _user_is_signing_off,
    detect_sarcastic_ack as _detect_sarcastic_ack,
    extract_stated_day_calories as _extract_stated_day_calories,
    DAY_TOTAL_TOLERANCE as _DAY_TOTAL_TOLERANCE,
)
from handlers.tool_executor import (
    execute_tool_calls, deterministic_confirmation, recovery_message,
    tool_heads_up, _heads_up_seed, NEEDS_HEADS_UP_TOOLS,
)

logger = logging.getLogger(__name__)

_LOGGING_TOOLS = frozenset({
    "log_food", "log_exercise", "update_food_entry",
    "delete_food_entry", "update_exercise_entry",
    "log_body_weight", "log_water", "clear_day_log",
})

# Voice-by-default for tool results. After ANY tool that yields a user-facing
# result, a follow-up runs to voice/close it — even when the first pass already
# wrote a lead-in. Only SILENT tools (pure side-effects whose pass-1 text, if any,
# is already the complete reply) skip the follow-up.
#
# This INVERTS the old opt-in allowlists (_VOICED_RESULT_TOOLS / _CARD_CLOSE_TOOLS):
# enrolling a tool was mandatory or its result was silently dropped whenever the
# first pass wrote text — the recurring dead-air / teaser class (query_history,
# then the native-card teaser, each fixed by remembering to add the tool). Default-
# on fails SAFE: a newly added tool gets an extra voicing at worst, never a dropped
# answer. The two failure modes it subsumes:
#   • data-fetch tools (web_search, search_food_database, query_history, track_metric,
#     find_nearby_places) — facts live ONLY in the tool result; the first pass ran
#     before the tool, so it could only write a heads-up.
#   • native-card tools (suggest_meals, suggest_workout, show_day_recap, show_food_log,
#     show_workout_log) — the card carries the substance; the actionable close is a
#     second bubble that must land after the card, in the follow-up pass.
#
# The follow-up is text-only (chat_follow_up runs tools=False), so the result must
# be voiceable from the tool_result + conversation. Logging tools take their own
# branch below (deterministic_confirmation fallback); this governs everything else.
#
# _SILENT_TOOLS — deliver their own artifact or are background side-effects, so a
# re-voice would be redundant or wrong:
#   generate_image          — url + caption delivered via the platform callback
#   store_attribute         — records a fact in the background, no user-facing result
#   note_food_clarification — records a clarification note, not a reply
#   schedule_check_in       — the pass-1 confirmation ("I'll check in at X") suffices
#   set_macro_targets       — the recommended values are pre-injected into the prompt
#                             (the [COACH NOTE — targets_unset] block), so the model
#                             voices them in pass 1; the result has nothing new.
_SILENT_TOOLS = frozenset({
    "generate_image", "store_attribute", "note_food_clarification",
    "schedule_check_in", "set_macro_targets",
})


def _voices_result(tool_name: str) -> bool:
    """Voice-by-default: a tool's result is voiced via a follow-up unless the tool
    is SILENT. Replaces membership checks against the old opt-in allowlists."""
    return tool_name not in _SILENT_TOOLS


def _normalize_plan_exercises(exercises) -> list:
    """Coerce the model's raw suggest_workout exercises to the workout_plan_card
    wire contract before they go on the wire.

    The card payload was the LLM's raw tool input, which OMITS is_cardio on normal
    lifts (the model only sets it on cardio). A native client whose decoder treats
    the contract's is_cardio as required reads the missing key as a hard failure
    and drops the WHOLE card (the iOS workout_plan_card rendered 0% — "you didn't
    send anything"). Always emit is_cardio (default False) and keep name/reps as
    strings so the contract holds for every client, including ones without a
    lenient decoder. Unknown extra keys are preserved (clients ignore them)."""
    out = []
    for e in (exercises or []):
        if not isinstance(e, dict):
            continue
        ex = dict(e)
        ex["is_cardio"] = bool(e.get("is_cardio") or e.get("cardio_type"))
        if ex.get("name") is not None:
            ex["name"] = str(ex["name"])
        if ex.get("reps") is not None:
            ex["reps"] = str(ex["reps"])
        out.append(ex)
    return out


# Workout logging renders NO card for now (2026-07-02). The live set-by-set flow
# made the card an error-prone extra step: a receipt for a still-mutating entry
# whose running set count lagged and often contradicted the prose ("3 sets done"
# sitting over a sets:1 card). Workouts are confirmed in TEXT instead — see the
# WORKOUT LOGGING prompt rule. Flip this to re-enable the card.
_WORKOUT_CARD_ENABLED = False


def _logged_entry_card(name: str, inp: dict) -> Optional[dict]:
    """The macro_card / workout_card for a log_food / log_exercise call — but ONLY
    when it actually created or rolled up into a real DB row.

    The dispatcher stashes that row id on inp["_entry_id"]. A deduped / no-op call
    (the model re-fired something already on the board, e.g. a SPURIOUS log_food on
    a non-food message) never sets it → returns None, so no stale card leaks onto a
    reply that logged nothing (Danny 2026-06-26: "what is 84.9kg in lbs" surfaced
    the earlier coffee's macro_card with entry_id=null). The card must mirror a row
    the user can actually tap/edit. Returns None for any non-logging tool.

    Payload is pulled from the tool_call INPUT — what the LLM said to log, which is
    what Arnie's reply confirms. Pure + side-effect free for unit testing."""
    inp = inp or {}
    entry_id = inp.get("_entry_id")
    if not entry_id:
        return None
    if name == "log_food":
        payload = {
            "name":      inp.get("food_name") or "",
            "quantity":  inp.get("quantity") or "",
            "calories":  int(round(inp.get("calories") or 0)),
            "protein_g": int(round(inp.get("protein")  or 0)),
            "carbs_g":   int(round(inp.get("carbs")    or 0)),
            "fats_g":    int(round(inp.get("fats")     or 0)),
            "source":    "photo" if inp.get("from_photo") else "manual",
            "entry_id":  entry_id,
        }
        # Decision-receipt context (day impact + verdict), stashed by the
        # executor at log time — see core/receipt.py. All keys optional on
        # the wire; older clients simply ignore them.
        receipt = inp.get("_receipt")
        if isinstance(receipt, dict):
            payload.update(receipt)
        # The model's own coach read outranks the deterministic verdict —
        # varied and contextual beats canned. Guarded: short, and no digits
        # (a number here could mismatch the card's own math).
        coach = (inp.get("coach_read") or "").strip()
        if coach and len(coach) <= 90 and not any(ch.isdigit() for ch in coach):
            payload["verdict"] = coach
        return {"type": "macro_card", "payload": payload}
    if name == "log_exercise":
        if not _WORKOUT_CARD_ENABLED:
            return None            # workouts are confirmed in text, not a card
        return {
            "type": "workout_card",
            "payload": {
                "name":             inp.get("exercise_name") or "",
                "sets":             inp.get("sets"),
                "reps":             str(inp.get("reps") or "") or None,
                "weight":           inp.get("weight"),
                "weight_unit":      inp.get("weight_unit") or "lbs",
                "rir":              inp.get("rir"),
                "duration_minutes": inp.get("duration_minutes"),
                "cardio_type":      inp.get("cardio_type"),
                "is_cardio":        bool(inp.get("is_cardio") or inp.get("cardio_type")),
                "entry_id":         entry_id,
            },
        }
    return None


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
    skills_fired: Optional[str] = None  # comma-sep tool names this turn (+":error"); null on no-tool turns
    streamed_bubble_count: int = 0  # bubbles already sent via on_text_delta (handler sends the rest)
    needs_location_share: bool = False  # find_nearby_places ran but had no location → prompt a share
    # ConversationLog row id for this turn (set post-persist in chat_service).
    # Surfaced on the wire so native clients can dedup history reloads by a
    # STABLE identity instead of text/timestamp heuristics.
    log_id: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# BUBBLE STREAMER — accumulates LLM text deltas and emits one bubble per |||
# as soon as it completes. The trailing buffer (anything after the last |||)
# is emitted by finalize() at end of stream. Lives here, not in core/llm.py,
# because |||-splitting is an Arnie-voice contract, not an LLM-API concern.
# ─────────────────────────────────────────────────────────────────────────────


def _canon_bubble(s: str) -> str:
    """Whitespace-collapse a bubble text for streamed-bubble deduplication.
    Two bubbles whose only difference is leading/trailing/internal whitespace
    should be treated as the same bubble — the post-build catch-up loop uses
    this so it can't re-emit a bubble that already streamed (the doubled-
    message bug on tool-fired turns)."""
    return " ".join(s.split()).strip()


class _BubbleStreamer:
    """Per-stream accumulator. on_bubble is async fn(text) → None called per
    completed bubble; finalize() flushes the trailing buffer. Single-use:
    create one per LLM call (first pass + follow-up each get their own).

    Errors in on_bubble are caught + logged so a Telegram send failure can't
    abort the LLM stream mid-flight (we'd lose the rest of the turn)."""

    def __init__(self, on_bubble):
        self.on_bubble = on_bubble
        self._buffer = ""
        self._full_text = ""
        self.flushed_count = 0
        # Canonical text of every bubble we've sent — the post-build catch-up
        # loop checks against this so it never re-emits a bubble that was
        # already streamed live (which was producing the doubled-message bug).
        self.flushed_canon: set[str] = set()
        # HOLD MODE — when True, on_delta buffers completed bubbles into
        # _held_bubbles instead of emitting them live. The first LLM pass runs
        # held so a premature log-confirmation it writes ("logged, 340 cal")
        # can't reach the user BEFORE the DB write actually happens. Once tool
        # execution returns, run_turn either discard_held() (a logging tool
        # fired → the follow-up voices the real committed total) or flush_held()
        # (no write → release the pass-1 text as normal).
        self.held = False
        self._held_bubbles: list[str] = []

    async def on_delta(self, delta: str):
        if not delta:
            return
        self._buffer += delta
        self._full_text += delta
        # Emit every completed bubble (delimited by |||) immediately.
        while "|||" in self._buffer:
            bubble, _, self._buffer = self._buffer.partition("|||")
            await self._emit(bubble)

    async def finalize(self):
        """Flush the trailing buffer (text after the last ||| in the stream)."""
        if self._buffer.strip():
            await self._emit(self._buffer)
            self._buffer = ""

    async def _emit(self, text: str):
        # Sanitize HERE before sending to the platform — the streaming path
        # bypasses Response.from_text (where _sanitize_bubble normally fires),
        # so without this call the model's em dashes reach the user verbatim
        # despite the brand rule. This closes the Telegram-side em-dash leak.
        # _sanitize_bubble is idempotent and strips trailing/leading whitespace
        # too, so the prior `.strip()` is redundant — kept the call for clarity.
        text = _sanitize_bubble(text)
        if not text:
            return
        # While held (first pass), buffer instead of sending — the write hasn't
        # happened yet, so any confirmation text here is unverified.
        if self.held:
            self._held_bubbles.append(text)
            return
        try:
            await self.on_bubble(text)
            self.flushed_count += 1
            self.flushed_canon.add(_canon_bubble(text))
        except Exception as e:
            logger.warning(f"bubble flush failed (continuing stream): {e}")

    async def flush_held(self):
        """Release any held first-pass bubbles to the user, in order. Called when
        the turn fired NO logging tool (pure chat, or a data-fetch turn), so the
        pass-1 text IS the reply and there's nothing to wait on."""
        self.held = False
        held, self._held_bubbles = self._held_bubbles, []
        for text in held:
            try:
                await self.on_bubble(text)
                self.flushed_count += 1
                self.flushed_canon.add(_canon_bubble(text))
            except Exception as e:
                logger.warning(f"held bubble flush failed (continuing): {e}")

    def discard_held(self):
        """Drop the held first-pass bubbles without sending them. Called when a
        logging tool fired: the real confirmation (with the committed DAY TOTAL,
        or an honest 'already on the board' / error line) comes from the
        post-write follow-up, never from pass-1's unverified text."""
        self._held_bubbles = []
        self.held = False


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
    on_interim: Optional[Callable] = None,  # async fn(text) → None; mid-turn heads-up
    on_completion: Optional[Callable] = None,  # fn(user) → str; defaults to plain welcome
    completion_facts: Optional[dict] = None,  # ephemeral TDEE/goal for the just-completed reflection
    on_text_bubble: Optional[Callable] = None,  # async fn(bubble) → None — stream bubbles as they land
    on_tool_start: Optional[Callable] = None,   # async fn(tool_names: list[str]) → None — fired once, just before tools run
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
    _prior_assistant = next((m.get("content", "") for m in reversed(messages)
                             if m.get("role") == "assistant"), "")

    # Sarcasm-on-error detection: a one-word "Great" / "Perfect" right after a
    # mechanics-leak / generic-net / bare-log-ack reply is almost always
    # frustration. Inject a recover cue into the system prompt so the model
    # acknowledges + resets rather than steaming past it.
    if isinstance(_user_text, str) and isinstance(_prior_assistant, str):
        if _detect_sarcastic_ack(_user_text, _prior_assistant):
            system = system + (
                "\n\nUSER MAY BE FRUSTRATED: their one-word 'great'/'perfect' "
                "right after your last reply reads as sarcastic — your previous "
                "turn shipped a mechanics line, a generic 'got that / X cal "
                "today' fallback, or a bare 'logged' ack. open with one short "
                "honest line acknowledging the miss ('my bad, lost the thread "
                "there'), then refocus on what they actually asked. don't "
                "double down on the canned reply."
            )

    # Streaming aggregator — one per turn, accumulates bubble count across the
    # first pass + follow-up + any self-heal retry. None when not streaming.
    _streamed_total = 0
    _streamer = _BubbleStreamer(on_text_bubble) if on_text_bubble else None
    _stream_handler = _streamer.on_delta if _streamer else None
    # Only pass stream_handler to LLM calls when active — keeps the chat() and
    # chat_follow_up() signatures backward-compatible with mocks that predate
    # T2.1 (no kwarg surface change for non-streaming callers / tests).
    _chat_extras = {"stream_handler": _stream_handler} if _stream_handler else {}

    # ── LLM first pass ───────────────────────────────────────────────────────
    # Generous token budget on purpose: a user can dump a whole day of food in one
    # message, which becomes one log_food tool_use block per item (~130 tokens each).
    # Token cost is NOT the constraint here — a complete, correct log is. At 1024 the
    # response truncated mid-turn: it logged ~1 item, the rest were cut off, and the
    # dangling preamble ("Now logging everything:") got sent raw. 4096 fits ~30 items.
    try:
        # Run the first pass HELD: its bubbles are buffered, not sent live, so a
        # log-confirmation the model writes here ("logged, 340 cal") can't outrun
        # the DB write (which happens later, in execute_tool_calls). After tools
        # return we either discard this text (a logging tool fired → the follow-up
        # voices the real committed total) or flush it (no write happened).
        if _streamer:
            _streamer.held = True
        result = await chat(messages, system, tools=True, max_tokens=4096,
                            **_chat_extras)
        # Flush trailing buffer immediately so a no-||| partial doesn't carry
        # over and prepend itself to the next call's first bubble. (Still held —
        # this only moves the trailing text into the held buffer.)
        if _streamer:
            await _streamer.finalize()

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
            # Self-heal retry: stream it too if streaming is on. The original
            # truncated/stalled output already flushed (finalize above), so the
            # retry's stream starts with a clean buffer.
            result = await chat(retry_messages, system, tools=True, max_tokens=8192,
                                **_chat_extras)
            if _streamer:
                await _streamer.finalize()
            _messages_for_followup = retry_messages
    except Exception as e:
        logger.error(f"LLM call failed for {_tag}: {e}")
        # Whole turn errored — give the user an honest recovery line in voice,
        # with a concrete next move ("resend that"). NEVER drop them into
        # silence or a vague "try again later" — that reads as broken; this
        # reads as "we had a sec, send it again." Retention play.
        resp = Response.from_text(recovery_message("llm_error", seed=_user_text))
        return TurnResult(
            response=resp, tool_calls=[], just_completed=False,
            in_onboarding=in_onboarding, onboarding_field_saved=None,
            today_log=today_log, user=user,
        )

    response_text = result["text"]
    raw_content   = result["raw_content"]

    # Deduplicate tool calls — the LLM sometimes emits two identical log_exercise /
    # log_food calls for the same item in one response (seen in screenshots: same
    # exercise logged twice at the same timestamp). Keep only the FIRST call per
    # (tool_name, input_hash). Preserves order; safe for all tool types.
    import json as _json
    _seen_calls: set = set()
    tool_calls = []
    for _tc in result["tool_calls"]:
        _k = (_tc["name"], _json.dumps(_tc.get("input", {}), sort_keys=True))
        if _k not in _seen_calls:
            _seen_calls.add(_k)
            tool_calls.append(_tc)
        else:
            logger.warning(f"Duplicate tool call suppressed for {_tag}: {_tc['name']} {_k[1][:80]}")
    onboarding_field_saved: Optional[str] = None
    # Tracks whether the final response_text was delivered via the live stream.
    # Streamed paths leave it True; any non-streamed assignment (deterministic
    # fallback, on_completion, hardcoded keep-alive) flips it False so the
    # post-build catch-up emits via on_text_bubble. This is the critical fix
    # for the "heads-up streamed but final answer never reaches user" bug
    # when web_search / follow-up fails.
    _response_streamed = True

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

        # ── Interim heads-up (web_search, search_food_database, query_history,
        # generate_image) ─────────────────────────────────────────────────────
        # Sent BEFORE slow tool execution so the user gets an immediate
        # "let me check" bubble instead of dead air the typing indicator can't
        # bridge. Hybrid wording: prefer the model's own first-pass in-voice
        # line (the prompt teaches a short heads-up for slow tools); fall back
        # to a deterministic per-tool bubble when the first pass left no text.
        # Gated by NEEDS_HEADS_UP_TOOLS — log-only turns NEVER trigger it.
        # NOT a double-send: for re-voicing tools (web_search) the final answer
        # comes from the forced follow-up which REPLACES response_text; for
        # non-revoicing slow tools (USDA, history, image), the follow-up coaches
        # on the tool result as usual. The interim is always a distinct bubble.
        needs_heads_up_tc = next(
            (tc for tc in tool_calls if tc["name"] in NEEDS_HEADS_UP_TOOLS),
            None,
        )
        if needs_heads_up_tc:
            _model_wrote_text = bool(response_text and response_text.strip())
            if _streamer:
                # Streaming mode (Telegram): the model's first-pass text already
                # flushed to the user via the bubble stream — DON'T also call
                # on_interim with the same text or the user gets a double-send.
                # Only fill in the deterministic fallback when the model wrote
                # nothing, and route it through on_text_bubble so it lands in
                # the same channel as the streamed bubbles.
                if not _model_wrote_text and on_text_bubble:
                    fallback = tool_heads_up(
                        needs_heads_up_tc["name"],
                        _heads_up_seed(needs_heads_up_tc),
                    )
                    try:
                        await on_text_bubble(fallback)
                        # Count it so the handler doesn't re-send it after the turn.
                        if _streamer:
                            _streamer.flushed_count += 1
                    except Exception as e:
                        logger.error(f"streaming heads-up fallback failed for {_tag}: {e}")
            elif on_interim:
                # Buffered mode (iMessage / no streaming): existing pattern —
                # prefer the model's first-pass line, fall back to deterministic.
                # Sanitize before send: when the line is the model's raw first
                # pass it can contain em dashes; the deterministic fallback is
                # already em-dash-free but sanitize is idempotent, so applying
                # uniformly is safer than branching.
                _interim_raw = (
                    response_text.strip() if _model_wrote_text
                    else tool_heads_up(
                        needs_heads_up_tc["name"],
                        _heads_up_seed(needs_heads_up_tc),
                    )
                )
                _interim = _sanitize_bubble(_interim_raw)
                try:
                    await on_interim(_interim)
                except Exception as e:
                    logger.error(f"interim heads-up failed for {_tag}: {e}")

        # Heads-up to streaming surfaces (iOS): the live thinking indicator
        # morphs from "Thinking…" to the action being taken ("Logging…",
        # "Reviewing your week…") the moment tools dispatch. Fired once, in
        # call order; the client maps names→labels and ignores internal tools.
        # Purely additive — failure here never blocks the turn.
        if on_tool_start:
            _started: list = []
            for _tc in tool_calls:
                _n = _tc.get("name")
                if _n and _n not in _started:
                    _started.append(_n)
            if _started:
                try:
                    await on_tool_start(_started)
                except Exception as e:
                    logger.error(f"on_tool_start failed for {_tag}: {e}")

        tool_results = await execute_tool_calls(
            tool_calls, user, _log_for_tools, db, _source,
            # Current turn text → the dedup turn-intent gate (skills/logging_intent.py).
            # An explicit add cue ("another", "a second X", "ещё") lets a legit repeat
            # log through instead of being eaten by the payload+window dedup. Defaults
            # to "" everywhere else, so non-conversation call paths are unchanged.
            user_message=_user_text if isinstance(_user_text, str) else "",
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

        # Render coach_on_photo results as text bubbles; replace dict with a
        # follow-up confirmation string. The model writes the coaching content
        # (decision + reasoning) DIRECTLY into the tool input — no chat_follow_up
        # round-trip is needed to paraphrase what it already authored. Without
        # this path, the tool_result dict is non-string content for Anthropic's
        # tool_result API, the forced follow-up produces no usable text, and
        # deterministic_confirmation emits its generic "Got that." stall —
        # exactly what happened on Danny's fridge photo (turn 1737, 2026-06-13).
        _coaching_bubbles: list[str] = []
        for tname, tresult in list(tool_results.items()):
            if isinstance(tresult, dict) and tresult.get("_type") == "photo_coaching":
                decision = (tresult.get("decision") or "").strip()
                reasoning = (tresult.get("reasoning") or "").strip()
                if decision:
                    _coaching_bubbles.append(decision)
                if reasoning and reasoning != decision:
                    _coaching_bubbles.append(reasoning)
                tool_results[tname] = (
                    f"Photo coaching delivered to user. "
                    f"decision={decision[:200]} reasoning={reasoning[:200]}. "
                    f"COACH INSTRUCTION: the decision and reasoning bubbles have "
                    f"already been sent to the user. Do NOT re-voice them. If "
                    f"natural, add ONE short closing bubble tying to the user's "
                    f"day so far (cals/protein remaining), otherwise stop here."
                )
        if _coaching_bubbles:
            _coaching_text = "|||".join(_coaching_bubbles)
            if response_text and response_text.strip():
                response_text = f"{response_text.strip()}|||{_coaching_text}"
            else:
                response_text = _coaching_text
            _response_streamed = False  # built from tool dict, never streamed

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

    # ── Fate of the held first-pass bubbles ───────────────────────────────────
    # The first pass ran held (its text was buffered, not sent). Now that tool
    # execution has returned we know whether a write happened:
    #   • a logging tool fired → DISCARD the pass-1 text. It may contain a
    #     premature or fabricated confirmation ("340 cal logged") that the DB
    #     may not back (dedup no-op, error, or a phantom claim). The follow-up
    #     below re-voices the truth from tool_results — the committed DAY TOTAL,
    #     or an honest "already on the board" / recovery line.
    #   • no logging tool (pure chat, or a data-fetch turn) → FLUSH the held
    #     bubbles: the pass-1 text IS the reply, nothing to wait on.
    # Placed OUTSIDE `if tool_calls:` so a no-tool chat turn still releases.
    if _streamer and _streamer.held:
        _fired_logging = any(tc["name"] in _LOGGING_TOOLS for tc in tool_calls)
        if _fired_logging:
            _streamer.discard_held()
        else:
            await _streamer.flush_held()

    # ── Detect onboarding completion ──────────────────────────────────────────
    just_completed = was_onboarding and not in_onboarding

    # ── Follow-up after tool calls ────────────────────────────────────────────
    _followup_tried = False

    async def _try_follow_up(system_override: Optional[str] = None,
                             max_tokens: int = 700) -> Optional[str]:
        """One chat_follow_up call + the shared try/except + logger.error.
        Returns the text, or None on failure (callers own their own fallbacks).
        Streams via _stream_handler when streaming mode is active; finalizes
        the streamer at the end so trailing buffer flushes as the last bubble."""
        # A deep_research turn delivers a full multi-bubble researched plan
        # nearly verbatim — 700 tokens would truncate it mid-plan. Raise the
        # budget for that tool only; every other follow-up keeps the tight cap.
        if max_tokens == 700 and any(
            tc.get("name") == "deep_research" for tc in tool_calls
        ):
            max_tokens = 2600
        try:
            text = await chat_follow_up(
                _messages_for_followup, raw_content, tool_calls, tool_results,
                system_override or system, max_tokens=max_tokens,
                **_chat_extras,
            )
            if _streamer:
                await _streamer.finalize()
            return text
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
                _response_streamed = False  # canned/welcome text wasn't streamed
    else:
        has_logging = any(tc["name"] in _LOGGING_TOOLS for tc in tool_calls)
        if has_logging and not in_onboarding:
            # Coach-unmute path: let Arnie coach on a log instead of a template.
            # Authoritative totals come from the tool result; "NUMBERS ARE SACRED"
            # in the system prompt prevents fabrication.
            _followup_tried = True
            response_text = await _try_follow_up()
            if not response_text:
                # Before falling to the canned "Keep sipping" / "Consistency is
                # the whole game" templates, try ONE directive retry for the
                # quick-log tools (log_water / log_body_weight). These almost
                # always have rich tool_results data the model can voice if
                # given a sharper instruction — the canned line was firing
                # because the first follow-up returned empty, not because the
                # data was missing.
                _quick_log = {tc["name"] for tc in tool_calls} & {
                    "log_water", "log_body_weight"
                }
                if _quick_log:
                    _directive = (
                        f"\n\nQUICK LOG: a {next(iter(_quick_log))} just ran. "
                        "voice it in 1-2 short bubbles — use the actual numbers "
                        "from the tool result (water total / weight kg). no "
                        "mechanics narration, no canned 'keep sipping'. one "
                        "real read + a forward beat."
                    )
                    try:
                        # chat_follow_up's signature is (messages,
                        # raw_assistant_content, tool_calls, tool_results,
                        # system, …) and it returns a STR. The prior call passed
                        # system in position 2 and did .get("text") on a string,
                        # so this whole quick-log voicing retry AlwaysErrored
                        # into the bare except — dead since it shipped. Fixed.
                        _retry = await chat_follow_up(
                            messages, raw_content, tool_calls, tool_results,
                            system + _directive, max_tokens=200,
                        )
                        response_text = (_retry or "").strip()
                    except Exception:
                        pass
                if not response_text:
                    response_text = deterministic_confirmation(
                        tool_calls, today_log, user.preferences, tool_results
                    )
                _response_streamed = False  # deterministic fallback wasn't streamed
        else:
            # DEEP-TURN DIRECT DELIVERY: a successful deep_research run stashed a
            # user-ready plan (already in Arnie's voice, ||| splits, "My move:"
            # close) on the tool input. Deliver it AS the reply and skip the
            # follow-up LLM pass entirely — re-generating ~1.4k tokens would add
            # 10-20s (the iOS 30s request timeout can't absorb it) and reintroduce
            # the compress/re-estimate risk the loop's synthesis already solved.
            # On a failed run `_deep_plan` is absent and the normal follow-up
            # voices the failure instruction like any other tool result.
            _deep_plan = next(
                (tc["input"].get("_deep_plan") for tc in tool_calls
                 if tc.get("name") == "deep_research"
                 and isinstance(tc.get("input"), dict)
                 and tc["input"].get("_deep_plan")),
                None,
            )
            if _deep_plan:
                response_text = _deep_plan.strip()
                _response_streamed = False
            else:
                # Voice-by-default: any non-SILENT tool forces a follow-up EVEN when
                # the first pass already wrote text. Data-fetch results (web_search,
                # etc.) and native-card closes both live outside pass-1 prose — the
                # first pass ran before the tool, so it could only write a heads-up/
                # lead-in. The generic _try_follow_up() re-voices via chat_follow_up
                # (tools=False) using the full system. Only _SILENT_TOOLS (side-
                # effects) opt out, so a newly added tool can never silently drop
                # its result. See _SILENT_TOOLS.
                has_voiceable_result = any(
                    _voices_result(tc["name"]) for tc in tool_calls
                )
                need_followup = (
                    tool_calls and raw_content
                    and (in_onboarding or not response_text or has_voiceable_result)
                )
                if need_followup:
                    _followup_tried = True
                    response_text = await _try_follow_up()

    if not response_text:
        # Last-resort follow-up — only if we haven't already tried
        if tool_calls and raw_content and not _followup_tried:
            response_text = await _try_follow_up()
        if not response_text:
            # Never a bare "done." — real confirmation or recovery line.
            # Branches:
            #   • tool_calls present → deterministic_confirmation reads the
            #     real numbers from the tool results (or surfaces a
            #     tool-error recovery line if a save failed).
            #   • no tool_calls AND no text → the degenerate stall case
            #     (model produced nothing usable, every repair failed).
            #     Admit confusion and tell the user what to send to
            #     recover. Retention play — beats silent dead-air.
            if tool_calls:
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences, tool_results
                )
            else:
                response_text = recovery_message("stall", seed=_user_text)
            _response_streamed = False  # neither path was streamed

    # ── Anti-dead-end guard ────────────────────────────────────────────────────
    # "done" / "got it" / "logged" as the WHOLE reply is banned — it kills the
    # conversation, and it's especially wrong right after the user ANSWERED a question
    # (that should continue, not close). The model still does it despite the prompt
    # rule, so enforce it in code: retry once for a substantive reply.
    #
    # IMPORTANT: only fire when NO logging tools ran. On a logging turn the tools
    # already did the real work — a brief follow-up like "Nice 💪" is valid coaching
    # even if it strips down to a dead-end token. Replacing it with
    # deterministic_confirmation risks sending the wrong canned message (e.g. the
    # body-weight fallback on a food log turn) and kills any coaching value.
    _dead_ended = False
    _logging_turn = any(tc["name"] in _LOGGING_TOOLS for tc in tool_calls)
    try:
        # In streaming mode, dead-end repair can't help: the bubble was already
        # flushed to the user. Skip the repair call (saves a roundtrip), and
        # rely on the prompt-level rule + the streaming follow-up to keep things
        # alive. Dead-end is still recorded in health flags below.
        if (_looks_like_dead_end(response_text)
                and not _logging_turn
                and _streamer is None):
            _dead_ended = True
            logger.warning(f"Dead-end reply for {_tag}: {response_text[:60]!r} — repairing")
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
        elif _looks_like_dead_end(response_text) and not _logging_turn:
            # Still log it for health telemetry even though we don't repair.
            _dead_ended = True
    except Exception as e:
        logger.debug(f"dead-end guard failed for {_tag}: {e}")

    # ── Post-response quality filter ──────────────────────────────────────────
    # Closes three gaps the anti-dead-end guard above can't reach:
    #
    #   1. Streaming dead-ends: the dead-end guard detected the problem but
    #      skipped repair because the bubble was already flushed. For streaming,
    #      we send a CORRECTIVE follow-up so the user gets coaching immediately
    #      after the bare ack — "Logged that." is followed right away by the
    #      totals and next move they actually needed.
    #
    #   2. Logging-turn dead-ends: the guard gates out logging turns to protect
    #      brief valid coaching ("Nice 💪"). But "Logged that." / "All logged." /
    #      "Logged it." are NEVER valid — they only contain acknowledgment, no
    #      coaching. These now get repaired regardless of tool calls.
    #
    #   3. Mechanics narration: "Updated totals are resynced." / "Entry saved."
    #      expose internal plumbing language. The dead-end guard misses them
    #      entirely (they're too long to match _DEAD_END_PHRASES). Caught here.
    #
    # Strategy: for non-streaming, replace response_text before it's frozen.
    # For streaming, the bad bubble is already sent — emit a corrective follow-up
    # via on_text_bubble so the user gets substance right after the bad bubble,
    # and update response_text so history stores the repaired version.
    _REPAIR_PROMPT = (
        "your last reply was either a bare acknowledgment ('Logged that.', 'Done.', "
        "'Sleep well.'), contained internal mechanics language ('totals resynced', "
        "'entry updated', 'changes saved') the user should never see, was a "
        "generic empty-praise phrase ('Great workout!', 'Nice job!', 'Amazing session!') "
        "with no real coaching content, OR was a tool-promise stall ('Let me grab the "
        "macros…', 'Checking the label…') without actually doing the thing. "
        "send a real coaching reply in your normal voice RIGHT NOW. "
        "if your last reply talked about a food or topic the user did NOT mention in "
        "their CURRENT message, that's the bug — refocus on what the user actually "
        "said this turn. their words are the anchor, not a previous open loop. "
        "if tool calls ran this turn: react to what was logged/changed, give the exact "
        "day total from [TODAY], then one clear next move. "
        "if NO tool calls ran (you got confused / lost the thread): briefly acknowledge "
        "the confusion in one line, then ask ONE specific question to get back on track "
        "— reference what the user said specifically, not a generic 'how did it feel?' "
        "example: 'lost my thread for a sec — what were you logging just now?' "
        "2-3 short bubbles (|||). no acknowledgment of the previous bad reply — "
        "just the coaching or the reset question."
    )
    _streaming_dead_end = _dead_ended and _streamer is not None
    # Use the narrow _looks_like_bare_log_ack (not the broad dead-end set) for logging
    # turns — otherwise valid brief coaching like "Nice 💪" ("nice" ∈ _DEAD_END_PHRASES)
    # would be incorrectly flagged and replaced with a full coaching prompt.
    _logging_dead_end = _logging_turn and _looks_like_bare_log_ack(response_text)
    _mechanics = _looks_like_mechanics(response_text)
    # Empty-praise detection: catches "Great workout! How did it feel?" and similar
    # LLM-generated phrases that contain no numbers, no next move, and create a
    # lifecycle loop (pending question keeps firing until answered). Short replies
    # only — long coaching replies with incidental praise are not caught.
    _empty_praise = _looks_like_empty_praise(response_text)
    # Stall detection: "Checking the label…" / "Let me grab the macros…" without
    # a corresponding tool call is a wrong-topic promise that strands the user.
    # Only repair when NO tool ran AND no logging tool succeeded this turn —
    # mid-log "let me get the chicken logged first" with a real log_food call
    # is fine.
    _stall = (not _logging_turn) and not tool_calls and _looks_like_stall(response_text)
    # Phantom log-claim: the user reported a set but the model claimed it was
    # recorded ("noted" / "on the board") without firing a tool — the dropped-set
    # bug. Repair with tools=True so the model actually logs it on the retry.
    _phantom = (not tool_calls) and _looks_like_phantom_log_claim(
        _user_text if isinstance(_user_text, str) else "", response_text, bool(tool_calls)
    )

    # Sign-off: a clear goodnight/closing → 'Sleep well 🌙' is correct. Repair
    # is disabled in this case so we don't generate a full coaching reply after
    # a goodnight (the "Logged: Ground turkey" after-goodnight regression).
    _signing_off = _user_is_signing_off(_user_text if isinstance(_user_text, str) else "")

    if (_streaming_dead_end or _logging_dead_end or _mechanics
            or _empty_praise or _stall or _phantom) and not _signing_off:
        try:
            # Stall repair runs with tools=True — the failure mode is the model
            # promising a tool ("Let me log…") without firing one, so we need to
            # let it actually call the tool on the retry. Other repair classes
            # already produced text (we just want better text), so they stay
            # tools=False to avoid spurious extra logs.
            #
            # Phantom-log is text-only (tools=False) ON PURPOSE: repair-fired tool
            # calls are NOT executed here (this path captures text only), so a
            # tools=True retry would risk an even worse phantom ("logged ✅" with
            # still no write). Instead we make the model OWN the miss honestly and
            # re-ask, so the user re-sends the set and it logs cleanly next turn.
            _repair_tools = _stall and not (_logging_dead_end or _mechanics)
            _repair_extra = (
                "\n\nIMPORTANT: your last reply claimed a set was recorded ('noted' / "
                "'on the board' / 'logged') but you fired NO tool, so NOTHING was saved. "
                "Do NOT claim it's logged. Briefly own the miss in one line and ask the "
                "user to re-send that exact set (weight, reps, and left/right if they "
                "split sides) so you can log it now — e.g. 'my bad, that one didn't save "
                "— what was the rear delt set again?'"
            ) if _phantom else ""
            _repair = await chat(
                messages + [{"role": "assistant", "content": response_text}],
                system + f"\n\nQUALITY REPAIR: {_REPAIR_PROMPT}{_repair_extra}",
                tools=_repair_tools, max_tokens=600 if _repair_tools else 400,
            )
            _repair_text = (_repair.get("text") or "").strip()
            if _repair_text:
                if on_text_bubble:
                    # Streaming: bad bubble already sent — emit repair as immediate follow-up
                    for _b in Response.from_text(_repair_text).bubbles:
                        await on_text_bubble(_b)
                response_text = _repair_text  # history + telemetry store the good version
                if _mechanics and not _dead_ended:
                    _dead_ended = True  # so telemetry records it
                logger.warning(
                    f"Quality repair fired for {_tag} "
                    f"(streaming_dead_end={_streaming_dead_end}, "
                    f"logging_dead_end={_logging_dead_end}, mechanics={_mechanics})"
                )
        except Exception as e:
            logger.debug(f"Quality repair failed for {_tag}: {e}")

    # ── Day-total truth guard ──────────────────────────────────────────────────
    # The DB is the only authority on the running day total. today_log.total_calories
    # is re-derived from the actual entries on every write (recompute_log_totals) and
    # is refreshed after this turn's tools, so it's exact. If the reply STATES a day
    # total that diverges from it, the number is not real: a phantom log ("logged,
    # 984 cal") with no committed write, a dedup no-op the model didn't notice, or
    # arithmetic carried forward across turns (984 = the true 859 + a Guinness that
    # never wrote). Correct it against the DB before it ships, and tell the model to
    # own the miss — never confirm calories that aren't on the board.
    _total_mismatch = False
    try:
        if today_log is not None and not in_onboarding:
            _db_cal = int(round(getattr(today_log, "total_calories", 0) or 0))
            _stated = _extract_stated_day_calories(response_text)
            if _stated is not None and abs(_stated - _db_cal) > _DAY_TOTAL_TOLERANCE:
                _total_mismatch = True
                logger.warning(
                    f"TOTAL_MISMATCH {_tag}: stated={_stated} db={_db_cal} — correcting"
                )
                _truth = (
                    f"\n\nNUMBER CORRECTION — the ONLY correct running day total right "
                    f"now is {_db_cal} calories, straight from the live log. Your last "
                    f"reply stated a different total, which is WRONG. Anything the user "
                    f"reported this turn that isn't reflected in {_db_cal} did NOT get "
                    f"logged — do not claim it did, do not 'double-check' and insist it's "
                    f"there. Re-send your reply using {_db_cal} as the day total; if a "
                    f"food they mentioned is missing, say so plainly in one line and ask "
                    f"them to re-send it so you can log it now. Never state a day total "
                    f"that isn't {_db_cal}."
                )
                _fix = await chat(
                    messages + [{"role": "assistant", "content": response_text}],
                    system + _truth, tools=False, max_tokens=400,
                )
                _fix_text = (_fix.get("text") or "").strip()
                if _fix_text:
                    if on_text_bubble:
                        # Streaming: the wrong total already reached the user — emit the
                        # corrected reply immediately after it. Register each bubble in
                        # the streamer's flushed set so the post-build catch-up can't
                        # re-emit it (the doubled-message guard).
                        for _b in Response.from_text(_fix_text).bubbles:
                            await on_text_bubble(_b)
                            if _streamer:
                                _streamer.flushed_count += 1
                                _streamer.flushed_canon.add(_canon_bubble(_b))
                    response_text = _fix_text
    except Exception as e:
        logger.debug(f"day-total guard failed for {_tag}: {e}")

    # ── Build the platform-agnostic Response ──────────────────────────────────
    # CONTRACT: response_text is FROZEN after this line. All further mutations
    # (bubble injection, dashboard URL, intro prepend) happen on resp.bubbles.
    # The only legitimate post-split read of response_text is sync_pending_questions,
    # which needs the raw LLM string for hook detection. If you ever join resp.bubbles
    # back into a string, derive it from the pre-dashboard slice, not after URL append.
    resp = Response.from_text(response_text)

    # ── Streaming catch-up: emit any non-streamed response bubbles ────────────
    # In streaming mode the model's text streamed live as it arrived. But several
    # paths populate response_text from a NON-streamed source — deterministic
    # fallback, on_completion welcome, hardcoded keep-alive. Those bubbles
    # haven't reached the user yet. _response_streamed tracks this:
    #   True  — final response_text == what was streamed → nothing extra to send
    #   False — final response_text came from a non-streamed fallback → emit
    #           each resp.bubbles via on_text_bubble so the user sees it
    #
    # CRITICAL: the previous index-based catch-up was buggy when the streamed
    # bubbles (e.g. a web_search heads-up "lemme look that up") were NOT in
    # resp.bubbles (which only holds the final response). The old loop saw
    # flushed_count(1) == len(resp.bubbles)(1) and emitted nothing — leaving
    # the user with only the heads-up, never the real answer.
    if _streamer and on_text_bubble:
        if not _response_streamed:
            for bubble in resp.bubbles:
                # Skip any bubble that already streamed live — the streamer
                # tracks canonical text of every bubble it flushed. Without this
                # guard, a tool-fired turn that streamed a heads-up bubble first
                # ("checking your logs") then rebuilt response_text would
                # re-emit ALL final bubbles, doubling content the user already
                # saw. This is the recurring "Morning! ... Morning! ..." bug.
                if _canon_bubble(bubble) in _streamer.flushed_canon:
                    continue
                try:
                    await on_text_bubble(bubble)
                    _streamer.flushed_count += 1
                    _streamer.flushed_canon.add(_canon_bubble(bubble))
                except Exception as e:
                    logger.warning(f"post-build bubble send failed for {_tag}: {e}")
                    break
        _streamed_total = _streamer.flushed_count

    if just_completed:
        resp.effect    = FX.CELEBRATE
        resp.effect_idx = 0
        resp.reaction  = React.LOVE
    elif was_onboarding and onboarding_field_saved:
        resp.reaction = onboarding_reaction(onboarding_field_saved)
    elif not in_onboarding:
        # First-ever food logged this turn? Only a still-gated user can be on
        # their first food (log_unlocked_at flips at 2 entries and grandfathered
        # users are pre-seeded), so established users never pay the COUNT query.
        _first_food = False
        if (any((tc.get("name") == "log_food") for tc in (tool_calls or []))
                and getattr(user, "log_unlocked_at", None) is None):
            try:
                from core.activation import _food_entry_count
                _first_food = (await _food_entry_count(db, user.id)) == 1
            except Exception:
                _first_food = False
        moment         = detect_moment(response_text, tool_calls, first_food=_first_food)
        resp.reaction  = moment.reaction
        resp.effect    = moment.effect
        resp.effect_idx = moment.effect_idx

    # ── Typed inline cards for native clients ─────────────────────────────────
    # A log_food / log_exercise call becomes a macro_card / workout_card — but ONLY
    # when it created a real DB row (see _logged_entry_card; a deduped no-op emits
    # no card, so a stale card never leaks onto a reply that logged nothing). The
    # iOS client renders these inline beneath the text; Telegram/iMessage adapters
    # ignore the field.
    if tool_calls:
        for tc in tool_calls:
            name = tc.get("name")
            inp = tc.get("input") or {}
            _logged = _logged_entry_card(name, inp)
            if _logged is not None:
                resp.cards.append(_logged)
                continue
            if name in ("log_food", "log_exercise"):
                # A logging tool that produced no card = deduped / no-op (no real
                # row). Don't fall through to the card branches below; just skip.
                continue
            if name == "show_day_recap":
                # The dispatcher stashed the full structured snapshot on
                # `inp["_recap_payload"]`; pass it straight through.
                recap = inp.get("_recap_payload")
                if recap:
                    resp.cards.append({
                        "type":    "recap_card",
                        "payload": recap,
                    })
            elif name == "show_food_log":
                log_payload = inp.get("_log_payload")
                if log_payload:
                    resp.cards.append({
                        "type":    "food_log_card",
                        "payload": log_payload,
                    })
            elif name == "show_workout_log":
                log_payload = inp.get("_log_payload")
                if log_payload:
                    resp.cards.append({
                        "type":    "workout_log_card",
                        "payload": log_payload,
                    })
            elif name == "suggest_meals":
                meals = inp.get("meals") or []
                if meals:
                    resp.cards.append({
                        "type": "meal_suggestions_card",
                        "payload": {
                            "title": inp.get("title"),
                            "meals": meals,
                        },
                    })
            elif name == "suggest_workout":
                # Normalize to the wire contract (is_cardio present, stable types)
                # so native clients can decode the card — see _normalize_plan_exercises.
                exercises = _normalize_plan_exercises(inp.get("exercises"))
                if exercises:
                    resp.cards.append({
                        "type": "workout_plan_card",
                        "payload": {
                            "title":     inp.get("title"),
                            "split_day": inp.get("split_day"),
                            "exercises": exercises,
                        },
                    })
            elif name in ("propose_workout_program", "show_workout_program"):
                # The dispatcher stashed the full structured program on
                # `inp["_program_payload"]` (or None if show_workout_program
                # found no active program — surface nothing in that case so
                # the LLM's coaching reply carries the empty-state).
                program_payload = inp.get("_program_payload")
                if program_payload:
                    resp.cards.append({
                        "type":    "workout_program_card",
                        "payload": program_payload,
                    })

    # ── Dashboard link after FIRST food/workout log (once per account) ────────
    # Telegram only. iMessage and iOS skip this nudge:
    #   • iOS renders the dashboard natively (Today/Week/Fitness/Brain tabs).
    #   • iMessage users tend to land on the iOS app shortly after, so a URL
    #     hand-off in the chat thread is redundant noise.
    if not in_onboarding and tool_calls and platform == "telegram":
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
        # had_logging_tool gates hook extraction — a closing "what's next?" after
        # a meal log is coaching voice, not an abandoned question worth re-asking.
        _had_logging = any(tc["name"] in _LOGGING_TOOLS for tc in tool_calls)
        await sync_pending_questions(
            db, user, llm_reply_text=response_text,
            source_type=source_type, had_logging_tool=_had_logging,
        )

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
            source_type=_source,
            tool_names={tc["name"] for tc in tool_calls},
            prior_assistant_text=_prior_assistant if isinstance(_prior_assistant, str) else "",
        )
        if _retried and "retried" not in health_flags:
            health_flags.append("retried")
        if _dead_ended:
            health_flags.append("dead_end")
        if _total_mismatch:
            health_flags.append("total_mismatch")
        # Wall-of-text: the cap is "5+ bubbles only when a plan/breakdown is asked for".
        # Flag turns that blew past it so verbosity is visible in /admin/flagged.
        if len(resp.bubbles) > 5:
            health_flags.append("wall_of_text")
        if health_flags:
            logger.warning(f"TURN_HEALTH {_tag} flags={','.join(health_flags)}")
    except Exception as e:
        logger.debug(f"turn-health detection failed for {_tag}: {e}")

    # Did a nearby-places lookup run WITHOUT a usable location? The executor's
    # no-location / empty branch returns a string starting "PLACES lookup ..."
    # (the success branch starts "NEARBY PLACES ..."). When so, the handler can
    # surface a one-tap share-location button instead of making the user type an
    # address. Fully wrapped — never affects the reply itself.
    _needs_location_share = False
    try:
        if any(tc["name"] == "find_nearby_places" for tc in tool_calls):
            _r = tool_results.get("find_nearby_places")
            if isinstance(_r, str) and _r.startswith("PLACES lookup"):
                _needs_location_share = True
    except Exception:
        pass

    # Tool telemetry for the conversation log: which tools fired this turn and
    # which errored (":error" suffix). Stored in ConversationLog.skills_fired —
    # previously blank on EVERY native (iOS) turn, leaving tool firing and
    # tool-level errors completely un-observable in the logs. Null on no-tool turns.
    _skills_fired = None
    if tool_calls:
        _parts = []
        for tc in tool_calls:
            nm = tc.get("name") or ""
            if not nm:
                continue
            _res = tool_results.get(nm)
            _errored = isinstance(_res, str) and _res.startswith("Error:")
            _parts.append(f"{nm}:error" if _errored else nm)
        _skills_fired = ",".join(_parts) or None

    return TurnResult(
        response=resp,
        tool_calls=tool_calls,
        just_completed=just_completed,
        in_onboarding=in_onboarding,
        onboarding_field_saved=onboarding_field_saved,
        today_log=today_log,
        user=user,
        health_flags=health_flags,
        skills_fired=_skills_fired,
        streamed_bubble_count=_streamed_total,
        needs_location_share=_needs_location_share,
    )
