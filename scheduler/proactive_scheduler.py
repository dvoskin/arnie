"""
Proactive messaging scheduler.
Runs every 30 minutes, checks each user's local time, and sends
LLM-generated nudges within their wake/sleep window.
Reminders are ON by default for all onboarded users.

Touchpoints (all relative to user local time):
  wake+30   — morning weight + breakfast check-in (wearable-aware)
  10:00     — late-morning nudge if nothing logged yet
  12:00     — midday pacing (nutrition velocity vs time-of-day target)
  15:30     — pre-workout fuel + readiness check (recovery-aware)
  16:30     — afternoon workout follow-up if not yet done
  19:00     — evening full-day pacing + dinner prompt
  21:00     — night closeout nudge
  22:00     — end-of-day performance report (all users, template-based)

Whoop sync runs every 2 hours.
"""
import collections
import logging
import os
from datetime import datetime, date, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()


def proactive_enabled() -> bool:
    """
    Master kill switch for ALL proactive outreach (timed nudges + weekly recap).
    Defaults OFF — proactive messaging stays dark until PROACTIVE_MESSAGING_ENABLED
    is explicitly set true. Flip the env var to re-enable; no code change needed.
    Whoop sync is unaffected (it's a background data pull, not a user message).
    """
    return os.getenv("PROACTIVE_MESSAGING_ENABLED", "false").lower() in ("true", "1", "yes")


def voice_proactive_enabled() -> bool:
    """
    Kill switch for TTS audio on proactive messages only. Text is still sent.
    Defaults ON so existing behavior is preserved; set VOICE_PROACTIVE_ENABLED=false
    to send proactive nudges as text-only with no voice note attached.
    """
    return os.getenv("VOICE_PROACTIVE_ENABLED", "true").lower() in ("true", "1", "yes")


def _proactive_allowlist() -> set:
    """
    Safe-rollout gate. PROACTIVE_ALLOWLIST = comma-separated identifiers (DB user id,
    telegram_id like 'im:+1555...' or a numeric Telegram id, or the resolved send
    target). When SET, proactive messages go ONLY to those users — validate on yourself
    or a few accounts before flipping it on for everyone. When UNSET/empty, no
    restriction (normal behavior). Read fresh each call so it can change without restart.
    """
    raw = os.getenv("PROACTIVE_ALLOWLIST", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def _allowlist_allows(*identifiers) -> bool:
    """True if no allowlist is configured (everyone), or any identifier is on it."""
    allow = _proactive_allowlist()
    if not allow:
        return True
    return any(i is not None and str(i) in allow for i in identifiers)


TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Engagement de-dup state is now persisted on the User row (nudges_sent,
# whoop_last_notified) so it survives deploys. No in-memory tracking needed.

# Nudge slots: (hour, minute_start, minute_end, slot_key)
_NUDGE_SLOTS = [
    # morning slot is dynamic (wake+30), handled separately
    (10, 0,  30, "late_morning_nolog"),
    (12, 0,  30, "midday_pacing"),
    (15, 30, 60, "preworkout"),
    (16, 30, 60, "workout_check"),
    (19, 0,  30, "evening_pacing"),
    (21, 0,  30, "night_closeout"),
]

from core.prompts.nudges import (
    NUDGE_SYSTEM as _NUDGE_SYSTEM,
    NUDGE_SLOT_INSTRUCTIONS as _SLOT_INSTRUCTIONS,
    NEW_USER_SYSTEM as _NEW_USER_SYSTEM,
    NEW_USER_SLOT_INSTRUCTIONS as _NEW_USER_SLOT_INSTRUCTIONS,
    NEW_USER_HOWTO_DIRECTIVE as _NEW_USER_HOWTO_DIRECTIVE,
)

# Eligibility decisions live in the reminders package now — the scheduler is the
# cron driver that asks "may I, and what" and then renders + sends. These aliases
# keep the historical private names (`_in_window`, `_has_timezone`, `_pacing_pct`)
# as module attributes so existing callers/tests are unaffected.
from reminders.eligibility import (
    in_window as _in_window,
    has_timezone as _has_timezone,
    pacing_pct as _pacing_pct,
    clamp_window as _clamp_window,
    is_in_live_conversation as _is_live_convo,
    should_skip_linked as _should_skip_linked,
    proactive_pref_on as _proactive_pref_on,
)

# Prompt copy for the consolidation hook lives in lifecycle.py (content-ownership
# rule: prose strings visible to users belong in prompts/ or lifecycle.py, not here).
from reminders.lifecycle import _SILENCE_HOOK_DIRECTIVE


def _hours_since_created(user) -> float:
    """Hours elapsed since user.created_at (UTC). Returns 999 if unknown."""
    if not user.created_at:
        return 999.0
    created = (
        user.created_at.replace(tzinfo=timezone.utc)
        if user.created_at.tzinfo is None
        else user.created_at
    )
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600.0


def _is_user_row(row) -> bool:
    """
    A row that represents a real inbound user turn — i.e. NOT a proactive check-in
    we sent. Proactive rows carry source_type=='proactive' (and raw_message==''),
    so they must not count as the user being live or break a silence streak.
    """
    return getattr(row, "source_type", None) != "proactive"


def _last_exchange(rows):
    """
    Returns (minutes_since_last_USER_message, last_user_text, last_arnie_text)
    from a pre-fetched newest-first window (D-SHARED-FETCH). minutes is None if the
    user has never messaged.

    USER messages only (D3): a proactive nudge we just sent must NOT count as the
    user being mid-conversation, or every send would self-trigger the live-convo
    suppressor on the next tick. We scan for the most recent non-proactive row.
    """
    from datetime import datetime as _dt
    user_rows = [r for r in rows if _is_user_row(r)]
    if not user_rows:
        # No real user turn in the window — return None sentinel so callers can
        # distinguish "never messaged" from "messaged with empty text".
        return None, None, None
    c = user_rows[0]  # newest-first → most recent real user turn
    ts = c.timestamp
    if ts is None:
        return None, c.raw_message, c.response
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    mins = (_dt.utcnow() - ts).total_seconds() / 60.0
    # Preserve None vs "" distinction: None means the field was not stored;
    # "" means the message existed but had no text (e.g. button tap, media).
    return mins, c.raw_message, c.response


def _silence_streak(rows) -> int:
    """
    Count consecutive proactive check-ins we've sent since the user's last real
    message — the user's "silence streak" (D3). Computed from the shared newest-
    first window (no new query): walk from newest, counting proactive rows until we
    hit a real user turn (which resets the streak to what we've counted so far).

    A streak of N means the last N things in the thread were unanswered check-ins.
    """
    streak = 0
    for r in rows:
        if _is_user_row(r):
            break
        streak += 1
    return streak


async def _llm_new_user_nudge(user, log, prefs, slot: str, name: str,
                              surface_howto: bool = False) -> str:
    """Generate a new-user engagement message via Claude Haiku.

    surface_howto: the user still hasn't logged anything at all since signup —
    append the /howto on-ramp directive so this nudge offers the rundown."""
    from core.llm import chat

    cal = round(log.total_calories) if log else 0
    pro = round(log.total_protein) if log else 0
    foods_logged = len(log.food_entries) if log and log.food_entries else 0
    exercises_logged = len(log.exercise_entries) if log and log.exercise_entries else 0

    lang = getattr(prefs, "preferred_language", None) or "English"
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None
    instr = _NEW_USER_SLOT_INSTRUCTIONS.get(slot, "Send a brief, personal coaching check-in.")
    if surface_howto:
        instr += _NEW_USER_HOWTO_DIRECTIVE

    # height/weight may be None now (height collected post-onboarding) — format safely
    h = f"{user.height_cm:.0f}cm" if user.height_cm else "?"
    w = f"{user.current_weight_kg:.1f}kg" if user.current_weight_kg else "?"

    prompt = (
        f"New athlete: {name}, goal={user.primary_goal or '?'}, "
        f"exp={user.training_experience or '?'}, "
        f"height={h}, weight={w}, language={lang}\n"
        f"Targets: {cal_t or '?'} cal / {pro_t or '?'}g protein\n"
        f"Today so far: {cal} cal, {pro}g protein, {foods_logged} food entries, {exercises_logged} exercises\n"
        f"Task: {instr}"
    )

    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_NEW_USER_SYSTEM,
            tools=False,
            max_tokens=130,
            model="claude-haiku-4-5-20251001",
        )
        return (result.get("text") or "").strip()
    except Exception as e:
        logger.error(f"New user nudge ({slot}) failed: {e}")
        return ""


async def _send_hook(telegram_id: str, text: str) -> None:
    """
    Send a conversation-hook follow-up (left-on-read re-ask). Bypasses the
    PROACTIVE_MESSAGING_ENABLED gate — hook re-asks are conversation continuity,
    not proactive marketing nudges. Still respects the allowlist.
    """
    if not _allowlist_allows(telegram_id):
        logger.info(f"Hook send to {telegram_id} skipped — not on PROACTIVE_ALLOWLIST")
        return
    from core.platform import Response, IMessageAdapter, TelegramAdapter
    resp = Response.from_text(text)
    if telegram_id.startswith("im:"):
        address = telegram_id[3:]
        chat_guid = f"iMessage;-;{address}"
        try:
            await IMessageAdapter(chat_guid).send(resp)
        except Exception as e:
            logger.error(f"Hook iMessage send failed → {telegram_id}: {e}")
        return
    from telegram import Bot
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await TelegramAdapter(bot, int(telegram_id)).send(resp)
        await bot.close()
    except Exception as e:
        logger.error(f"Hook send failed → {telegram_id}: {e}")


async def _send(telegram_id: str, text: str, effect: str = None):
    """
    Send a proactive message to the user, rendered natively per platform.
    Splits on ||| for multi-bubble. telegram_id prefixed "im:" → iMessage, else Telegram.
    effect — optional FX.* applied on iMessage (ignored on Telegram).
    """
    # Master kill switch — no proactive message goes out while disabled, on any channel.
    if not proactive_enabled():
        return
    # Safe-rollout gate — when an allowlist is set, only its members get proactive sends.
    if not _allowlist_allows(telegram_id):
        logger.info(f"Proactive send to {telegram_id} skipped — not on PROACTIVE_ALLOWLIST")
        return
    from core.platform import Response, IMessageAdapter, TelegramAdapter
    resp = Response.from_text(text)
    if effect:
        resp.effect = effect
        resp.effect_idx = -1

    if telegram_id.startswith("im:"):
        address = telegram_id[3:]
        chat_guid = f"iMessage;-;{address}"
        try:
            await IMessageAdapter(chat_guid).send(resp)
        except Exception as e:
            logger.error(f"Proactive iMessage send failed → {telegram_id}: {e}")
        return

    from telegram import Bot
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await TelegramAdapter(bot, int(telegram_id)).send(resp)
        await bot.close()
    except Exception as e:
        logger.error(f"Proactive send failed → {telegram_id}: {e}")
async def _log_proactive(db, user_id, text: str, slot_key: str) -> None:
    """
    Record a user-facing proactive send to the conversation history (source_type=
    'proactive', skills_fired=slot_key, parsed_intent left None so these never reach
    /admin/flagged). Best-effort: a logging failure must never break the send path.
    """
    try:
        from db.queries import log_conversation
        await log_conversation(
            db, user_id, raw_message="", response=text,
            source_type="proactive", skills_fired=slot_key,
        )
    except Exception as e:
        logger.error(f"Proactive log failed (user {user_id}, slot {slot_key}): {e}")


async def _send_logged(db, user_id, telegram_id: str, text: str, slot_key: str) -> None:
    """
    Send a user-facing proactive message, then log it. Wraps the IO-only `_send`
    (which stays send-only, shared by user-LESS internal callers) with the history
    write every user-facing proactive path needs for continuity (D2) and the
    silence streak (D3). slot_key is the structured nudge identity.
    """
    await _send(telegram_id, text)
    await _log_proactive(db, user_id, text, slot_key)


async def _send_logged_with_voice(db, user_id, telegram_id: str, text: str,
                                  slot_key: str, name: str = "",
                                  language: str = "English") -> None:
    """Voice-enabled `_send_logged` — the voice-bubble proactive paths (morning
    briefing, evening pacing, conversation-hook re-ask)."""
    await _send_with_voice(telegram_id, text, name=name, language=language)
    await _log_proactive(db, user_id, text, slot_key)


async def _send_slot_deduped(
    db, user, send_id: str, msg: str, slot_key: str,
    sent_slots: set, today_str: str,
    with_voice: bool = False, name: str = "", language: str = "English",
) -> bool:
    """Send a recurring slot nudge with per-day dedup.

    Checks a date-keyed entry in sent_slots before sending so the same slot
    never fires twice on the same calendar day (e.g. across a deploy restart).
    Updates sent_slots in-place and persists user.nudges_sent on send.
    Returns True if sent, False if skipped (already sent today or empty msg).
    """
    if not msg:
        return False
    day_key = f"{slot_key}:{today_str}"
    if day_key in sent_slots:
        logger.debug(f"Slot '{slot_key}' already sent today for user {user.id} — skipping")
        return False
    if with_voice:
        await _send_logged_with_voice(db, user.id, send_id, msg, slot_key, name=name, language=language)
    else:
        await _send_logged(db, user.id, send_id, msg, slot_key)
    sent_slots.add(day_key)
    user.nudges_sent = ",".join(sorted(sent_slots))
    await db.commit()
    return True


# In-process TTS cache keyed on (text_hash, name, language).
# TTL = 1800s (~1 scheduler tick). Avoids paying voice_variant (LLM) +
# text_to_speech (TTS API) for identical or near-identical proactive messages
# across users hitting the same slot in the same tick.
_TTS_CACHE: dict[tuple, tuple[bytes, float]] = {}
_TTS_CACHE_TTL = 1800.0


async def _send_with_voice(telegram_id: str, text: str, name: str = "", language: str = "English") -> None:
    await _send(telegram_id, text)
    if telegram_id.startswith("im:"):
        return
    if not proactive_enabled() or not _allowlist_allows(telegram_id):
        return
    if not voice_proactive_enabled():
        return
    try:
        import hashlib
        import time as _time
        from core.llm import text_to_speech, voice_variant

        cache_key = (hashlib.md5(text.encode()).hexdigest(), name, language)
        now = _time.monotonic()
        cached = _TTS_CACHE.get(cache_key)
        if cached and cached[1] > now:
            audio_bytes = cached[0]
        else:
            spoken = await voice_variant(text, name=name, language=language)
            audio_bytes = await text_to_speech(spoken, voice="onyx")
            if audio_bytes:
                _TTS_CACHE[cache_key] = (audio_bytes, now + _TTS_CACHE_TTL)

        if not audio_bytes:
            return
        import io
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)
        buf = io.BytesIO(audio_bytes)
        buf.name = "arnie.mp3"
        await bot.send_voice(chat_id=int(telegram_id), voice=buf)
        await bot.close()
    except Exception as e:
        logger.error(f"Voice send failed → {telegram_id}: {e}")

