"""
Shared conversation pipeline — the single orchestration core for all platforms.

Both bot/imessage_handler and bot/telegram_handler delegate to run_turn().
Platform-specific bits (typing indicator, image delivery, adapter.send,
onboarding keyboards, completion text) stay in each handler; this module
owns everything from LLM call through Response assembly.
"""
from __future__ import annotations

import re

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
    tool_heads_up, _heads_up_seed, NEEDS_HEADS_UP_TOOLS,
    FOOD_LOOKUP_HEADS_UP, blocked_log_reply,
    headsup_voice_enabled, sentence_case,
    deep_food_heads_up, late_heads_up_enabled, late_heads_up_delay_s,
)
# Module level rather than per-call: the model calls below consult it, and
# core.deadline imports nothing but the stdlib, so there is no cycle to dodge.
from core import deadline

logger = logging.getLogger(__name__)

_LOGGING_TOOLS = frozenset({
    "log_food", "log_exercise", "update_food_entry",
    "delete_food_entry", "update_exercise_entry",
    "delete_exercise_entry", "delete_water_entry",
    "restore_food_entry", "restore_exercise_entry",
    "log_body_weight", "log_water", "clear_day_log",
})


def _conversational_context(raw):
    """The interpreter's `context` dict as a `ConversationalContext`, or None.

    `core.food_turn` reports it as a plain dict because it sits upstream of the
    response layer and may not import it; this is the one place that turns it
    into the typed obligation the plan carries.

    NO APPROVED WORDING IS SUPPLIED, deliberately. `contextual_preface` is
    therefore silent on the fallback path — and `fallback()` runs only when the
    composer has already failed validation twice, where a deterministic
    renderer improvising a reply to distress is a worse failure than leaving
    that half unanswered. Approved wording belongs to whoever owns the copy,
    not to a builder.
    """
    if not isinstance(raw, dict):
        return None
    try:
        from core.food_response import ConversationalContext
        return ConversationalContext(
            topic=raw.get("topic") or "",
            user_statement=raw.get("said") or "",
            emotional_signal=raw.get("signal") or "",
            response_obligation=raw.get("obligation") or "briefly acknowledge",
            priority=raw.get("priority") or "normal")
    except Exception:
        return None

# (The [[LOGGED]]/[[DID]] manifest, its prompt instructions, and the LOG_FASTPATH
# marker gate were ripped 2026-07-23 — sonnet-5 emitted the manifest 0/4, so it was
# dead weight, and structured food turns (core/food_turn.py) made it unnecessary.
# _sanitize_bubble still strips stray [[...]] tokens echoed from old history.)

# LOOKUP RESCUE: the user asks about a SPECIFIC product and the model answers with
# an ESTIMATE (Bonilla de la Vista, IMG_8582) instead of calling
# search_food_database / web_search → force the lookup, re-voice real numbers.
# Detected by the hedged-estimate heuristic (turn_health). Switch: LOOKUP_RESCUE.
_LOOKUP_TOOLS = frozenset({"search_food_database", "web_search"})


def photo_food_message(user_text: str) -> str | None:
    """Photo turns carry the vision pass's [FOOD_LOG] block inside the user
    text. When its INTENT is log, synthesize the structured logger's message
    from the PACKAGED/ITEM lines so photos ride the SAME single path as text —
    say + write are one artifact, and narration-without-write is structurally
    impossible (prod phantom 2026-07-24 15:51, task #26). Returns None for
    non-photo turns, non-log intents (diary deletes etc.), or empty blocks."""
    if not isinstance(user_text, str) or "[FOOD_LOG]" not in user_text:
        return None
    if not re.search(r"INTENT:\s*log\b", user_text):
        return None
    items = re.findall(r"(?:PACKAGED|ITEM):\s*(.+)", user_text)
    cleaned = []
    for it in items:
        # Drop the unknown-macro tail ("? cal, ?g P, ...") — enrichment owns
        # numbers; the logger needs the name + stated serving only.
        it = re.sub(r",\s*~?\??\s*\d*\s*cal.*$", "", it.strip(), flags=re.I)
        it = it.strip(" ,")
        if it:
            cleaned.append(it)
    if not cleaned:
        return None
    return "I had " + "; ".join(cleaned[:8])


def _lookup_rescue_enabled() -> bool:
    return os.getenv("LOOKUP_RESCUE", "true").lower() in ("true", "1", "yes")

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


def _food_heads_up_subject(tool_calls) -> Optional[str]:
    """The food name to put in a slow-lookup heads-up, or None.

    One logged food -> its name; two -> "a and b"; three or more (or a name that
    would read too long) -> None, so the heads-up falls to the neutral pool
    rather than a clumsy list. The interpreter has already returned by the time
    this is read, so the name is a fact, not a guess.
    """
    names = []
    for tc in (tool_calls or []):
        if tc.get("name") in _FOOD_LOG_TOOLS:
            fn = ((tc.get("input") or {}).get("food_name") or "").strip()
            if fn:
                names.append(fn)
    seen = set()
    uniq = [n for n in names if not (n.lower() in seen or seen.add(n.lower()))]
    if len(uniq) == 1:
        subject = uniq[0]
    elif len(uniq) == 2:
        subject = f"{uniq[0]} and {uniq[1]}"
    else:
        return None
    return subject if 0 < len(subject) <= 40 else None

#: How long a food turn may run before its lookup earns a heads-up bubble.
#: Read where the tools dispatch, so the interpreter pass is already spent and
#: the wait is measured rather than predicted — a turn that arrives faster than
#: this says nothing, which is what separates a heads-up from the pre-action
#: narration removed in `NO TRANSACTION NARRATION`.
_FOOD_HEADS_UP_AFTER_S = 2.5

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


#: Card types that put a NEW card on screen for this turn, and so carry figures
#: the sentence must not recite. `macro_card_patch` is deliberately absent: it
#: revises a card the user is already looking at, so it takes nothing away from
#: what this reply still owes them.
_RENDERS_A_CARD = frozenset({"macro_card", "workout_card"})


def _logged_entry_card(name: str, inp, call=None) -> Optional[dict]:
    """The macro_card / workout_card for a log_food / log_exercise call — but ONLY
    when it actually created or rolled up into a real DB row.

    An `update_food_entry` returns a `macro_card_patch` instead: same payload,
    keyed by `entry_id`, for the client to apply to the card that row is already
    on. See that branch. Everything below is true of both — a patch is gated on
    a real row exactly as a card is.

    The dispatcher stashes that row id on inp["_entry_id"]. A deduped / no-op call
    (the model re-fired something already on the board, e.g. a SPURIOUS log_food on
    a non-food message) never sets it → returns None, so no stale card leaks onto a
    reply that logged nothing (Danny 2026-06-26: "what is 84.9kg in lbs" surfaced
    the earlier coffee's macro_card with entry_id=null). The card must mirror a row
    the user can actually tap/edit. Returns None for any non-logging tool.

    Payload is pulled from the executed call — the committed macros the executor
    synced back, which is what Arnie's reply confirms. `call` is the typed
    CallResult (P0.3b); `inp` remains accepted for the legacy/unit-test path.
    Pure + side-effect free for unit testing."""
    inp = (call.raw_input if call is not None else inp) or {}
    entry_id = (call.entry_id if call is not None and call.entry_id is not None
                else inp.get("_entry_id") or inp.get("entry_id"))
    if not entry_id:
        return None
    # A CORRECTED ROW IS STILL A ROW — BUT IT IS NOT A NEW ONE.
    #
    # Updates emitted no card at all, so after "the bar was cookies and cream"
    # the entire confirmation was whatever sentence the composer wrote —
    # nothing showed the new name or the new numbers, and the correction landed
    # invisibly. So a correction earns a receipt, same payload shape as a log,
    # because it mirrors the same row.
    #
    # It travels as a PATCH, not as a card. Emitted as `macro_card` it joined
    # this turn's `cards` list beside the genuinely new rows, and the client
    # buckets that list by card type — so one turn that corrected the tuna and
    # logged the chips (2026-08-03, le#921 + le#922) grouped both into a single
    # meal card, and the corrected tuna reappeared on the chips' card while
    # still living on its own earlier one. A meal card lists what this turn
    # CREATED; a correction belongs to the card the row is already on, which
    # only `entry_id` can identify.
    #
    # `macro_card_patch` is the same payload under a type that says what to do
    # with it. The entry_id gate above is unchanged and still absolute: a patch
    # exists only where a real row was updated, so the card/row invariant holds
    # on this branch exactly as it does for a log. Clients that predate the type
    # decode it as unknown and ignore it (WireContract's forward-compat case)
    # rather than rendering a second card for a row they already show.
    if name == "update_food_entry":
        _nm = str(inp.get("food_name") or inp.get("food_hint") or "").strip()
        if not _nm:
            # Nothing to show. An amount-only correction on a row we cannot
            # name would render a blank card, which is noise, not a receipt.
            return None
        payload = {
            "name":      _nm,
            "quantity":  inp.get("quantity") or "",
            "source":    "manual",
            "entry_id":  entry_id,
            "corrected": True,
        }
        # ABSENT IS NOT ZERO. A correction to WHAT something was omits the
        # macros on purpose, so the ladder re-resolves them for the new
        # identity — coercing that to 0 renders a card claiming the food has no
        # calories, which is worse than showing no numbers at all. Emit only
        # what we actually have and let the client fill the rest from the row.
        for key, field in (("calories", "calories"), ("protein_g", "protein"),
                           ("carbs_g", "carbs"), ("fats_g", "fats")):
            value = inp.get(field)
            if isinstance(value, (int, float)):
                payload[key] = int(round(value))
        _ev = (call.event_id if call is not None and call.event_id is not None
               else inp.get("_event_id"))
        if _ev is not None:
            payload["event_id"] = _ev
        # Decision-receipt context (day impact + verdict) — same channel as the
        # log_food branch below, see core/receipt.py. `_stash_receipt` has
        # stashed this for corrections since 2a4c839 (updated=True), but this
        # reader never picked it back up, so a correction's card carried a
        # name and macros with no remaining-figures row: the one thing a
        # person looks for after changing a number.
        receipt = (call.receipt if call is not None and call.receipt is not None
                   else inp.get("_receipt"))
        if isinstance(receipt, dict):
            payload.update(receipt)
        return {"type": "macro_card_patch", "payload": payload}
    if name in ("log_food", "restore_food_entry"):
        # A restore is a committed food row like any other — it earns the same
        # tappable card (P0 card/ledger unification, 2026-07-24).
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
        # WHAT WE ASSUMED INSTEAD OF ASKING. When the consequence engine judges
        # an unknown too small to interrupt for, the turn still made a choice —
        # a portion, a preparation, a variant. Surfacing it on the row is what
        # separates "logged fast" from "logged fast and quietly guessed": the
        # card can show it as a correctable chip instead of the user having to
        # notice a number looks wrong. Optional on the wire like the rest.
        _assumed = [a for a in (inp.get("assumptions") or [])
                    if isinstance(a, dict) and a.get("text")]
        if _assumed:
            payload["assumptions"] = _assumed[:3]
        # Undo token: the ledger event behind this write. Optional on the
        # wire — older clients ignore it; new clients render one-tap Undo.
        _ev = (call.event_id if call is not None and call.event_id is not None
               else inp.get("_event_id"))
        if _ev is not None:
            payload["event_id"] = _ev
        # Decision-receipt context (day impact + verdict), stashed by the
        # executor at log time — see core/receipt.py. All keys optional on
        # the wire; older clients simply ignore them.
        receipt = (call.receipt if call is not None and call.receipt is not None
                   else inp.get("_receipt"))
        if isinstance(receipt, dict):
            payload.update(receipt)
        # The model's own coach read outranks the deterministic verdict —
        # varied and contextual beats canned. Guarded: short, and no digits
        # (a number here could mismatch the card's own math).
        coach = (inp.get("coach_read") or "").strip()
        if coach and len(coach) <= 90 and not any(ch.isdigit() for ch in coach):
            # ...but it may not contradict the numbers on its own card. A
            # shipped card read "Strong protein hit — the day closes clean from
            # here" directly above its own "38g protein to go". Short: yes. No
            # digits: yes. Both guards passed and the card still said two
            # opposite things at once, because neither guard looked at the
            # snapshot the rest of the payload was built from.
            from core.receipt import coach_read_contradicts
            if not coach_read_contradicts(coach, receipt if isinstance(
                    receipt, dict) else None):
                payload["verdict"] = coach
        return {"type": "macro_card", "payload": payload}
    if name == "log_exercise":
        if not _workout_card_enabled():
            return None            # WORKOUT_CARD=false → text-only confirmation
        # Prefer the FINAL DB-row values the dispatcher stashed (_card_sets /
        # _card_reps) so an appended set shows the movement's running total
        # ("3×12,13,13"), not the lone set from this one call. Falls back to the
        # call input for a fresh single log.
        _cs = (call.card_sets if call is not None and call.card_sets is not None
               else inp.get("_card_sets", inp.get("sets")))
        _cr = (call.card_reps if call is not None and call.card_reps is not None
               else inp.get("_card_reps"))
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
    # The row this turn REPLACED, when it was a regenerate/edit (set alongside
    # the supersede mark in chat_service). History already hides the old row on
    # reload; this is what lets a live client drop the message — and its card —
    # the moment the replacement arrives, instead of leaving a stale card
    # stacked beside the new reply.
    superseded_log_id: Optional[int] = None


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


async def run_turn(*args, **kwargs) -> TurnResult:
    """Entry point for a turn: one food trace, one time budget (PRs #29, #30).

    Both of the things opened here used to open too late, for the same reason —
    each was installed at the layer that happened to need it rather than at the
    layer that bounds a turn.

    THE TRACE opened inside `core.food_turn.run()`, which returns the structured
    action and the tool calls. The nutrient resolution during execution, the
    database writes, the failed writes, the card render and the final coaching
    line all happen afterwards, in this function, so a trace that closed with the
    interpreter pass could not see any of them: the seven-stage trace was really
    a three-stage one wearing a longer name.

    THE BUDGET opened inside `execute_tool_calls`, which made it a tool-batch
    budget wearing a turn budget's name — it began after the interpreter model
    call and ended before the response composer, so a turn could spend the
    interpreter's timeout, then a full batch budget, then the composer's, with
    every part behaving exactly as configured while the user waited for the sum.

    Opening a trace for EVERY turn, food or not, is deliberate: nothing at the
    top of a turn knows yet whether food is involved. `finish` only emits a line
    for traces that actually recorded a stage, so non-food turns stay silent. The
    nested budget in the executor stays too — nested budgets can only tighten, so
    it still protects the paths that call the executor directly and cannot extend
    this one.

    `*args`/`**kwargs` rather than the real signature: callers pass a mix of
    positional and keyword arguments, and restating twenty parameters here would
    be a second signature to keep in step with the first.
    """
    from core import food_trace
    from core.request_trace import RequestTrace, active as _trace_active
    from skills.nutrition.v2_gate import for_user as _v2_for_user

    fields = {}
    try:
        user = args[0] if args else kwargs.get("user")
        platform = args[4] if len(args) > 4 else kwargs.get("platform", "")
        fields = dict(turn_id=(kwargs.get("turn_id") or ""),
                      user_id=getattr(user, "id", None),
                      channel=str(platform or ""))
    except Exception:
        fields = {}

    # Durable per-turn latency row (B5). The main pipeline never wrote to
    # turn_metrics — only quick_log did — so "did main-turn p50 regress after
    # that deploy", the question asked and unanswered on 2026-07-30, had no
    # data behind it. ONE RequestTrace at this boundary (every return path runs
    # the finally), made ambient so the LLM / tool / voice leaves time
    # themselves via `timed()`, and persisted on an ISOLATED session so a
    # telemetry row can never commit or roll back with the turn's own write.
    _rt = RequestTrace(turn_id=fields.get("turn_id") or "",
                       channel=fields.get("channel") or "",
                       command="turn", user_id=fields.get("user_id"))
    _outcome, _result = "ok", None
    try:
        # Trace outside the budget: a turn that runs out of time is exactly the
        # turn whose trace has to survive to say so.
        with food_trace.span(**fields), deadline.budget(), _trace_active(_rt), \
                _v2_for_user(fields.get("user_id")):
            _result = await _run_turn(*args, **kwargs)
        return _result
    except Exception as e:
        _outcome = f"error:{type(e).__name__}"
        raise
    finally:
        try:
            _sf = getattr(_result, "skills_fired", "") or ""
            if any(t in _sf for t in ("log_food", "log_exercise", "log_weight")):
                _rt.command = "turn:log"      # a logging turn, distinct from chat
            _rt.done(outcome=_outcome)
            await _rt.persist_isolated()
        except Exception:
            pass


