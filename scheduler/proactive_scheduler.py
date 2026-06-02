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


async def _last_exchange(db, user_id):
    """
    Returns (minutes_since_last_message, last_user_text, last_arnie_text).
    minutes is None if the user has never messaged. Used to make proactive
    messages context-aware and to avoid firing on top of a live conversation.
    """
    from db.queries import get_recent_conversations
    from datetime import datetime as _dt
    convs = await get_recent_conversations(db, user_id, limit=1)
    if not convs:
        return None, "", ""
    c = convs[0]
    ts = c.timestamp
    if ts is None:
        return None, (c.raw_message or ""), (c.response or "")
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    mins = (_dt.utcnow() - ts).total_seconds() / 60.0
    return mins, (c.raw_message or ""), (c.response or "")


async def _llm_new_user_nudge(user, log, prefs, slot: str, name: str) -> str:
    """Generate a new-user engagement message via Claude Haiku."""
    from core.llm import chat

    cal = round(log.total_calories) if log else 0
    pro = round(log.total_protein) if log else 0
    foods_logged = len(log.food_entries) if log and log.food_entries else 0
    exercises_logged = len(log.exercise_entries) if log and log.exercise_entries else 0

    lang = getattr(prefs, "preferred_language", None) or "English"
    cal_t = prefs.calorie_target if prefs else None
    pro_t = prefs.protein_target if prefs else None
    instr = _NEW_USER_SLOT_INSTRUCTIONS.get(slot, "Send a brief, personal coaching check-in.")

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


async def _llm_nudge(user, log, prefs, health_snap, slot: str, name: str) -> str:
    """Generate a personalized nudge via Claude Haiku. Returns '' on failure."""
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
        return (result.get("text") or "").strip()
    except Exception as e:
        logger.error(f"LLM nudge ({slot}) failed: {e}")
        return ""


_BRIEFING_SYSTEM = """\
You are Arnie sending a morning performance briefing, the message that makes the
user glad to hear from you. Not generic motivation: clarity and one clear action.

Rules:
- sentence case, like a real person texting. 2-4 short bubbles split with |||.
- lead with what matters: their trend or momentum, stated with a real number.
- if a notable pattern or projection is given, weave ONE in, make them go "huh, didn't notice that".
- end with the single highest-leverage action for today, framed as a small mission.
- close on a question or the mission so they reply. never generic ("have a great day!").
- match their preferred language. return only the message text with ||| separators.\
"""