def _recent_checkins_block(recent_proactive) -> str:
    """
    Render the last few proactive check-ins we sent into a short context block so
    the nudge LLM can avoid repeating itself (D2 continuity). `recent_proactive` is
    the proactive subset of the shared window (newest-first). '' if none.
    """
    if not recent_proactive:
        return ""
    lines = []
    for r in recent_proactive[:3]:  # newest first, cap at 3
        txt = (getattr(r, "response", "") or "").replace("|||", " / ").strip()
        if txt:
            lines.append(f'- "{txt[:160]}"')
    if not lines:
        return ""
    return ("Recent check-ins you already sent (do NOT repeat one of these — vary the "
            "angle or move on):\n" + "\n".join(lines))


async def _llm_nudge(user, log, prefs, health_snap, slot: str, name: str,
                     recent_proactive=None, needs_weight: bool = False) -> str:
    """Generate a personalized nudge via Claude Haiku. Returns '' on failure.

    recent_proactive: the proactive rows from the shared window (newest-first), used
    to surface a "recent check-ins you sent" block so the nudge doesn't repeat one
    it just sent (D2 continuity).
    needs_weight: for morning_checkin — when True, override the instruction to open
    with a goal-specific weight ask before anything else.
    """
    from core.llm import chat

    cal = round(log.total_calories) if log else 0
    pro = round(log.total_protein) if log else 0
    water = round(log.total_water_ml) if log else 0
    workout_done = log.workout_completed if log else False
    cardio_done = log.cardio_completed if log else False
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None

    health_str = ""
    if health_snap:
        parts = []
        if health_snap.recovery_score is not None:
            rec = health_snap.recovery_score
            label = "green" if rec >= 67 else ("yellow" if rec >= 34 else "red")
            parts.append(f"recovery={rec}% ({label})")
        if health_snap.hrv is not None:
            parts.append(f"HRV={health_snap.hrv:.0f}ms")
        if health_snap.resting_hr is not None:
            parts.append(f"RHR={health_snap.resting_hr:.0f}bpm")
        if health_snap.sleep_hours is not None:
            parts.append(f"sleep={health_snap.sleep_hours:.1f}h")
        if health_snap.strain is not None:
            parts.append(f"strain={health_snap.strain:.1f}")
        if health_snap.steps is not None:
            parts.append(f"steps={health_snap.steps:,}")
        if parts:
            src = getattr(health_snap, "source", "wearable")
            health_str = f"Wearable ({src}): {', '.join(parts)}"

    foods_logged = len(log.food_entries) if log and log.food_entries else 0
    exercises_logged = len(log.exercise_entries) if log and log.exercise_entries else 0

    instr = _SLOT_INSTRUCTIONS.get(slot, "Send a brief coaching check-in about their day.")

    # For morning_checkin: override instruction to open with a goal-specific weight ask
    # when weight hasn't been logged yet today (cut/bulk only).
    if slot == "morning_checkin" and needs_weight:
        _goal = user.primary_goal or ""
        if _goal == "cut":
            instr = (
                "Open the FIRST bubble with asking for their morning weight — "
                "e.g. 'What's your weight this morning?' or 'Good morning, scale first?'. "
                "Then prompt breakfast. Reference recovery data if present. "
                "Keep it warm and direct — 2-3 bubbles total."
            )
        elif _goal == "bulk":
            instr = (
                "Open the FIRST bubble with asking for their scale reading — "
                "e.g. 'What's the scale showing today?' or 'Morning, scale check?'. "
                "Then ask about breakfast. Reference recovery data if present. "
                "Energetic and direct — 2-3 bubbles total."
            )

    checkins_block = _recent_checkins_block(recent_proactive)

    lang = getattr(prefs, "preferred_language", None) or "English"
    prompt = (
        f"Athlete: {name}, goal={user.primary_goal or '?'}, "
        f"exp={user.training_experience or '?'}, diet={user.dietary_preferences or 'none'}, "
        f"language={lang}\n"
        f"Today: {cal} cal"
        f"{' / ' + str(cal_t) + ' target' if cal_t else ''} | "
        f"{pro}g protein"
        f"{' / ' + str(pro_t) + 'g target' if pro_t else ''} | "
        f"water {water}ml | "
        f"workout {'✓' if workout_done else '✗'} | cardio {'✓' if cardio_done else '✗'} | "
        f"{foods_logged} food entries | {exercises_logged} exercises\n"
        f"{health_str}\n"
        f"{checkins_block + chr(10) if checkins_block else ''}"
        f"Task: {instr}"
    )

    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_NUDGE_SYSTEM,
            tools=False,
            max_tokens=130,
            model="claude-haiku-4-5-20251001",
        )
        return _cap_bubbles((result.get("text") or "").strip(), 3)
    except Exception as e:
        logger.error(f"LLM nudge ({slot}) failed: {e}")
        return ""