async def _clear_deferred(db, pending_row, prior) -> None:
    """Strip `deferred_calls` from an open pending question's payload.

    A stash that has been WRITTEN must stop being a stash. The question itself
    may still be open and unanswered — that is why this edits the payload
    rather than stamping `answered_at` — but the food inside it is on the board
    now, and anything that reloads the row would write it again.

    Never raises: a failure here leaves a stale IOU, which dedup can still
    catch inside its window, whereas an exception would cost the reply.
    """
    if pending_row is None or not (prior or {}).get("deferred_calls"):
        return
    try:
        import json as _json
        _payload = dict(prior or {})
        _payload.pop("deferred_calls", None)
        pending_row.payload_json = _json.dumps(_payload)
        await db.commit()
    except Exception as e:
        logger.error("could not clear deferred_calls (they may re-commit "
                     "on a later turn): %s", e, exc_info=True)


def _shadow_clarification_fields(sft, resp) -> None:
    """Report what a TYPED clarification contract would have shipped.

    Writes nothing. `resp.buttons` is already decided; this says what
    `core.semantics.ClarificationField` makes of the same turn, so the
    disagreement is measurable before anything depends on it.

    The number worth watching is `unanswerable` — questions carrying no
    options. Each one is a turn where the user must type, and where iOS
    re-derives chips by parsing Arnie's own rendered sentence
    (`QuickReplyEngine.swift`). Measured on prod 2026-08-03: 39 of the last 40
    asks shipped `options: []`.
    """
    try:
        from skills.nutrition.clarification_adapter import (
            fields_from_turn, free_text_required, missing_expected_options)
        fields = fields_from_turn(sft or {})
        if not fields:
            return
        # TWO NUMBERS, because they mean different things. A free-text question
        # is not broken — "what restaurant was it from?" correctly requires
        # typing. Only a field that PROMISES a choice and offers none is a
        # defect, and conflating them would have overstated breakage and pushed
        # toward generating chips for questions that should stay free text.
        blind = missing_expected_options(fields)
        typed_free = free_text_required(fields)
        _btns = len(getattr(resp, "buttons", None) or ())
        _typed = sum(len(f.options) for f in fields)
        logger.info(
            "event=clarification_shadow fields=%d typed_options=%d "
            "wire_buttons=%d missing_expected=%d free_text=%d attributes=%s%s",
            len(fields), _typed, _btns, len(blind), len(typed_free),
            ",".join(f.attribute for f in fields),
            "" if _typed == _btns else
            f" MISMATCH typed={_typed} wire={_btns}")
    except Exception:      # a measurement may never cost the turn
        logger.debug("clarification shadow failed", exc_info=True)


async def _settle_expired_deferred(db, user, prior, today_log, *,
                                   source_type=None) -> tuple:
    """Commit the foods an expired clarification was still holding.

    Returns `(calls, call_results)` — WHAT it committed, not merely how many.

    It returned a count, and a count cannot become a card. `_logged_entry_card`
    is gated on an `entry_id` that lives ONLY on the typed `CallResult`, because
    the executor is immutable by design (`execution_result.stash` never writes
    the command input, P0.3e). So discarding what `execute_tool_calls` returned
    here committed the food and threw away the one object that could render it:
    the held rice landed in the day total, moved the day's numbers, and appeared
    on no card on any turn — visible to the user only as a total that did not
    match anything they could see (live, 2026-08-04).

    Both are returned because both are needed downstream: the raw call dicts
    join this turn's `tool_calls`, and the results join `_execution`, which is
    the identity-keyed pairing the card builder walks.

    NEVER raises and never blocks the turn: a failure here must degrade to the
    old behaviour (the food is lost) rather than cost the user the reply they
    are waiting for.

    The asked-about item is deliberately NOT here — it rides `staged_items` and
    genuinely has no answer, so it stays unwritten. `deferred_calls` is the
    rest of the meal: foods the user reported, that we understood and priced,
    and that were held back only because a DIFFERENT item raised a question.
    Their day is not in doubt, only their company.

    Written against the STASHED date when there is one, so a meal held
    overnight lands on the day it was eaten rather than the day it expired.
    `log_food` already accepts `input["date"]` and resolves the target day via
    `get_or_create_log_for_date`, so the past-day case needs no new machinery.
    """
    try:
        from core.food_turn import deferred_calls as _deferred
        calls = _deferred(prior)
        if not calls:
            return [], []
        _stashed_date = (prior or {}).get("log_date") or ""
        if _stashed_date:
            for _tc in calls:
                if _tc.get("name") == "log_food":
                    # `setdefault` — a call that already names its own day
                    # keeps it.
                    (_tc.setdefault("input", {})).setdefault(
                        "date", _stashed_date)
        if today_log is None:
            from db.queries import get_or_create_today_log
            today_log = await get_or_create_today_log(
                db, user.id, getattr(user, "timezone", None) or "UTC")
        names = [(c.get("input") or {}).get("food_name") for c in calls]
        logger.warning(
            "event=deferred_commit outcome=expired_rescue user=%s count=%d "
            "foods=%s date=%s — the question aged out; the food did not",
            getattr(user, "id", "?"), len(calls), names, _stashed_date or "-")
        await execute_tool_calls(calls, user, today_log, db,
                                 source_type or "text")
        # The typed view the executor just published. Read here rather than
        # returned by `execute_tool_calls` because that is the established
        # pattern (`run_turn` reads the same contextvar right after its own
        # batch), and read IMMEDIATELY so a later batch cannot overwrite it.
        _results = []
        try:
            from core.execution_result import LAST_EXECUTION
            _ex = LAST_EXECUTION.get()
            _results = list(getattr(_ex, "calls", ()) or ())
        except Exception:      # a missing card must never cost the write
            logger.debug("settled deferred: no typed view", exc_info=True)
        return calls, _results
    except Exception as e:
        logger.error("expired-deferred rescue FAILED (food lost): %s", e,
                     exc_info=True)
        return [], []