async def _llm_morning_briefing(user, log, prefs, health_snap, db, name: str,
                                last_user_msg: str = "", last_arnie_msg: str = "") -> str:
    """Data-rich morning briefing: momentum + trend + projection + pattern + leverage action."""
    from core.llm import chat
    from db.queries import get_recent_logs, get_recent_weights
    from core.momentum import compute_momentum
    from core.insights_engine import weight_projection, discover_pattern

    logs = await get_recent_logs(db, user.id, days=21)
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
    if m: data.append(f"Momentum: {m.score}/100 ({m.tier}, {m.direction}); drivers: {', '.join(m.drivers) or 'n/a'}")
    if trend: data.append(trend)
    if projection: data.append(f"Projection: {projection}")
    if pattern: data.append(f"Pattern noticed: {pattern}")
    if cal_t: data.append(f"Calorie target {cal_t}, protein target {pro_t}")
    if rec is not None: data.append(f"Recovery today: {rec}%")
    if mission_text: data.append(f"TODAY'S MISSION (end the briefing with this as the action): {mission_text}")
    if last_user_msg or last_arnie_msg:
        data.append(f"Last thing they told you: \"{last_user_msg[:140]}\" — you replied: \"{last_arnie_msg[:140]}\". "
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
    await _send(user.telegram_id, msg)
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
    prompt = (
        f"Athlete: {name}, language={lang}\n"
        f"Earlier you asked them this and they never answered:\n"
        f"  \"{pq.question}\"\n"
        f"Circle back and re-ask it ONCE, naturally — like a friend who genuinely "
        f"wants to know, not a form re-prompt. {tone}\n"
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
        return (result.get("text") or "").strip()
    except Exception as e:
        logger.error(f"Follow-up generation failed for user {user.id}: {e}")
        return ""


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
        await _send(send_id, msg)
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
                continue

            # Route this user's proactive messages to their preferred platform
            # (set when they linked both). Falls back to their own identity.
            send_id = await resolve_send_target(db, user)

            # ── Safe-rollout allowlist ────────────────────────────────────────
            # Skip non-allowlisted users early so we don't burn LLM calls generating
            # nudges they'll never receive. _send() also gates as a hard backstop.
            if not _allowlist_allows(user.id, user.telegram_id, send_id):
                continue

            # ── Context awareness: never fire on top of a live conversation ───
            # If the user exchanged messages with Arnie in the last ~25 min, they're
            # already engaged — a scheduled nudge would be a jarring non-sequitur.
            # Skip this tick; it re-checks 30 min later when the thread's gone quiet.
            mins_since, _last_u, _last_a = None, "", ""
            try:
                mins_since, _last_u, _last_a = await _last_exchange(db, user.id)
                if _is_live_convo(mins_since):
                    continue
            except Exception:
                pass

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
                continue

            # ── Weekly recap (Sunday 18:00–18:30, once per week) ──────────────
            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                iso_week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
                if (now.weekday() == 6 and now.hour == 18 and now.minute < 30
                        and prefs and prefs.proactive_messaging_enabled
                        and user.weekly_recap_week != iso_week):
                    name = user.name or "hey"
                    recap = await _llm_weekly_recap(user, prefs, db, name)
                    if recap:
                        await _send(send_id, recap)
                        user.weekly_recap_week = iso_week
                        await db.commit()
                        continue
            except Exception as e:
                logger.error(f"Weekly recap error for user {user.id}: {e}")

            # ── End-of-day report (21:00–21:30) — ALL onboarded users ─────────
            # Kept inside the 9am-9pm window so we never message late at night.
            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                hour, minute = now.hour, now.minute

                if hour == 21 and minute < 30:
                    log = await get_today_log(db, user.id, user.timezone or "UTC")
                    if log and log.total_calories > 0:
                        name = user.name or "hey"
                        report = _fmt_day_report(log, prefs, name, user=user)
                        await _send(send_id, report)
                        continue
            except Exception as e:
                logger.error(f"Day report error for user {user.id}: {e}")

            # Proactive nudges — default ON for all onboarded users
            if not _proactive_pref_on(prefs):
                continue

            try:
                tz = pytz.timezone(user.timezone or "UTC")
                now = datetime.now(tz)
                hhmm = now.strftime("%H:%M")
                hour, minute = now.hour, now.minute

                # Hard-cap the proactive window to 9am-9pm local, even if the
                # user's stored wake/sleep is wider. Respects a TIGHTER personal
                # window (e.g. wake 10:00) but never sends before 9am or after 9pm.
                wake, sleep = _clamp_window(prefs)
                if not _in_window(hhmm, wake, sleep):
                    continue

                log = await get_today_log(db, user.id, user.timezone or "UTC")
                name = user.name or "hey"

                # Get latest health snapshot (today's if available, else most recent)
                health_snaps = await get_recent_health_snapshots(db, user.id, days=2)
                health_snap = health_snaps[0] if health_snaps else None

                day_pct = _pacing_pct(hour, minute, wake, sleep)

                # ── Context-aware follow-up: re-ask an unanswered open question ──
                # Highest priority inside the window — a hanging question Arnie
                # asked outranks a generic slot nudge. The reminders layer picks
                # the one due question (tier-scaled timing) and we re-ask it once.
                if await _maybe_followup_pending(db, user, send_id, name, mins_since):
                    continue  # one proactive message per tick

                # ── New user engagement burst (first 72 hours post-onboarding) ──
                # Fires at fixed intervals after account creation. Independent of
                # daily time slots. Uses a separate LLM persona focused on learning
                # about the user and building early engagement. Falls off after 48h.
                if user.onboarding_completed and user.created_at:
                    hours_since = _hours_since_created(user)

                    if hours_since <= 50.0:
                        # Persisted across deploys via user.nudges_sent (comma-separated)
                        sent_slots = set(
                            s for s in (user.nudges_sent or "").split(",") if s
                        )

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
                            msg = await _llm_new_user_nudge(user, log, prefs, new_slot, name)
                            if msg:
                                await _send(send_id, msg)
                                # Persist the fired slot so it never re-fires after a deploy
                                sent_slots.add(new_slot)
                                user.nudges_sent = ",".join(sorted(sent_slots))
                                await db.commit()
                            logger.info(f"New user nudge '{new_slot}' sent to user {user.id} ({hours_since:.1f}h in)")
                            continue  # skip normal slots this tick — avoid message flood

                # ── Morning check-in (30 min after wake) ──────────────────────
                wake_h, wake_m = int(wake.split(":")[0]), int(wake.split(":")[1])
                morn_h, morn_m = wake_h, wake_m + 30
                if morn_m >= 60:
                    morn_h += 1
                    morn_m -= 60

                if hour == morn_h and 0 <= minute - morn_m < 30:
                    if not log or log.total_calories == 0:
                        # Data-rich performance briefing (momentum + trend + leverage action)
                        msg = await _llm_morning_briefing(user, log, prefs, health_snap, db, name,
                                                          last_user_msg=_last_u, last_arnie_msg=_last_a)
                        if not msg:
                            msg = await _llm_nudge(user, log, prefs, health_snap, "morning_checkin", name)
                        if not msg:
                            msg = f"morning {name}.|||log your weight if you've got it, then tell me breakfast."
                        await _send(send_id, msg)

                # ── Late morning (10:00–10:30, only if nothing logged) ─────────
                elif hour == 10 and minute < 30:
                    if not log or log.total_calories < 50:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "late_morning_nolog", name)
                        if not msg:
                            msg = f"10am and nothing logged yet, {name}. Skipped breakfast or just haven't told me?"
                        await _send(send_id, msg)

                # ── Midday pacing (12:00–12:30) ────────────────────────────────
                elif hour == 12 and minute < 30:
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
                            msg = await _llm_nudge(user, log, prefs, health_snap, "midday_pacing", name)
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
                            await _send(send_id, msg)
                        elif log and log.total_calories > 0:
                            # On track — brief positive
                            msg = await _llm_nudge(user, log, prefs, health_snap, "midday_pacing", name)
                            if msg:
                                await _send(send_id, msg)

                # ── Pre-workout readiness (15:30–16:00) ───────────────────────
                elif hour == 15 and 30 <= minute < 60:
                    # Skip if workout done or exercises are already being logged (mid-workout)
                    exercises_in_progress = log and len(log.exercise_entries or []) > 0
                    if log and not log.workout_completed and not exercises_in_progress:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "preworkout", name)
                        if not msg:
                            rec = health_snap.recovery_score if health_snap else None
                            if rec is not None and rec < 34:
                                msg = (
                                    f"Recovery's in the red today ({rec}%), {name}. "
                                    f"Still training? Might be worth going lighter."
                                )
                            else:
                                msg = f"3:30 — workout not logged yet, {name}. Still on for today?"
                        await _send(send_id, msg)

                # ── Afternoon workout check (16:30–17:00) ────────────────────
                elif hour == 16 and 30 <= minute < 60:
                    # Skip if workout done or exercises are already being logged (mid-workout)
                    exercises_in_progress = log and len(log.exercise_entries or []) > 0
                    if log and not log.workout_completed and not exercises_in_progress:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "workout_check", name)
                        if not msg:
                            msg = f"4:30 — workout still hasn't happened, {name}. Happening today or are we calling it a rest day?"
                        await _send(send_id, msg)

                # ── Evening pacing (19:00–19:30) ──────────────────────────────
                elif hour == 19 and minute < 30 and log and log.total_calories > 0:
                    msg = await _llm_nudge(user, log, prefs, health_snap, "evening_pacing", name)
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
                    await _send(send_id, msg)

                # ── Night closeout (21:00–21:30) ──────────────────────────────
                elif hour == 21 and minute < 30:
                    if log and log.status == "open" and log.total_calories > 0:
                        msg = await _llm_nudge(user, log, prefs, health_snap, "night_closeout", name)
                        if not msg:
                            msg = "Day still open. Done eating? Send me anything you missed and close it out."
                        await _send(send_id, msg)

            except Exception as e:
                logger.error(f"Reminder error for user {user.id}: {e}")


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
    """Pull latest Whoop data for all connected users and send notifications for new recovery data."""
    from db.database import AsyncSessionLocal
    from db.queries import get_users_with_whoop, get_recent_health_snapshots
    from api.whoop import sync_user_whoop

    today_str = str(date.today())

    async with AsyncSessionLocal() as db:
        try:
            users = await get_users_with_whoop(db)
        except Exception as e:
            logger.error(f"Whoop sync: failed to get users: {e}")
            return

        total = 0
        for user in users:
            try:
                old_snaps = await get_recent_health_snapshots(db, user.id, days=1)
                old_recovery = old_snaps[0].recovery_score if old_snaps else None

                synced = await sync_user_whoop(db, user, days=2)
                total += synced

                if synced > 0 and user.telegram_id:
                    new_snaps = await get_recent_health_snapshots(db, user.id, days=1)
                    if new_snaps:
                        snap = new_snaps[0]
                        # Persisted dedup — one recovery ping per user per day, survives deploys
                        already = (user.whoop_last_notified == f"{today_str}:{snap.recovery_score}")
                        if (snap.recovery_score is not None
                                and snap.recovery_score != old_recovery
                                and not already):
                            user.whoop_last_notified = f"{today_str}:{snap.recovery_score}"
                            await db.commit()
                            msg = _fmt_whoop_notification(snap)
                            if msg:
                                await _send(user.telegram_id, msg)
            except Exception as e:
                logger.error(f"Whoop sync/notify failed for user {user.id}: {e}")

    logger.info(f"Whoop sync complete: {total} user-days updated")


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
    _scheduler.add_job(
        _run_whoop_sync,
        IntervalTrigger(hours=2),
        id="whoop_sync",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(f"Proactive scheduler started ({reminders_status}, Whoop sync every 2 hr)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