_BRIEFING_SYSTEM = """\
You are Arnie sending a morning performance briefing, the message that makes the
user glad to hear from you. Not generic motivation: clarity and one clear action.

Rules:
- sentence case, like a real person texting. 2-4 short bubbles split with |||.
- if data includes a WEIGHT PROMPT directive: ALWAYS open the FIRST bubble with that
  weight ask, before any coaching. don't bury it halfway through. one short bubble,
  then the rest of the briefing. example: "What's your weight this morning?|||[rest]"
- lead with what matters: their trend or momentum, stated with a real number.
- if a notable pattern or projection is given, weave ONE in, make them go "huh, didn't notice that".
- end with the single highest-leverage action for today, framed as a small mission.
- close on a question or the mission so they reply. never generic ("have a great day!").
- match their preferred language. return only the message text with ||| separators.\
"""


async def _llm_morning_briefing(user, log, prefs, health_snap, db, name: str,
                                last_user_msg=None, last_arnie_msg=None,
                                logs=None, weights=None,
                                needs_weight: bool = False) -> str:
    """Data-rich morning briefing: momentum + trend + projection + pattern + leverage action.

    logs / weights: pre-fetched by the caller when possible (T2-3 optimisation).
    Pass None to let this function fetch internally (backward-compatible).
    last_user_msg / last_arnie_msg: None means no prior exchange (never messaged);
    "" means the row existed but had no text — both suppress the prior-exchange block.
    needs_weight: when True, include a weight-ask directive as the FIRST data point so
    the model opens the briefing by asking for the user's morning weight.
    """
    from core.llm import chat
    from db.queries import get_recent_logs, get_recent_weights
    from core.momentum import compute_momentum
    from core.insights_engine import weight_projection, discover_pattern

    if logs is None:
        logs = await get_recent_logs(db, user.id, days=21)
    if weights is None:
        weights = await get_recent_weights(db, user.id, days=30)
    m = compute_momentum(logs, prefs, weights, user)
    projection = weight_projection(weights, user)
    pattern = discover_pattern(logs, prefs)

    # 7-day weight trend in lbs
    trend = ""
    if len(weights) >= 2:
        sw = sorted(weights, key=lambda w: w.timestamp)
        d = (sw[-1].weight_kg - sw[0].weight_kg) * 2.20462
        trend = f"7-day weight trend: {d:+.1f} lbs (now {sw[-1].weight_kg*2.20462:.0f})"

    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None
    rec = health_snap.recovery_score if health_snap else None

    # Set today's mission (the day's highest-leverage action / open loop)
    mission_text = None
    try:
        from core.missions import pick_mission, set_mission_on_user
        mission = pick_mission(log, logs, prefs, user)
        if mission:
            set_mission_on_user(user, mission)
            await db.commit()
            mission_text = mission["text"]
    except Exception as e:
        logger.warning(f"mission set failed: {e}")

    data = [f"Athlete: {name}, goal {user.primary_goal or '?'}"]
    # Weight prompt: cut/bulk users who haven't logged today's weight get a directive
    # to open the briefing with the weight ask as the very first bubble.
    if needs_weight:
        _goal = user.primary_goal or ""
        if _goal == "cut":
            data.append(
                "WEIGHT PROMPT: weight not logged yet today. OPEN the briefing FIRST "
                "with asking for their morning weight — e.g. 'What's your weight this morning?' "
                "or 'Hop on the scale, what are we working with?' — before any coaching. "
                "One short opening bubble, then the briefing."
            )
        elif _goal == "bulk":
            data.append(
                "WEIGHT PROMPT: weight not logged yet today. OPEN the briefing FIRST "
                "with asking for their scale reading — e.g. 'What's the scale showing today?' "
                "or 'Morning, scale check first?' — before any coaching. "
                "One short opening bubble, then the briefing."
            )
    if m: data.append(f"Momentum: {m.score}/100 ({m.tier}, {m.direction}); drivers: {', '.join(m.drivers) or 'n/a'}")
    if trend: data.append(trend)
    if projection: data.append(f"Projection: {projection}")
    if pattern: data.append(f"Pattern noticed: {pattern}")
    if cal_t: data.append(f"Calorie target {cal_t}, protein target {pro_t}")
    if rec is not None: data.append(f"Recovery today: {rec}%")
    if mission_text: data.append(f"TODAY'S MISSION (end the briefing with this as the action): {mission_text}")
    if last_user_msg is not None or last_arnie_msg is not None:
        # None = no prior exchange; "" = message existed with no text. Both can
        # still carry the response side, so include the block when either is set.
        _u = (last_user_msg or "")[:140]
        _a = (last_arnie_msg or "")[:140]
        data.append(f"Last thing they told you: \"{_u}\" — you replied: \"{_a}\". "
                    f"only reference it if it flows naturally (e.g. continuing yesterday's thread).")
    data.append(f"Language: {getattr(prefs,'preferred_language',None) or 'English'}")

    prompt = ("\n".join(data) + "\n\nWrite the morning briefing. Pick the most useful 2-3 of these "
              "signals, state the trend with a number, and end with today's mission as the single action.")
    try:
        r = await chat([{"role": "user", "content": prompt}], system=_BRIEFING_SYSTEM,
                       tools=False, max_tokens=200, model="claude-haiku-4-5-20251001")
        return (r.get("text") or "").strip()
    except Exception as e:
        logger.error(f"Morning briefing failed: {e}")
        return ""


async def _llm_weekly_recap(user, prefs, db, name: str) -> str:
    """Sunday 'your week' recap — momentum vs last week, PRs, and a memory moment."""
    from core.llm import chat
    from db.queries import get_recent_logs, get_recent_weights
    from core.momentum import compute_momentum
    from core.insights_engine import personal_records, fmt_records
    from core.memory_moments import find_memory_moment

    logs = await get_recent_logs(db, user.id, days=21)
    weights = await get_recent_weights(db, user.id, days=60)
    m = compute_momentum(logs, prefs, weights, user)
    recs = fmt_records(personal_records(logs, weights))
    moment = find_memory_moment(weights, logs, user)

    # week-over-week training + logging
    from datetime import date as _d, timedelta as _td
    today = _d.today()
    this_wk = [l for l in logs if (today - l.date).days < 7 and (l.total_calories or 0) > 0]
    last_wk = [l for l in logs if 7 <= (today - l.date).days < 14 and (l.total_calories or 0) > 0]
    wk_workouts = sum(1 for l in this_wk if l.workout_completed)
    data = [f"Athlete: {name}, goal {user.primary_goal or '?'}",
            f"This week: {len(this_wk)} days logged, {wk_workouts} workouts",
            f"Last week: {len(last_wk)} days logged"]
    if m: data.append(f"Momentum: {m.score}/100 ({m.tier}, {m.direction})")
    if recs: data.append(recs)
    if moment: data.append(f"Memory moment to weave in: {moment}")
    data.append(f"Language: {getattr(prefs,'preferred_language',None) or 'English'}")

    prompt = ("\n".join(data) + "\n\nWrite a short Sunday 'your week' recap. Celebrate what's real "
              "with numbers, note momentum, weave in the memory moment if present, and set the tone "
              "for next week. end with a question. sentence case, like a real text. 3-5 bubbles split with |||.")
    try:
        r = await chat([{"role": "user", "content": prompt}], system=_BRIEFING_SYSTEM,
                       tools=False, max_tokens=260, model="claude-haiku-4-5-20251001")
        return (r.get("text") or "").strip()
    except Exception as e:
        logger.error(f"Weekly recap failed: {e}")
        return ""


