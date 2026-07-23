"""
Shared conversation pipeline — the single orchestration core for all platforms.

Both bot/imessage_handler and bot/telegram_handler delegate to run_turn().
Platform-specific bits (typing indicator, image delivery, adapter.send,
onboarding keyboards, completion text) stay in each handler; this module
owns everything from LLM call through Response assembly.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from typing import Any, Callable, Optional

from core.llm import chat, chat_follow_up
from core.log_voice import voice_log, fast_log_voice_enabled
from core.platform import (
    Response, React, FX, onboarding_reaction, detect_moment,
    _sanitize_bubble,
)
from core.prompts.onboarding import format_completion_facts
from core.turn_health import (
    looks_like_stall as _looks_like_stall,
    promises_more_logging as _promises_more_logging,
    looks_like_undercounted_food as _looks_like_undercounted_food,
    estimate_food_items as _estimate_food_items,
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
    tool_heads_up, _heads_up_seed, NEEDS_HEADS_UP_TOOLS, blocked_log_reply,
    headsup_voice_enabled, sentence_case,
)

logger = logging.getLogger(__name__)

_LOGGING_TOOLS = frozenset({
    "log_food", "log_exercise", "update_food_entry",
    "delete_food_entry", "update_exercise_entry",
    "log_body_weight", "log_water", "clear_day_log",
})

# ── DETERMINISTIC LOG-CONFIRM MARKER (Danny 2026-07-23) ───────────────────────
# Instead of guessing a phantom from the LLM's freeform phrasing ("🏋️", "logged",
# "on the board" — a whack-a-mole of hotfixes), the model emits ONE hidden token
# whenever it CLAIMS a log. It's stripped before display; if it's present but NO
# logging tool fired, the write didn't happen → force-log. One signal, every log
# type, deterministic. Switch: LOG_MARKER.
_LOG_MARKER = "[[LOGGED]]"


def _log_marker_enabled() -> bool:
    return os.getenv("LOG_MARKER", "true").lower() in ("true", "1", "yes")


def _log_fastpath_enabled() -> bool:
    """D (marker-gated deterministic fast-path). When the manifest ([[DID: log_food]]
    / [[LOGGED]]) is present AND a real log tool fired, the write is confirmed — ship
    the deterministic confirmation (real numbers from the committed DB, zero model
    latency) and SKIP the voice_log pass. Confirmations come from the DB, not model
    narration. Default OFF (a reply-voice change on the hot path — flip after review).
    Switch: LOG_FASTPATH=true."""
    return os.getenv("LOG_FASTPATH", "false").lower() in ("true", "1", "yes")


_LOG_MARKER_INSTRUCTION = (
    "\n\n[ACTION MANIFEST — machine check, NOT user-facing]\n"
    "Whenever your reply tells the user you DID something a tool performs — logged, "
    "recorded, saved, added, updated, or deleted a food, set, exercise, body weight, "
    "or water; or looked up / checked / searched a food's nutrition — append at the "
    "VERY END a hidden manifest naming the EXACT tool(s) you actually called this "
    "turn: [[DID: log_food]] , [[DID: log_exercise, log_water]] , "
    "[[DID: search_food_database]] , [[DID: update_food_entry]] . It is stripped "
    "before the user ever sees it; never mention, explain, or vary it. Name a tool "
    "ONLY when you truly called it THIS turn. Do NOT emit it for a plan, a question, "
    "a clarification, or your own estimate that called no tool. A tool named in "
    "[[DID: ...]] but not actually called is treated as a FAILED action and is "
    "force-run — so if you claim it, call it. (A bare [[LOGGED]] is still accepted "
    "as 'a write happened'.)"
)


# ── GENERIC ACTION MANIFEST + LOOKUP RESCUE (B, 2026-07-23) ───────────────────
# Generalizes the boolean [[LOGGED]] marker: the model also names the EXACT tool(s)
# it claims via [[DID: tool, ...]]. A tool named but not fired = a claimed-action
# gap → rescue. First arm wired here is LOOKUP: the user asks about a SPECIFIC
# product and the model ANSWERS WITH AN ESTIMATE (Bonilla de la Vista, IMG_8582)
# instead of calling search_food_database / web_search. This is the reliability
# foundation meant to scale to many tools. Switch: LOOKUP_RESCUE.
_LOOKUP_TOOLS = frozenset({"search_food_database", "web_search"})


def _lookup_rescue_enabled() -> bool:
    return os.getenv("LOOKUP_RESCUE", "true").lower() in ("true", "1", "yes")


def _parse_did(text: str) -> set:
    """Tool names the model claims it called this turn, from [[DID: a, b]] tags."""
    import re
    out = set()
    for m in re.finditer(r"\[\[\s*DID\s*:\s*([^\]]+?)\s*\]\]", text or "", re.I):
        for name in m.group(1).split(","):
            name = name.strip()
            if name:
                out.add(name)
    return out


_LOOKUP_MARKER_INSTRUCTION = (
    "\n\n[LOOKUP DISCIPLINE — machine check, NOT user-facing]\n"
    "When the user asks what's in / how many calories or macros are in a SPECIFIC "
    "product, brand, or restaurant item (not a staple you know cold like plain rice "
    "or an egg), you MUST call search_food_database — or web_search for a brand or "
    "restaurant item USDA won't have — and answer FROM the result. Do NOT give your "
    "own approximation and imply you checked it. When you DO look something up, "
    "append the exact hidden tag [[DID: search_food_database]] or [[DID: web_search]] "
    "at the very end (stripped before the user sees it; never mention or vary it). An "
    "estimate to a specific-product question with no lookup is force-checked and "
    "re-answered with the real numbers."
)

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
    "schedule_check_in", "set_macro_targets", "refresh_coach_brief",
})


def _voices_result(tool_name: str) -> bool:
    """Voice-by-default: a tool's result is voiced via a follow-up unless the tool
    is SILENT. Replaces membership checks against the old opt-in allowlists."""
    return tool_name not in _SILENT_TOOLS


def _fluid_rescue_enabled() -> bool:
    """Hold a NO-tool turn's voicing through the rescue decision so any fix ships
    as ONE reply, never a base reply + a visible late patch (Danny 2026-07-21:
    "fluid, not witness the backend"). FLUID_RESCUE=false restores the old
    live-flush behaviour."""
    return os.getenv("FLUID_RESCUE", "true").lower() in ("true", "1", "yes")


# ── July-5 strip kill-switches (2026-07-22) ──────────────────────────────────
# Each gates one bolt-on pass stacked on the healthy 2-pass turn. Introduced
# DEFAULTING TO CURRENT BEHAVIOR so landing them is a no-op; the strip flips the
# defaults one at a time, each independently revertible via its env var. The
# goal is July-5 quality: fast, single-source voice, clarifies on real ambiguity,
# and NO heuristic forced-re-log passes (they caused the reliability regression).
def _hold_voicing_enabled() -> bool:
    """HOLD the pure-food reply until voice_log verifies its total before any
    bubble ships. voice_log is now single-source over the DB-committed total, so
    it structurally can't phantom a number — the hold is dead weight and the
    direct cause of log-reply lag vs July-5's live streaming. HOLD_VOICING=false
    streams live; =true restores the hold (default). NOTE 2026-07-22: a blanket
    default-off REGRESSED — it leaks the pass-1 premature confirmation on the
    general streaming path (tests/test_streaming.py). Kept ON; a targeted strip
    (pure-food path only) is the correct next step, not a global flip."""
    return os.getenv("HOLD_VOICING", "true").lower() in ("true", "1", "yes")


def _self_heal_enabled() -> bool:
    """Retry pass-1 once (bigger budget + finish nudge) on truncation/stall.
    Completeness is now owned by the deterministic scribe reconcile, so the
    _stalled regex-over-prose trigger over-fires and doubles TTFB. When on, the
    trigger is also narrowed to truncation-only. SELF_HEAL_ENABLED=false disables
    the retry entirely; =true keeps it."""
    return os.getenv("SELF_HEAL_ENABLED", "true").lower() in ("true", "1", "yes")


def _phantom_rescue_enabled() -> bool:
    """The no-tool 'claimed logged but called no tool' forced-re-log pass — an
    authority-inverting heuristic that guesses-and-logs instead of letting the
    model clarify, and the flip-flop behind the reliability regression. The
    single-source voice_log can't phantom a total, so this net is redundant.
    STRIPPED by default (2026-07-22, restore July-5 reliability); set
    PHANTOM_RESCUE_ENABLED=true to bring the force-re-log back."""
    return os.getenv("PHANTOM_RESCUE_ENABLED", "false").lower() in ("true", "1", "yes")


def _omission_rescue_enabled() -> bool:
    """The no-tool 'reported a food but logged nothing' forced-re-log pass. Same
    authority inversion as phantom; the deterministic partial-drop reconcile
    already catches genuine drops with no extra model pass.
    STRIPPED by default (2026-07-22); set OMISSION_RESCUE_ENABLED=true to restore."""
    return os.getenv("OMISSION_RESCUE_ENABLED", "false").lower() in ("true", "1", "yes")


def _activity_rescue_enabled() -> bool:
    """The co-mentioned-workout forced tools=True pass — a whole extra
    tool-calling round-trip to log-or-ask an activity on any food+activity turn.
    ACTIVITY_RESCUE_ENABLED default STRIPPED (2026-07-22, a cheap appended clarify
    replaces it); set =true to restore the extra tool pass."""
    return os.getenv("ACTIVITY_RESCUE_ENABLED", "false").lower() in ("true", "1", "yes")


def _exercise_phantom_enabled() -> bool:
    """Force-log a SET/movement the model claimed ("🏋️ … logged") but never wrote
    (Danny 2026-07-23: sets dropped deeper into the session). Default ON — the
    exercise-side counterpart to the food phantom rescue, which the food-only
    trigger never reached. EXERCISE_PHANTOM=false disables."""
    return os.getenv("EXERCISE_PHANTOM", "true").lower() in ("true", "1", "yes")


_FOOD_LOG_TOOLS = frozenset({"log_food", "update_food_entry"})

# Lookups a food-log turn may ALSO fire without being "impure": brand-macro and
# history lookups done IN SERVICE of the log, not a separate answer owed to the
# user. voice_log reads the COMMITTED food facts (already enriched by these), so
# it voices the result correctly with NO follow-up. Allowing them here is the
# double fix (2026-07-21): a branded/multi-item log that also hit
# search_food_database / web_search used to fall to the follow-up + post-build
# catch-up path — TWO text sources, the "long reply then only the short one
# survives reload" bug. Now it takes the single voice source like any log.
_LOG_COMPANION_TOOLS = frozenset({
    "search_food_database", "web_search", "query_history", "track_metric",
})


def _is_pure_food_log(tool_calls, user_text) -> bool:
    """A turn whose real action is logging food — the single fast-voice path.

    Widened 2026-07-21 to kill the double: a food-log turn stays "pure" even when
    it also fired a LOOKUP tool (brand macros, history, web) in service of the
    log — voice_log reads the committed, already-enriched facts, so that result
    needs no separate voicing. Only a genuinely-asked question (a "?" the log-read
    can't answer) or a truly unrelated tool (workout, image, nearby-places) drops
    it to the full follow-up path so THAT result still gets voiced. Silent
    side-effect tools never count against "pure"."""
    names = [tc.get("name") for tc in (tool_calls or [])]
    if not any(n in _FOOD_LOG_TOOLS for n in names):
        return False
    for n in names:
        if n in _FOOD_LOG_TOOLS or n in _SILENT_TOOLS or n in _LOG_COMPANION_TOOLS:
            continue
        return False   # a genuinely unrelated tool means there's more to voice
    if isinstance(user_text, str) and "?" in user_text:
        return False   # a real question needs a coached answer, not just a log read
    return True


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
def _workout_card_enabled() -> bool:
    """Emit a workout_card on each log_exercise so the iOS card re-renders live as
    sets/movements land (Danny 2026-07-23 — he couldn't tell if sets logged). The
    card is gated on a real DB row (_entry_id below), so it appears ONLY when the
    set actually wrote: no card = it didn't land, which is the visibility signal.
    WORKOUT_CARD=false reverts to text-only confirmations."""
    return os.getenv("WORKOUT_CARD", "true").lower() in ("true", "1", "yes")


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
        if not _workout_card_enabled():
            return None            # WORKOUT_CARD=false → text-only confirmation
        # Prefer the FINAL DB-row values the dispatcher stashed (_card_sets /
        # _card_reps) so an appended set shows the movement's running total
        # ("3×12,13,13"), not the lone set from this one call. Falls back to the
        # call input for a fresh single log.
        _cs = inp.get("_card_sets", inp.get("sets"))
        _cr = inp.get("_card_reps")
        _cr = str(_cr) if _cr is not None else (str(inp.get("reps") or "") or None)
        return {
            "type": "workout_card",
            "payload": {
                "name":             inp.get("exercise_name") or "",
                "sets":             _cs,
                "reps":             _cr,
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
    # entry_ids of log cards ALREADY streamed early (right after tool execution,
    # before the follow-up voicing pass) so the done-frame doesn't re-send them.
    streamed_card_ids: list = dataclasses.field(default_factory=list)
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
        # The RAW bubbles actually sent to the user, in order — so the turn's
        # returned reply can be reconstructed as EXACTLY what streamed. This is
        # what makes the deterministic fallback impossible to double-send on a
        # streaming turn: if the model's reply already reached the user, the
        # returned response IS that reply, not a canned tail (the triple-
        # confirmation bug, root-caused 2026-07-20 — the done-frame carried the
        # canned bubbles even after suppression guarded the re-send loop).
        self.flushed_bubbles: list[str] = []
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
            self.flushed_bubbles.append(text)
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
                self.flushed_bubbles.append(text)
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
    on_card: Optional[Callable] = None,         # async fn(cards: list[dict]) → None — log cards, streamed the instant they're written (before the follow-up pass)
) -> TurnResult:
    """
    Core pipeline: LLM call → tool execution → coach-unmute / follow-up /
    deterministic fallback → Response assembly (detect_moment, dashboard-link-once).

    Returns a TurnResult so each handler can apply its own delivery layer.
    """
    import time as _time_mod
    _turn_t0 = _time_mod.monotonic()
    _source = source_type or platform
    _tag = f"{platform}:{user.id}"
    _retried = False  # turn-health: did the self-heal fire this turn?
    _messages_for_followup = messages
    _first_stop_reason = None
    _user_text = next((m.get("content", "") for m in reversed(messages)
                       if m.get("role") == "user"), "")
    _prior_assistant = next((m.get("content", "") for m in reversed(messages)
                             if m.get("role") == "assistant"), "")

    # GATE-EFFECTIVE MESSAGE — computed ONCE, top-level, so it protects EVERY
    # intent-sensitive path (dedup gate, carryover guard, AND the phantom-claim
    # rescue). A clarify-ANSWER ("regular size minimal oil") carries the food
    # named in the prior turn's message; without this the phantom detector saw
    # only the answer, found no food word, and let a "wrap logged" claim ship
    # unrescued (Danny's wrap saga #7125-7127, 2026-07-20).
    from skills.logging_intent import effective_intent_message as _eff_intent
    _prev_user_text = next(
        (m.get("content") for m in reversed(messages[:-1])
         if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
    _prev_assistant_text = next(
        (m.get("content") for m in reversed(messages[:-1])
         if m.get("role") == "assistant" and isinstance(m.get("content"), str)), "")
    _gate_user_message = _eff_intent(
        _user_text if isinstance(_user_text, str) else "",
        _prev_user_text, _prev_assistant_text)

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
    _early_card_ids: list = []   # log cards streamed early (before the follow-up)
    # VERIFY-BEFORE-STREAM: on a streaming logging turn we HOLD the follow-up voicing
    # (buffer, don't stream live) until the day-total guard has checked its running
    # total against the DB. Then the verified response_text is emitted ONCE via the
    # post-build catch-up. Without this, a phantom total streams live and the guard's
    # correction can only APPEND — the double-reply (turkey+rice: "1698" then "1566").
    _hold_voicing = False
    # ASK-FIRST HOLD: set below (pre-execute) when a strict-mode swing holds the
    # meal's writes; read in the reply-selection block. Init here so a no-tool
    # turn (which skips the tool-execution block) never reads it unbound.
    _ask_first_q = None
    _streamer = _BubbleStreamer(on_text_bubble) if on_text_bubble else None
    _stream_handler = _streamer.on_delta if _streamer else None
    # Only pass stream_handler to LLM calls when active — keeps the chat() and
    # chat_follow_up() signatures backward-compatible with mocks that predate
    # T2.1 (no kwarg surface change for non-streaming callers / tests).
    _chat_extras = {"stream_handler": _stream_handler} if _stream_handler else {}
    _scribe_task = None  # the parallel scribe extraction; set inside the pass below
    _missing_from_scribe: list = []  # named-but-unlogged items → partial-drop rescue

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
        from core.llm import pick_model
        _stage_model = pick_model(user)
        if _stage_model:
            _chat_extras["model"] = _stage_model
        # SCRIBE — launch deterministic item extraction IN PARALLEL with pass-1 (Haiku
        # finishes before opus → no added latency). Only for multi-item food messages;
        # consulted after pass-1 to name a dropped item precisely (egg whites, etc.).
        _scribe_task = None
        try:
            import asyncio as _asyncio
            from core.scribe import scribe_enabled, should_run_scribe, extract_food_items
            if scribe_enabled() and should_run_scribe(_gate_user_message):
                _scribe_task = _asyncio.create_task(
                    extract_food_items(_gate_user_message))
        except Exception:
            _scribe_task = None
        # Append the log-confirm marker instruction once; every downstream chat
        # (retry, rescues) reuses this same `system`, so the model is told to emit
        # [[LOGGED]] on any real log throughout the turn.
        if _log_marker_enabled():
            system = system + _LOG_MARKER_INSTRUCTION
        if _lookup_rescue_enabled():
            system = system + _LOOKUP_MARKER_INSTRUCTION
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
        # Partial stall: it logged SOME items then promised the rest ("Salmon's in.
        # Let me get the rest.") — a drip the zero-tool stall check misses. Force the
        # remaining items THIS turn. Only for logging turns (tools already fired).
        _partial_stall = bool(result["tool_calls"]) and _promises_more_logging(_txt)
        # Silent under-log: an enumerated multi-item meal (burrito bowl, 10 components)
        # where only 1-2 log_food fired and the reply looked complete — no promise to
        # catch. Count items named vs logged; a big shortfall self-heals.
        _num_food_logs = sum(1 for _tc in (result["tool_calls"] or [])
                             if (_tc.get("name") or "") == "log_food")
        _undercount = _looks_like_undercounted_food(_gate_user_message, _num_food_logs)
        # SCRIBE — NOT a forcing gate on pass-1 (forcing re-itemized composites →
        # the delete-storms). It stays ALIVE for the POST-WRITE completeness
        # reconcile below (2026-07-21): after the writes land we ask the scribe
        # which named items are MISSING and rescue ONLY those, so a dropped
        # distinct dish ("175g turkey and 100g rice" → turkey logged, rice dropped
        # ~1/3 of the time) gets ADDED without touching the composite it correctly
        # logged as one. Self-heal below still fires only on a real truncation/
        # stall. Kill switch: SCRIBE_ENABLED.
        if _partial_stall or _undercount:
            logger.info(
                f"completeness flag for {_tag} (partial_stall={_partial_stall}, "
                f"undercount={_undercount}, food_logs={_num_food_logs})")
        if _self_heal_enabled() and (_truncated or _stalled):
            logger.warning(
                f"Incomplete first pass for {_tag} (truncated={_truncated}, "
                f"stalled={_stalled}) — retrying once with a finish nudge")
            _retried = True
            _nudge = (
                "Finish that now, in ONE message: actually CALL the tools for every "
                "item you listed, then confirm with the running total. Don't narrate, "
                "don't stop on a colon, don't promise to do it next.")
            retry_messages = messages + [
                {"role": "assistant", "content": _txt or "(started but didn't finish)"},
                {"role": "user", "content": _nudge},
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
        try:
            if _scribe_task is not None and not _scribe_task.done():
                _scribe_task.cancel()   # don't leak the parallel extraction
        except Exception:
            pass
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
                if headsup_voice_enabled():
                    _interim = sentence_case(_interim)   # 'checking…' → 'Checking…'
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

        # ── ASK-FIRST HOLD (strict mode, July-7 behavior) ────────────────────
        # A strict user wants an unstated high-swing detail (grilled vs fried,
        # butter/sauce amount, portion) ASKED before the log, not sharpened after.
        # opus-4-8 ignores the frozen prompt's ask-first rule and logs first
        # (verified 2026-07-22), so enforce it here: detect the swing on the
        # PROPOSED log_food inputs, and if one clears the mode threshold, HOLD the
        # meal's writes, ask ONE question, and let the answer turn log it (the
        # prompt's "hold -> ask -> then log EVERYTHING"). Switch: ASK_FIRST_HOLD.
        if (not in_onboarding and _is_pure_food_log(tool_calls, _user_text)):
            from core.clarify import (
                ask_first_hold_enabled, is_ask_first_mode, clarify_swings)
            if ask_first_hold_enabled() and is_ask_first_mode(user):
                # If a hold is ALREADY open, THIS turn is the answer to it — never
                # re-hold (that's the clarify loop that ate the log). Let the
                # force-log-on-answer branch commit it instead.
                _already_held = False
                try:
                    from db.queries import get_open_pending_question as _gopq
                    _already_held = (await _gopq(
                        db, user.id, "food_ask_first")) is not None
                except Exception:
                    _already_held = False
                if not _already_held:
                    try:
                        _ask_first_q = await clarify_swings(tool_calls, None, user)
                    except Exception as _e:
                        logger.warning(f"ask-first hold check failed: {_e}")
                        _ask_first_q = None
        if _ask_first_q:
            # STASH the full held log_food inputs so the answer turn can replay
            # them DETERMINISTICALLY if the model loops (never lose the meal).
            _held_inputs = [dict(tc.get("input") or {})
                            for tc in tool_calls if tc.get("name") == "log_food"]
            _held_names = [i.get("food_name") for i in _held_inputs]
            # Record the pending WITH the stash FIRST; only actually HOLD (drop the
            # writes) if it persisted — so we can never remove a meal's writes
            # without a recoverable way to replay them.
            _held_ok = False
            try:
                from db.queries import record_pending_question
                # kind="food_ask_first" (NOT "food_clarification") so the
                # force-log-on-answer branch tells a HELD meal (nothing logged,
                # must LOG on the answer) apart from the log-first clarify pending
                # (item already logged, UPDATE on answer) — mixing them double-logs.
                _pq = await record_pending_question(
                    db, user.id, kind="food_ask_first", question=_ask_first_q,
                    tier="food_clarification", hook_style="question")
                _pq.item_referenced = next((n for n in _held_names if n), "meal")
                _pq.payload_json = json.dumps(_held_inputs)
                await db.commit()
                _held_ok = True
            except Exception as _e:
                logger.warning(f"ask-first stash failed, NOT holding: {_e}")
            if _held_ok:
                logger.info(f"event=ask_first_hold user={getattr(user,'id',None)} "
                            f"items={_held_names}")
                # Drop the food writes — nothing logs this turn; the answer logs.
                tool_calls = [tc for tc in tool_calls if tc.get("name") != "log_food"]
                if _streamer:        # don't show the pass-1 log-confirmation text
                    try:
                        _streamer.discard_held()
                    except Exception:
                        pass
            else:
                # Couldn't persist the stash → do NOT hold; let the log go through
                # normally this turn (log-first fallback), never a silent drop.
                _ask_first_q = None

        # The gates judge the CURRENT message — but a clarify-ANSWER carries
        # the intent of the exchange it answers (item names live in the prior
        # user message; the answer says "6 oz fish and yes…"). Combine for
        # the gate only — _gate_user_message is computed once at the top.
        tool_results = await execute_tool_calls(
            tool_calls, user, _log_for_tools, db, _source,
            # Turn text → the dedup turn-intent gate (skills/logging_intent.py).
            # An explicit add cue ("another", "a second X", "ещё") lets a legit repeat
            # log through instead of being eaten by the payload+window dedup. Defaults
            # to "" everywhere else, so non-conversation call paths are unchanged.
            user_message=_gate_user_message,
        )

        # ── SCRIBE SHADOW (observe-only) ─────────────────────────────────
        # The write-set validator judges what the model ACTUALLY did against
        # the justification rules and logs divergences — it changes nothing.
        # This is stage-2 groundwork for the talker/scribe split: the
        # divergence stream tunes the rules until they can gate writes for
        # real. Kill switch: SCRIBE_SHADOW_ENABLED=false. Fully wrapped.
        try:
            if os.getenv("SCRIBE_SHADOW_ENABLED", "true").lower() in ("true", "1", "yes"):
                from core.write_set import validate_write_set, summarize
                _shadow = summarize(validate_write_set(
                    tool_calls, _gate_user_message,
                    getattr(_log_for_tools, "food_entries", None) or [],
                    from_photo=(_source == "photo"),
                ))
                # OMISSION HINT — the symmetric failure the write-set can't
                # see (the dates and salmon both began as missed logs): a
                # food-report-shaped message with zero log writes. Broad by
                # design (questions about food match too) — a divergence
                # counter for review, never an alarm on its own.
                _no_log_write = not any(
                    (tc.get("name") or "") in
                    ("log_food", "log_exercise", "log_water", "log_body_weight")
                    for tc in (tool_calls or []))
                _omission_hint = False
                if _no_log_write and isinstance(_user_text, str):
                    from core.turn_health import _FOOD_REPORT_RE as _frr
                    _omission_hint = bool(_frr.search(_user_text))
                if _shadow["flagged"]:
                    logger.warning(
                        f"event=scribe_shadow user={getattr(user, 'id', None)} "
                        f"counts={_shadow['counts']} flagged={_shadow['flagged']} "
                        f"omission_hint={_omission_hint}"
                    )
                else:
                    logger.info(
                        f"event=scribe_shadow user={getattr(user, 'id', None)} "
                        f"counts={_shadow['counts']} omission_hint={_omission_hint}"
                    )
        except Exception:
            logger.warning("scribe shadow failed (observe-only)", exc_info=True)

        # ── EARLY CARD EMIT — DISABLED 2026-07-20 ─────────────────────────
        # Streaming the card the instant the row was written (added 3a656f1,
        # 2026-07-20) made it arrive BEFORE the user's own message / the reply
        # on the client — the "card on top of my message" regression. Ordering
        # matters more than the ~1-2s the card lands sooner, and this is how it
        # behaved for months. Cards now flow through the done-frame in order
        # (streamed_card_ids stays empty, so the done-frame emits them all).
        _early_card_ids: list = []

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

        # ── PARTIAL-DROP reconcile (scribe) ───────────────────────────────────
        # The model intermittently logs the first distinct dish and drops the rest
        # ("175g turkey and 100g rice" → turkey only, ~1/3 of the time). A tool DID
        # fire, so the phantom/omission nets can't see it, and self-heal is
        # truncation/stall-only. Ask the scribe which NAMED items never logged and
        # (below) rescue ONLY those. SAFE against over-split: the scribe extracts a
        # bowl/wrap/burrito as ONE item, so a correctly-logged composite has nothing
        # missing (validated 2026-07-21). Kill switch: SCRIBE_ENABLED.
        if _scribe_task is not None:
            _fired_food_log = any(tc.get("name") == "log_food" for tc in tool_calls)
            try:
                if _fired_food_log:
                    from core.scribe import unlogged_items as _unlogged
                    _extracted = await _scribe_task
                    _logged_names = [
                        (tc.get("input") or {}).get("food_name") or ""
                        for tc in tool_calls if tc.get("name") == "log_food"
                    ]
                    # DETERMINISTIC partial-drop (2026-07-21): the scribe found MORE
                    # items than logged → log the missing one(s) DIRECTLY from the
                    # scribe's own macros through the normal enrichment path. NO Opus
                    # rescue call — that was the latency + regenerate-double-log
                    # source. unlogged_items is COUNT-gated (a composite logs as ONE
                    # → nothing missing, never over-splits) and uses FUZZY identity
                    # so a renamed item ('Parmesan' logged as 'Parmigiano') is seen
                    # as covered, not re-logged. Runs BEFORE voice_log so the meal
                    # voices COMPLETE in one clean reply. Kill switch: SCRIBE_ENABLED.
                    _to_log = _unlogged(_extracted, _logged_names)
                    if _to_log:
                        logger.warning(
                            f"event=partial_drop {_tag} logged={_logged_names} "
                            f"adding={[it.get('name') for it in _to_log]}")
                        _synth = [{"name": "log_food", "input": {
                            "food_name": it.get("name"),
                            "quantity": it.get("quantity") or "",
                            "calories": it.get("calories"),
                            "protein": it.get("protein"),
                            "carbs": it.get("carbs"),
                            "fats": it.get("fats"),
                        }} for it in _to_log]
                        try:
                            _pd_res = await execute_tool_calls(
                                _synth, user, _log_for_tools, db, _source,
                                user_message=_gate_user_message)
                            for _tc in _synth:
                                tool_calls.append(_tc)
                                tool_results.setdefault(
                                    _tc["name"], _pd_res.get(_tc["name"], ""))
                            if today_log is not None:
                                await db.refresh(today_log)
                            logger.warning(f"event=partial_drop_det outcome=logged {_tag}")
                        except Exception as e:
                            logger.error(f"deterministic partial-drop failed {_tag}: {e}")
                else:
                    _scribe_task.cancel()
            except Exception:
                try:
                    _scribe_task.cancel()
                except Exception:
                    pass

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
            # Keep HOLDING for the follow-up voicing: its running total must be
            # verified against the DB before a single bubble reaches the user, so a
            # phantom total can be CORRECTED (replaced) instead of only appended.
            # The verified response_text ships once via the post-build catch-up.
            _streamer.held = True
            _hold_voicing = _hold_voicing_enabled()
        elif _fluid_rescue_enabled() and not tool_calls:
            # FLUID (Danny 2026-07-21: "the UX should be fluid, not witness the
            # backend"). A NO-tool turn is exactly where the phantom/omission
            # rescue fires — and releasing the pass-1 text HERE made that fix land
            # as a SECOND late bubble after the user already saw the (often wrong)
            # base reply — the visible two-step. Keep it held; the FINAL reply
            # (pass-1 text, or a rescue that replaces it) ships ONCE via the
            # post-build catch-up. No live-typing is lost — pass-1 ran held. SCOPED
            # to no-tool turns so a data-fetch heads-up ("let me check", a
            # web_search turn) still flushes live below — that's an intended cue,
            # not a seam.
            _streamer.discard_held()
            _hold_voicing = _hold_voicing_enabled()
        else:
            await _streamer.flush_held()

    # ── Detect onboarding completion ──────────────────────────────────────────
    just_completed = was_onboarding and not in_onboarding

    # ── Follow-up after tool calls ────────────────────────────────────────────
    _followup_tried = False
    # True when a fallback replaced response_text AFTER real bubbles already
    # streamed — the user HAS their reply; the fallback is for the RECORD
    # (persistence), never a second on-screen send (the triple-confirmation
    # report: full streamed reply + the canned confirmation tail).
    _suppress_trailing = False

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
        _all_blocked = blocked_log_reply(tool_calls, tool_results) \
            if has_logging else None
        if _ask_first_q:
            # ASK-FIRST HOLD: the meal's writes were dropped so the swing gets
            # pinned BEFORE logging. The reply IS the question — no log voicing,
            # no follow-up (nothing was written to voice). The answer turn logs.
            _followup_tried = True
            response_text = _ask_first_q
            _response_streamed = False
            if _streamer:
                try:
                    await _streamer.finalize()
                except Exception:
                    pass
        elif _all_blocked is not None and not in_onboarding:
            # Every log this turn was an already-on-the-board block: no row
            # written, totals unchanged. The model follow-up is SKIPPED — a
            # fabricated "logged, you're at X" can't ship if it's never
            # generated. Deterministic honest readback instead.
            _followup_tried = True
            response_text = _all_blocked
            _response_streamed = False
            if _streamer:
                try:
                    await _streamer.finalize()
                except Exception:
                    pass
        elif has_logging and not in_onboarding:
            _followup_tried = True
            # ── FAST CLEAN LOG VOICE — SINGLE SOURCE ──────────────────────────
            # A pure food-log turn gets ONE sub-second read over the committed
            # facts (core/log_voice): numbers handed in from the DB (can't phantom
            # a total), a tiny focused prompt (can't ramble / loop). And if that
            # read returns nothing (a transient Sonnet miss), the fallback is the
            # deterministic confirmation — NEVER the legacy follow-up. The follow-up
            # streams live AND the post-build catch-up re-emits, which is the double;
            # on a voice_log miss it was silently reappearing (Danny 17:23: long
            # reply, then hidden, template stored, card late). One source, always.
            # Switch: FAST_LOG_VOICE=false.
            _pure_food = _is_pure_food_log(tool_calls, _user_text)
            _fast_voice = None
            _clarify_q = None
            if _pure_food:
                # Mode-gradient clarify-on-swing runs CONCURRENTLY with the voice
                # read (both are quick reads over the committed log), so asking
                # about a real swing ("how much butter on the toast?") costs ~no
                # extra wall-clock. It NEVER withholds a log — every item is already
                # on the board; the question only sharpens it next turn. Code layer,
                # not the frozen prompt (feedback_arnie_food_prompt_frozen).
                import asyncio as _aio
                from core.clarify import clarify_swings, clarify_swings_enabled
                # Log-first clarify is OFF by default now (ask-first replaces it);
                # gate the call so we don't run it — or append its question — when
                # CLARIFY_SWINGS is off. clarify_swings no longer self-gates.
                _run_clarify = clarify_swings_enabled()
                # D — marker-gated fast-path: manifest present + a real log tool fired
                # = the write is confirmed, so ship the deterministic confirmation and
                # SKIP the voice_log model pass (latency). Falls through to voice_log if
                # the model forgot the marker, so it never fails a confirmation.
                _fastpath = (
                    _log_fastpath_enabled()
                    and any(tc.get("name") in _LOGGING_TOOLS for tc in tool_calls)
                    and (_parse_did(response_text or "") or _LOG_MARKER in (response_text or "")))
                if _fastpath:
                    _fast_voice = deterministic_confirmation(
                        tool_calls, today_log, user.preferences, tool_results)
                    if _run_clarify:
                        _clarify_q = await clarify_swings(tool_calls, tool_results, user)
                elif fast_log_voice_enabled():
                    if _run_clarify:
                        _fast_voice, _clarify_q = await _aio.gather(
                            voice_log(tool_calls, tool_results, today_log, user),
                            clarify_swings(tool_calls, tool_results, user))
                    else:
                        _fast_voice = await voice_log(
                            tool_calls, tool_results, today_log, user)
                elif _run_clarify:
                    _clarify_q = await clarify_swings(tool_calls, tool_results, user)
            if _pure_food:
                response_text = _fast_voice or deterministic_confirmation(
                    tool_calls, today_log, user.preferences, tool_results)
                if _clarify_q:
                    response_text = (
                        (response_text.rstrip() + "|||" + _clarify_q)
                        if (response_text or "").strip() else _clarify_q)
                    # Record the open question so next turn [PENDING CLARIFICATION]
                    # surfaces it and the user's answer UPDATES the entries
                    # (auto-resolves on update_food_entry). Best-effort — a failed
                    # record never breaks the reply.
                    try:
                        from db.queries import record_pending_question
                        _pq = await record_pending_question(
                            db, user.id, kind="food_clarification",
                            question=_clarify_q, tier="casual",
                            hook_style="question")
                        _pq.item_referenced = next(
                            ((tc.get("input") or {}).get("food_name")
                             for tc in tool_calls if tc.get("name") == "log_food"),
                            "meal")
                        _pq.tier = "food_clarification"
                        await db.commit()
                    except Exception as _e:
                        logger.warning(f"clarify pending-record failed: {_e}")
                _response_streamed = False
            else:
                # Non-pure logging turn (water / weight, or a co-asked question)
                # keeps the voiced follow-up path for now.
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
                    # Same trailing-send suppression as the generic fallback
                    # site below: when the follow-up already STREAMED the
                    # reply and only its RETURN came back empty, the user has
                    # their answer — the canned text persists for the record
                    # but must never send after it (the banana-turn triple,
                    # 2026-07-19 23:15Z, was THIS site: food logs take the
                    # has_logging branch, which the first fix didn't cover).
                    if _streamer is not None and _streamer.flushed_count > 0:
                        _suppress_trailing = True
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
            # A follow-up that STREAMED its reply but returned empty/raised on
            # the way out (e.g. finalize hiccup) lands here with the user
            # already holding a complete answer. Persist the fallback, but
            # NEVER send it after the real reply.
            # EXCEPT when the only thing that streamed was a slow-tool HEADS-UP
            # ("lemme look that up 🔎" for web_search): that is NOT the answer, so
            # the fallback MUST still reach the user — otherwise a Tavily/re-voice
            # failure strands them on the heads-up forever (the "Check online" bug).
            _has_headsup_tool = any(
                tc.get("name") in NEEDS_HEADS_UP_TOOLS for tc in (tool_calls or []))
            if (_streamer is not None and _streamer.flushed_count > 0
                    and not _has_headsup_tool):
                _suppress_trailing = True

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
    # ── LEAKED TOOL-CALL XML RECOVERY (Denys #7129) ─────────────────────
    # An older model under a heavy prompt sometimes writes its function-call
    # SYNTAX as text ("<invoke name=log_food>…") instead of executing it. The
    # bubble sanitizer strips it so it never SHIPS; here we RECOVER the intended
    # log from the markup and force a clean reply. Fully wrapped.
    try:
        from core.turn_health import has_leaked_tool_xml, extract_leaked_tool_calls
        if has_leaked_tool_xml(response_text):
            logger.warning(f"event=leaked_tool_xml user={getattr(user,'id',None)} — recovering")
            _leaked = [tc for tc in extract_leaked_tool_calls(response_text)
                       if tc.get("name") in _LOGGING_TOOLS | {"log_water", "log_body_weight"}]
            if _leaked:
                if today_log is None:
                    from db.queries import get_or_create_today_log
                    today_log = await get_or_create_today_log(
                        db, user.id, user.timezone or "UTC")
                _lr = await execute_tool_calls(
                    _leaked, user, today_log, db, _source, user_message=_gate_user_message)
                for _tc in _leaked:
                    tool_calls.append(_tc)
                    tool_results[_tc["name"]] = _lr.get(_tc["name"], "")
            # Strip the markup from the reply; if nothing usable remains, the
            # phantom rescue below regenerates a proper confirmation.
            from core.platform import _strip_tool_xml
            response_text = _strip_tool_xml(response_text).strip()
    except Exception:
        logger.warning("leaked-xml recovery failed", exc_info=True)

    # Uses the GATE-EFFECTIVE message (prior + clarify-answer combined) so a
    # phantom claim on an answer turn ("regular size minimal oil" → "wrap
    # logged", no tool) is caught — the food name lives in the prior message.
    _phantom = _phantom_rescue_enabled() and (not tool_calls) and _looks_like_phantom_log_claim(
        _gate_user_message, response_text, bool(tool_calls)
    )
    # TOTAL-CLAIM PHANTOM (the medjool-dates incident, 2026-07-20 03:29Z, on
    # Opus): no claim-word, no tool — the reply simply STATED macros and a
    # recomputed running total ("puts you at 2,219 / 2,165") over a row that
    # was never written. On a no-write food-report turn, a stated total that
    # exceeds the DB total beyond tolerance is fabricated arithmetic → same
    # blocking rescue as a worded claim.
    if not _phantom and not tool_calls:
        try:
            from core.turn_health import (
                claimed_day_total as _claimed_total,
                _FOOD_REPORT_RE as _food_report_re,
                DAY_TOTAL_TOLERANCE as _day_tol,
            )
            _claim = _claimed_total(response_text)
            _db_total = round(getattr(today_log, "total_calories", 0) or 0)
            if (_claim is not None
                    and _food_report_re.search(_gate_user_message or "")
                    and _claim > _db_total + _day_tol):
                logger.warning(
                    f"event=total_claim_phantom user={getattr(user, 'id', None)} "
                    f"claimed={_claim} db={_db_total}")
                _phantom = True
        except Exception:
            pass

    # OMISSION rescue: the user reported eating a specific food and the reply even
    # STATED its calories, but fired NO log tool and asked NO question — it
    # commented instead of logging (the "2 Starburst, 40 cal, tiny hit that
    # doesn't change anything" miss, 2026-07-21; the model logs it ~4/5 turns and
    # editorializes the 5th). No false "logged" claim, so the phantom paths above
    # miss it. High-precision: plans, questions, and non-food "had a rough day"
    # (no macros stated) are all excluded (see looks_like_unlogged_food_report).
    _omission = False
    if not tool_calls and not _phantom:
        try:
            from core.turn_health import looks_like_unlogged_food_report
            if _omission_rescue_enabled() and looks_like_unlogged_food_report(_gate_user_message, response_text):
                # The cheap filter passed (reply quantified a food, not a
                # question/plan/ack). CONFIRM with the scribe that the message
                # actually NAMES a food — this separates "Barebells caramel cashew"
                # (a real bare-name log) from "log my whole day" or an ack→recap
                # (no specific food → the reply's number is a day total, not a
                # missed item). Reuse the pre-launched scribe if it ran (multi-item
                # turn), else extract on demand here.
                from core.scribe import scribe_enabled, extract_food_items
                if scribe_enabled():
                    _ex = (await _scribe_task) if _scribe_task is not None \
                        else (await extract_food_items(_gate_user_message))
                    _scribe_task = None  # consumed
                    _omission = any((it.get("name") or "").strip() for it in (_ex or []))
                    if _omission:
                        logger.warning(
                            f"event=unlogged_food_report {_tag} "
                            f"items={[it.get('name') for it in _ex]}")
        except Exception:
            _omission = False
    # Lifecycle: cancel a still-pending scribe on a no-tool turn that didn't use it.
    if not tool_calls and _scribe_task is not None:
        try:
            _scribe_task.cancel()
        except Exception:
            pass
        _scribe_task = None

    # Sign-off: a clear goodnight/closing → 'Sleep well 🌙' is correct. Repair
    # is disabled in this case so we don't generate a full coaching reply after
    # a goodnight (the "Logged: Ground turkey" after-goodnight regression).
    _signing_off = _user_is_signing_off(_user_text if isinstance(_user_text, str) else "")

    async def _announce_work(intent_line: str, tool_names: list):
        """UNIVERSAL: before ANY operation that adds a round-trip and makes the user
        wait — a slow tool, or a rescue that re-runs the model to get the best/most
        accurate info — give immediate feedback: one short in-voice line conveying
        WHAT Arnie is doing and WHY, plus morph the live thinking indicator to those
        tools. Not tied to any single tool or rescue (Danny 2026-07-23). Best-effort;
        never blocks the work it precedes."""
        try:
            if intent_line:
                if _streamer and on_text_bubble:
                    await on_text_bubble(intent_line)
                    _streamer.flushed_count += 1
                elif on_interim:
                    await on_interim(intent_line)
            if on_tool_start and tool_names:
                await on_tool_start(tool_names)
        except Exception as _e:
            logger.warning(f"announce_work failed for {_tag}: {_e}")

    # ── Phantom-claim RESCUE: execute the log, don't apologize ──────────────
    # The old text-only repair could at best own the miss and ask the user to
    # re-send — and when it produced nothing, the false "logged" claim SHIPPED
    # (Danny, 2026-07-18 01:30 UTC: "another 150g of turkey and 100g rice" →
    # "Second round of turkey and rice logged" with zero food_entries written;
    # he had to catch it himself 18 minutes later). Logging is the number-one
    # thing that must work, so a phantom claim now triggers a REAL recovery:
    # one tools=True pass whose tool calls are EXECUTED through the same
    # executor as the main turn (add-intent gate included via user_message).
    # Only if that still writes nothing do we fall back to owning the miss.
    # PARTIAL-DROP: a distinct dish the user named never logged (turkey logged,
    # rice dropped). tool_calls IS present, so this fires ALONGSIDE the no-tool
    # phantom/omission triggers.
    _partial_drop = bool(_missing_from_scribe)
    # EXERCISE phantom: a set/movement claimed ("🏋️ … logged") but no log_exercise
    # fired — the drops Danny hit 2026-07-23. Reuses the same rescue below (its
    # nudge already handles log_exercise); the executor dedup stops a real dup.
    _ex_phantom = False
    if _exercise_phantom_enabled() and not _signing_off:
        try:
            from core.turn_health import looks_like_unlogged_exercise
            _ex_fired = any(tc.get("name") == "log_exercise" for tc in tool_calls)
            _ex_phantom = looks_like_unlogged_exercise(
                _gate_user_message, response_text, _ex_fired)
        except Exception:
            _ex_phantom = False
    # DETERMINISTIC action-manifest phantom: the model named a write tool in
    # [[DID: log_food, ...]] (or the legacy [[LOGGED]] token) — it thinks it wrote
    # something — but NO logging tool fired this turn → the write didn't happen.
    # The reliable, tool-agnostic signal; the "🏋️"/worded heuristics stay as backup.
    _marker_phantom = False
    _did_tools = _parse_did(response_text or "") if _log_marker_enabled() else set()
    if _log_marker_enabled() and not _signing_off:
        _write_claimed = bool(_did_tools & _LOGGING_TOOLS) or (_LOG_MARKER in (response_text or ""))
        if _write_claimed:
            _marker_phantom = not any(tc.get("name") in _LOGGING_TOOLS for tc in tool_calls)
            if _marker_phantom:
                logger.warning(f"event=marker_phantom {_tag} — write claimed ([[DID]]/[[LOGGED]]), no log tool fired")
    if (_phantom or _omission or _partial_drop or _ex_phantom or _marker_phantom) \
            and not _signing_off:
        try:
            if _partial_drop and not (_phantom or _omission):
                # Add ONLY the missing item(s); everything already on the board —
                # and any composite correctly logged as one — stays untouched.
                _rescue_nudge = (
                    "[SYSTEM HEALTH CHECK — not the user] You logged part of what "
                    "the user reported but MISSED these item(s): "
                    f"{', '.join(_missing_from_scribe)}. Call log_food NOW for ONLY "
                    "those missing item(s), using the exact quantities from the "
                    "user's message. Do NOT re-log, delete, or modify anything "
                    "already on the board — only ADD the missing item(s). If an "
                    "item is really part of a dish you already logged as ONE (a "
                    "filling inside a bowl/wrap/burrito), call NO tool for it. Then "
                    "confirm just the added item in one short line with real numbers."
                )
            else:
                _rescue_nudge = (
                    "[SYSTEM HEALTH CHECK — not the user] The user reported "
                    "eating or doing something (past/present tense) and your "
                    "reply discussed it — even stated its calories — but NO "
                    "logging tool was called, so NOTHING was saved. Call the "
                    "right log tool NOW for exactly what they reported — food "
                    "(log_food), exercise (log_exercise), BODY WEIGHT "
                    "(log_body_weight, e.g. 'weight looks like 194.2' → log "
                    "194.2), or water (log_water) — INCLUDING the item the user "
                    "named just before answering your clarifying question (e.g. "
                    "they said 'chicken wrap', you asked size, they said "
                    "'regular' → log the wrap). Log EVERY item they reported "
                    "this turn, even a tiny one (2 starburst, a mint, a bite) — "
                    "a small item is still logged, never just commented on. "
                    "Exact quantities. Then confirm in one short message with "
                    "the real numbers. Do NOT reply without the tool call. "
                    "BUT if the user did NOT actually report consuming/doing a "
                    "specific thing (just chit-chat, a plan they haven't done, "
                    "or a question), call NO tool. Do NOT re-log items already "
                    "on today's board from a SEPARATE earlier meal."
                )
            # Announce the round-trip so the re-run isn't dead air (universal).
            await _announce_work(
                "Let me make sure that's logged.",
                list(_did_tools & _LOGGING_TOOLS)
                or (["log_exercise"] if _ex_phantom else ["log_food"]))
            _ALLOWED_RESCUE = ("log_food", "log_exercise", "log_body_weight",
                               "log_water",
                               # A CORRECTION phantom ("Royo bagels are 80 cal",
                               # "fixing it now") rescues into an UPDATE, not a new
                               # log — include it so the edit actually writes.
                               "update_food_entry")
            _rescue = {}
            _rescue_calls = []
            # PROACTIVE path (I — ORCHESTRATOR, default off): a small/fast tool-only
            # caller re-derives the dropped call(s) from the user's message — cheaper
            # and more reliable than re-prompting the 46k-token coach. Full phantoms
            # only (a partial drop needs the "log ONLY the missing item" nudge, which
            # the orchestrator can't know). Falls back to the re-prompt when off or empty.
            from core.orchestrator import orchestrator_enabled as _orch_on
            if _orch_on() and not _partial_drop:
                try:
                    from core.orchestrator import call_tools as _orch_call
                    _rescue_calls = [tc for tc in (await _orch_call(_gate_user_message))
                                     if tc.get("name") in _ALLOWED_RESCUE]
                    if _rescue_calls:
                        logger.warning(f"event=orchestrator_rescue {_tag} "
                                       f"tools={[tc.get('name') for tc in _rescue_calls]}")
                except Exception as _oe:
                    logger.warning(f"orchestrator rescue failed for {_tag}: {_oe}")
            if not _rescue_calls:
                _rescue = await chat(
                    messages + [
                        {"role": "assistant", "content": response_text},
                        {"role": "user", "content": _rescue_nudge},
                    ],
                    system, tools=True, max_tokens=700,
                )
                _rescue_calls = [
                    tc for tc in (_rescue.get("tool_calls") or [])
                    if tc.get("name") in _ALLOWED_RESCUE
                ]
            if _rescue_calls:
                # First pass fired no tools, so the executor's log was never
                # prepared — create today's log here exactly like the main path.
                if today_log is None:
                    from db.queries import get_or_create_today_log
                    today_log = await get_or_create_today_log(
                        db, user.id, user.timezone or "UTC")
                _rescue_results = await execute_tool_calls(
                    _rescue_calls, user, today_log, db, _source,
                    # Combined prior+answer message so the rescue's dedup gate
                    # doesn't block the clarify-answer item it's re-logging.
                    user_message=_gate_user_message,
                )
                _wrote = any(
                    isinstance(v, str)
                    and v.lstrip().startswith(("Logged", "Updated", "Adjusted"))
                    for v in _rescue_results.values()
                )
                if _wrote:
                    if today_log is not None:
                        try:
                            await db.refresh(today_log)
                        except Exception:
                            pass
                    _rescue_text = (_rescue.get("text") or "").strip()
                    if not _rescue_text:
                        _rescue_text = deterministic_confirmation(
                            _rescue_calls, today_log, user.preferences, _rescue_results)
                    if _rescue_text:
                        if _partial_drop and not (_phantom or _omission):
                            # KEEP the valid original confirmation (the items that
                            # DID log) and APPEND the recovered missing item — never
                            # overwrite a correct reply with just the add.
                            _trigger = "partial_drop"
                            response_text = (
                                (response_text.rstrip() + "|||" + _rescue_text)
                                if (response_text or "").strip() else _rescue_text)
                            if on_text_bubble and not _hold_voicing:
                                for _b in Response.from_text(_rescue_text).bubbles:
                                    await on_text_bubble(_b)
                        else:
                            # phantom/omission: the original reply was wrong (false
                            # claim / commented-not-logged) → REPLACE it.
                            _trigger = ("phantom" if _phantom else
                                        "omission" if _omission else
                                        "exercise_phantom" if _ex_phantom else
                                        "marker_phantom")
                            if on_text_bubble and not _hold_voicing:
                                for _b in Response.from_text(_rescue_text).bubbles:
                                    await on_text_bubble(_b)
                            response_text = _rescue_text
                        tool_calls = list(tool_calls or []) + _rescue_calls
                        _phantom = _omission = _partial_drop = _ex_phantom = _marker_phantom = False  # rescued
                        logger.warning(
                            f"event=log_rescue outcome=logged trigger={_trigger} {_tag} "
                            f"tools={[tc.get('name') for tc in _rescue_calls]}")
            if _phantom or _omission or _partial_drop or _ex_phantom or _marker_phantom:
                logger.warning(f"event=log_rescue outcome=unrescued {_tag} — "
                               f"model fired no tool")
        except Exception as e:
            logger.error(f"Phantom rescue failed for {_tag}: {e}")

    # ── LOOKUP RESCUE (B): estimated a specific product instead of looking it up ──
    # The user asked about a SPECIFIC product's nutrition and the model answered with
    # its OWN estimate — it named a lookup tool in the manifest but never called it,
    # or hedged an estimate with no lookup at all (Bonilla de la Vista, IMG_8582).
    # Force the lookup and re-answer with the real numbers. Switch: LOOKUP_RESCUE.
    _lookup_fired = any(tc.get("name") in _LOOKUP_TOOLS for tc in tool_calls)
    _lookup_gap = False
    if _lookup_rescue_enabled() and not _signing_off and not _lookup_fired and response_text:
        if _did_tools & _LOOKUP_TOOLS:
            _lookup_gap = True   # claimed a lookup tool in the manifest, never fired it
        else:
            try:
                from core.turn_health import looks_like_estimated_product_query
                _lookup_gap = looks_like_estimated_product_query(
                    _user_text if isinstance(_user_text, str) else "", response_text)
            except Exception:
                _lookup_gap = False
    if _lookup_gap:
        try:
            # Announce the search + re-voice round-trip (universal helper) —
            # intention: getting the accurate numbers instead of an estimate.
            await _announce_work(
                "Let me pull the exact numbers so this is accurate.",
                ["search_food_database"])
            _lu_nudge = (
                "[SYSTEM HEALTH CHECK — not the user] The user asked about a SPECIFIC "
                "product's nutrition and you gave your OWN estimate without looking it "
                "up. Call search_food_database NOW for exactly that product — or "
                "web_search for a brand/restaurant item USDA won't have — then give the "
                "real numbers in your voice, one tight read. If it is a generic staple "
                "you truly know cold (plain rice, an egg), call no tool and keep your "
                "answer.")
            _lu = await chat(
                messages + [
                    {"role": "assistant", "content": response_text},
                    {"role": "user", "content": _lu_nudge},
                ],
                system, tools=True, max_tokens=500,
            )
            _lu_calls = [tc for tc in (_lu.get("tool_calls") or [])
                         if tc.get("name") in _LOOKUP_TOOLS]
            if _lu_calls:
                if today_log is None:
                    from db.queries import get_or_create_today_log
                    today_log = await get_or_create_today_log(
                        db, user.id, user.timezone or "UTC")
                _lu_results = await execute_tool_calls(
                    _lu_calls, user, today_log, db, _source,
                    user_message=_gate_user_message)
                _voiced = (await chat_follow_up(
                    messages, _lu.get("raw_content"), _lu_calls, _lu_results,
                    system, max_tokens=300) or "").strip()
                if _voiced:
                    if on_text_bubble and not _hold_voicing:
                        for _b in Response.from_text(_voiced).bubbles:
                            await on_text_bubble(_b)
                    response_text = _voiced
                    tool_calls = list(tool_calls or []) + _lu_calls
                    logger.warning(
                        f"event=lookup_rescue outcome=looked_up {_tag} "
                        f"tools={[tc.get('name') for tc in _lu_calls]}")
        except Exception as e:
            logger.error(f"Lookup rescue failed for {_tag}: {e}")

    # ── ASK-FIRST ANSWER: force the held log on the answer turn ──────────────────
    # The ask-first HOLD asked before logging and wrote nothing (pending
    # kind=food_ask_first). opus then clarify-LOOPS on the answer instead of
    # committing (verified 2026-07-22), so force it: if that pending is open and
    # this turn logged no food, run ONE forcing pass that logs every item from the
    # exchange with the user's answer applied, then resolve the pending. Dormant
    # unless ASK_FIRST_HOLD created the pending — never fires with the hold off.
    from core.clarify import ask_first_hold_enabled as _afh_enabled
    if _afh_enabled() and not _signing_off and not _ask_first_q:
        _held_pq = None
        try:
            from db.queries import get_open_pending_question
            _held_pq = await get_open_pending_question(db, user.id, "food_ask_first")
        except Exception:
            _held_pq = None
        if _held_pq is not None:
            import re as _re_af
            _cancel = bool(_re_af.search(
                r"\b(never\s*mind|don'?t\s+log|do\s+not\s+log|cancel|skip\s+it|"
                r"forget\s+it|scratch\s+that)\b", _user_text or "", _re_af.I))
            _fired_food = any(tc.get("name") == "log_food" for tc in tool_calls)
            try:
                if not _cancel and not _fired_food:
                    _af_nudge = (
                        "[SYSTEM HEALTH CHECK — not the user] Earlier you asked the "
                        "user to clarify a food BEFORE logging it, and you logged "
                        f"NOTHING. They have now answered: \"{_user_text}\". Log EVERY "
                        "food item from that exchange NOW with log_food, applying "
                        "their answer to the ambiguous detail (cooking fat, sauce, "
                        "portion). Exact quantities. Do NOT ask another question. Then "
                        "confirm in one short line with the real numbers.")
                    _af = await chat(
                        messages + [{"role": "assistant", "content": response_text or ""},
                                    {"role": "user", "content": _af_nudge}],
                        system, tools=True, max_tokens=700)
                    _af_calls = [tc for tc in (_af.get("tool_calls") or [])
                                 if tc.get("name") == "log_food"]
                    _used_stash = False
                    if not _af_calls:
                        # The model LOOPED (asked again / fired no tool). Replay the
                        # EXACT held items from the turn-1 stash so the meal is NEVER
                        # lost — unrefined by the answer, but captured. This is the
                        # bulletproof half (option A): model-refined when it
                        # cooperates, deterministic stash when it doesn't.
                        try:
                            _stashed = json.loads(_held_pq.payload_json or "[]")
                        except Exception:
                            _stashed = []
                        _af_calls = [{"name": "log_food", "input": _i}
                                     for _i in _stashed
                                     if isinstance(_i, dict) and _i.get("food_name")]
                        _used_stash = bool(_af_calls)
                    if _af_calls:
                        if today_log is None:
                            from db.queries import get_or_create_today_log
                            today_log = await get_or_create_today_log(
                                db, user.id, user.timezone or "UTC")
                        _af_results = await execute_tool_calls(
                            _af_calls, user, today_log, db, _source,
                            user_message=_gate_user_message)
                        try:
                            await db.refresh(today_log)
                        except Exception:
                            pass
                        # On a stash replay the model's text is the loop question —
                        # discard it and voice the deterministic confirmation.
                        _af_text = deterministic_confirmation(
                            _af_calls, today_log, user.preferences, _af_results) \
                            if _used_stash else (
                                (_af.get("text") or "").strip()
                                or deterministic_confirmation(
                                    _af_calls, today_log, user.preferences, _af_results))
                        if _af_text:
                            if on_text_bubble and not _hold_voicing:
                                for _b in Response.from_text(_af_text).bubbles:
                                    await on_text_bubble(_b)
                            response_text = _af_text
                        tool_calls = list(tool_calls or []) + _af_calls
                        logger.warning(
                            f"event=ask_first_answer_logged {_tag} "
                            f"via={'stash' if _used_stash else 'model'} "
                            f"tools={[tc.get('name') for tc in _af_calls]}")
                # Resolve either way — the user engaged; never re-ask this loop.
                from datetime import datetime as _dt_af
                _held_pq.answered_at = _dt_af.utcnow()
                await db.commit()
            except Exception as e:
                logger.error(f"ask-first answer force-log failed for {_tag}: {e}")

    # ── ACTIVITY completeness: a co-mentioned workout the model ignored ─────────
    # The user reported a food AND a workout/sport ("chicken plate… and also played
    # racquetball", Justin 2026-07-21) but the model logged the food and silently
    # DROPPED the activity — no log_exercise, not even a question. Address it: log
    # it if there's enough (activity + duration), else ask ONE quick question. The
    # food reply is VALID, so APPEND the activity line; never overwrite it.
    _fired_exercise = any(tc.get("name") == "log_exercise" for tc in tool_calls)
    _activity_omission = False
    if _activity_rescue_enabled() and not _fired_exercise and not _signing_off:
        try:
            from core.turn_health import looks_like_unaddressed_activity
            _activity_omission = looks_like_unaddressed_activity(
                _gate_user_message, response_text)
        except Exception:
            _activity_omission = False
    if _activity_omission:
        try:
            _act_results: dict = {}
            _act = await chat(
                messages + [
                    {"role": "assistant", "content": response_text},
                    {"role": "user", "content":
                        "[SYSTEM HEALTH CHECK — not the user] The user mentioned "
                        "doing a WORKOUT or SPORT this turn (e.g. 'played "
                        "racquetball', 'went for a run') and you did NOT address it "
                        "at all. If they gave enough to log it (the activity + a "
                        "duration or distance), call log_exercise NOW. If not, add "
                        "ONE short friendly line asking only what you need to log it "
                        "('nice — how long did you play racquetball?'). Do NOT re-log "
                        "or touch any FOOD. Reply with ONLY that one activity line."},
                ],
                system, tools=True, max_tokens=300,
            )
            _act_calls = [tc for tc in (_act.get("tool_calls") or [])
                          if tc.get("name") == "log_exercise"]
            if _act_calls:
                if today_log is None:
                    from db.queries import get_or_create_today_log
                    today_log = await get_or_create_today_log(
                        db, user.id, user.timezone or "UTC")
                _act_results = await execute_tool_calls(
                    _act_calls, user, today_log, db, _source,
                    user_message=_gate_user_message)
                try:
                    await db.refresh(today_log)
                except Exception:
                    pass
                tool_calls = list(tool_calls or []) + _act_calls
            _act_text = (_act.get("text") or "").strip()
            if not _act_text and _act_calls:
                _act_text = deterministic_confirmation(
                    _act_calls, today_log, user.preferences, _act_results)
            if _act_text:
                response_text = (
                    (response_text.rstrip() + "|||" + _act_text)
                    if (response_text or "").strip() else _act_text)
                if on_text_bubble and not _hold_voicing:
                    for _b in Response.from_text(_act_text).bubbles:
                        await on_text_bubble(_b)
            logger.warning(f"event=activity_rescue {_tag} logged={bool(_act_calls)}")
        except Exception as e:
            logger.error(f"Activity rescue failed for {_tag}: {e}")

    # STRIP (2026-07-21): the quality-repair pass NEVER runs on a logging turn.
    # It was an added recheck that spent an extra Opus round-trip AND emitted a
    # second text source on top of the log voice — a latency tax and a double
    # risk on the exact path that must stay clean. The log voice (voice_log →
    # deterministic_confirmation fallback) is already number-accurate and
    # em-dash/tilde-sanitized, so a logging turn needs no rewrite. Non-logging
    # coaching turns keep the repair (that path is "spot on" per Danny and is
    # untouched). Phantom claims are handled ABOVE by the rescue, which only
    # fires on no-tool turns, so gating here can't suppress a real phantom.
    if (_streaming_dead_end or _logging_dead_end or _mechanics
            or _empty_praise or _stall or _phantom) and not _signing_off \
            and not _logging_turn:
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
            # END ON A USER MESSAGE, never an assistant prefill. The current
            # Anthropic model rejects a trailing-assistant message with a 400
            # ("This model does not support assistant message prefill. The
            # conversation must end with a user message."), which then fell
            # through to the OpenAI fallback and a 429 (request too large) —
            # exactly why the turkey+rice rescue never landed (2026-07-21 logs:
            # phantom_rescue unrescued → 400 prefill → OpenAI 429). Fold the
            # prior reply into the user turn instead.
            _repair = await chat(
                messages + [{"role": "user", "content": (
                    "[SYSTEM QUALITY CHECK — not the user] Your last reply was:\n"
                    f"\"\"\"{response_text}\"\"\"\n\n"
                    "Rewrite it now, following the QUALITY REPAIR instructions "
                    "in the system prompt."
                )}],
                system + f"\n\nQUALITY REPAIR: {_REPAIR_PROMPT}{_repair_extra}",
                tools=_repair_tools, max_tokens=600 if _repair_tools else 400,
            )
            _repair_text = (_repair.get("text") or "").strip()
            if _repair_text:
                if on_text_bubble and not _hold_voicing:
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
            # DAY-BOUNDARY SAFETY (the 12:15am pops-cereal "0/2165 after a full day"):
            # at the pre-dawn rollover a log lands on YESTERDAY's log (user-tz grace)
            # while a UTC-resolved path may hand this turn a fresh EMPTY new-day log.
            # If a logging tool FIRED this turn but `today_log` is empty, the write went
            # to another day — NEVER clobber the reply's real total down to that empty
            # day's 0. (A genuine phantom on an empty day fires NO tool, so it's still
            # caught.)
            _fired_log = any(tc["name"] in _LOGGING_TOOLS for tc in tool_calls)
            _boundary_empty = (_db_cal <= 0
                               and not (getattr(today_log, "food_entries", None) or []))
            if _fired_log and _boundary_empty and _stated and _stated > _DAY_TOTAL_TOLERANCE:
                logger.warning(
                    f"day-total guard SKIP {_tag}: log fired but today_log empty "
                    f"(stated={_stated}) — pre-dawn/UTC day-boundary, not a phantom")
            elif _stated is not None and abs(_stated - _db_cal) > _DAY_TOTAL_TOLERANCE:
                _total_mismatch = True
                logger.warning(f"TOTAL_MISMATCH {_tag}: stated={_stated} db={_db_cal}")
                # PASSIVE (strip step 7): no corrective model pass, no re-emitted bubble.
                # voice_log is handed the DB total so a clean log can't mismatch — the old
                # corrective chat() was dead weight on that path AND a real footgun (it
                # zeroed a full day at the tz boundary, and its re-emit was a second text
                # source = a double). The mismatch stays a health_flag metric. When the
                # reply hasn't shipped yet (it lands via the catch-up) and a log fired,
                # fall to the deterministic confirmation's real DB numbers — never a
                # second model call that can itself hallucinate.
                if _fired_log and not _response_streamed:
                    response_text = deterministic_confirmation(
                        tool_calls, today_log, user.preferences, tool_results)
    except Exception as e:
        logger.debug(f"day-total guard failed for {_tag}: {e}")

    # ── Build the platform-agnostic Response ──────────────────────────────────
    # CONTRACT: response_text is FROZEN after this line. All further mutations
    # (bubble injection, dashboard URL, intro prepend) happen on resp.bubbles.
    # The only legitimate post-split read of response_text is sync_pending_questions,
    # which needs the raw LLM string for hook detection. If you ever join resp.bubbles
    # back into a string, derive it from the pre-dashboard slice, not after URL append.
    # STREAMED REPLY IS AUTHORITATIVE. If the model's reply already reached the
    # user live (the streamer flushed real bubbles) but response_text was then
    # overwritten by a non-streamed fallback (empty follow-up return → canned
    # deterministic_confirmation), the RETURNED reply must be what STREAMED —
    # otherwise the WebSocket done-frame ships the canned bubbles and the client
    # appends them (the triple-confirmation bug: suppression guarded the re-send
    # loop but not the returned resp.bubbles the done-frame carries).
    if (_streamer is not None and _suppress_trailing
            and getattr(_streamer, "flushed_bubbles", None)):
        response_text = "|||".join(_streamer.flushed_bubbles)
        _response_streamed = True   # it IS what streamed — no catch-up needed

    # VERIFY-BEFORE-STREAM finalize: on a held logging turn the follow-up voicing was
    # buffered, never shown, and its total was verified/corrected above. Drop the
    # unverified buffer and mark the reply un-streamed so the catch-up below ships the
    # final response_text exactly once — one verified reply, never a phantom + a fix.
    if _hold_voicing and _streamer is not None:
        _streamer.discard_held()
        _response_streamed = False

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
        if not _response_streamed and not _suppress_trailing:
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
        # Require an ACTUAL write this turn ("Logged …" result), not just a
        # log_food call — a deduped re-log of entry #1 must not re-celebrate.
        _food_wrote = any(
            (tc.get("name") == "log_food") for tc in (tool_calls or [])
        ) and any(
            isinstance(v, str) and v.lstrip().startswith("Logged")
            for v in (tool_results or {}).values()
        )
        if _food_wrote and getattr(user, "log_unlocked_at", None) is None:
            try:
                from core.activation import _food_entry_count
                _first_food = (await _food_entry_count(db, user.id)) == 1
            except Exception:
                _first_food = False
        # ── Reasoning receipt: the turn's REAL artifacts, humanized ──────
        try:
            from core.reasoning import build_reasoning
            resp.reasoning = build_reasoning(
                tool_calls, tool_results, None,
                int((_time_mod.monotonic() - _turn_t0) * 1000))
        except Exception:
            resp.reasoning = None   # a broken receipt never breaks a turn

        # Effects need a REAL event behind them: a log tool that actually
        # wrote this turn. Goal/streak language merely restated (a recheck,
        # a summary) downgrades to the reaction alone inside detect_moment.
        _any_log_wrote = any(
            (tc.get("name") in ("log_food", "log_exercise",
                                "log_body_weight", "log_water"))
            for tc in (tool_calls or [])
        ) and any(
            isinstance(v, str) and v.lstrip().startswith("Logged")
            for v in (tool_results or {}).values()
        )
        _ut = _user_text if isinstance(_user_text, str) else ""
        import re as _re_moment
        if _re_moment.match(r"^\[REGENERATE(:\d+)?\]$", _ut.strip()):
            # A regenerate is a dissatisfaction signal — never tapback or
            # celebrate it (the balloons-on-recheck report, 07-19).
            pass
        else:
            moment         = detect_moment(response_text, tool_calls,
                                           first_food=_first_food,
                                           user_text=_ut, wrote=_any_log_wrote)
            resp.reaction  = moment.reaction
            resp.effect    = moment.effect
            resp.effect_idx = moment.effect_idx

        # ── Achievements: quiet trophies, loud moments ────────────────────
        # Only turns that actually WROTE a log can mint a badge (a chat-only
        # turn can't change any count), so established users pay nothing on
        # ordinary turns. `effect_taken` keeps one celebration per turn — a
        # first-food moment or goal FX already celebrating mutes the badge's
        # own celebration (it still lands in the trophy sheet). Fail-open:
        # a broken badge check must never break a coaching turn.
        _prog_tools = {"set_program_day", "set_program_target",
                       "add_program_exercise", "remove_program_exercise"}
        if any((tc.get("name") in _prog_tools) for tc in (tool_calls or [])):
            resp.program_updated = True
        _log_wrote = any(
            (tc.get("name") in ("log_food", "log_exercise")) for tc in (tool_calls or [])
        ) and any(
            isinstance(v, str) and v.lstrip().startswith("Logged")
            for v in (tool_results or {}).values()
        )
        if _log_wrote:
            try:
                from core.achievements import check_achievements
                resp.achievement = await check_achievements(
                    db, user, effect_taken=resp.effect is not None)
            except Exception:
                logger.warning("achievement check failed (fail-open)", exc_info=True)

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
            # No-location failure ("PLACES lookup ...") OR a stale-anchor
            # success (the executor's ANCHOR note) — both earn the one-tap
            # share-location button so a fresh pin is a tap, not typing.
            if isinstance(_r, str) and (
                _r.startswith("PLACES lookup") or "\nANCHOR:" in _r
            ):
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
        streamed_card_ids=_early_card_ids,
        needs_location_share=_needs_location_share,
    )