async def _run_turn(
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
    turn_id: Optional[str] = None,  # canonical transaction identity (core/turn_identity)
) -> TurnResult:
    """
    Core pipeline: LLM call → tool execution → coach-unmute / follow-up /
    deterministic fallback → Response assembly (detect_moment, dashboard-link-once).

    Returns a TurnResult so each handler can apply its own delivery layer.
    """
    import time as _time_mod
    _turn_t0 = _time_mod.monotonic()
    # Canonical turn identity rides the whole turn ambiently (contextvar):
    # ledger events stamp it, the exactly-once claim keys on it. Set even when
    # None so a prior turn's id can never leak into this one on a reused task.
    from core.turn_identity import CURRENT_TURN_ID as _TID
    _TID.set(turn_id)
    # ONE EVIDENCE CONTEXT FOR THE WHOLE TURN, ambient beside the turn id, so
    # speculative enrichment (which starts while the interpreter is still
    # streaming) and B-1 field derivation (which runs after) resolve the SAME
    # object. Set even when a previous turn ran on this task: a stale context
    # would serve assessments about evidence nobody fetched this time.
    from core.evidence_context import CURRENT_EVIDENCE as _EV
    from core.evidence_context import EvidenceContext as _EvCtx
    _EV.set(_EvCtx())
    _turn_route = "legacy"   # refined by the lanes below; emitted in turn_trace
    # Tool names the user has already been shown a progress event for. The
    # indicator is a claim about what is happening NOW, so announcing a name
    # twice reads as two separate backend actions.
    _announced: set = set()
    # WHY this turn is on the legacy path, when it is. A silent `_sft = None`
    # made the single most consequential routing decision in the turn
    # undiagnosable in production: the same message could take either path on
    # different days and the logs looked identical. Codes are stable strings
    # (mixed_domain, non_english, kill_switch, interpreter_none,
    # interpreter_timeout, pipeline_exception, ask_stash_failed, idempotent_dup)
    # and ride out in turn_trace next to the route.
    _legacy_reason = ""

    from core import food_trace as _ft_vis

    #: Whether the early heads-up already spoke. The late one below
    #: must not repeat it — two 'checking the macros' in one turn reads
    #: as the lane stuttering, not as reassurance.
    _early_heads_up_sent = False

    #: SECOND-TIER heads-up (P1 felt-latency). When the first heads-up speaks it
    #: schedules a self-guarding timer that, ~6s in, adds a fuller "still here,
    #: here's what's taking the time" line — only if the reply is not yet ready.
    #: `_reply_ready` flips the instant the food reply is final, so the timer
    #: no-ops on every one of run_turn's exits without needing a cancel;
    #: `_late_task` is held only to keep the task off the GC while it sleeps.
    _reply_ready = False
    _late_task = None

    #: Routing is one decision, so it contributes ONE stage record however many
    #: exits reach it. `stage_ms` sums, so a turn that declines twice would
    #: otherwise report double the time it spent deciding.
    _route_closed = False

    def _end_route():
        nonlocal _route_closed
        if _route_closed:
            return
        _route_closed = True
        try:
            from core import food_trace as _ft_r
            from core.food_trace import Stage as _StageR
            _ft_r.record(_StageR.ROUTE,
                         duration_ms=(_time_mod.monotonic() - _turn_t0) * 1000.0)
        except Exception:
            pass

    def _to_legacy(reason: str, **detail):
        """Hand this turn back to the legacy path, on the record.

        `detail` is the part that makes the record usable. `reason` names the
        DECISION (interpreter_none, kill_switch); the interesting question is
        almost always which of several very different situations produced it,
        and until now the answer was not written down anywhere. The
        2026-08-04 transcript had to be diagnosed by reading source, because
        the line that fired said the interpreter returned nothing — true, and
        useless.
        """
        nonlocal _legacy_reason
        _legacy_reason = reason
        # ON THE LATENCY LINE TOO. The reason has always been logged, in a
        # DIFFERENT line from the timings — so "which escapes are the slow
        # ones" needed two greps and a join nobody wrote.
        try:
            from core import food_trace as _ft_l
            _ft_l.note(legacy_escape_reason=reason, **{
                k: v for k, v in detail.items() if v not in (None, "")})
        except Exception:
            pass
        _end_route()
        _extra = "".join(f" {k}={v}" for k, v in detail.items()
                         if v not in (None, ""))
        logger.info(
            f"event=structured_food_fallback reason={reason}{_extra} {_tag}")
        return None
    _source = source_type or platform
    _tag = f"{platform}:{user.id}"
    _retried = False  # turn-health: did the self-heal fire this turn?
    _messages_for_followup = messages
    _first_stop_reason = None
    # ── Regeneration semantics (Danny 2026-07-24) ─────────────────────────────
    # A [REGENERATE:<id>] turn re-runs with an explicit directive instead of the
    # raw marker: a regen of a LOGGED turn means those board entries are suspect
    # — revise via the board (update/remove), never duplicate; a regen of a
    # SUGGESTION turn means vary the options ("give me some more options").
    # The old row is superseded downstream and its card never carries forward.
    for _m_r in reversed(messages):
        if _m_r.get("role") == "user" and isinstance(_m_r.get("content"), str) \
                and _m_r["content"].strip().startswith("[REGENERATE"):
            _m_r["content"] = (
                "[The user tapped regenerate on your previous reply. They were "
                "not satisfied. Redo the turn properly. If that reply logged "
                "anything, those entries sit on today's board and are suspect: "
                "revise them through the board (update or remove), never log "
                "duplicates. If it suggested meals, give clearly DIFFERENT "
                "options this time, like they asked for more choices. Never "
                "repeat the rejected reply.]")
            break

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
    # Food a HELD clarification settled earlier in this turn. It commits well
    # before `tool_calls` is bound (which happens ~800 lines below and would
    # overwrite anything appended at the settle site), so it is carried here and
    # merged once the typed execution view exists. Without the merge the rows
    # land and no card is ever built for them — see `_settle_expired_deferred`.
    _settled_calls: list = []
    _settled_results: list = []
    # Whether this turn's hand-back to legacy was the writes-only settle rather
    # than an interpreter failure. They took the same log line, so a SUCCESS
    # (held food committed, reply belongs to the conversational brain) was
    # indistinguishable from the most common failure in the product.
    _wo_settled = False
    # VERIFY-BEFORE-STREAM: on a streaming logging turn we HOLD the follow-up voicing
    # (buffer, don't stream live) until the day-total guard has checked its running
    # total against the DB. Then the verified response_text is emitted ONCE via the
    # post-build catch-up. Without this, a phantom total streams live and the guard's
    # correction can only APPEND — the double-reply (turkey+rice: "1698" then "1566").
    _hold_voicing = False
    _streamer = _BubbleStreamer(on_text_bubble) if on_text_bubble else None
    _stream_handler = _streamer.on_delta if _streamer else None
    # Only pass stream_handler to LLM calls when active — keeps the chat() and
    # chat_follow_up() signatures backward-compatible with mocks that predate
    # T2.1 (no kwarg surface change for non-streaming callers / tests).
    _chat_extras = {"stream_handler": _stream_handler} if _stream_handler else {}
    _scribe_task = None  # the parallel scribe extraction; set inside the pass below
    _execution = None    # typed per-call execution view; set after tools run

    # ── STRUCTURED FOOD TURN (Danny 2026-07-23/24): the interpreter proposes an
    # ordered plan (log/update/delete, mixed turns commit in the user's order),
    # deterministic policy arbitrates its reported ambiguities, duplicates are
    # absorbed by the idempotency claim, and narration renders from ONE
    # committed snapshot (core/food_ledger.render_committed). The plan executes
    # as source=structured_food tool calls through the normal executor, so
    # enrichment/dedup/cards run unchanged — and the 46k-token pass is skipped
    # entirely on these turns. Asks are a different ACTION from writes and run
    # BEFORE any commit; "undo"/"bring back" is a deterministic ledger inverse
    # (core/ledger_undo, zero model calls). Anything the lane passes on takes
    # the legacy path untouched.
    _sft = None
    # One path for EVERYONE: onboarding users get the ask ladder too
    # (Samuel 2026-07-24: 7 unstated portions, zero asks), and photo
    # turns MUST enter or photo_food_message (5f0e195) never runs.
    try:
        # THE GATE AND THE CLASSIFIER ARE THE SAME QUESTION. `food_relevance`
        # is `applies` with a better answer behind it — same call site, same
        # meaning, so nothing here has to know whether a regex or a model
        # decided. Falls back to the regexes whenever the model lane is off or
        # unavailable.
        from core.food_turn import food_relevance as _sft_relevant
        from core.food_turn import (structured_food_enabled, ASK_KIND,
                                    applies as _sft_applies, run as _sft_run,
                                    thread_relevance as _sft_rel,
                                    applies_destructive as _sft_dest)
        if not structured_food_enabled():
            _to_legacy("kill_switch")
        if structured_food_enabled():
            # ── B-1: is this turn ANSWERING a canonical operation? ──
            #
            # Asked BEFORE the legacy prior loads and before `_sft_run` is
            # reachable. An owned answer never touches the broad food
            # interpreter — that is how "6 oz" became a second meal — so the
            # branch returns rather than falling through.
            #
            # The rollout gate is NOT consulted here and cannot be: the
            # answer module does not import it, and a test reads its AST to
            # keep that true. Ownership was decided once, at the ask.
            try:
                from core import b1_answer_turn as _b1_ans
                from core.turn_identity import current_turn_id as _b1_tid
                _b1_out = await _b1_ans.handle(
                    db, user=user,
                    source_turn_id=turn_id or _b1_tid() or "",
                    message=_user_text or "")
            except Exception:
                # `handle()` is TOTAL once ownership is established, so
                # reaching here means the failure happened before we could
                # know whether this meal is owned — an import error, a
                # session already poisoned. Falling through to the
                # interpreter could duplicate a pending meal; refusing costs
                # one turn and writes nothing. Refuse.
                logger.error("b1 answer turn failed before ownership was "
                             "known — refusing rather than proceeding legacy",
                             exc_info=True)
                from core.b1_answer_turn import AnswerTurn as _B1Turn
                from core.clarification_answer import Outcome as _B1Outcome
                _b1_out = _B1Turn(_B1Outcome.REFUSED, internal_failure=True,
                                  reason="b1 answer path unavailable")
            if _b1_out is not None:
                await db.commit()
                logger.info(
                    "event=b1_answer outcome=%s operation=%s user=%s",
                    _b1_out.outcome.value, _b1_out.operation_id, user.id)
                # THE TRACE THIS BRANCH NEVER LEFT. `finish()` only emits a
                # line when the trace recorded a stage, and this return happens
                # before `Stage.ROUTE` is ever recorded — so every typed answer
                # closed its span silently and the canonical commit had no
                # food_trace line at all. `operation_id` is what joins this line
                # to the ask turn, which carries a different `turn_id`.
                #
                # A commit records `Stage.EXECUTE` in the coordinator; the other
                # outcomes record here, because "the answer turn asked again" and
                # "the answer turn refused" are funnel states that otherwise look
                # identical to a turn that never ran.
                try:
                    from core import food_trace as _b1_ft
                    _b1_ft.note(operation_id=_b1_out.operation_id or "")
                    _b1_outcome_v = str(getattr(_b1_out.outcome, "value", ""))
                    if _b1_out.internal_failure:
                        _b1_ft.record(_b1_ft.Stage.CLARIFY,
                                      outcome=_b1_ft.Outcome.FAILED,
                                      detail=f"b1:{_b1_outcome_v}")
                    elif _b1_outcome_v in ("repair", "partial"):
                        _b1_ft.record(_b1_ft.Stage.CLARIFY,
                                      outcome=_b1_ft.Outcome.ASKED,
                                      detail=f"b1:{_b1_outcome_v}")
                    elif _b1_outcome_v != "applied":
                        _b1_ft.record(_b1_ft.Stage.CLARIFY,
                                      outcome=_b1_ft.Outcome.HELD,
                                      detail=f"b1:{_b1_outcome_v}")
                except Exception:
                    pass
                # ONE extraction, passed to both renderers. Neither may
                # re-read the commit result, so they cannot drift apart.
                _b1_facts = _b1_ans.facts_for(_b1_out)
                _b1_resp = Response.from_text(_b1_ans.copy_for(_b1_facts))
                # WHEN THE COMMITTED TRUTH GOT WORDS — the same moment the
                # legacy commit render marks, so the two lanes' numbers mean
                # the same thing. Both this and `api/chat.py` stamp it strictly
                # AFTER their `db.commit()`; the row is durable by the time we
                # claim a committed answer became visible.
                #
                # `entry_id` IS NOT THE CONDITION ON ITS OWN — the third place
                # this lane made that mistake. A REPLAY carries the ORIGINAL
                # entry's id, which is the point of a replay, so `entry_id` is
                # present on a turn that wrote nothing. The user retyping an
                # offered option label reaches exactly this branch, and the
                # mark dated a commit that happened on some earlier turn.
                #
                # It was invisible until now only because a replay recorded no
                # stage and `finish()` emits nothing for a stageless trace.
                # `core/b1_answer_turn.py` now records the replay so the turn
                # has a line at all — which turns this from a silent wrong
                # number into a `funnel=visible_without_commit` line, and into
                # a test failure under the autouse invariant.
                #
                # Same condition as `api/chat.py`: what THIS turn wrote, read
                # off the trace so the mark cannot disagree with the count it
                # is about. Zero exactly when the coordinator never ran.
                try:
                    from core import food_trace as _b1_ft2
                    _b1_vis = _b1_ft2.current()
                    if getattr(_b1_facts, "entry_id", None) \
                            and _b1_vis is not None \
                            and _b1_vis.items_written > 0:
                        _b1_ft2.mark("commit_visible")
                        # `commit_or_load_existing` only flushed into the
                        # transaction that closed above; this is where the write
                        # actually became durable, so this is where the count
                        # earns the name `committed`.
                        _b1_ft2.committed_durably()
                except Exception:
                    pass
                _b1_card = _b1_ans.card_for(_b1_facts)
                if _b1_card is not None:
                    # ONE facts object, two renderings. The card cannot
                    # disagree with the sentence above it because neither
                    # recomputes anything.
                    _b1_resp.cards.append(_b1_card)
                # TURN HEALTH, WHICH THIS LANE HAD NEVER RUN.
                #
                # `detect_turn_flags` lives ~3000 lines below and this branch
                # returns before reaching it, so every canonical answer turn
                # left `health_flags` empty — not "the detector did not fire",
                # but "the detector was never called". That is why
                # `phantom_log_claim` looked silent on the 2026-08-05 data
                # loss: called directly with those exact strings it fires
                # correctly. Zero coverage, not a tuning problem, and every
                # future canonical lane inherits it unless it is run here.
                #
                # AND THIS LANE CAN DO BETTER THAN THE LEGACY PROXY. The
                # legacy call passes `has_tool_calls` as a stand-in for "did a
                # write happen" — a proxy that is simply false here, since the
                # canonical path commits without the model firing a tool. We
                # know the answer: `entry_id` is set exactly when a row landed.
                # So the fact is passed where the proxy would have been.
                _b1_flags: list = []
                try:
                    _b1_flags = detect_turn_flags(
                        user_text=_user_text if isinstance(_user_text, str) else "",
                        # The bubbles ARE the reply — `Response` has no
                        # `.text`, and reading a field that does not
                        # exist is how this silently ran zero times
                        # once already.
                        response_text="|||".join(_b1_resp.bubbles or []),
                        has_tool_calls=bool(getattr(_b1_facts, "entry_id", None)),
                        # The FACT, not the proxy. This lane knows whether a
                        # row landed, so it says so rather than letting a
                        # detector infer it from the sentence it just wrote.
                        wrote_this_turn=bool(getattr(_b1_facts, "entry_id", None)),
                        # ONLY REPAIR ASKS. `!= "applied"` was too broad and
                        # broad in the DANGEROUS direction: `asked_this_turn`
                        # SUPPRESSES phantom detection, so lumping CANCELLED
                        # and REFUSED in with it would hide a false
                        # confirmation on exactly the paths most likely to
                        # emit one — a refused or internally-failed turn that
                        # still says "logged". Of the four outcomes only
                        # REPAIR re-asks the field; the other three end the
                        # turn.
                        #
                        # `.value`, not the enum: `_B1Outcome` is imported
                        # inside the except handler above and is unbound on
                        # the happy path. Reading it here raised NameError
                        # into the swallow below and the check ran zero times.
                        #
                        # `partial` JOINED IT AT B-1.5, and it is the only
                        # addition that belongs. A partially answered question
                        # writes no row and re-asks the fields still open, so
                        # it is an ASK by both tests this flag cares about.
                        # Its copy is `copy_for`'s partial branch, which
                        # acknowledges and asks and cannot say "logged" — the
                        # property that makes suppressing detection here safe.
                        asked_this_turn=(
                            str(getattr(_b1_out.outcome, "value", ""))
                            in ("repair", "partial")),
                        stop_reason="b1_answer",
                        retried=False, tool_error=bool(_b1_out.internal_failure),
                        source_type=_source, tool_names=set(),
                        prior_assistant_text="")
                    if _b1_flags:
                        logger.warning(
                            "TURN_HEALTH %s flags=%s",
                            f"{platform}:{user.id}", ",".join(_b1_flags))
                except Exception:
                    # Telemetry may never cost the reply the user already has —
                    # but it must not fail QUIETLY either. At DEBUG this hid
                    # two of my own bugs in this very block, and a health check
                    # that silently never runs looks exactly like a healthy
                    # system. Loud, and still harmless.
                    logger.warning("b1 turn-health failed", exc_info=True)
                return TurnResult(
                    response=_b1_resp, health_flags=_b1_flags,
                    tool_calls=[], just_completed=False,
                    in_onboarding=in_onboarding, onboarding_field_saved=None,
                    today_log=today_log, user=user)

            _sft_prior_pq = None
            _sft_prior = None
            try:
                from db.queries import get_open_pending_question as _gopq_s
                _sft_prior_pq = await _gopq_s(db, user.id, ASK_KIND)
                if _sft_prior_pq is not None:
                    _sft_prior = json.loads(_sft_prior_pq.payload_json or "{}")
            except Exception:
                _sft_prior_pq, _sft_prior = None, None
            # Pending-state expiry (ledger fix #6): a stale confirm ("yes"
            # twenty minutes later) or ancient clarify must never bind a
            # fresh turn — resolve it and treat the turn as cold.
            if _sft_prior_pq is not None:
                try:
                    from core.food_ledger import pending_expired as _pq_exp
                    if _pq_exp(_sft_prior_pq, (_sft_prior or {}).get("kind")):
                        # THE QUESTION EXPIRES. THE FOOD DOES NOT.
                        #
                        # Since an ask writes nothing (FOOD_PARTIAL_COMMIT
                        # defaults false), the whole understood meal lives ONLY
                        # as `deferred_calls` in this payload until
                        # `_settle_deferred` commits it at `run()`'s exit. That
                        # exit needs another food turn. Retiring the row here
                        # without reading it therefore destroyed every food the
                        # user reported — not the one item we asked about, the
                        # MEAL. On origin/main the ready foods were already
                        # written, so expiry cost one item; the flag flip turned
                        # that into total, silent loss, which is the exact class
                        # this branch exists to close.
                        #
                        # Settled HERE rather than deferred to the next turn,
                        # because this is the last moment anything knows the
                        # food exists: the next turn may not be a food turn at
                        # all, and then `run()` never executes.
                        _sc, _sr = await _settle_expired_deferred(
                            db, user, _sft_prior, today_log,
                            source_type=_source)
                        _settled_calls += _sc
                        _settled_results += _sr
                        from datetime import datetime as _dt_x
                        _sft_prior_pq.answered_at = _dt_x.utcnow()
                        await db.commit()
                        _sft_prior_pq, _sft_prior = None, None
                except Exception:
                    pass
            # GRADED THREAD RELEVANCE (ledger fix #4): intent-aware, not a
            # flat 15-minute takeover. An open ask binds answers; a
            # minutes-old write binds reports and corrections; an hours-old
            # write binds only explicit corrections/removals. Challenges,
            # explanation requests, coaching asks and commentary stay with
            # the conversational brain even seconds after a write.
            _mins_since_write = None
            try:
                from datetime import datetime as _dt_t
                from core import clock as _clock
                _latest = max((getattr(_fe, "timestamp", None)
                               for _fe in (getattr(today_log, "food_entries", None) or [])
                               if getattr(_fe, "timestamp", None) is not None),
                              default=None)
                if _latest is not None:
                    _mins_since_write = (
                        _clock.now() - _latest).total_seconds() / 60.0
            except Exception:
                _mins_since_write = None
            _route_mid = False
            try:
                _route_mid = _sft_rel(_user_text or "", _mins_since_write,
                                      _sft_prior is not None)
            except Exception:
                _route_mid = False
            # Today's board — built BEFORE routing so single-entry deletes
            # ("remove the fries") can gate on having something to delete,
            # and corrections/repeats resolve to real entry ids.
            _board = []
            try:
                for _fe in (getattr(today_log, "food_entries", None) or []):
                    if getattr(_fe, "id", None) is not None:
                        # HOW LONG AGO. Without it the board reads "already
                        # logged today" for a row written eight hours ago and
                        # for one written sixty seconds ago, so a message
                        # elaborating on what we just wrote ("the chicken was a
                        # small breast") is indistinguishable from a fresh meal
                        # — and gets logged a second time. The rows carry the
                        # timestamp already; nothing new is stored.
                        _age = None
                        try:
                            from datetime import datetime as _dt_b
                            from core import clock as _clock
                            _ts = getattr(_fe, "timestamp", None)
                            if _ts is not None:
                                _age = max(0, int(
                                    (_clock.now() - _ts).total_seconds()
                                    // 60))
                        except Exception:
                            _age = None
                        _board.append({
                            "id": _fe.id,
                            "food": getattr(_fe, "parsed_food_name", "") or "",
                            "qty": getattr(_fe, "quantity", "") or "",
                            "mins_ago": _age,
                            "cal": getattr(_fe, "calories", 0) or 0})
            except Exception:
                _board = []
            _last_assistant = next(
                (m.get("content", "") for m in reversed(messages)
                 if m.get("role") == "assistant" and isinstance(m.get("content"), str)),
                "")
            _photo_food = photo_food_message(_user_text or "")
            # Strict-confirm fast path: an affirmative on a confirm
            # pending logs the stashed items verbatim — no re-parse, no
            # model. Anything non-affirmative falls through to the logger
            # with the prior (corrections adjust, then log).
            # DETERMINISTIC UNDO/RESTORE (ledger Phase 2): "undo" / "bring
            # back the fries" is an inverse on the event ledger — zero
            # model calls, immediate. Only on a quiet thread (no open ask:
            # an undo mid-question means "cancel", which the ack path and
            # pending expiry already cover). The plan feeds the SAME
            # structured pipeline below (execution, snapshot, renderer).
            _undo_plan = None
            if _sft_prior is None:
                try:
                    from core.ledger_undo import build_plan as _undo_build
                    _undo_plan = await _undo_build(db, user, _user_text or "")
                except Exception:
                    _undo_plan = None
            _confirm_hit = None
            if (_sft_prior is not None
                    and (_sft_prior.get("kind") == "confirm")
                    and _sft_prior.get("items")):
                from core.food_turn import _YES_RE as _yes_re_c
                if _yes_re_c.match((_user_text or "").strip()):
                    _confirm_hit = _sft_prior["items"]
            # THE FREE SIGNALS DECIDE FIRST, AND THE INDICATOR GOES WITH THEM.
            #
            # The gate below was an `or` chain that awaited the model third,
            # ahead of two terms costing nothing:
            #
            #     prior · photo · AWAIT food_relevance · board+destructive · thread
            #
            # So a turn that is food BECAUSE THE THREAD IS ACTIVE, or because
            # the board plus a destructive verb say so, paid a Haiku round trip
            # to be told something already known — and the "Logging…" indicator,
            # which fires on the far side of the gate, waited behind it. The
            # user watched a generic thinking dot for a model call whose answer
            # could not change the outcome.
            #
            # Ordering them first is free in both directions: `or` short-
            # circuits, so the model is now asked only about the cold-start
            # case it was written for, and the indicator can morph before the
            # gate rather than after it. Nothing here fires the indicator on a
            # turn that is not food — every term is a signal that already says
            # food, which is why the model call can be skipped on it at all.
            _food_now = bool(_sft_prior is not None or _photo_food is not None
                             or _route_mid
                             or (_board and _sft_dest(_user_text or "")))
            # WHICH free signal settled it, claimed BEFORE the gate is reached.
            # `or` short-circuits, so on any of these the model never runs —
            # and that is precisely the number worth counting: every claim here
            # is a Haiku round trip we did not pay for. Ordered to match the
            # boolean above so the label names the term that actually won.
            from core import food_trace as _ft_route
            if _undo_plan is not None:
                _ft_route.claim_route("undo")
            elif _confirm_hit is not None:
                _ft_route.claim_route("confirm")
            elif _sft_prior is not None:
                _ft_route.claim_route("prior")
            elif _photo_food is not None:
                _ft_route.claim_route("photo")
            elif _route_mid:
                _ft_route.claim_route("thread")
            elif _food_now:
                _ft_route.claim_route("board_destructive")
            if (_undo_plan is None and _confirm_hit is None and _food_now
                    and on_tool_start and "log_food" not in _announced):
                try:
                    await on_tool_start(["log_food"])
                    _announced.add("log_food")
                    _ft_vis.mark("first_visible")
                except Exception:
                    pass

            if _undo_plan is not None:
                _sft = _undo_plan
                _turn_route = "ledger_undo"
                _sft["_before"] = (
                    int(getattr(today_log, "total_calories", 0) or 0),
                    int(getattr(today_log, "total_protein", 0) or 0))
                logger.info(f"event=ledger_undo outcome=routed {_tag} "
                            f"kinds={','.join(_sft.get('kinds') or [])}")
            elif _confirm_hit is not None:
                # Deterministic replay of the confirmed items through the
                # SAME builder the interpreter uses (_log_call) — one
                # item→call codepath; provenance marks the replay.
                from core.food_turn import _log_call as _sft_log_call
                _calls_c = [c for c in
                            (_sft_log_call(_it,
                                           source="structured_food:confirm_replay")
                             for _it in _confirm_hit[:8])
                            if c is not None]
                _turn_route = "confirm_replay"
                _sft = {"action": "log", "tool_calls": _calls_c,
                        "say": ("Locked in, {batch_cal} cal and "
                                "{batch_protein}g protein. You're at {day_cal} "
                                "with {cal_left} left and {protein_left}g "
                                "protein to go."),
                        "_before": (
                            int(getattr(today_log, "total_calories", 0) or 0),
                            int(getattr(today_log, "total_protein", 0) or 0))}
                try:
                    from datetime import datetime as _dt_cf
                    _sft_prior_pq.answered_at = _dt_cf.utcnow()
                    await db.commit()
                except Exception:
                    pass
            elif not (_food_now
                      or await _sft_relevant(_user_text or "",
                                             _last_assistant or "")):
                # The cold-start gate turned this message away. WHICH shape it
                # was is the difference between a language we don't serve yet
                # and a hole in the gate, and both used to log as nothing.
                from core.food_turn import decline_reason as _sft_why
                _to_legacy(_sft_why(_user_text or "") or "not_food_shaped")
            else:
                # Immediate status: morph the live thinking indicator to
                # "Logging…" the moment the logger starts, so its pass is
                # never silent dead air (Danny 2026-07-23). Already fired above
                # for every turn the free signals settled; this is the
                # cold-start case, where nothing knew it was food until the
                # model gate said so.
                _end_route()
                _ctx_t0 = _time_mod.monotonic()
                if on_tool_start and "log_food" not in _announced:
                    try:
                        await on_tool_start(["log_food"])
                        _announced.add("log_food")
                        _ft_vis.mark("first_visible")
                    except Exception:
                        pass
                # Day context so the logger's own coach line ("say") can state
                # where the day stands — real numbers we hand it, one model call.
                _dl = ""
                try:
                    _p = getattr(user, "preferences", None)
                    if today_log is not None and _p is not None:
                        _dl = (f"before this meal they were at "
                               f"{int(today_log.total_calories or 0)} of "
                               f"{int(getattr(_p, 'calorie_target', 0) or 0)} cal and "
                               f"{int(today_log.total_protein or 0)} of "
                               f"{int(getattr(_p, 'protein_target', 0) or 0)}g protein.")
                except Exception:
                    _dl = ""
                # Their REGULARS — the logger resolves "a Barebells" to THEIR
                # Barebells (exact history macros, flavor-aware ask) instead
                # of inventing an estimate (Danny 2026-07-23, strict mode).
                _regs = []
                try:
                    from db.queries import frequent_foods
                    _regs = await frequent_foods(db, user.id)
                except Exception:
                    _regs = []
                # Everything the interpreter is handed — day line, board,
                # regulars, last assistant turn — is fetched between the route
                # decision and here, and none of it was timed. It is all DB
                # work on the critical path, ahead of the turn's largest model
                # call, so a slow regulars query looked like a slow model.
                try:
                    from core import food_trace as _ft_c
                    from core.food_trace import Stage as _StageC
                    _ft_c.record(_StageC.CONTEXT,
                                 duration_ms=(_time_mod.monotonic() - _ctx_t0) * 1000.0,
                                 board=len(_board or ()), regulars=len(_regs or ()))
                except Exception:
                    pass
                # SPEAK WHILE THE INTERPRETER IS STILL WRITING. The heads-up
                # below fires after this call returns — four seconds and ~450
                # lines later — so it reassured the user about a wait they had
                # already finished. The stream handler already watches for a
                # food NAME in order to start enrichment early; the first one
                # is also the earliest moment anything in this turn KNOWS it
                # is food, which is what makes it safe to speak then.
                #
                # Deliberately not on the answer turn: a clarification answer
                # is short, already in a thread the user is watching, and a
                # "checking the macros" there reads as the question being
                # re-asked.
                async def _early_heads_up(_food_name: str) -> None:
                    nonlocal _early_heads_up_sent, _late_task
                    if _early_heads_up_sent or _sft_prior is not None:
                        return
                    # The message seeds the hash (so two foods in a row do
                    # not repeat a line); the FOOD decides whether a label is
                    # a truthful thing to mention.
                    line = tool_heads_up(FOOD_LOOKUP_HEADS_UP,
                                         _user_text or _food_name,
                                         subject=_food_name)
                    if _streamer and on_text_bubble:
                        await on_text_bubble(line)
                        _streamer.flushed_count += 1
                    elif on_interim:
                        await on_interim(line)
                    else:
                        return
                    _early_heads_up_sent = True
                    _ft_vis.mark("first_visible")

                    # SECOND-TIER heads-up (P1 felt-latency). If the turn is
                    # still running a few seconds on, add a fuller "still on it,
                    # here's what's taking the time" line — the way a good
                    # assistant narrates a long step. Self-guards on
                    # `_reply_ready`, so it no-ops the moment the reply is final
                    # and needs no cancel on run_turn's many exits. Never writes.
                    if late_heads_up_enabled() and _late_task is None:
                        async def _late_heads_up() -> None:
                            try:
                                import asyncio as _aio
                                await _aio.sleep(late_heads_up_delay_s())
                                if _reply_ready or not _early_heads_up_sent:
                                    return
                                _dline = deep_food_heads_up(
                                    _food_name, seed=_user_text or _food_name)
                                if _streamer and on_text_bubble:
                                    await on_text_bubble(_dline)
                                    _streamer.flushed_count += 1
                                elif on_interim:
                                    await on_interim(_dline)
                                else:
                                    return
                                _ft_vis.mark("late_heads_up")
                            except Exception:
                                pass
                        try:
                            import asyncio as _aio
                            _late_task = _aio.ensure_future(_late_heads_up())
                        except Exception:
                            _late_task = None

                _sft = await _sft_run(_photo_food or _user_text or "", user,
                                      prior=_sft_prior, history=messages,
                                      day_line=_dl, board=_board,
                                      last_assistant=_last_assistant,
                                      regulars=_regs,
                                      thread_active=bool(
                                          _route_mid or _photo_food),
                                      on_first_food=_early_heads_up)
                if _sft is not None and _sft.get("_writes_only"):
                    # A STASH MAY PAY ITS DEBT WITHOUT TAKING THE TURN.
                    # `_settle_deferred` recovered held food on a turn the
                    # interpreter declined — so the food is written here, and
                    # the turn goes back to the conversational brain that it
                    # actually belongs to. Without this the food composer
                    # answered a coaching question with a meal recap.
                    # THE REAL PRIOR, not a synthetic dict. It carries
                    # `log_date`, and without it the stashed-date steering in
                    # `_settle_expired_deferred` is dead on this path — a meal
                    # held overnight lands on the answer day, which is the
                    # wrong-day write the expiry path exists to prevent.
                    _wo = dict(_sft_prior or {})
                    _wo["deferred_calls"] = _sft.get("tool_calls") or []
                    _sc, _sr = await _settle_expired_deferred(
                        db, user, _wo, today_log, source_type=_source)
                    _settled_calls += _sc
                    _settled_results += _sr
                    # AND TEAR UP THE IOU. Setting `_sft = None` skips the
                    # branch that stamps `answered_at`, so the pending row kept
                    # its `deferred_calls` and EVERY later turn reloaded and
                    # re-wrote the same stash — and while an ask is open every
                    # turn is a food turn, with `_run_untraced` returning None
                    # for any non-food message. Measured: the same two foods
                    # re-committed turn after turn, eventually folding into a
                    # later meal's receipt. Dedup is the only thing in the way
                    # and its window is 90 minutes against a pending that
                    # survives ~40 hours.
                    await _clear_deferred(db, _sft_prior_pq, _sft_prior)
                    _sft = None
                    _wo_settled = True
                if _sft is None:
                    # The interpreter times out or the model fails and control
                    # transfers to legacy behaviour. Fail-safe during rollout —
                    # but a transfer nobody can see is a transfer nobody can
                    # measure, and this is the most common one.
                    #
                    # AND IT WAS NOT ONE THING. A model timeout, an unparseable
                    # response, a message with no food in it, a refused re-ask
                    # and a deliberate writes-only hand-back all logged the
                    # same line — including the writes-only case, which is a
                    # SUCCESS (held food committed) wearing the name of a
                    # failure. `none_reason` names which; the rest is the
                    # context needed to judge whether the escape was right.
                    from core.food_turn import decline_detail as _why_none
                    _to_legacy(
                        "interpreter_none",
                        none_reason=("writes_only" if _wo_settled
                                     else (_why_none() or "unrecorded")),
                        had_pending_clarification=bool(_sft_prior),
                        settled_held=len(_settled_calls) or "",
                    )
                if _sft is not None:
                    # Day snapshot BEFORE the writes — the say tokens are filled
                    # from the committed delta after enrichment runs.
                    _sft["_before"] = (
                        int(getattr(today_log, "total_calories", 0) or 0),
                        int(getattr(today_log, "total_protein", 0) or 0))
                    # CROSS-DAY CLARIFICATION FIX. When this turn is the ANSWER
                    # to a question asked on an EARLIER logging day, the stashed
                    # `log_date` is that earlier day. New-item writes must land
                    # on THAT day, not today — otherwise "which bar was it?"
                    # asked last night and answered this morning logs the food
                    # to today. update/delete target an entry_id that already
                    # belongs to the right day, so only fresh log_food calls are
                    # steered.
                    try:
                        _stashed_date = (_sft_prior or {}).get("log_date") or ""
                        _today_iso = getattr(
                            getattr(today_log, "date", None),
                            "isoformat", lambda: "")()
                        if _stashed_date and _stashed_date != _today_iso:
                            for _tc in (_sft.get("tool_calls") or []):
                                if _tc.get("name") != "log_food":
                                    continue
                                _inp = _tc.setdefault("input", {})
                                if not _inp.get("date"):
                                    _inp["date"] = _stashed_date
                    except Exception:
                        pass
                    if (_sft.get("action") in ("log", "commit") and _sft_prior
                            and _sft_prior.get("items")):
                        # Stash the confirmed items; the hold notice is
                        # appended AFTER narration renders (a held name's
                        # digits — "Fage 0%" — must not trip the say
                        # contract and vaporize the notice).
                        _sft["_held_stash"] = _sft_prior["items"]
            _b1_ask = None
            if _sft and _sft["action"] == "ask":
                # ── B-1: does the canonical quantity path own this turn? ──
                #
                # ASKED HERE, ONCE, BEFORE ANYTHING IS PERSISTED. This is the
                # only place all four inputs exist together — the staged
                # decision (from food_turn), the database (for the user's own
                # portion history), the client (can it render an ID-addressed
                # payload?) and the locale. Evaluating the predicate anywhere
                # else would mean evaluating half of it in two places.
                #
                # Everything before the write may decline freely; nothing has
                # been taken and the legacy ask below is exactly today's
                # behaviour. Once `_b1_ask` is non-None the operation EXISTS,
                # and from then on the meal completes canonically — apply,
                # repair, cancel or commit — with no later flag check.
                try:
                    if not _sft.get("b1_material"):
                        # SAY SO. Without this, "B-1 was never consulted" and
                        # "B-1 declined" are indistinguishable in the traces —
                        # the same cannot-say defect /health had, and it cost
                        # two production sessions to diagnose by hand. An ask
                        # that produced no material is a REACHABILITY fact and
                        # belongs in the decline mix like any other reason.
                        from core import b1_metrics as _b1m
                        _b1m.declined(user_id=user.id, reason="no_material")
                    if _sft.get("b1_material"):
                        from core import b1_quantity_operation as _b1
                        from core.language import command_locale
                        from core.turn_identity import current_turn_id as _tid
                        _prefs = getattr(user, "preferences", None)
                        _b1_ask = await _b1.try_take_ownership(
                            db, user=user, material=_sft["b1_material"],
                            turn_id=_tid() or "",
                            # THE CHANNEL, NOT THE MODALITY. `_source` is
                            # `source_type or platform`, and `source_type`
                            # carries text/voice/photo — so a Telegram text
                            # message arrived as "text", matched no channel,
                            # and declined `client_incapable` on the one
                            # channel B-1 was built to prove. Measured in
                            # production 2026-08-05, and it is the same
                            # modality-vs-channel conflation
                            # `feedback_arnie_platform_mislabel` already
                            # records. Capability is a property of the
                            # CLIENT, so it reads `platform`.
                            # THE CHANNEL, NOT A VERDICT ABOUT IT. The caller
                            # used to compute capability here and pass the
                            # answer in, which made lane ownership a decision
                            # with two owners — this half and the cohort half
                            # inside `try_take_ownership`. It now passes the
                            # fact and `canonical_food_enabled` decides.
                            #
                            # `platform`, never `source_type`: capability is a
                            # property of the CLIENT, and conflating the two
                            # is what `feedback_arnie_platform_mislabel`
                            # records.
                            channel=platform,
                            locale=command_locale(
                                getattr(_prefs, "preferred_language", None),
                                _user_text or ""))
                except Exception:
                    # DECLINED, NOT FAILED. Nothing was persisted — the
                    # operation is created as the last step — so the turn
                    # falls through to the legacy ask it would have used
                    # anyway. This is not the mid-flight fallback C10
                    # forbids: no ownership was ever taken.
                    logger.warning("b1 ownership attempt failed; staying "
                                   "legacy", exc_info=True)
                    _b1_ask = None

                if _b1_ask is not None:
                    # ONE question on the wire and ONE durable record. The
                    # legacy `pending_questions` stash below is skipped
                    # entirely — two pending representations for one meal is
                    # the condition the migration exists to end.
                    _sft["b1_interaction"] = _b1_ask.wire_payload()
                    _sft["questions"] = _b1_ask.legacy_questions()
                    _sft["options"] = [
                        o["label"] for o in
                        _b1_ask.wire_payload()["groups"][0]["fields"][0]["options"]]
                    # AND THE SENTENCE. This block rewrote the other three and
                    # left `text` as the interpreter composed it, so B-1 stored
                    # "How much Chicken breast?" with options 6 oz / 16 oz and
                    # production asked "How was the chicken breast cooked?".
                    # The canonical question reached the database and never the
                    # user, who then answered a question we had not asked — and
                    # the quantity parser was handed a preparation. Measured
                    # live 2026-08-06 on operations :9146 and :9151.
                    #
                    # It belongs HERE, beside the other three, because four
                    # renderings of one field in four places is how they drift;
                    # `_sft["text"]` is returned verbatim as the bubble further
                    # down, so this is the last point at which they are still
                    # one thing.
                    # NO ARGUMENT. The ask carries the capability the lane gate
                    # resolved; recomputing it here from `platform` was the
                    # second derivation that let the persisted decision and the
                    # rendered sentence disagree in production
                    # (chat_quantity:26:telegram:9241 — recorded id_addressed,
                    # shown as label text).
                    _sft["text"] = _b1_ask.ask_copy()
                    _sft.pop("b1_material", None)
                    await db.commit()
                    logger.info(
                        "event=b1_owns_turn operation=%s b1_cohort=%s user=%s",
                        _b1_ask.operation_id, _b1_ask.cohort, user.id)

            # Hold: record the pending (with the original report stashed) so
            # the ANSWER turn routes back through this pipeline and logs.
            #
            # SKIPPED ENTIRELY when B-1 owns the turn: one meal gets one
            # pending record. Writing both would put two representations of
            # one question in two stores, which is precisely the condition
            # (`payload_json` vs `pending_operations`) this migration exists
            # to end — and the answer turn would then have to pick.
            if _sft and _sft["action"] == "ask" and _b1_ask is None:
                try:
                    from db.queries import record_pending_question
                    _pq_s = await record_pending_question(
                        db, user.id, kind=ASK_KIND, question=_sft["text"][:500],
                        tier="food_clarification", hook_style="question")
                    # A follow-up ask threads the earlier exchange into the
                    # stashed original, and counts itself — the bounded
                    # re-ask policy (max 2) reads ask_count on the answer
                    # turn.
                    _orig_stash = _user_text or ""
                    if _sft_prior and _sft_prior.get("original"):
                        _orig_stash = (f"{_sft_prior['original']}\n"
                                       f"Then: {_user_text or ''}")
                    _pq_s.payload_json = json.dumps(
                        {"original": _orig_stash, "question": _sft["text"],
                         "kind": _sft.get("kind") or "clarify",
                         "ask_count": int((_sft_prior or {}).get("ask_count")
                                          or 0) + 1,
                         "items": _sft.get("items") or None,
                         # THE SHAPE WE ASKED IN TRAVELS WITH THE QUESTION.
                         #
                         # `food_turn.parse_prior_answer` dispatches on
                         # `response_schema` and returns None the moment it is
                         # absent — and this dict was the only thing standing
                         # between the ask and the answer turn. So every
                         # deterministic parser in
                         # `skills/nutrition/answer_parsers` was unreachable in
                         # production: the answer re-ran the entire interpreter,
                         # and the staged item the question was bound to was
                         # gone by the time the reply arrived.
                         #
                         # `parse_command` needs no schema, which is exactly why
                         # "skip it" has always behaved and "about a cup" has
                         # not — the half that needed this was the half that
                         # settles a field.
                         #
                         # Written defensively because only the staged-pipeline
                         # branch builds a ClarificationQuestion; the other ask
                         # return points store empties here and behave exactly
                         # as they do today.
                         "response_schema": _sft.get("response_schema") or "",
                         "question_id": _sft.get("question_id") or "",
                         "staged_item_id": _sft.get("staged_item_id") or "",
                         # THE RESOLUTION ITSELF, not a reference to it.
                         # `staged_item_id` names an object that stops existing
                         # when this turn ends; this is the object. The
                         # answering turn applies the answer to it instead of
                         # re-interpreting the message and re-pricing the food.
                         "staged_items": _sft.get("staged_items") or [],
                         # THE WRITES THE ASK IS HOLDING, as built rows.
                         # `staged_items` is the ASKED item, carried so an
                         # answer can be applied to it; this is everything the
                         # ask settled and chose not to write yet. Without it
                         # an ask that writes nothing is an ask that LOSES
                         # whatever the answer turn forgets to mention — the
                         # corn behind the turkey clarification
                         # (tests/test_leave_no_food_behind.py). food_turn's
                         # `_settle_deferred` reads it back off `prior` and
                         # commits it on whatever the answer turn decides,
                         # including a fall-through to legacy.
                         "deferred_calls": _sft.get("deferred_calls") or [],
                         "requested_fields": list(
                             _sft.get("requested_fields") or ()),
                         "options": list(_sft.get("options") or ()),
                         # The per-question structure behind the chips: the
                         # answer turn and the clarification wire both read it,
                         # so a re-ask renders the same groups the first ask did.
                         "questions": list(_sft.get("questions") or ()),
                         "meal_group_id": _sft.get("meal_group_id") or "",
                         # THE LOGGING DAY THIS QUESTION WAS ASKED ON. The
                         # answer may arrive after midnight; without this the
                         # re-logged food lands on the answer day instead of the
                         # meal's day. `today_log.date` is the user-local logical
                         # day, already timezone-correct. Read back on the answer
                         # turn to steer the write (see CROSS-DAY CLARIFICATION
                         # FIX above) and to keep the pending alive overnight
                         # (see food_ledger.pending_expired).
                         "log_date": getattr(
                             getattr(today_log, "date", None),
                             "isoformat", lambda: "")()})
                    await db.commit()
                except Exception as _e:
                    logger.warning(f"structured-ask stash failed, logging instead: {_e}")
                    _sft = await _sft_run(_user_text or "", user,
                                          prior={"original": _user_text or "",
                                                 "question": ""})
                    if _sft and _sft["action"] not in ("log", "commit"):
                        _sft = _to_legacy("ask_stash_failed")
            # The user engaged with the question — resolve the pending so it
            # can never loop.
            #
            # ONLY WHEN THIS TURN ACTUALLY CONSUMED IT (audit T-1b). This used
            # to close the pending whenever one existed, including on a turn
            # where the interpreter returned None and control fell through to
            # legacy. That is not a rare path: a reply naming the brand
            # ("Its from a brand called Legendary Foods") comes back as a
            # web_search with no log_food, so `_sft` is None — and the question
            # was closed anyway.
            #
            # The next turn then arrived COLD. No prior, no ask_count, no
            # stashed items, nothing for `parse_prior_answer` to read, and the
            # item had to be re-derived from `last_assistant`. Measured in
            # production: three turns to log one protein roll, and the
            # ask/answer contract the lane is built around never closed once.
            #
            # Leaving it open is bounded on both sides already: the re-ask
            # policy caps at 2 via ask_count, and `pending_expired` retires a
            # clarify after FOOD_ASK_TTL_MIN. Closing a question nobody answered
            # is the more expensive of the two failures — it loses the user's
            # reply AND the question.
            if _sft_prior_pq is not None and _sft is not None:
                try:
                    from datetime import datetime as _dt_s
                    _sft_prior_pq.answered_at = _dt_s.utcnow()
                    await db.commit()
                except Exception:
                    pass
            if _sft:
                # Versioned decision trace (ledger fix: version everything)
                # — greppable per turn: action, op kinds, and the contract
                # versions that produced them.
                from core.food_ledger import (INTERPRETER_VERSION,
                                              POLICY_VERSION,
                                              RENDERER_VERSION)
                logger.info(
                    f"event=structured_food action={_sft['action']} {_tag} "
                    f"items={len(_sft.get('tool_calls') or [])} "
                    f"kinds={','.join(_sft.get('kinds') or []) or '-'} "
                    f"iv={INTERPRETER_VERSION} pv={POLICY_VERSION} "
                        f"rv={RENDERER_VERSION}")
    except Exception as _e:
        logger.warning(f"structured food turn failed, legacy path: {_e}")
        _sft = _to_legacy("pipeline_exception")

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
        # THE FIRST PASS ONLY. `pick_model`'s own contract says so — "Follow-up
        # voicing always stays on the workhorse" — and `_chat_extras` is SHARED
        # with the `chat_follow_up` call below, which has no `model` parameter.
        #
        # So this did not merely upgrade the wrong call: it raised TypeError on
        # every follow-up, and the user got the recovery line ("Couldn't pull a
        # clean read on that just now") instead of their answer. Only for users
        # inside NEW_USER_WINDOW_DAYS, which is to say the exact cohort the
        # staged model exists to impress, on any turn whose first pass emitted
        # tool calls and no text — which is most logging turns.
        _pass_extras = dict(_chat_extras)
        if _stage_model:
            _pass_extras["model"] = _stage_model
        # SCRIBE — launch deterministic item extraction IN PARALLEL with pass-1 (Haiku
        # finishes before opus → no added latency). Only for multi-item food messages;
        # consulted after pass-1 to name a dropped item precisely (egg whites, etc.).
        # NEVER on a structured food turn — the structured logger is authoritative
        # there, and the scribe reconciling against the COMBINED gate message re-logged
        # a prior turn's salad as a third item (Danny 2026-07-23, "wth is #3").
        _scribe_task = None
        if _sft is None:
            try:
                import asyncio as _asyncio
                from core.scribe import scribe_enabled, should_run_scribe, extract_food_items
                if scribe_enabled() and should_run_scribe(_gate_user_message):
                    _scribe_task = _asyncio.create_task(
                        extract_food_items(_gate_user_message))
            except Exception:
                _scribe_task = None
        if _sft is not None and _sft["action"] in ("log", "update", "delete",
                                                   "commit"):
            # Structured interpreter already decided the writes (an ordered
            # plan of new items, board corrections and removals) — the plan
            # executes as source=structured_food tool calls through the
            # existing executor, and the big model is skipped entirely.
            # EXACTLY-ONCE guard (ledger fix #6/#16): the same (user, message,
            # plan) landing again within the idempotency window is a duplicate
            # delivery (client retry, double webhook, cross-device race) —
            # answer honestly, write nothing twice.
            _idem_dup = False
            try:
                from core.food_ledger import (turn_idempotency_key as _ik_fn,
                                              already_processed as _ik_seen,
                                              mark_processed as _ik_mark)
                # The canonical turn_id (client message identity) is the
                # strongest dedup key — a transport retry preserves it
                # byte-for-byte. Semantic fingerprint is the fallback for
                # turns that arrived without one (P0.1).
                _ikey = turn_id or _ik_fn(user.id, _user_text or "",
                                          _sft["tool_calls"])
                if _ik_seen(_ikey):
                    _idem_dup = True
                    logger.info(f"event=structured_food_duplicate layer=memory {_tag}")
                else:
                    # Durable claim (FOOD_LEDGER_V2 Phase 2): survives restarts
                    # and cross-device races via the processed_turns unique key.
                    # Fail OPEN — a claim-infra hiccup must never block a real
                    # meal; the in-process registry above still covers retries.
                    try:
                        from db.queries import claim_processed_turn
                        _names_ik = ", ".join(
                            (tc.get("input") or {}).get("food_name") or
                            str((tc.get("input") or {}).get("entry_id") or "")
                            for tc in _sft["tool_calls"])[:200]
                        if not await claim_processed_turn(
                                db, user.id, _ikey, result_summary=_names_ik):
                            _idem_dup = True
                            logger.info(
                                f"event=structured_food_duplicate layer=durable {_tag}")
                    except Exception:
                        pass
                    if not _idem_dup:
                        _ik_mark(_ikey)
            except Exception:
                _idem_dup = False
            if _idem_dup:
                _turn_route = "duplicate"
                result = {"text": ("Already got that one - it's on the board "
                                   "from a moment ago."),
                          "raw_content": [], "tool_calls": [],
                          "stop_reason": "structured_food"}
                _sft = None
            else:
                if _turn_route == "legacy":
                    _turn_route = f"structured_{_sft['action']}"
                result = {"text": "", "raw_content": [],
                          "tool_calls": _sft["tool_calls"],
                          "stop_reason": "structured_food"}
                # NO TRANSACTION NARRATION (Danny 2026-07-25). This used to
                # emit "Give me a moment. Logging all 2 now." as a real chat
                # bubble before the write — which is the same pre-action
                # narration the system prompt bans the MODEL from producing and
                # turn_health flags as a stall marker. Emitting it
                # deterministically bypassed both guards and made the flow read
                # as several systems taking turns.
                #
                # Enrichment is still a network round-trip, so the wait is
                # real. It is covered by on_tool_start below (line ~1182),
                # which the transports already use to drive the typing
                # indicator — and which disappears when the card lands, instead
                # of leaving a permanent bubble describing a wait that is over.
        elif _sft is not None and _sft["action"] == "ask":
            # THE QUESTION IS THE REPLY — but the foods it is NOT asking about
            # still get logged. This said "no tools, nothing logged" and
            # hardcoded an empty list, which is why moderate's PARTIAL_COMMIT
            # never partially committed: `decide()` separates ready from held,
            # `_apply_clarification_veto` drops the held items' calls and keeps
            # the rest, and then every survivor was discarded here. Moderate
            # behaved exactly like strict, holding an entire meal for its least
            # certain item.
            #
            # Only the cleared calls arrive — food_turn ran the same veto the
            # commit path runs — so a held food still cannot be written behind
            # an unanswered question.
            _turn_route = "structured_ask"
            # RELEASED. The hold was for one reason: the answer turn
            # re-interpreted the whole meal and logged it a second time,
            # because `food_dedup` matches on the normalized name and "Egg" on
            # the ask is not "Eggs" on the answer. That is fixed upstream — the
            # board now carries how long ago each row landed, and a message
            # refining something written moments ago is an UPDATE to that
            # entry_id rather than a new food. Measured on a four-food meal:
            # the follow-up produced 4 updates and 0 new rows, where it
            # previously produced 4 duplicates.
            #
            # Only cleared calls arrive — food_turn ran the same veto the
            # commit path runs — so a HELD food still cannot be written behind
            # an unanswered question.
            result = {"text": _sft["text"], "raw_content": [],
                      "tool_calls": _sft.get("tool_calls") or [],
                      # THE CANONICAL INTERACTION, carried to the wire. Built
                      # and persisted since B-1; it had no channel to a client
                      # until now, so `POST /chat/answer` demanded ids nothing
                      # could tell anyone.
                      "b1_interaction": _sft.get("b1_interaction"),
                      "stop_reason": "structured_food"}
        else:
            # Under the turn budget. Setting the deadline contextvar bounds
            # nothing on its own — only calls that consult it are bounded, and
            # this is the largest blocking call a non-food turn makes. Without
            # it, a food interpreter pass that exhausted the budget still handed
            # this call a fresh full model timeout, so the degraded-source case
            # the budget exists for could still cost interpreter + composer back
            # to back.
            #
            # THE OBLIGATIONS — AND THE TURN'S STATE FACTS — RIDE WITH THE
            # MESSAGE, not only in the system prompt. The tool-calling rule
            # already lives there and still drops deep in session
            # (bench_deep_session: narrated logs with no tool call) — while
            # the user typing "make sure you call the tool" reliably works.
            # Placement, not wording: text adjacent to the turn being answered
            # does not decay with depth. Request-side only; the stored
            # conversation keeps what the user actually said.
            #
            # Every block is a pure function of state the turn already loaded
            # — the open pending, the board's recent rows, the message's
            # script, the user's clock and units. No classifier decides
            # whether a turn "needs" one; a block is present exactly when its
            # state exists.
            from core.turn_obligations import (last_action_block,
                                               open_question_block,
                                               reply_language_block,
                                               time_block, units_block,
                                               with_turn_obligations)
            _blocks = []
            try:
                _blocks = [open_question_block(_sft_prior),
                           last_action_block(_board),
                           reply_language_block(_user_text or ""),
                           time_block(user), units_block(user)]
            except Exception as _tb_e:
                logger.warning(f"turn context blocks unavailable: {_tb_e}")
                _blocks = []
            result = await deadline.wait_for(
                chat(with_turn_obligations(messages, _blocks), system,
                     tools=True, max_tokens=4096, **_pass_extras))
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
            result = await deadline.wait_for(
                chat(retry_messages, system, tools=True, max_tokens=8192,
                     **_pass_extras))
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
        _reply_ready = True  # turn is ending — mute any pending second heads-up
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
        # ── A SLOW LOG EARNS ONE TOO ─────────────────────────────────────────
        #
        # "log-only turns NEVER trigger it" was written when a log WAS fast: the
        # model picked the tool and the row landed. The structured lane put an
        # interpreter pass, a shelf lookup and a composer in front of that, and
        # production food turns now run 9-15 s while the slower-sounding lanes
        # ("looking it up.") say something at one second. The rule outlived the
        # shape it described.
        #
        # Gated on ELAPSED TIME, not on a guess about which foods are slow. By
        # this line the interpreter has already returned, so the wait is a
        # measured fact rather than a prediction — and a turn that got here
        # quickly stays silent, which is what keeps this from becoming the stall
        # marker that pre-action narration was removed for. If the interpreter
        # gets faster, this stops firing on its own.
        #
        # `search_food_database`'s pool is the right wording already: "pulling
        # the macros.", "checking the macros." It describes a LOOKUP. Nothing
        # here claims a write is underway — that is the line
        # `NO TRANSACTION NARRATION` draws, and it still holds.
        if needs_heads_up_tc is None and not _early_heads_up_sent \
                and _sft is not None \
                and _sft.get("action") in ("log", "commit", "update") \
                and any(tc.get("name") in _FOOD_LOG_TOOLS for tc in tool_calls) \
                and (_time_mod.monotonic() - _turn_t0) >= _FOOD_HEADS_UP_AFTER_S:
            # Its OWN pool, not `search_food_database`'s. That one is an
            # emergency string — flat on purpose, because on every other lane
            # the model has already written the heads-up in its own voice and
            # the deterministic line is the rare degenerate case. The food lane
            # has no model first pass at all (`result["text"]` is ""), so this
            # line is not a fallback here, it is what the user always sees.
            needs_heads_up_tc = {"name": FOOD_LOOKUP_HEADS_UP,
                                 "input": {"query": _user_text or "",
                                           "subject": _food_heads_up_subject(
                                               tool_calls)}}
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
                        subject=(needs_heads_up_tc.get("input") or {}).get("subject"),
                    )
                    try:
                        await on_text_bubble(fallback)
                        _ft_vis.mark("first_visible")
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
                        subject=(needs_heads_up_tc.get("input") or {}).get("subject"),
                    )
                )
                _interim = _sanitize_bubble(_interim_raw)
                if headsup_voice_enabled():
                    _interim = sentence_case(_interim)   # 'checking…' → 'Checking…'
                try:
                    await on_interim(_interim)
                    _ft_vis.mark("first_visible")
                except Exception as e:
                    logger.error(f"interim heads-up failed for {_tag}: {e}")

        # Heads-up to streaming surfaces (iOS): the live thinking indicator
        # morphs from "Thinking…" to the action being taken ("Logging…",
        # "Reviewing your week…") the moment tools dispatch. Fired once, in
        # call order; the client maps names→labels and ignores internal tools.
        # Purely additive — failure here never blocks the turn.
        # ONE ANNOUNCEMENT PER NAME PER TURN. The structured food branch fires
        # "log_food" early so the interpreter's pass isn't silent dead air, and
        # this site then fired it again for the same dispatch — the client reads
        # each call as a fresh action, so the live indicator restarted and the
        # turn looked like two backend operations. `_announced` is the turn's
        # record of what the user has already been told; a name in it is not
        # re-sent, and a batch with nothing new sends nothing at all.
        if on_tool_start:
            _started: list = []
            for _tc in tool_calls:
                _n = _tc.get("name")
                if _n and _n not in _started and _n not in _announced:
                    _started.append(_n)
            if _started:
                _announced.update(_started)
                try:
                    await on_tool_start(_started)
                except Exception as e:
                    logger.error(f"on_tool_start failed for {_tag}: {e}")

        # (Ask-before-log lives in the STRUCTURED FOOD TURN above — one system.
        # The old model-side ASK_FIRST_HOLD/clarify_swings hold was ripped
        # 2026-07-23: two ask brains collided and its guards piled up.)

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
        # Typed execution view (P0.3a): the executor publishes it; the scraper
        # fallback covers mocked executors. Downstream (narration filters,
        # cards) consumes THIS — never inp["_..."] keys directly.
        from core.execution_result import (LAST_EXECUTION as _LX,
                                           without_execution_state as _exec_bare)
        # The real executor publishes the native view; a mocked/stubbed one
        # leaves nothing, so we report the batch honestly with no invented ids.
        _execution = _LX.get() or _exec_bare(tool_calls, tool_results)

        # ── COMMIT ACCOUNTING (review fix, PR #29) ───────────────────────────
        # The executor is the only witness to what was actually written. The
        # clarifier's `ready` count is an approval, and reporting it as
        # `committed` meant a turn whose every write was blocked still showed a
        # full commit rate in the funnel — the one number the rollout gates on.
        #
        # Only recorded when the writes came from the food lane — the same
        # condition the render block below uses. A legacy-lane turn has no food
        # funnel to report and must not manufacture one. Keyed off `_sft` rather
        # than off "the trace has stages", because the planner can fall back to
        # the legacy policy and still execute food writes: that turn HAS a
        # commit funnel and skipping it would leave the writes unaccounted.
        try:
            from core import food_trace as _ft
            from core.food_trace import Outcome as _FtOutcome, Stage as _FtStage
            if _sft is not None and _sft.get("action") in ("log", "update",
                                                           "delete", "commit"):
                _food_calls = tuple(
                    c for c in (getattr(_execution, "calls", ()) or ())
                    if getattr(c, "name", "") in ("log_food",
                                                  "restore_food_entry"))
                _committed = tuple(c for c in _food_calls if c.committed)
                # `written` AND `committed` TOGETHER, because on this lane they
                # genuinely are the same event: the legacy helpers commit
                # independently, so a row that exists is a row that is durable.
                # Stating both keeps the funnel's shape identical across lanes —
                # the canonical lane has to separate them, and a reader
                # comparing the two must not find the term simply missing here.
                _ft.note(items_attempted=len(_food_calls),
                         items_written=len(_committed),
                         items_committed=len(_committed),
                         items_failed=len(_food_calls) - len(_committed))
                _ft.record(
                    _FtStage.EXECUTE,
                    outcome=(_FtOutcome.OK if _committed
                             else (_FtOutcome.HELD if _food_calls
                                   else _FtOutcome.SKIPPED)),
                    attempted=len(_food_calls), committed=len(_committed),
                    failed=len(_food_calls) - len(_committed))
        except Exception:
            pass

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
        # A QUESTION IS NOT A PREMATURE CONFIRMATION. `discard_held` exists to
        # bin pass-1 text that claims a write before the write happened — but
        # it keys on "a logging tool fired", and on an ASK turn that also wrote
        # the held bubble is the system's own QUESTION. Dropping it is how a
        # partial commit lost its question twice over (be65fb6, 2026-07-27).
        # The write is held now, so this is belt-and-braces; it stays because
        # FOOD_PARTIAL_COMMIT=true can put the writes back, and this guard is
        # what makes that switch safe to flip.
        if _fired_logging and not (_sft is not None
                                   and _sft.get("action") == "ask"):
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
        _all_blocked = None
        if has_logging:
            _all_blocked = blocked_log_reply(tool_calls, tool_results,
                                             user_message=_user_text or "")
            if _all_blocked is None and blocked_log_reply(
                    tool_calls, tool_results) is not None:
                # EVERY log deduped, and the user asked for none of it. The
                # model has the whole thread in context, so a contentless
                # follow-on ("Look it", right after a logged meal) re-proposes
                # that meal; the dedup then blocks it. Nothing was written and
                # nothing was requested, so there is no news — the receipt
                # ("That's already on the board: Mustard, 3 cal") answers a
                # question nobody asked, and the log-voice branch below would
                # narrate a write that never happened.
                #
                # Dropping the turn's logging framing sends it down the
                # ordinary reply path instead, which is what a message that
                # was never a log request should have got in the first place.
                has_logging = False
        if _all_blocked is not None and not in_onboarding:
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
            if _sft is not None and _sft.get("action") == "ask":
                # THE QUESTION IS THE REPLY (audit I-1).
                #
                # Since the partial-commit release an ask CARRIES the ready
                # items' log_food calls, so `has_logging` is True and this whole
                # narration chain runs on a turn whose reply was already
                # decided. `"ask"` is absent from the structured branch below,
                # `_is_pure_food_log` is True for a clean log_food batch, and
                # the `elif _pure_food` arm then replaced the clarification with
                # a deterministic log confirmation.
                #
                # What the user saw was "✓ Logged …" on a turn that had asked
                # them a question — and because the pending was recorded
                # regardless, their next message was parsed as the answer to a
                # question they were never shown. On a mixed meal, which is
                # precisely the case partial commit exists for.
                #
                # There is nothing to narrate. The writes are real and already
                # executed, and the ask text names both what landed and what is
                # being held. Anything this chain produces is a second opinion
                # about a turn that already has one.
                #
                # Marked unstreamed for the same reason the structured commit
                # branch below does: the text came from the interpreter's
                # result, not from a model stream, so the catch-up send is what
                # actually delivers it.
                _response_streamed = False
            elif _sft is not None and _sft.get("action") in ("log", "update",
                                                             "delete", "commit"):
                # STRUCTURED turn: narration comes from ONE committed snapshot
                # (ledger fix #5), built over the calls the executor actually
                # COMMITTED — a refused CAS update or blocked write is named,
                # never narrated as success. The interpreter's words are kept
                # only when they carry no unbacked numeric OR semantic claims;
                # otherwise the deterministic render takes over. Numeric
                # contract first: model-authored digits outside {tokens} →
                # tokenized replacement (647-vs-343, IMG_8610).
                from core.food_turn import enforce_say_contract
                from core.food_ledger import compute_batch as _fl_batch
                # Committed-vs-refused now reads from the typed execution view
                # (P0.3a) — on structured turns the executed batch IS the plan.
                _ok_calls = _execution.ok_tool_calls()
                _failed_names = _execution.failed_names()
                try:
                    await db.refresh(today_log)
                except Exception:
                    pass
                _ac = int(getattr(today_log, "total_calories", 0) or 0)
                _ap = int(getattr(today_log, "total_protein", 0) or 0)
                _bc0, _bp0 = _sft.get("_before", (_ac, _ap))
                _p = getattr(user, "preferences", None)
                _ct = int(getattr(_p, "calorie_target", 0) or 0) if _p else 0
                _pt = int(getattr(_p, "protein_target", 0) or 0) if _p else 0
                if not _ok_calls:
                    # Every write refused (stale board, missing entry): honest
                    # reset beats a fabricated confirmation.
                    #
                    # Through the renderer like every other moment. This was
                    # the one reply in the structured lane still hardcoded at
                    # its detection site — so the turn where Arnie has to
                    # admit something went wrong was the only turn that could
                    # not adapt its wording to the person or the situation,
                    # and it read like an error string because it was one.
                    #
                    # `approved_message` IS the sentence below, so with the
                    # composer off this renders byte-identically to before.
                    # `user_fixable` is the fact that matters: the board moved
                    # under us, they can just say it again — this is not an
                    # outage, and the brief forbids blaming them for it.
                    try:
                        from core.food_response import (FailureIntent,
                                                        plan_failure)
                        from core.food_response import render_plan as _render
                        from core.food_response import with_context as _ctx
                        response_text = await _render(_ctx(plan_failure(
                            FailureIntent(
                                code="board_changed",
                                user_fixable=True,
                                recovery_action=("ask them to say it again so "
                                                 "it can be applied"),
                                approved_message=(
                                    "Hold on - the board changed since I "
                                    "looked, so I didn't apply that. Tell me "
                                    "again and I'll set it straight.")),
                            user_message=_user_text or ""),
                            user=user, messages=messages))
                    except Exception:
                        response_text = ("Hold on - the board changed since I "
                                         "looked, so I didn't apply that. Tell "
                                         "me again and I'll set it straight.")
                else:
                    # {batch_*} per plan kind over the COMMITTED calls: pure
                    # log → post-enrichment day delta; update/delete → the
                    # entry's new value (a +95 bump narrated as "logged, 95
                    # cal" reads like a phantom food — truffle fries,
                    # 2026-07-23); mixed → the logged items' own numbers.
                    _batch_c, _batch_p = _fl_batch(
                        _sft.get("action"), _ok_calls, _ac - _bc0, _ap - _bp0)
                    _say = enforce_say_contract(
                        (_sft.get("say") or "").strip(), _ok_calls)
                    # ── THE RESPONSE CONTRACT AUTHORS THE CONFIRMATION ─────
                    #
                    # This used to be two steps with a seam between them:
                    # `render_committed()` wrote the whole reply, then
                    # `strip_card_recitation()` took back the parts the card
                    # was already showing. Old copy generated first and
                    # imperfectly stripped second, with the plan — which knows
                    # exactly which facts the card shows — having no say in
                    # what got written.
                    #
                    # One call now. The plan carries the committed snapshot,
                    # the interpreter's say, the note, the follow-up and the
                    # failure notice, and `core.food_response` does the
                    # authoring with the card facts already in hand. The words
                    # are unchanged; what changed is who wrote them.
                    _failure_notice = ""
                    if _failed_names:
                        from core.food_ledger import build_failure_notice
                        # Log the RESULT TEXT, not just the name. The Barebells
                        # drop was undiagnosable after the fact — "it got
                        # dropped for some reason" — because the only record of
                        # why was a notice that named a cause it had guessed.
                        for _c in _execution.calls:
                            if not _c.committed:
                                logger.warning(
                                    f"event=food_call_blocked tool={_c.name} "
                                    f"status={_c.status} "
                                    f"result={(_c.result_text or '')[:200]!r}")
                        _failure_notice = build_failure_notice(
                            _execution.failures())
                    try:
                        from core.food_ledger import build_snapshot
                        from core.food_response import (CARD_FACTS,
                                                        FoodItemSummary,
                                                        FoodResponseIntent,
                                                        FoodResponsePlan,
                                                        apply_policy, fallback)
                        _snap = build_snapshot(_ok_calls, _batch_c, _batch_p,
                                               _ac, _ap, _ct, _pt)
                        # ONE DAY, ONE SOURCE — for the sentence AND the card.
                        #
                        # The card's remaining figures come from the RECEIPT
                        # (`core/receipt.py`, stashed at write time); the
                        # narration's come from this snapshot. Two reads of the
                        # same day, taken at different moments from different
                        # objects, and they drift: a shipped turn showed a card
                        # reading "1,245 cal left · 102g protein to go" with
                        # the sentence directly beneath it saying "710 for the
                        # day, 133g protein to go" — 210 calories and 31g of
                        # protein apart, inside one bubble.
                        #
                        # `_resync_batch_receipts` already fixed the sibling
                        # case, where card 1 was computed against a day holding
                        # only item 1. It reconciles the cards to each OTHER
                        # and had nothing to say about the prose, because the
                        # prose is authored from an object it never sees.
                        #
                        # FOOD_LEDGER_V2 lists the real repair under Remaining
                        # in Phase 2 — "card + narration from the same
                        # snapshot". Until the card render path takes the
                        # snapshot itself, this is the same guarantee reached
                        # the way the batch resync already reaches it: rewrite
                        # the receipts the cards are built from, from the
                        # committed snapshot, so both sides read one number.
                        #
                        # Deliberately only the DAY figures. The item's own
                        # macros are its own and must keep coming from what was
                        # committed for that row.
                        #
                        # THIS LOOP WAS DEAD (found 2026-08-03 by
                        # tests/test_a_full_day_of_food.py::check_i6). It wrote
                        # to `inp["_receipt"]`, and `execution_result.stash`
                        # stopped writing execution state onto the command at
                        # P0.3e — "The command input is NEVER written". The
                        # card reads `call.receipt` FIRST and only falls back to
                        # `inp["_receipt"]` (see `_logged_entry_card`), so the
                        # one thing this could reach was the branch that no
                        # longer runs. `ok_tool_calls()` also rebuilds its dicts
                        # on every call, so even the fallback was a copy.
                        #
                        # Reconcile the receipt the card ACTUALLY reads.
                        # `CallResult` is frozen, but `receipt` is a dict and is
                        # the same object the card renders from.
                        try:
                            for _cr in (_execution.successful
                                        if _execution is not None else ()):
                                if isinstance(_cr.receipt, dict):
                                    # SIGNED — the card's own field always was,
                                    # and every consumer keys on the sign.
                                    _cr.receipt["remaining_cal"] = \
                                        _snap.cal_remaining
                                    _cr.receipt["remaining_protein"] = \
                                        _snap.protein_remaining
                        except Exception:
                            pass    # a card with a stale number beats no card
                        # The committed item NAMES travel with the plan, and
                        # they are now what the SENTENCE is built from: the
                        # card strip takes every figure, so without these the
                        # deterministic floor for a logged meal is the empty
                        # string (`food_response._subject_line`). An empty
                        # plan here is a card with nothing said over it.
                        #
                        # EACH NAME CARRIES WHAT HAPPENED TO IT. The plan has
                        # one `intent` for the whole turn, and a turn that
                        # corrects one row and creates another has no single
                        # verb — so every name took COMMIT's, and a correction
                        # was announced as a fresh log. An update names itself
                        # by `food_hint` when the correction changed an amount
                        # rather than an identity (the same "new name, else the
                        # name it had" resolution `_logged_entry_card` uses);
                        # without that fallback the corrected row contributes an
                        # empty name and the sentence cannot mention it at all.
                        _names = []
                        for c in (_ok_calls or []):
                            _cin = c.get("input") or {}
                            _upd = c.get("name") == "update_food_entry"
                            _nm = str(_cin.get("food_name") or "").strip()
                            if _upd and not _nm:
                                _nm = str(_cin.get("food_hint") or "").strip()
                            _names.append(FoodItemSummary(name=_nm,
                                                          corrected=_upd))
                        _names = tuple(_names)
                        # WHETHER A CARD RENDERS IS A PROPERTY OF THE TURN, NOT
                        # OF THE TRANSPORT. This read `on_card is not None`,
                        # which is a question about the CALLER: only the iOS
                        # WebSocket path (`_stream_turn`) supplies that
                        # callback. Photo, voice and HTTP-fallback text all go
                        # through `_coached_reply`, pass no callback, and then
                        # return the very same cards in the payload — so the
                        # plan was authored believing no card would render,
                        # the recitation strip stayed off, and prose recited
                        # the calories printed on the card directly above it.
                        # Photo logging is the heaviest card path there is.
                        #
                        # Ask the card builder itself instead of restating its
                        # rule: `_logged_entry_card` is pure and side-effect
                        # free by contract, and it is the SAME call that emits
                        # the cards further down — so this cannot drift from
                        # what actually renders the way a duplicated
                        # "has an entry_id" test would.
                        # SUPPRESSION IS ABOUT THE LOG CARD. This asks "may
                        # the sentence skip what the card already says", and a
                        # correction's receipt is supplementary: the sentence
                        # naming what changed IS the confirmation that it took.
                        # Counting update cards here made "Bumped the birria to
                        # 2 tacos" read as recitation, so it was stripped and
                        # the reply fell back to "Fixed." — the one word that
                        # does not say what was fixed.
                        #
                        # Read off the emitted TYPE, not off the tool name. The
                        # rule is "did a card render in this turn", and since a
                        # correction became a `macro_card_patch` — applied to a
                        # card belonging to an EARLIER turn — the card builder
                        # answers that question directly. Naming the tool here
                        # restated a rule that now lives one layer down, which
                        # is how the two drift apart.
                        _card_renders = any(
                            (_logged_entry_card(c.name, c.raw_input, call=c)
                             or {}).get("type") in _RENDERS_A_CARD
                            for c in (_execution.successful
                                      if _execution is not None else ()))
                        # NAME THE MOMENT. Every structured turn declared
                        # itself a COMMIT — a correction, a deletion and an
                        # undo all announced themselves as a fresh log, which
                        # is why "actually only one taco" came back sounding
                        # like a second taco had just been logged. The intent
                        # is what tells the composer which moment this is:
                        # `_INTENT_BRIEF` already says "one natural
                        # acknowledgement of what changed" for CORRECT and
                        # "state briefly what was reversed" for UNDO, and
                        # nothing ever selected them.
                        #
                        # Deliberately derived from what the turn DID —
                        # the executed action and the route — never from a
                        # model field, so it cannot disagree with the writes.
                        # A mixed plan stays COMMIT: its label is already
                        # "commit" precisely because no single verb fits.
                        _act = (_sft.get("action") or "").strip()
                        if _turn_route == "ledger_undo" or _act == "delete":
                            _intent = FoodResponseIntent.UNDO
                        elif _act == "update":
                            _intent = FoodResponseIntent.CORRECT
                        else:
                            _intent = FoodResponseIntent.COMMIT
                        # WHAT WE CHOSE INSTEAD OF ASKING. The consequence
                        # engine can decline a question as too small to be
                        # worth interrupting for — that judges the INTERRUPTION,
                        # not the doubt, and the turn still picked a portion or
                        # a preparation. It travels to the card as a correctable
                        # chip and to the sentence here, because a surface with
                        # no cards (Telegram, iMessage) would otherwise show a
                        # number with no sign that anything was guessed.
                        #
                        # Scales with mode for free: strict asks where quick
                        # assumes, so strict arrives here with little to say and
                        # quick with the most. No separate per-mode copy.
                        # NAMED, because an unattributed list gets misattributed.
                        # Passing bare texts made the composer guess which food
                        # each belonged to, and it shipped "Salty Peanut
                        # Fairlife" — one item's flavour on another item's
                        # shake. The pairing is not the composer's to infer.
                        _assumed = []
                        for _c in (_ok_calls or []):
                            _ci = _c.get("input") or {}
                            _cn = str(_ci.get("food_name") or "").strip()
                            for _a in (_ci.get("assumptions") or []):
                                if not isinstance(_a, dict):
                                    continue
                                _at = str(_a.get("text") or "").strip()
                                if _at:
                                    _assumed.append(f"{_cn}: {_at}" if _cn
                                                    else _at)
                        _assumed = tuple(dict.fromkeys(_assumed))
                        # WHERE EACH NUMBER CAME FROM. `_stash_sourcing` built
                        # this for the receipt and stashed it on the call —
                        # roughly fifty lines above here — and the plan had no
                        # field for it, so the receipt knew the whole story and
                        # the sentence knew only the total.
                        _sourcing = []
                        for _c in (_ok_calls or []):
                            _ci = _c.get("input") or {}
                            _src = _ci.get("_sourcing")
                            if not isinstance(_src, dict):
                                continue
                            _detail = str(_src.get("detail") or "").strip()
                            if not _detail:
                                continue
                            _sourcing.append({
                                "name": str(_ci.get("food_name") or "").strip(),
                                "detail": _detail,
                                "confidence": str(_src.get("confidence") or "")})
                        # BEFORE -> AFTER, from the calls themselves.
                        # `food_hint` is the row's name as it stood; the input
                        # is what it becomes. Without this the composer is told
                        # to name the change and has only the result to look at.
                        _changed, _unpriced = [], []
                        # Execution state lives on the typed call, keyed by the
                        # identity of the command it ran — the same join
                        # `build_reasoning` uses.
                        _typed_by_input = {}
                        try:
                            for _tcall in (_execution.calls
                                           if _execution is not None else ()):
                                _typed_by_input[id(_tcall.raw_input)] = _tcall
                        except Exception:
                            _typed_by_input = {}
                        for _c in (_ok_calls or []):
                            if _c.get("name") != "update_food_entry":
                                continue
                            _ci = _c.get("input") or {}
                            _was = str(_ci.get("food_hint") or "").strip()
                            _now = str(_ci.get("food_name") or "").strip()
                            _qty = str(_ci.get("quantity") or "").strip()
                            if _now and _was and _now.lower() != _was.lower():
                                _changed.append(f"{_was} is now {_now}")
                            elif _qty:
                                _changed.append(
                                    f"{_was or _now} is now {_qty}")
                            # THE CORRECTION THAT COULD NOT BE PRICED.
                            #
                            # The executor already knows: it renamed the row,
                            # found nothing that could cost the new identity,
                            # declined to write a zero, and stashed
                            # `correction_unpriced` with the note that this is
                            # "a FAILURE to disclose, not a silent no-op". It
                            # was read by nothing, so the disclosure never
                            # happened — the reply said "Fixed it to a double
                            # cheeseburger" over the single cheeseburger's 324
                            # cal, and the user had to notice ("the calories
                            # haven't updated tho") and supply 450 themselves.
                            #
                            # IT WAS READ FROM THE WRONG SIDE OF THE SEAM.
                            #
                            # `_stash_call` writes to the ambient CALL_CTX and
                            # documents that "the command input is NEVER
                            # written" (executor immutability, P0.3e).
                            # `ok_tool_calls()` returns `{name, input:
                            # raw_input}` — the command, without any of that
                            # context. So this read `_ci.get(...)` off the raw
                            # input, where nothing ever put it, and the list
                            # stayed empty on every turn: the disclosure has
                            # never once fired in production.
                            #
                            # Its test asserts that the executor's SOURCE TEXT
                            # contains the string "correction_unpriced" — which
                            # it does — so a source-level grep stood in for the
                            # behaviour and the gap survived.
                            #
                            # The outcome now rides the typed call, which is
                            # the side of the seam that carries execution state.
                            #
                            # PRICED WRONG COUNTS TOO. `correction_unpriced`
                            # fires only when the ladder returned nothing. A
                            # re-resolution returning the SAME number passes
                            # that test and is indistinguishable to the person
                            # reading the reply: they said it was different and
                            # the figure did not move. Production, 2026-07-29:
                            # "Yea they were deep fried" re-resolved "Shrimp,
                            # deep fried, 7 small" — which searches as shrimp —
                            # and came back at the same 35 cal. The reply said
                            # "that's a real jump from a light sauté" over an
                            # unchanged row, and the user had to ask "How does
                            # it change the total then?", a question which then
                            # performed the write.
                            _tc = _typed_by_input.get(id(_ci))
                            _co = getattr(_tc, "correction", None) if _tc else None
                            if isinstance(_co, dict) and _co.get("renamed") \
                                    and not _co.get("moved_numbers"):
                                if _now or _was:
                                    _unpriced.append(_now or _was)
                        _plan = apply_policy(FoodResponsePlan(
                            intent=_intent,
                            corrections=tuple(_changed),
                            unpriced_corrections=tuple(_unpriced),
                            committed_items=tuple(n for n in _names if n.name),
                            committed_snapshot=_snap,
                            assumptions=_assumed,
                            sourcing=tuple(_sourcing),
                            model_say=_say,
                            note=_sft.get("note") or "",
                            follow_up=_sft.get("follow_up") or "",
                            failure_notice=_failure_notice,
                            card_will_render=_card_renders,
                            # WHAT ELSE THEY SAID, as an obligation. The
                            # interpreter reports it on the same pass that read
                            # the food, so a mixed turn costs no extra call —
                            # and without this the plan modelled only the half
                            # it could compute, which made silence the
                            # compliant answer to "I think I'm going to quit".
                            conversational_context=_conversational_context(
                                _sft.get("context")),
                            facts_visible_in_card=(CARD_FACTS if _card_renders
                                                   else frozenset())))
                        # THE COMPOSER, FINALLY CONNECTED. `compose_async` was
                        # built, validated, tested and called from nowhere —
                        # `composer_enabled()` had no reference outside its own
                        # definition and the test that asserts the env var
                        # parses. Setting FOOD_COMPOSER=true did nothing at all.
                        #
                        # It phrases an APPROVED plan: it cannot choose what to
                        # say, only how. Every output goes through the same
                        # `validate()` the fallback satisfies, twice, and any
                        # failure returns the deterministic text — so the worst
                        # case is exactly today's behaviour plus one Haiku call.
                        from core.food_response import (composer_enabled,
                                                        compose_async)
                        from core.food_response import with_context as _ctx
                        # The snapshot already carries the day; this adds the
                        # PERSON — goal and logging mode — so the same meal
                        # reads differently to someone cutting on strict than
                        # to someone maintaining on quick. Same helper the ask
                        # path uses, so both moments reason from one contract.
                        _plan = _ctx(_plan, user=user,
                                     messages=messages)
                        if composer_enabled():
                            _txt, _why = await compose_async(_plan)
                            response_text = _txt
                            if _why != "ok":
                                logger.info(
                                    "event=food_composer outcome=fallback "
                                    "reason=%s", _why)
                        else:
                            response_text = fallback(_plan)
                    except Exception as _e:
                        # The renderer must never cost the user their reply —
                        # fall back to the token-filled say (same numbers).
                        logger.warning(f"commit render fallback: {_e}")
                        from core.food_turn import fill_say_tokens
                        response_text = fill_say_tokens(
                            _say, _batch_c, _batch_p, _ac, _ap, _ct, _pt)
                        if _failure_notice:
                            response_text = f"{response_text}|||{_failure_notice}"
                # WHEN THE COMMITTED TRUTH GOT WORDS. Marked here rather than
                # at the write, because a row in the database the user cannot
                # see has not been delivered — and the gap between this and
                # `first_visible` is the whole case for showing the card
                # before the sentence. With the early card still disabled this
                # lands within a few ms of `complete_ms`, and that equality IS
                # the finding rather than a measurement bug.
                #
                # ONLY IF SOMETHING COMMITTED. A turn whose every write was
                # BLOCKED still reaches this render — to say so — and stamping
                # the mark there dated a moment that never happened. Because
                # the field is a latency, that bad mark read as a FAST turn
                # rather than a missing one, which is the direction that hides
                # a problem instead of showing it. `api/chat.py` already guards
                # its own mark on `entry_id`; this is the legacy lane earning
                # the same condition rather than assuming it.
                #
                # Read off the trace instead of a local, so the mark cannot
                # disagree with the count it is supposed to be about — the
                # funnel's `visible => committed > 0` holds by construction
                # here rather than by the two happening to be computed alike.
                # `items_committed` is set above, in this same function.
                _vis_trace = _ft_vis.current()
                if _vis_trace is not None and _vis_trace.items_committed > 0:
                    _ft_vis.mark("commit_visible")
                # The food reply is final here — release the second-tier heads-up
                # guard (and stop its timer sleeping) so it can never speak over
                # the answer it was covering for.
                _reply_ready = True
                if _late_task is not None:
                    try:
                        _late_task.cancel()
                    except Exception:
                        pass
                # Hold notice AFTER the contract/render: held names come from
                # the system's own stash, and their digits ("Fage 0%") must
                # never vaporize the notice (Dove bar incident class).
                if _sft.get("_held_stash"):
                    from core.food_turn import note_held_items
                    # The BOARD too, not just this turn's writes — a row logged
                    # a turn ago is done, not held. See `note_held_items`.
                    response_text = note_held_items(
                        response_text, _sft["_held_stash"], _ok_calls,
                        board=_board or ())
                _response_streamed = False
                # RENDER (review fix, PR #29). The last stage of a food turn is
                # the sentence the user reads, and it used to fall outside the
                # trace entirely — so "the card was wrong" and "the card was
                # right but the words were wrong" were indistinguishable in
                # triage. Recorded here, after the say contract and the hold
                # notice, because this is the point the reply is final.
                try:
                    from core import food_trace as _ft_r
                    from core.food_trace import Stage as _FtStageR
                    _ft_r.record(_FtStageR.RENDER,
                                 cards=len(_ok_calls or ()),
                                 held=len(_sft.get("_held_stash") or ()),
                                 chars=len(response_text or ""))
                except Exception:
                    pass
            elif _pure_food:
                # Legacy pure-food turn keeps the voice_log read; the deterministic
                # template is the last net.
                if fast_log_voice_enabled():
                    _fast_voice = await voice_log(
                        tool_calls, tool_results, today_log, user)
                response_text = _fast_voice or deterministic_confirmation(
tool_calls, today_log, user.preferences, tool_results,
user_message=_user_text or "")
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
                        tool_calls, today_log, user.preferences, tool_results,
                        user_message=_user_text or ""
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
                # The question-guard can empty the canned ack — never dead-air.
                response_text = deterministic_confirmation(
                    tool_calls, today_log, user.preferences, tool_results,
                    user_message=_user_text or ""
                ) or recovery_message("stall", seed=_user_text)
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
        pass

    # ── LEAKED CODE FENCE ────────────────────────────────────────────────────
    # The same failure wearing different syntax. The XML net above recognises
    # `<invoke`; a model that wraps its output in ``` trips nothing, so the
    # fence shipped (iOS rendered it monospace) and no call was recovered.
    # `_sanitize_bubble` now removes the markers on the way out, so this is
    # purely the DETECTION half: a fenced reply means the model was formatting
    # a payload instead of talking, which is worth seeing in the logs and on
    # the turn's health flags even when the text under it was fine.
    #
    # Deliberately NOT a recovery: parsing a call out of a fence and executing
    # it is the authority-inverting guess-and-log pattern that got
    # PHANTOM_RESCUE_ENABLED stripped on 2026-07-22, and the first fenced
    # payload we saw in the wild was a DELETE. Flag it; never act on it.
    _leaked_fence = False
    try:
        from core.platform import had_code_fence
        if had_code_fence(response_text):
            _leaked_fence = True
            logger.warning(
                "event=leaked_code_fence user=%s tools=%s",
                getattr(user, "id", None),
                ",".join(tc.get("name") or "?" for tc in (tool_calls or []))
                or "-")
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
    # THE ARITHMETIC IS SELF-VALIDATING, SO IT NEEDS NO PERMISSION FROM THE USER'S
    # WORDING. This guard used to also require `_FOOD_REPORT_RE` to match the user
    # message, and that conjunction is what let the 2026-08-03 phantom through: an
    # ANSWER turn ("6 oz of chicken and like a cup of rice") carries no eating verb
    # at all — the report lives in the prior — so no widening of a food-report
    # regex can be relied on to cover answer turns. Dropping the precondition
    # cannot create a false positive, because a reply that states the day total
    # CORRECTLY never exceeds the DB by more than the tolerance; only a fabricated
    # total does. A stated total is checkable against the ledger on its own terms.
    # NO LEDGER, NO VERDICT. `today_log` can be absent (a turn before the day row
    # exists, a failed load), and `getattr(None, ...) or 0` makes that look like a
    # day with zero calories — against which EVERY stated total is fabricated. That
    # is the same mistake as judging a row against a payload that predates it, and
    # dropping the wording precondition below is what would have exposed it: the
    # guard must abstain when it has nothing to check against, not convict.
    if not _phantom and not tool_calls and today_log is not None:
        try:
            from core.turn_health import (
                claimed_day_total as _claimed_total,
                DAY_TOTAL_TOLERANCE as _day_tol,
            )
            _claim = _claimed_total(response_text)
            _db_total = round(getattr(today_log, "total_calories", 0) or 0)
            if (_claim is not None
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
                _fresh = [n for n in tool_names if n not in _announced]
                if _fresh:
                    _announced.update(_fresh)
                    await on_tool_start(_fresh)
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
    # rice dropped). (The old _missing_from_scribe partial-drop leg of THIS
    # rescue was removed 2026-07-24: its producer was superseded by the
    # deterministic reconcile above, leaving the branch permanently dead.)
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
    # (The [[DID]]/[[LOGGED]] marker-phantom and the ask-first phantom-hold guard
    # were ripped 2026-07-23: sonnet-5 emitted the manifest 0/4 so the marker was
    # dead weight, and ask-before-log now lives in the structured food turn. Food
    # reports are structured; the worded heuristics below cover the legacy paths.)
    if (_phantom or _omission or _ex_phantom) \
            and not _signing_off:
        try:
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
                ["log_exercise"] if _ex_phantom else ["log_food"])
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
            if _orch_on():
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
                        _phantom = _omission = _ex_phantom = False  # rescued
                        logger.warning(
                            f"event=log_rescue outcome=logged trigger={_trigger} {_tag} "
                            f"tools={[tc.get('name') for tc in _rescue_calls]}")
            if _phantom or _omission or _ex_phantom:
                logger.warning(f"event=log_rescue outcome=unrescued {_tag} — "
                               f"model fired no tool")
        except Exception as e:
            logger.error(f"Phantom rescue failed for {_tag}: {e}")

    # ── LOOKUP RESCUE: estimated a specific product instead of looking it up ──────
    # The user asked about a SPECIFIC product's nutrition and the model hedged its
    # OWN estimate with no lookup (Bonilla de la Vista, IMG_8582). Force the lookup
    # and re-answer with the real numbers. Switch: LOOKUP_RESCUE.
    _lookup_fired = any(tc.get("name") in _LOOKUP_TOOLS for tc in tool_calls)
    _lookup_gap = False
    if _lookup_rescue_enabled() and not _signing_off and not _lookup_fired and response_text:
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

    # (The ASK-FIRST ANSWER force-log block was ripped 2026-07-23 — the structured
    # food turn owns ask + answer + log now, with its own pending kind.)

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
        # A QUESTION IS NOT A CLAIM ABOUT THE DAY (audit N-1).
        #
        # A structured ask states its READING — "roll 300 cal, bar 200" — and
        # `extract_stated_day_calories` reads a figure out of it and compares it
        # to the board, which the turn has not written to. The guard then
        # replaces the question with `deterministic_confirmation`.
        #
        # It could not fire before the I-1 fix because `_fired_log` was False on
        # a bare ask. Partial commit makes an ask carry writes, and I-1 sets
        # `_response_streamed = False` on that path, so this became reachable in
        # exactly the case partial commit exists for.
        #
        # It is not firing today only because T-2 rejects a `Total:` line
        # upstream, in another module, by regex. That is protection by
        # coincidence. The guard should know the turn's disposition instead.
        _structured_ask = (_sft is not None and _sft.get("action") == "ask")
        if today_log is not None and not in_onboarding and not _structured_ask:
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
tool_calls, today_log, user.preferences, tool_results,
user_message=_user_text or "")
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
    # ONLY WHEN A CANONICAL OPERATION OWNS THE TURN. Absent otherwise, so its
    # presence IS the signal that a structured answer is possible — and a
    # channel that cannot answer by id simply never sees it.
    _b1_ix = result.get("b1_interaction") if isinstance(result, dict) else None
    if _b1_ix:
        resp.interaction = _b1_ix

    # ── Answer chips for a structured ask ─────────────────────────────────────
    # The ask's REAL options (ambiguity top_options, brand shelves) become
    # tappable buttons, each bound to its question by group index. Only on a
    # turn whose final disposition is still the ask — a rescue or repair that
    # replaced the reply must not ship chips for a question it no longer asks.
    # Options-less questions ship no chips: a count ask ("how many pieces?")
    # offering invented numbers would state a precision the user never gave.
    if (_sft is not None and _sft.get("action") == "ask"
            and not _signing_off):
        try:
            from core.platform import Button as _Btn, chip_labels as _chips
            _chip_buttons = []
            for _gi, _qd in enumerate(_sft.get("questions") or []):
                # The product is dropped from its own options: the question
                # already names it, so repeating it on every chip spends the
                # width that makes them readable.
                for _lbl in _chips(_qd.get("options"),
                                   drop_prefix=(_qd.get("item") or "")):
                    _chip_buttons.append(_Btn(label=_lbl, group=_gi))
            if not _chip_buttons:
                _chip_buttons = [_Btn(label=_lbl, group=0)
                                 for _lbl in _chips(_sft.get("options"))]
            if _chip_buttons:
                resp.buttons = _chip_buttons[:8]
        except Exception:
            logger.debug("ask chips not attached", exc_info=True)
        _shadow_clarification_fields(_sft, resp)

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
            # WHO DECIDED, AND WHY — persisted, because the trace is a log line.
            # `_turn_route` is settled by here (the lanes above are the only
            # writers); `_legacy_reason` is what separates "the lane looked at
            # this and handed it back" from "the gate never admitted it", and
            # `route_owner` is first-claim-wins on the ambient trace.
            _route_receipt = {"lane": _turn_route or "legacy"}
            if _legacy_reason:
                _route_receipt["legacy_reason"] = _legacy_reason
            try:
                from core import food_trace as _ft_r
                _cur = _ft_r.current()
                if _cur is not None and getattr(_cur, "route_owner", ""):
                    _route_receipt["owner"] = _cur.route_owner
            except Exception:
                pass
            resp.reasoning = build_reasoning(
                tool_calls, tool_results, None,
                int((_time_mod.monotonic() - _turn_t0) * 1000),
                execution=_execution, route=_route_receipt)
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

    # ── Food a held clarification settled earlier in this turn ────────────────
    # It never rides `tool_calls` — it committed hundreds of lines above, before
    # that list is even bound — and merging it in there would hand the settled
    # rows to every other consumer of the list (narration filters, commit
    # accounting, dedup), which is not what happened and not what should be
    # reported. The CARD is the one thing that was missing, so the card is the
    # only thing added, from the typed results the executor published.
    #
    # First, because these rows are the earlier part of the meal: the food the
    # user reported before the question that held it.
    for _sr_call in _settled_results:
        try:
            _card = _logged_entry_card(
                getattr(_sr_call, "name", ""), None, call=_sr_call)
            if _card is not None:
                resp.cards.append(_card)
        except Exception:      # a card is never worth the reply
            logger.debug("settled-deferred card skipped", exc_info=True)

    # ── Typed inline cards for native clients ─────────────────────────────────
    # A log_food / log_exercise call becomes a macro_card / workout_card — but ONLY
    # when it created a real DB row (see _logged_entry_card; a deduped no-op emits
    # no card, so a stale card never leaks onto a reply that logged nothing). The
    # iOS client renders these inline beneath the text; Telegram/iMessage adapters
    # ignore the field.
    #
    # An update_food_entry rides the same list as a `macro_card_patch`: NOT a row
    # on this turn's card, but a revision addressed by entry_id to the card that
    # row already appears on. One ordered channel on purpose — patches persist
    # into `cards_json` and rehydrate through the same client-side builder as the
    # cards do, so a reloaded transcript resolves to what the live one showed.
    if tool_calls:
        _calls_by_id = {}
        try:
            for _c in (_execution.calls if _execution is not None else ()):
                _calls_by_id[id(_c.raw_input)] = _c
        except Exception:
            _calls_by_id = {}
        for tc in tool_calls:
            name = tc.get("name")
            inp = tc.get("input") or {}
            # Typed view first (P0.3b): the card mirrors what the executor
            # actually committed, not what the model asked for.
            _cr = _calls_by_id.get(id(inp))
            _logged = _logged_entry_card(name, inp, call=_cr)
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
            # A TURN THAT ASKS IS NOT CLAIMING TO HAVE LOGGED. Measured
            # 2026-08-06: "Already got chicken breast on the books at 718 cal.
            # Now, salmon, how much did you have?" was flagged as a phantom
            # log. It names a PRIOR meal and asks about the current one —
            # honest reporting, and exactly what the assistant should do. The
            # turn's own action settles it; no phrasing rule can.
            asked_this_turn=bool(
                isinstance(_sft, dict) and _sft.get("action") == "ask"),
        )
        # The model wrapped its reply in a code fence — markers already
        # stripped at the bubble chokepoint, recorded here so a formatting
        # failure that used to ship silently shows up in /admin/flagged.
        if _leaked_fence:
            health_flags.append("leaked_code_fence")
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

    # ── End-to-end turn trace (review #22): ONE greppable line per turn —
    # identity, route, tools, health flags, latency, contract versions. The
    # seed of the replayable decision trace; fully wrapped, never breaks a
    # turn. `route` answers "which lane handled this?" without log archaeology.
    try:
        from core.turn_identity import current_turn_id as _ctid
        from core.food_ledger import (INTERPRETER_VERSION as _tr_iv,
                                      POLICY_VERSION as _tr_pv)
        logger.info(
            f"event=turn_trace {_tag} turn={_ctid() or '-'} "
            f"route={_turn_route} tools={_skills_fired or '-'} "
            # Only meaningful when the turn ACTUALLY ended up on legacy — a
            # reason recorded on a turn the structured path went on to own is
            # noise, and worse, reads as a fallback that never happened.
            f"legacy_reason={(_legacy_reason or '-') if _turn_route == 'legacy' else '-'} "
            f"flags={','.join(health_flags) or '-'} "
            f"ms={int((_time_mod.monotonic() - _turn_t0) * 1000)} "
            f"iv={_tr_iv} pv={_tr_pv}")
    except Exception:
        pass

    # ── SHADOW OBSERVATION (P0.2): the parallel coordinator predicts this
    # turn's lane from the same gates and logs predicted-vs-actual. Inert
    # unless TURN_COORDINATOR_MODE is set, read-only always, and it runs
    # AFTER the turn is decided so it can never influence the answer. The
    # disagreement rate this produces is the promotion gate.
    try:
        from core.turns.observe import observing as _obs_on
        if _obs_on():
            from core.turns.models import TurnRequest as _TReq
            from core.turns.observe import (observe_turn as _observe,
                                            legacy_lane as _legacy_lane,
                                            legacy_disposition as _legacy_disp)
            from core.turn_identity import current_turn_id as _obs_ctid
            await _observe(
                _TReq(turn_id=_obs_ctid() or "-", user_id=user.id,
                      platform=platform, source_type=source_type,
                      text=_user_text or "",
                      metadata={"db": db, "user": user,
                                "today_log": today_log,
                                "in_onboarding": bool(in_onboarding),
                                "has_board": bool(getattr(today_log,
                                                          "food_entries", None)),
                                "food_prior": locals().get("_sft_prior"),
                                "food_pending": locals().get("_sft_prior") is not None}),
                # BOTH HALVES, TRUTHFULLY. `_legacy_reason` is what separates
                # "the lane declined this turn" from "the lane never saw it" —
                # `_turn_route` is "legacy" for both — and the disposition was
                # previously reported only for an ask, so `agree_disp`
                # short-circuited to True on every commit.
                actual_route=_legacy_lane(_turn_route, _legacy_reason or ""),
                actual_disposition=_legacy_disp(_turn_route,
                                                _legacy_reason or ""),
                # WHAT THIS TURN ACTUALLY DECIDED. Without it the observation
                # re-ran FoodPlanStage — the whole Sonnet interpreter — after
                # the reply had already shipped, for 2.6 s a food turn. Passed
                # explicitly, even when None: a lane that ran and returned
                # nothing is a `pass`, and asking the same model the same
                # question twice measures its nondeterminism, not our wiring.
                interpretation=locals().get("_sft"))
    except Exception:
        pass

    # Every non-error path converges here — release the second-tier heads-up
    # guard so a still-sleeping timer can never speak after the reply has landed.
    _reply_ready = True
    if _late_task is not None:
        try:
            _late_task.cancel()
        except Exception:
            pass

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