# Varied, voice-matched one-time asks for legacy users missing a timezone.
_CITY_NUDGES = [
    "Quick one, what city are you in?|||Just so my check-ins land during your day and not at 3am 😅",
    "Hey, what city you based in these days?|||Want to make sure I'm hitting you up at sane hours, not the middle of the night.",
    "Random q, where are you based?|||Lets me time my check-ins to your day instead of blowing up your phone at 2am.",
]


async def _maybe_send_city_nudge(db, user, prefs):
    """
    One-time city ask for users with no known timezone. Sent only during a
    globally-daytime UTC window (so even without their tz we avoid overnight),
    and only once (tracked via nudges_sent='city_ask').
    """
    sent = set(s for s in (user.nudges_sent or "").split(",") if s)
    if "city_ask" in sent:
        return
    # 15:00–21:00 UTC ≈ daytime across the Americas + Europe (our user base).
    if not (15 <= datetime.now(timezone.utc).hour < 21):
        return
    import random
    msg = random.choice(_CITY_NUDGES)
    await _send_logged(db, user.id, user.telegram_id, msg, "city_ask")
    sent.add("city_ask")
    user.nudges_sent = ",".join(sorted(sent))
    await db.commit()
    logger.info(f"Sent one-time city/timezone nudge to user {user.id}")


async def _llm_followup(user, pq, name: str) -> str:
    """
    Generate a natural re-ask for an unanswered question, voiced like a friend
    circling back. Phrasing pressure scales with the question's tier + how many
    times we've already asked (reminders.pending.follow_up_tone). '' on failure.
    """
    from core.llm import chat
    from reminders.pending import follow_up_tone

    lang = getattr(getattr(user, "preferences", None), "preferred_language", None) or "English"
    tone = follow_up_tone(pq)
    hook_style = getattr(pq, "hook_style", None) or "question"

    if hook_style == "engagement":
        # Engagement phrase (e.g. "let me know", "still with me") — not a question.
        # Don't re-ask as if it were one; just re-engage naturally.
        context_line = (
            f"You previously ended a message with \"{pq.question}\" — they didn't respond. "
            f"Re-engage warmly and naturally, as if picking up where you left off. "
            f"Do NOT ask \"did you see my message\" or reference the silence."
        )
    else:
        # True question — can use the "you asked" framing.
        context_line = (
            f"Earlier you asked them this and they never answered:\n"
            f"  \"{pq.question}\"\n"
            f"Circle back and re-ask it ONCE, naturally — like a friend who genuinely "
            f"wants to know, not a form re-prompt."
        )

    prompt = (
        f"Athlete: {name}, language={lang}\n"
        f"{context_line}\n"
        f"{tone}\n"
        f"Do NOT say 'I asked earlier' or reference that they ignored you. "
        f"1-2 short bubbles split with |||."
    )
    try:
        result = await chat(
            [{"role": "user", "content": prompt}],
            system=_NUDGE_SYSTEM,
            tools=False,
            max_tokens=120,
            model="claude-haiku-4-5-20251001",
        )
        return _cap_bubbles((result.get("text") or "").strip(), 2)
    except Exception as e:
        logger.error(f"Follow-up generation failed for user {user.id}: {e}")
        return ""


def _cap_bubbles(text: str, max_bubbles: int) -> str:
    """Hard-cap a |||-separated reply to at most `max_bubbles` bubbles.

    The prompts ask for 1-2 bubbles but Haiku occasionally over-shoots, which
    is how the 3:19 PM dinner triple-nudge slipped through. Cap deterministically
    so the model can't spam regardless of prompt drift. Drops trailing bubbles
    (keeps the first N) since prompts lead with the most important content.
    """
    if not text:
        return text
    bubbles = [b.strip() for b in text.split("|||") if b.strip()]
    if len(bubbles) <= max_bubbles:
        return text
    return "|||".join(bubbles[:max_bubbles])


async def _eod_report_window(db, user_id: int, tz) -> tuple[int, int]:
    """Resolve the local hour:minute the EOD report should fire for a user.

    Default 21:00. If the user's median dinner-log time over the last 14 days
    is later than 20:30, slide the report to 30 minutes after that median so
    late-dinner users don't get the recap before dinner is logged. Clamped to
    [20:30, 22:30].

    No new DB queries beyond what scheduler already pulls — relies on
    get_recent_logs's food_entries with meal_type='dinner'. Falls back to
    (21, 0) on any error.
    """
    try:
        from db.queries import get_recent_logs
        logs = await get_recent_logs(db, user_id, days=14)
        dinner_hours = []
        for lg in logs or []:
            for e in (getattr(lg, "food_entries", None) or []):
                if getattr(e, "meal_type", None) == "dinner":
                    mt = getattr(e, "meal_time", None)
                    if mt is None:
                        continue
                    # meal_time is stored UTC-naive; convert to user local for hour.
                    from datetime import timezone as _tz
                    local = mt.replace(tzinfo=_tz.utc).astimezone(tz)
                    dinner_hours.append(local.hour * 60 + local.minute)
        if not dinner_hours:
            return 21, 0
        dinner_hours.sort()
        median_min = dinner_hours[len(dinner_hours) // 2]
        target_min = median_min + 30
        # Clamp to [20:30, 22:30]
        target_min = max(20 * 60 + 30, min(22 * 60 + 30, target_min))
        return target_min // 60, target_min % 60
    except Exception:
        return 21, 0


async def _maybe_followup_pending(db, user, send_id: str, name: str,
                                  mins_since) -> bool:
    """
    If the user has a due, unanswered question, re-ask the highest-priority one.
    Returns True if a follow-up was sent (caller skips other nudges this tick).

    The reminders layer owns the decision (which question, whether it's time);
    this function is the IO: generate → send → record the re-ask. Resolution
    (marking it answered) happens on the user's next inbound turn, not here.
    """
    from db.queries import (
        get_open_pending_questions, mark_pending_question_followed_up,
    )
    from reminders.pending import select_follow_up

    try:
        open_qs = await get_open_pending_questions(db, user.id)
        if not open_qs:
            return False
        pq = select_follow_up(open_qs, mins_since_last_exchange=mins_since)
        if pq is None:
            return False
        msg = await _llm_followup(user, pq, name)
        if not msg:
            return False
        slot_key = f"followup_{getattr(pq, 'kind', 'pending')}"
        if getattr(pq, "kind", "") == "conversation_hook":
            lang = getattr(getattr(user, "preferences", None), "preferred_language", None) or "English"
            await _send_logged_with_voice(db, user.id, send_id, msg, slot_key,
                                          name=name, language=lang)
        else:
            await _send_logged(db, user.id, send_id, msg, slot_key)
        await mark_pending_question_followed_up(db, pq.id)
        logger.info(
            f"Follow-up re-ask ({pq.kind}, tier={pq.tier}, "
            f"attempt={pq.follow_up_count}) → user {user.id}"
        )
        return True
    except Exception as e:
        logger.error(f"Pending follow-up error for user {user.id}: {e}")
        return False


async def _run_reminders():
    from db.database import AsyncSessionLocal
    from db.queries import get_all_active_users, get_today_log, get_recent_health_snapshots

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)

        # ── Per-tick skip observability (D-OBSERVE) ───────────────────────────
        # Count why each user was skipped this tick, by reason, and how many
        # actually got a message. Emitted as ONE summary line after the loop so
        # the (otherwise totally silent) gate chain is legible in prod without
        # per-user log spam. Pure instrumentation — never changes control flow.
        # Per-user detail is available on demand via /admin/proactive-debug.
        skip_counts = collections.Counter()

        for user in users:
            prefs = user.preferences

            # ── Single primary channel: never double-send to linked accounts ──
            # When a user links Telegram + iMessage, both rows exist and are
            # onboarded. The secondary row's linked_to_user_id points at the
            # canonical account, which already holds all their data. Skip the
            # secondary entirely so every proactive message goes out exactly once
            # (on the account they linked into). Gated by the linking flag so
            # turning linking off cleanly reverts to per-row behavior.
            from db.queries import linking_enabled, resolve_send_target
            if _should_skip_linked(user, linking_enabled()):
                skip_counts["linked"] += 1
                continue

            # Route this user's proactive messages to their preferred platform
            # (set when they linked both). Falls back to their own identity.
            send_id = await resolve_send_target(db, user)

            # ── Safe-rollout allowlist ────────────────────────────────────────
            # Skip non-allowlisted users early so we don't burn LLM calls generating
            # nudges they'll never receive. _send() also gates as a hard backstop.
            if not _allowlist_allows(user.id, user.telegram_id, send_id):
                skip_counts["allowlist"] += 1
                continue

            # ── Shared window (D-SHARED-FETCH) ────────────────────────────────
            # ONE ordered fetch per user, reused for every derived signal below:
            #   • minutes-since-last-USER-message (live-convo check)
            #   • the proactive silence streak (D3, Tier-2 gate)
            #   • the recent check-ins we've sent (D2 continuity)
            # No separate SELECTs for _last_exchange / streak / recent sends.
            from db.queries import get_recent_conversations
            try:
                recent_rows = await get_recent_conversations(db, user.id, limit=15)
            except Exception:
                recent_rows = []
            recent_proactive = [r for r in recent_rows if not _is_user_row(r)]
            silence_streak = _silence_streak(recent_rows)

            # ── Context awareness: never fire on top of a live conversation ───
            # If the user exchanged messages with Arnie in the last ~25 min, they're
            # already engaged — a scheduled nudge would be a jarring non-sequitur.
            # Skip this tick; it re-checks 30 min later when the thread's gone quiet.
            # USER messages only (D3): a check-in we just sent must not self-trigger
            # this suppressor on the next tick.
            mins_since, _last_u, _last_a = _last_exchange(recent_rows)
            if _is_live_convo(mins_since):
                skip_counts["live_convo"] += 1
                continue

            # ── Timezone gate: NO timed proactive until we know their timezone ─
            # Legacy/unknown users default to "UTC". Without a real tz we can't
            # tell local time, so sending would risk 3am spam. Skip all timed
            # messages and instead ask once for their city (during safe UTC hours).
            if not _has_timezone(user):
                try:
                    if prefs and prefs.proactive_messaging_enabled:
                        await _maybe_send_city_nudge(db, user, prefs)
                except Exception as e:
                    logger.error(f"City nudge error for user {user.id}: {e}")
                skip_counts["no_tz"] += 1
                continue

            # ── Weekly recap (Sunday 18:00–18:30, once per week) ──────────────
            # Gated by frequency_allows — "light" and "none" tiers skip the recap.
            try:
                from reminders.eligibility import frequency_allows as _freq_allows
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                iso_week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
                if (now.weekday() == 6 and now.hour == 18 and now.minute < 30
                        and prefs and prefs.proactive_messaging_enabled
                        and _freq_allows(prefs, "weekly_recap")
                        and user.weekly_recap_week != iso_week):
                    name = user.name or "hey"
                    recap = await _llm_weekly_recap(user, prefs, db, name)
                    if recap:
                        await _send_logged(db, user.id, send_id, recap, "weekly_recap")
                        user.weekly_recap_week = iso_week
                        await db.commit()
                        skip_counts["sent"] += 1
                        continue
            except Exception as e:
                logger.error(f"Weekly recap error for user {user.id}: {e}")

            # ── T2-1: hoist timezone + log — ONE fetch per user per tick ────────
            # Both the EOD report and the proactive nudge path need the same log.
            # Computing them here avoids a second get_today_log call for users at
            # 21:00 who had no calories (EOD falls through, nudge path ran anyway).
            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                hour, minute = now.hour, now.minute
                log = await get_today_log(db, user.id, user.timezone or "UTC")
                # Per-tick dedup state — used for EOD report and all recurring slots
                today_str = str(now.date())
                sent_slots = set(s for s in (user.nudges_sent or "").split(",") if s)
            except Exception as e:
                logger.error(f"Time/log fetch error for user {user.id}: {e}")
                continue

            # ── Profile consolidation (03:00–03:30 local, once per day) ──────────
            # Nightly cleanup pass: discontinues redundant/superseded attributes
            # and shortens verbose values. Runs via a cheap Haiku call — no user
            # message, just DB housekeeping. Uses per-day dedup via sent_slots.
            try:
                if hour == 3 and minute < 30:
                    day_key = f"consolidate:{today_str}"
                    if day_key not in sent_slots:
                        from memory.profile_consolidator import consolidate_user_profile
                        await consolidate_user_profile(user, db)
                        sent_slots.add(day_key)
                        user.nudges_sent = ",".join(sorted(sent_slots))
                        await db.commit()
            except Exception as e:
                logger.error(f"Profile consolidation error for user {user.id}: {e}")

            # ── End-of-day report — adaptive timing + frequency-gated ─────────
            # Default 21:00–21:30 local. If the user's median dinner-log time over
            # the last 14 days is later than 20:30, the report shifts to 30 min
            # after that median, clamped to [20:30, 22:30] so it never spams late.
            # Gated by frequency_allows("day_report") — "none" skips it entirely.
            # Deduped by date so a deploy restart during the window never sends twice.
            # The outer `continue` at the report hour prevents night_closeout from
            # also firing the same tick.
            try:
                from reminders.eligibility import frequency_allows as _freq_allows
                report_h, report_m = await _eod_report_window(db, user.id, tz)
                if hour == report_h and minute < 30:
                    if (log and log.total_calories > 0 and _proactive_pref_on(prefs)
                            and _freq_allows(prefs, "day_report")):
                        day_key = f"day_report:{today_str}"
                        if day_key not in sent_slots:
                            name = user.name or "hey"
                            report = _fmt_day_report(log, prefs, name, user=user)
                            _report_lang = getattr(prefs, "preferred_language", None) or "English"
                            if _report_lang.lower() not in ("english", "en"):
                                report = await _translate_report(report, _report_lang)
                            await _send_logged(db, user.id, send_id, report, "day_report")
                            sent_slots.add(day_key)
                            user.nudges_sent = ",".join(sorted(sent_slots))
                            await db.commit()
                            skip_counts["sent"] += 1
                    continue  # skip slot chain at report hour regardless of send
            except Exception as e:
                logger.error(f"Day report error for user {user.id}: {e}")

            # Proactive nudges — default ON for all onboarded users
            if not _proactive_pref_on(prefs):
                skip_counts["pref_off"] += 1
                continue

            try:
                hhmm = now.strftime("%H:%M")

                # Hard-cap the proactive window to 9am-9pm local, even if the
                # user's stored wake/sleep is wider. Respects a TIGHTER personal
                # window (e.g. wake 10:00) but never sends before 9am or after 9pm.
                wake, sleep = _clamp_window(prefs)
                if not _in_window(hhmm, wake, sleep):
                    skip_counts["window"] += 1
                    continue

                name = user.name or "hey"

                # Get latest health snapshot — only use it when it's today's or
                # yesterday's. A 3-day-old Whoop reading shouldn't drive a morning
                # briefing claim like "Recovery's in the red today (28%)" — it
                # might be totally stale. Falls back to None which all downstream
                # branches already handle.
                health_snaps = await get_recent_health_snapshots(db, user.id, days=2)
                health_snap = health_snaps[0] if health_snaps else None
                if health_snap is not None:
                    _snap_date = getattr(health_snap, "date", None)
                    if _snap_date is None or (now.date() - _snap_date).days > 1:
                        health_snap = None

                day_pct = _pacing_pct(hour, minute, wake, sleep)

                # ── Tier-3 frequency filter (D6) ──────────────────────────────
                # reminder_frequency NARROWS which timed slots may fire. It is NOT a
                # second kill switch — proactive_messaging_enabled (checked above) is
                # the only hard OFF, and "none" still permits the smallest non-empty
                # subset. Bind a tiny per-user predicate the slot branches consult.
                from reminders.eligibility import frequency_allows, gate_decision
                def _freq_ok(slot_key: str, _p=prefs) -> bool:
                    return frequency_allows(_p, slot_key)

                # ── T2-2: Tier-2 silence gate BEFORE follow-up ────────────────
                # Suppressed users skip the followup DB hit entirely.
                # Consolidate users get ONE follow-up attempt (using the freshly
                # registered proactive_hook) and then skip individual slots.
                # "send" verdict falls through to the normal followup + slot path.
                hours_in = _hours_since_created(user)
                verdict = gate_decision(silence_streak, hours_in, prefs)
                if verdict == "suppress":
                    skip_counts["suppress"] += 1
                    continue
                if verdict == "consolidate":
                    skip_counts["consolidate"] += 1
                    # Respect reminder_frequency for consolidate hook — "none" users
                    # explicitly want minimal contact; don't re-ask silence on them.
                    if frequency_allows(prefs, "proactive_hook"):
                        try:
                            from db.queries import record_pending_question
                            await record_pending_question(
                                db, user.id, kind="proactive_hook",
                                question=_SILENCE_HOOK_DIRECTIVE,
                                tier="proactive_hook",
                            )
                        except Exception as e:
                            logger.error(f"proactive_hook record failed for user {user.id}: {e}")
                        # Re-ask the freshly registered hook if due; then skip slots.
                        await _maybe_followup_pending(db, user, send_id, name, mins_since)
                    continue

                # ── Context-aware follow-up: re-ask an unanswered open question ──
                # Only reached when verdict == "send". Highest priority — a hanging
                # question outranks a generic slot nudge. Gated by frequency_allows
                # via the followup_ prefix collapse in eligibility.py.
                if frequency_allows(prefs, "followup_pending"):
                    if await _maybe_followup_pending(db, user, send_id, name, mins_since):
                        skip_counts["sent"] += 1
                        continue  # one proactive message per tick

                # ── New user engagement burst (first 72 hours post-onboarding) ──
                # Fires at fixed intervals after account creation. Independent of
                # daily time slots. Uses a separate LLM persona focused on learning
                # about the user and building early engagement. Falls off after 48h.
                if user.onboarding_completed and user.created_at:
                    hours_since = _hours_since_created(user)

                    # Warmup respects reminder_frequency: a user who picked "none"
                    # (Morning only) gets no aggressive day-1 burst — they were
                    # explicit. The morning_checkin still fires below as their one
                    # allowed daily anchor.
                    if hours_since <= 50.0 and frequency_allows(prefs, "warmup_15m"):
                        # NOTE: profile collection (age/sex/height for target calc)
                        # is now a PendingQuestion of kind 'profile_stats', recorded
                        # in the conversation path and re-asked by _maybe_followup_pending
                        # above — a single state-aware loop that resolves the moment the
                        # stats land, instead of bespoke slot timers here.

                        # Aggressive day-1 cadence, tapering into day 2.
                        # (window_start, window_end, slot_key) — strongest at the start.
                        _windows = [
                            (0.25, 0.9,  "warmup_15m"),
                            (1.0,  1.9,  "warmup_1h"),
                            (2.0,  3.4,  "warmup_2h"),
                            (4.0,  5.4,  "warmup_4h"),
                            (7.0,  8.9,  "warmup_7h"),
                            (10.0, 12.9, "warmup_10h"),
                            (23.0, 25.5, "warmup_24h"),
                            (35.0, 37.9, "warmup_36h"),
                            (47.0, 50.0, "warmup_48h"),
                        ]
                        new_slot = None
                        for lo, hi, key in _windows:
                            if lo <= hours_since < hi and key not in sent_slots:
                                new_slot = key
                                break

                        if new_slot:
                            # A day-or-two in and still not a single log? Offer the
                            # /howto on-ramp. Only the later warmup slots qualify, and
                            # the "never logged" check (one small query) runs only when
                            # one of them actually fires — at most a few times per user.
                            surface_howto = False
                            if new_slot in ("warmup_24h", "warmup_36h", "warmup_48h"):
                                from db.queries import get_recent_logs
                                _recent = await get_recent_logs(db, user.id, days=3)
                                _ever_logged = any(
                                    (dl.food_entries or dl.exercise_entries)
                                    for dl in _recent
                                )
                                surface_howto = not _ever_logged
                            msg = await _llm_new_user_nudge(user, log, prefs, new_slot, name,
                                                            surface_howto=surface_howto)
                            if msg:
                                await _send_logged(db, user.id, send_id, msg, new_slot)
                                # Persist the fired slot so it never re-fires after a deploy
                                sent_slots.add(new_slot)
                                user.nudges_sent = ",".join(sorted(sent_slots))
                                await db.commit()
                                skip_counts["sent"] += 1
                            logger.info(f"New user nudge '{new_slot}' sent to user {user.id} ({hours_since:.1f}h in)")
                            continue  # skip normal slots this tick — avoid message flood

                # ── Morning check-in (15 min after wake) ──────────────────────
                wake_h, wake_m = int(wake.split(":")[0]), int(wake.split(":")[1])
                morn_h, morn_m = wake_h, wake_m + 15
                if morn_m >= 60:
                    morn_h += 1
                    morn_m -= 60

                if hour == morn_h and 0 <= minute - morn_m < 30 and _freq_ok("morning_checkin"):
                    if not log or log.total_calories == 0:
                        # T2-3: pre-fetch only when confirmed in morning slot — avoids
                        # 21-day + 30-day scans for every user every tick.
                        from db.queries import get_recent_logs, get_recent_weights
                        _morning_logs = await get_recent_logs(db, user.id, days=21)
                        _morning_weights = await get_recent_weights(db, user.id, days=30)

                        # Weight ask: cut/bulk users get a weight prompt if they haven't
                        # logged their body weight yet today. maintenance/other goals skip it.
                        _goal = user.primary_goal or ""
                        _today_has_weight = any(
                            w.weight_kg is not None and w.timestamp is not None
                            and w.timestamp.replace(tzinfo=timezone.utc).astimezone(tz).date() == now.date()
                            for w in _morning_weights
                        )
                        # Also check linked accounts (iMessage user logged weight but
                        # Telegram user is canonical — the data lives on the linked user_id).
                        if not _today_has_weight and getattr(user, "linked_users", None):
                            try:
                                from db.queries import get_recent_weights as _grw
                                for _linked_uid in [lu.id for lu in user.linked_users]:
                                    _linked_weights = await _grw(db, _linked_uid, days=2)
                                    if any(
                                        w.weight_kg is not None and w.timestamp is not None
                                        and w.timestamp.replace(tzinfo=timezone.utc).astimezone(tz).date() == now.date()
                                        for w in _linked_weights
                                    ):
                                        _today_has_weight = True
                                        break
                            except Exception:
                                pass
                        _needs_weight = _goal in ("cut", "bulk") and not _today_has_weight

                        # Data-rich performance briefing (momentum + trend + leverage action)
                        msg = await _llm_morning_briefing(user, log, prefs, health_snap, db, name,
                                                          last_user_msg=_last_u, last_arnie_msg=_last_a,
                                                          logs=_morning_logs, weights=_morning_weights,
                                                          needs_weight=_needs_weight)
                        if not msg:
                            msg = await _llm_nudge(user, log, prefs, health_snap, "morning_checkin", name,
                                                   recent_proactive=recent_proactive,
                                                   needs_weight=_needs_weight)
                        if not msg:
                            # Goal-specific hardcoded fallback
                            if _needs_weight:
                                if _goal == "cut":
                                    msg = (f"Good morning {name} ☀️|||"
                                           "What's your weight this morning?|||"
                                           "Let's get today's first check-in started.")
                                else:  # bulk
                                    msg = (f"Morning {name} 💪|||"
                                           "What's the scale showing today?|||"
                                           "Let's get today's first log in.")
                            else:
                                msg = f"morning {name}.|||what've you had so far? let's get the day on the board."
                        lang = getattr(prefs, "preferred_language", None) or "English"
                        if await _send_slot_deduped(db, user, send_id, msg, "morning_checkin",
                                                    sent_slots, today_str,
                                                    with_voice=True, name=name, language=lang):
                            skip_counts["sent"] += 1

                # ── Late morning (10:00–10:30, only if nothing logged) ─────────
                elif hour == 10 and minute < 30 and _freq_ok("late_morning_nolog"):
                    if not log or log.total_calories < 50:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "late_morning_nolog", name,
                                               recent_proactive=recent_proactive)
                        if not msg:
                            msg = f"10am and nothing logged yet, {name}. Skipped breakfast or just haven't told me?"
                        if await _send_slot_deduped(db, user, send_id, msg, "late_morning_nolog",
                                                    sent_slots, today_str):
                            skip_counts["sent"] += 1

                # ── Midday pacing (12:00–12:30) ────────────────────────────────
                elif hour == 12 and minute < 30 and _freq_ok("midday_pacing"):
                    if prefs.calorie_target or prefs.protein_target:
                        cal = log.total_calories if log else 0
                        pro = log.total_protein if log else 0
                        cal_pct = (cal / prefs.calorie_target) if prefs.calorie_target else None
                        pro_pct = (pro / prefs.protein_target) if prefs.protein_target else None

                        # Only nudge if meaningfully off-pacing
                        cal_behind = cal_pct is not None and cal_pct < day_pct - 0.12
                        cal_ahead = cal_pct is not None and cal_pct > day_pct + 0.20
                        pro_behind = pro_pct is not None and pro_pct < day_pct - 0.12

                        if cal_behind or cal_ahead or pro_behind:
                            msg = await _llm_nudge(user, log, prefs, health_snap, "midday_pacing", name,
                                                   recent_proactive=recent_proactive)
                            if not msg:
                                parts = []
                                if pro_behind:
                                    rem = prefs.protein_target - pro
                                    parts.append(f"{pro:.0f}g protein so far — {rem:.0f}g left, hit it at lunch")
                                if cal_behind:
                                    rem_c = prefs.calorie_target - cal
                                    parts.append(f"only {cal:.0f} cal in, need ~{rem_c:.0f} more")
                                if cal_ahead:
                                    parts.append(f"already at {cal:.0f} cal — pace yourself through the afternoon")
                                msg = ", ".join(parts).capitalize() + "."
                            if await _send_slot_deduped(db, user, send_id, msg, "midday_pacing",
                                                        sent_slots, today_str):
                                skip_counts["sent"] += 1
                        # On-track users get no midday nudge — they're doing fine

                # ── Pre-workout readiness (15:30–16:00) ───────────────────────
                elif hour == 15 and 30 <= minute < 60 and _freq_ok("preworkout"):
                    # Skip if workout done or exercises are already being logged (mid-workout)
                    exercises_in_progress = log and len(log.exercise_entries or []) > 0
                    if log and not log.workout_completed and not exercises_in_progress:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "preworkout", name,
                                               recent_proactive=recent_proactive)
                        if not msg:
                            rec = health_snap.recovery_score if health_snap else None
                            if rec is not None and rec < 34:
                                msg = (
                                    f"Recovery's in the red today ({rec}%), {name}. "
                                    f"Still training? Might be worth going lighter."
                                )
                            else:
                                msg = f"3:30 — workout not logged yet, {name}. Still on for today?"
                        if await _send_slot_deduped(db, user, send_id, msg, "preworkout",
                                                    sent_slots, today_str):
                            skip_counts["sent"] += 1

                # ── Afternoon workout check (16:30–17:00) ────────────────────
                elif hour == 16 and 30 <= minute < 60 and _freq_ok("workout_check"):
                    # Skip if workout done or exercises are already being logged (mid-workout)
                    exercises_in_progress = log and len(log.exercise_entries or []) > 0
                    if log and not log.workout_completed and not exercises_in_progress:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "workout_check", name,
                                               recent_proactive=recent_proactive)
                        if not msg:
                            msg = f"4:30 — workout still hasn't happened, {name}. Happening today or are we calling it a rest day?"
                        if await _send_slot_deduped(db, user, send_id, msg, "workout_check",
                                                    sent_slots, today_str):
                            skip_counts["sent"] += 1

                # ── Evening pacing (19:00–19:30) ──────────────────────────────
                elif (hour == 19 and minute < 30 and log and log.total_calories > 0
                        and _freq_ok("evening_pacing")):
                    msg = await _llm_nudge(user, log, prefs, health_snap, "evening_pacing", name,
                                           recent_proactive=recent_proactive)
                    if not msg:
                        parts = []
                        if prefs.calorie_target:
                            rem_c = prefs.calorie_target - log.total_calories
                            if abs(rem_c) > 100:
                                parts.append(f"<b>{rem_c:+.0f} cal</b>")
                        if prefs.protein_target:
                            rem_p = prefs.protein_target - log.total_protein
                            if rem_p > 20:
                                parts.append(f"<b>{rem_p:.0f}g protein</b> still needed")
                        if parts:
                            msg = (
                                "Evening check:\n" +
                                "\n".join(f"• {p}" for p in parts) +
                                "\n\nWhat's dinner looking like?"
                            )
                        else:
                            msg = f"Looking solid today, {name}. Log dinner when you have it."
                    lang = getattr(prefs, "preferred_language", None) or "English"
                    if await _send_slot_deduped(db, user, send_id, msg, "evening_pacing",
                                                sent_slots, today_str,
                                                with_voice=True, name=name, language=lang):
                        skip_counts["sent"] += 1

                # ── Night closeout (21:00–21:30) ──────────────────────────────
                elif hour == 21 and minute < 30 and _freq_ok("night_closeout"):
                    if log and log.total_calories > 0:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "night_closeout", name,
                                               recent_proactive=recent_proactive)
                        if not msg:
                            msg = "Day still open. Done eating? Send me anything you missed and close it out."
                        if await _send_slot_deduped(db, user, send_id, msg, "night_closeout",
                                                    sent_slots, today_str):
                            skip_counts["sent"] += 1

            except Exception as e:
                logger.error(f"Reminder error for user {user.id}: {e}")

        # ── One summary line per tick (D-OBSERVE) ─────────────────────────────
        # Makes the silent gate chain legible: how many users we evaluated, how
        # many got a message, and how many were dropped at each durable gate.
        logger.info(
            "proactive tick: users=%d sent=%d linked=%d allowlist=%d no_tz=%d "
            "window=%d live=%d suppress=%d consolidate=%d pref_off=%d",
            len(users), skip_counts["sent"], skip_counts["linked"],
            skip_counts["allowlist"], skip_counts["no_tz"], skip_counts["window"],
            skip_counts["live_convo"], skip_counts["suppress"],
            skip_counts["consolidate"], skip_counts["pref_off"],
        )


def _fmt_whoop_notification(snap) -> str:
    """Format a Whoop sync notification message."""
    if snap.recovery_score is None:
        return ""
    rec = snap.recovery_score
    emoji = "🟢" if rec >= 67 else ("🟡" if rec >= 34 else "🔴")
    lines = [f"<b>⚡ Whoop — {snap.date}</b>", ""]
    lines.append(f"{emoji} Recovery: <b>{rec}%</b>")
    detail = []
    if snap.hrv:
        detail.append(f"HRV {snap.hrv:.0f}ms")
    if snap.resting_hr:
        detail.append(f"RHR {snap.resting_hr:.0f}bpm")
    if detail:
        lines.append("  ".join(detail))
    if snap.sleep_hours:
        s = f"😴 Sleep: {snap.sleep_hours:.1f}h"
        extras = []
        if snap.sleep_deep_hours:
            extras.append(f"deep {snap.sleep_deep_hours:.1f}h")
        if snap.sleep_rem_hours:
            extras.append(f"REM {snap.sleep_rem_hours:.1f}h")
        if extras:
            s += f" ({', '.join(extras)})"
        lines.append(s)
    if snap.strain is not None:
        lines.append(f"💪 Strain: {snap.strain:.1f}")
    return "\n".join(lines)


async def _translate_report(text: str, language: str) -> str:
    """
    Translate a template-generated EOD report to the user's preferred language.
    Preserves ||| bubble separators. Falls back to original English on any failure.
    Used only when preferred_language is set to a non-English language.
    """
    from core.llm import chat
    try:
        result = await chat(
            [{"role": "user", "content": (
                f"Translate this coaching message to {language}. "
                f"Keep the same casual, direct coach tone — like a real coach texting. "
                f"Preserve the ||| separators exactly as-is between message bubbles. "
                f"Return ONLY the translated text, no explanation or preamble:\n\n{text}"
            )}],
            system=(
                "You are a sports coach translator. Translate the message into the specified "
                "language in a casual, direct coaching voice. Preserve ||| separators. "
                "Return only the translated text."
            ),
            tools=False,
            max_tokens=220,
            model="claude-haiku-4-5-20251001",
        )
        translated = (result.get("text") or "").strip()
        return translated if translated else text
    except Exception as e:
        logger.error(f"Report translation failed ({language}): {e}")
        return text


def _fmt_day_report(log, prefs, user_name: str, user=None) -> str:
    """
    Conversational end-of-day recap — multi-bubble (|||), in Arnie's voice.
    Deterministic (no LLM cost) but reads like a coach texting, not an app card.
    Closes the day's mission if there was one. Rendered per-platform by the adapter.
    """
    name = (user_name or "").strip()
    cal = round(log.total_calories or 0)
    pro = round(log.total_protein or 0)
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None

    bubbles = []

    # Opener — varies with how the day went
    if cal_t and pro_t:
        cal_ok = abs(cal - cal_t) <= cal_t * 0.1
        pro_ok = pro >= pro_t * 0.9
        if cal_ok and pro_ok and log.workout_completed:
            bubbles.append(f"That's a clean day, {name}. 🔥" if name else "That's a clean day. 🔥")
        elif cal_ok and pro_ok:
            bubbles.append("Solid day on the numbers.")
        else:
            bubbles.append(f"End of day check, {name}." if name else "End of day check.")

    # Calories line
    if cal_t:
        diff = cal - cal_t
        if abs(diff) <= cal_t * 0.1:
            bubbles.append(f"{cal}/{cal_t} cal. Right where you want to be.")
        elif diff < 0:
            bubbles.append(f"{cal}/{cal_t} cal, {abs(diff)} under. Make sure that's on purpose.")
        else:
            bubbles.append(f"{cal}/{cal_t} cal, {diff} over. Not a big deal, just noting it.")
    elif cal:
        bubbles.append(f"{cal} cal logged today.")

    # Protein line — the one that matters most for the goal
    if pro_t:
        if pro >= pro_t * 0.9:
            bubbles.append(f"Protein at {pro}g. Nailed it. 💪")
        elif pro >= pro_t * 0.7:
            bubbles.append(f"Protein landed at {pro}/{pro_t}g. Close, push it earlier tomorrow.")
        else:
            short = pro_t - pro
            bubbles.append(f"Protein only hit {pro}g, {short}g short. That's the one to fix tomorrow.")

    # Training acknowledgment (only if notable)
    if log.workout_completed:
        bubbles.append("And you trained. That's the day. 👊")

    # Close today's mission (the open loop set this morning)
    if user is not None:
        try:
            from core.missions import mission_completed
            done = mission_completed(user, log)
            if done is True:
                bubbles.append(f"And you hit today's mission: {user.active_mission}. 🔥")
            elif done is False:
                bubbles.append(f"Missed today's mission ({user.active_mission}), first thing tomorrow.")
        except Exception:
            pass

    if not bubbles:
        bubbles.append("Quiet day on the log.")
        bubbles.append("Tomorrow we lock in. What's the plan?")

    return "|||".join(bubbles)


async def _run_whoop_sync():
    """Pull latest Whoop data for all connected users (silent — no push notification)."""
    from db.database import AsyncSessionLocal
    from db.queries import get_users_with_whoop
    from api.whoop import sync_user_whoop

    async with AsyncSessionLocal() as db:
        try:
            users = await get_users_with_whoop(db)
        except Exception as e:
            logger.error(f"Whoop sync: failed to get users: {e}")
            return

        total = 0
        for user in users:
            try:
                # Resolve canonical so snapshots land on the right user_id
                from db.queries import resolve_user as _resolve
                canonical = await _resolve(db, user.telegram_id)
                snapshot_uid = canonical.id

                synced = await sync_user_whoop(db, user, days=7,
                                               snapshot_user_id=snapshot_uid)
                total += synced
                # Automatic WHOOP push notification is disabled — recovery data is
                # synced silently and surfaced via the morning briefing and wearable
                # context block instead of a standalone push.
            except Exception as e:
                logger.error(f"Whoop sync/notify failed for user {user.id}: {e}")

    logger.info(f"Whoop sync complete: {total} user-days updated")


async def _run_one_shot_checkin(user_id: int, telegram_id: str, directive: str) -> None:
    """
    Execute a one-shot check-in scheduled by the 'schedule_check_in' tool.
    Generates an LLM nudge using the directive as context, then sends it.
    Fully wrapped — a failure here must never surface to the user.
    """
    try:
        from db.database import AsyncSessionLocal
        from db.queries import reload_user, get_today_log
        from core.llm import chat

        async with AsyncSessionLocal() as db:
            user = await reload_user(db, user_id)
            if not user:
                return
            prefs = user.preferences
            log = await get_today_log(db, user_id, getattr(user, "timezone", "UTC"))
            name = user.name or ""
            cal = round(log.total_calories) if log else 0
            pro = round(log.total_protein) if log else 0
            cal_t = prefs.calorie_target if prefs else None
            pro_t = prefs.protein_target if prefs else None

            prompt = (
                f"Athlete: {name}, goal={user.primary_goal or '?'}\n"
                f"Today: {cal} cal"
                f"{' / ' + str(cal_t) + ' target' if cal_t else ''} | "
                f"{pro}g protein"
                f"{' / ' + str(pro_t) + 'g target' if pro_t else ''} | "
                f"workout {'✓' if (log and log.workout_completed) else '✗'}\n"
                f"Check-in task: {directive}\n"
                f"Send a short, direct coaching message. 1-2 bubbles (split with |||). "
                f"Sound like a real coach following up, not a notification."
            )
            from core.prompts.nudges import NUDGE_SYSTEM
            result = await chat(
                [{"role": "user", "content": prompt}],
                system=NUDGE_SYSTEM,
                tools=False,
                max_tokens=150,
                model="claude-haiku-4-5-20251001",
            )
            msg = (result.get("text") or "").strip()
            if msg:
                await _send_logged(db, user_id, telegram_id, msg, "scheduled_checkin")
    except Exception as e:
        logger.error(f"One-shot check-in failed (user {user_id}): {e}")


def schedule_one_shot_checkin(
    user_id: int,
    telegram_id: str,
    directive: str,
    send_at_local: str,  # HH:MM
    user_timezone: str = "UTC",
) -> bool:
    """
    Schedule a one-time LLM-generated check-in for later today.
    Returns True if scheduled, False if the time is in the past or scheduling fails.
    Only works when the scheduler is running.
    """
    if not _scheduler.running:
        logger.warning("schedule_one_shot_checkin called but scheduler not running")
        return False
    try:
        import pytz as _pytz
        from datetime import datetime as _dt
        tz = _pytz.timezone(user_timezone or "UTC")
        now_local = _dt.now(tz)
        h, m = int(send_at_local.split(":")[0]), int(send_at_local.split(":")[1])
        fire_local = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        if fire_local <= now_local:
            logger.warning(f"schedule_one_shot_checkin: {send_at_local} is in the past for user {user_id}")
            return False
        fire_utc = fire_local.astimezone(_pytz.utc)
        job_id = f"checkin_{user_id}_{send_at_local.replace(':', '')}"
        _scheduler.add_job(
            _run_one_shot_checkin,
            "date",
            run_date=fire_utc,
            args=[user_id, telegram_id, directive],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(f"Scheduled check-in for user {user_id} at {send_at_local} local ({fire_utc} UTC)")
        return True
    except Exception as e:
        logger.error(f"schedule_one_shot_checkin failed for user {user_id}: {e}")
        return False


async def _run_conversation_hooks() -> None:
    """
    Re-ask open conversation_hook questions for users who haven't responded.

    Runs independently of PROACTIVE_MESSAGING_ENABLED — this is conversation
    continuity (Arnie asked something, user went quiet) not a marketing nudge.
    Fires every 30 min; the per-question timing policy (first_delay_h / spacing_h
    / max_follow_ups) in reminders.pending prevents it from being spammy.
    """
    from db.database import AsyncSessionLocal
    from db.queries import (
        get_all_active_users, get_open_pending_questions,
        mark_pending_question_followed_up, resolve_send_target,
        get_recent_conversations, linking_enabled,
    )
    from reminders.pending import select_follow_up

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)
        sent = 0
        from reminders.eligibility import frequency_allows as _freq_allows
        for user in users:
            try:
                if not getattr(user, "onboarding_completed", False):
                    continue
                if _should_skip_linked(user, linking_enabled()):
                    continue

                # Respect the user's reminder_frequency. "none" (Morning only)
                # users opted into a single daily anchor — re-asking dropped
                # questions throughout the day defeats that explicit choice.
                # "light" (Morning & evening) is the floor that allows hooks.
                prefs = getattr(user, "preferences", None)
                if not _freq_allows(prefs, "conversation_hook"):
                    continue

                send_id = await resolve_send_target(db, user)
                if not _allowlist_allows(user.id, user.telegram_id, send_id):
                    continue

                recent_rows = await get_recent_conversations(db, user.id, limit=15)
                mins_since, _, _ = _last_exchange(recent_rows)

                # Never fire mid-conversation.
                if _is_live_convo(mins_since):
                    continue

                open_qs = await get_open_pending_questions(db, user.id)
                hook_qs = [q for q in open_qs
                           if getattr(q, "kind", "") == "conversation_hook"]
                if not hook_qs:
                    continue

                pq = select_follow_up(hook_qs, mins_since_last_exchange=mins_since)
                if pq is None:
                    continue

                name = user.name or "hey"
                msg = await _llm_followup(user, pq, name)
                if not msg:
                    continue

                lang = (getattr(getattr(user, "preferences", None),
                                "preferred_language", None) or "English")
                # Use _send_hook (bypasses PROACTIVE gate) + log it so the silence
                # streak and continuity blocks see the send.
                await _send_hook(send_id, msg)
                await _log_proactive(db, user.id, msg, "followup_conversation_hook")
                await mark_pending_question_followed_up(db, pq.id)
                sent += 1
                logger.info(
                    f"Conversation hook re-ask (tier={pq.tier}, "
                    f"attempt={pq.follow_up_count}) → user {user.id}"
                )
            except Exception as e:
                logger.error(f"Conversation hook error for user {user.id}: {e}")

        if sent:
            logger.info(f"Conversation hooks: sent {sent} re-ask(s) this tick")


def start_scheduler():
    if _scheduler.running:
        return
    # Reminder job only runs when proactive messaging is enabled. _send() also
    # gates every outbound message, so this is belt-and-suspenders.
    if proactive_enabled():
        _scheduler.add_job(
            _run_reminders,
            IntervalTrigger(minutes=30),
            id="proactive_reminders",
            replace_existing=True,
            max_instances=1,
        )
        _allow = _proactive_allowlist()
        reminders_status = (
            f"reminders every 30 min, ALLOWLIST active ({len(_allow)} users only)"
            if _allow else "reminders every 30 min"
        )
    else:
        reminders_status = "reminders DISABLED (PROACTIVE_MESSAGING_ENABLED not set)"
    # Conversation-hook re-asks always run — they're conversation continuity,
    # not proactive nudges, and don't require PROACTIVE_MESSAGING_ENABLED.
    _scheduler.add_job(
        _run_conversation_hooks,
        IntervalTrigger(minutes=30),
        id="conversation_hooks",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.add_job(
        _run_whoop_sync,
        IntervalTrigger(minutes=30),
        id="whoop_sync",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(f"Proactive scheduler started ({reminders_status}, Whoop sync every 30 min)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
