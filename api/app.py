"""
FastAPI app — runs alongside the Telegram bot in the same process.
Exposes:
  GET  /health                  — health check
  GET  /dashboard/{token}       — read-only user dashboard (HTML)
  GET  /api/stats/{token}       — dashboard data (JSON)
  POST /health/apple?token=...  — Apple Health inbound webhook
"""
import asyncio
import os
import hmac
import html
import logging
from datetime import date, timedelta, datetime
from typing import Optional

import stripe
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from api.templates import _dashboard_html, _apple_guide_html
from api.brain_page import _brain_html
from api.brain_insights import generate_lobe_insight
from core.urls import dashboard_url
from pydantic import BaseModel, field_validator

from db.database import AsyncSessionLocal
from db.queries import (
    get_user_by_webhook_token, upsert_health_snapshot,
    get_today_log, get_log_by_date, get_recent_logs, get_recent_weights,
    get_recent_health_snapshots,
    update_food_entry, delete_food_entry,
    update_exercise_entry, delete_exercise_entry,
    add_food_entry, add_exercise_entry, add_body_metric,
    get_or_create_today_log, get_or_create_log_for_date,
    resolve_send_target,
    _user_today,
    set_subscription_active, set_subscription_cancelled,
)
from api.usda import search_food as _usda_search

logger = logging.getLogger(__name__)


def _esc(s: object) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


app = FastAPI(title="Arnie API", docs_url=None, redoc_url=None)


def _require_admin(token: str) -> None:
    """
    Gate an admin endpoint. FAILS CLOSED: if ADMIN_TOKEN is unset, admin is disabled
    (503) rather than accepting an empty token. Constant-time compare avoids leaking
    the token via timing. Raises HTTPException on any failure; returns None on success.
    """
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin disabled (ADMIN_TOKEN unset)")
    if not hmac.compare_digest(token or "", expected):
        raise HTTPException(status_code=403, detail="Forbidden")

# CORS — allow the landing page (separate Render static service) to POST the
# iMessage signup form to this API.
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tryarnie.com", "https://www.tryarnie.com",
        "https://arnie-landing.onrender.com",
        # Local dev — landing page is served from the same FastAPI origin
        "http://localhost:10000",
        "http://127.0.0.1:10000",
    ],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

# Native API (iOS app) — auth (sign-in) + chat + dashboard data endpoints
from api.auth_routes import router as auth_router
from api.chat import router as chat_router
from api.health_sync import router as health_sync_router
from api.food_edit import router as food_edit_router
from api.exercise_edit import router as exercise_edit_router
from api.dashboard_api import router as dashboard_api_router
from api.devices import router as devices_router
from api.water import router as water_router
from api.profile_edit import router as profile_edit_router
from api.settings_api import prefs_router, feedback_router, signout_router
from api.insights_api import router as insights_api_router
from api.quick_log import router as quick_log_router
from api.whoop_api import router as whoop_api_router
from api.location_api import router as location_api_router
from api.diagnostics import router as diagnostics_router
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(dashboard_api_router)
app.include_router(health_sync_router)
app.include_router(food_edit_router)
app.include_router(exercise_edit_router)
app.include_router(devices_router)
app.include_router(water_router)
app.include_router(profile_edit_router)
app.include_router(prefs_router)
app.include_router(feedback_router)
app.include_router(signout_router)
app.include_router(insights_api_router)
app.include_router(quick_log_router)
app.include_router(whoop_api_router)
app.include_router(location_api_router)
app.include_router(diagnostics_router)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "Arnie Bot"}


@app.get("/health")
async def healthcheck():
    # Build-stamp: Render injects RENDER_GIT_COMMIT/BRANCH at runtime, so this tells
    # us EXACTLY which commit the live container is running (vs. what's on origin).
    return {
        "status": "ok",
        "commit": os.getenv("RENDER_GIT_COMMIT", "unknown")[:12],
        "branch": os.getenv("RENDER_GIT_BRANCH", "unknown"),
    }


# Favicon served by the app itself, so the dashboard's relative /favicon.png resolves
# on whatever host serves it (app.tryarnie.com or the service host). Source asset is
# the brand favicon shipped in the repo (landing/favicon.png).
_FAVICON_PATH = os.path.join(os.path.dirname(__file__), "..", "landing", "favicon.png")


@app.get("/favicon.png", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if os.path.exists(_FAVICON_PATH):
        return FileResponse(
            _FAVICON_PATH, media_type="image/png",
            headers={"Cache-Control": "public, max-age=604800"},  # 7 days
        )
    raise HTTPException(status_code=404, detail="not found")


# ── Stripe Webhooks ────────────────────────────────────────────────────────────

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Receive Stripe events and update subscription status in the DB."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    # Fail closed: never process a payment webhook without verification material.
    if not webhook_secret:
        logger.error("Stripe webhook hit but STRIPE_WEBHOOK_SECRET is unset — rejecting.")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    async with AsyncSessionLocal() as db:
        if event_type == "checkout.session.completed":
            telegram_id = data.get("metadata", {}).get("telegram_id")
            customer_id = data.get("customer")
            subscription_id = data.get("subscription")
            if telegram_id and customer_id and subscription_id:
                sub = stripe.Subscription.retrieve(subscription_id)
                period_end = datetime.utcfromtimestamp(sub["current_period_end"])
                await set_subscription_active(db, telegram_id, customer_id, period_end)
                await _notify_payment_success(telegram_id)
                logger.info(f"Subscription activated: telegram_id={telegram_id}")

        elif event_type == "customer.subscription.deleted":
            customer_id = data.get("customer")
            if customer_id:
                telegram_id = await set_subscription_cancelled(db, customer_id)
                if telegram_id:
                    await _notify_subscription_cancelled(telegram_id)
                    logger.info(f"Subscription cancelled: customer={customer_id}")

        elif event_type == "invoice.payment_failed":
            logger.warning(f"Payment failed for customer: {data.get('customer')}")

    return {"ok": True}


async def _notify_payment_success(telegram_id: str) -> None:
    """Send a confirmation DM via the bot when payment succeeds."""
    try:
        ptb_app = app.state.ptb_app
        await ptb_app.bot.send_message(
            chat_id=int(telegram_id),
            text=(
                "You're on <b>Arnie Premium</b> 🎉\n\n"
                "Full coaching, unlimited memory, proactive check-ins — all unlocked.\n\n"
                "Use /billing anytime to manage your subscription."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Could not notify user {telegram_id} of payment: {e}")


async def _notify_subscription_cancelled(telegram_id: str) -> None:
    """Send a DM when a subscription is cancelled."""
    try:
        ptb_app = app.state.ptb_app
        await ptb_app.bot.send_message(
            chat_id=int(telegram_id),
            text=(
                "Your Arnie Premium subscription has been cancelled.\n\n"
                "You still have access until the end of your billing period. "
                "Use /upgrade anytime to resubscribe."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Could not notify user {telegram_id} of cancellation: {e}")


# ── Dashboard change notifications ────────────────────────────────────────────

def _dashboard_msg(action: str, **kw) -> str:
    """Build a short Arnie-voice confirmation for a dashboard edit. Returns ||| text."""
    label = kw.get("label", "")
    cal = kw.get("cal", 0)
    cal_t = kw.get("cal_target")
    cal_str = f"{cal}/{cal_t}" if cal_t else str(cal)
    if action == "food_edit":
        return f"updated {label}.|||sitting at {cal_str} cal today."
    if action == "food_delete":
        return f"pulled {label} off the log.|||{cal_str} cal on the day."
    if action == "exercise_edit":
        name = f" {label}" if label else ""
        return f"updated{name} in your training log. how'd the session go?"
    if action == "exercise_delete":
        name = label if label else "that"
        return f"pulled {name} from your training log."
    if action == "profile_targets":
        return f"new targets locked in.|||{label}"
    if action == "profile_reminders_on":
        return "check-ins back on, i'll be in touch."
    if action == "profile_reminders_off":
        return "going quiet. ping me when you need."
    if action == "profile_quick":
        return "quick mode on, logging without the back and forth from now."
    if action == "profile_strict":
        return "strict mode on, i'll confirm before anything goes in."
    if action == "profile_field":
        return f"updated your {label}."
    if action == "weight_log":
        # Goal/delta-aware reaction to a dashboard weigh-in. Kept short and in
        # Arnie's voice (lower-case, no emoji), with a second bubble after |||
        # that adds context only when we actually have it. Inputs:
        #   label      — formatted weight, e.g. "182.4 lbs"
        #   goal       — 'cut' | 'bulk' | other
        #   prev_lbs   — most recent prior weigh-in in lbs (None if first ever)
        #   delta_lbs  — current - prev (signed); ignored if prev_lbs is None
        #   to_goal    — abs distance remaining to goal_weight_lbs (None if no goal)
        goal_v = kw.get("goal") or ""
        prev = kw.get("prev_lbs")
        delta = kw.get("delta_lbs")
        to_goal = kw.get("to_goal")
        first = f"logged you at {label}."
        # Subtle "you can text me too" hint, on its own bubble. Fires only on
        # the user's first-ever weigh-in (no prior BodyMetric → prev_lbs is
        # None) — after that they either already use chat or have decided the
        # dashboard is their lane. Suppressing on subsequent logs is the
        # "not repetitive" requirement.
        if prev is None or delta is None:
            tail = "first weigh-in saved — i'll watch the trend from here."
            hint = "you can also just text me the number next time, same thing."
            return f"{first}|||{tail}|||{hint}"
        adelta = abs(delta)
        # < 0.3 lbs of movement reads as noise on most scales; don't over-narrate.
        if adelta < 0.3:
            tail = "basically flat from last time — that's still data."
        else:
            right_way = (goal_v == "cut" and delta < 0) or (goal_v == "bulk" and delta > 0)
            direction = "down" if delta < 0 else "up"
            if right_way:
                tail = f"{direction} {adelta:.1f} from last time — that's the direction we want."
            else:
                # Wrong way for the goal, or no goal set. Stay even-keeled — one
                # data point isn't a trend, and Arnie shouldn't sound alarmed.
                if goal_v in ("cut", "bulk"):
                    tail = f"{direction} {adelta:.1f} from last time — one read, not a trend. keep logging."
                else:
                    tail = f"{direction} {adelta:.1f} from last time."
        if to_goal is not None and to_goal > 0:
            tail += f" {to_goal:.1f} to go."
        return f"{first}|||{tail}"
    return ""


async def _send_dashboard_notification(send_target: str, text: str) -> None:
    """
    Send a dashboard-change confirmation on the user's preferred channel.
    No proactive gate — this is reactive confirmation of a user action.
    """
    if not text or not send_target:
        return
    try:
        from core.platform import Response, IMessageAdapter, TelegramAdapter
        resp = Response.from_text(text)
        if send_target.startswith("im:"):
            address = send_target[3:]
            await IMessageAdapter(f"iMessage;-;{address}").send(resp)
        else:
            ptb_app = app.state.ptb_app
            await TelegramAdapter(ptb_app.bot, int(send_target)).send(resp)
    except Exception as e:
        logger.warning(f"dashboard notification failed for {send_target}: {e}")


# ── Whoop OAuth ────────────────────────────────────────────────────────────────

@app.get("/whoop/callback", response_class=HTMLResponse)
async def whoop_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Whoop redirects here after user authorizes. Exchange code for tokens."""
    if error:
        # `error` comes straight from the URL — escape it (reflected XSS otherwise).
        return HTMLResponse(
            f"<h2>Whoop connection failed</h2><p>Error: {html.escape(error)}</p>"
            f"<p>You can try again in Telegram with /connect whoop</p>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse("<h2>Missing code or state.</h2>", status_code=400)

    from api.whoop import exchange_code, sync_user_whoop
    from db.queries import set_whoop_tokens
    from datetime import datetime, timedelta

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    redirect_uri = f"{base_url}/whoop/callback"

    result = await exchange_code(code, redirect_uri)

    # If Whoop says "code already used" but the user already has valid tokens
    # from a previous (successful) exchange, treat this as success instead of
    # an error. This handles browser back/refresh after a working connection.
    if not result.get("ok") and "already been used" in (result.get("details") or "").lower():
        async with AsyncSessionLocal() as db:
            # Whoop tokens live on the raw token-owner row, not the canonical
            # linked account — keep follow_link=False so the OAuth flow is
            # unchanged by the dashboard canonicalization.
            existing_user = await get_user_by_webhook_token(db, state, follow_link=False)
            if existing_user and existing_user.whoop_refresh_token:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Whoop already connected</title>
<style>body{font-family:system-ui;text-align:center;padding:60px 20px;background:#0f1117;color:#f1f5f9}
.box{max-width:480px;margin:auto;background:#1a1d27;border:1px solid #2e3347;border-radius:12px;padding:32px}
.check{font-size:48px;color:#22c55e}h1{font-size:24px;margin:16px 0}p{color:#94a3b8;margin:8px 0}</style>
</head><body>
<div class="box">
  <div class="check">✓</div>
  <h1>Already connected</h1>
  <p>Your Whoop is already linked. No action needed.</p>
  <p style="margin-top:20px">Run <b>/whoop</b> in Telegram to see your status.</p>
</div></body></html>""")

    if not result.get("ok"):
        # Escape everything interpolated into the HTML below (defense in depth).
        err = html.escape(str(result.get("error", "Unknown error")))
        details = html.escape(str(result.get("details", "")))
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Whoop connection failed</title>
<style>body{{font-family:system-ui;text-align:left;padding:40px;background:#0f1117;color:#f1f5f9;max-width:640px;margin:auto}}
.box{{background:#1a1d27;border:1px solid #2e3347;border-radius:12px;padding:24px}}
h1{{font-size:22px;margin:0 0 12px;color:#ef4444}}
code{{background:#0f1117;padding:2px 6px;border-radius:4px;font-size:12px;color:#94a3b8;display:block;padding:12px;margin-top:8px;white-space:pre-wrap;word-break:break-all}}
.next{{margin-top:20px;padding-top:16px;border-top:1px solid #2e3347;color:#94a3b8}}</style>
</head><body><div class="box">
<h1>Whoop connection failed</h1>
<p><b>Error:</b> {err}</p>
{f'<code>{details}</code>' if details else ''}
<div class="next">
  <p><b>Common causes:</b></p>
  <ul style="color:#94a3b8;line-height:1.7">
    <li>The auth code already expired (they're one-time, ~30 seconds) — try /connect whoop again</li>
    <li>WHOOP_CLIENT_ID or WHOOP_CLIENT_SECRET env var on Render is wrong or missing</li>
    <li>The Redirect URL in Whoop's developer dashboard doesn't exactly match this server's URL</li>
  </ul>
</div></div></body></html>""", status_code=400)

    tokens = result["tokens"]
    user_id_for_sync = None
    async with AsyncSessionLocal() as db:
        # Store Whoop tokens on the raw token-owner row (follow_link=False),
        # matching where the OAuth flow has always written them.
        user = await get_user_by_webhook_token(db, state, follow_link=False)
        if not user:
            return HTMLResponse("<h2>Invalid state — user not found.</h2>", status_code=401)

        expires_at = datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        await set_whoop_tokens(
            db, user.id,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            expires_at=expires_at,
        )
        user_id_for_sync = user.id

    # Kick off the initial sync in the background — DON'T block the response.
    # Whoop's three API calls together can take 30+ seconds and Render's
    # load balancer will 502 if the response doesn't come back in time.
    import asyncio
    asyncio.create_task(_background_initial_sync(user_id_for_sync, user.telegram_id))

    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Whoop connected</title>
<style>body{{font-family:system-ui;text-align:center;padding:60px 20px;background:#0f1117;color:#f1f5f9}}
.box{{max-width:480px;margin:auto;background:#1a1d27;border:1px solid #2e3347;border-radius:12px;padding:32px}}
.check{{font-size:48px;color:#22c55e}}h1{{font-size:24px;margin:16px 0}}p{{color:#94a3b8;margin:8px 0}}</style>
</head><body>
<div class="box">
  <div class="check">✓</div>
  <h1>Whoop connected</h1>
  <p>Tokens saved. I'm pulling your last 7 days of data in the background — should be ready in 30 seconds or so.</p>
  <p style="margin-top:20px">Head back to Telegram and run <b>/whoop</b> to see your latest snapshot.</p>
</div></body></html>""")


async def _background_initial_sync(user_id: int, telegram_id: str = ""):
    """Run the initial Whoop data pull after the OAuth callback has returned."""
    import logging
    import os
    logger = logging.getLogger(__name__)
    from api.whoop import sync_user_whoop
    try:
        async with AsyncSessionLocal() as db:
            from db.queries import reload_user
            user = await reload_user(db, user_id)
            synced = await sync_user_whoop(db, user, days=7)
            logger.info(f"Background Whoop sync: user {user_id} → {synced} days")

            # Determine which Telegram ID to notify. If the canonical user is an
            # iMessage identity (telegram_id starts with "im:"), find a linked
            # Telegram account to send the notification to instead.
            notify_id = telegram_id
            if notify_id and notify_id.startswith("im:"):
                from sqlalchemy import select as sa_select
                from db.models import User as _User
                linked_tg = (await db.execute(
                    sa_select(_User).where(
                        _User.linked_to_user_id == user_id,
                        _User.telegram_id.not_like("im:%"),
                    )
                )).scalars().first()
                notify_id = linked_tg.telegram_id if linked_tg else ""
                if notify_id:
                    logger.info(f"Whoop sync: routing notification to linked TG {notify_id[:8]}...")

            if notify_id:
                snaps = await get_recent_health_snapshots(db, user_id, days=1)
                snap = snaps[0] if snaps else None
                from telegram import Bot
                bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN", ""))
                if snap and snap.recovery_score is not None:
                    rec = snap.recovery_score
                    emoji = "🟢" if rec >= 67 else ("🟡" if rec >= 34 else "🔴")
                    parts = [f"✅ <b>Whoop connected + synced!</b>", ""]
                    parts.append(f"{emoji} Recovery: <b>{rec}%</b>")
                    if snap.hrv:
                        parts.append(f"HRV: {snap.hrv:.0f}ms  |  RHR: {snap.resting_hr:.0f}bpm" if snap.resting_hr else f"HRV: {snap.hrv:.0f}ms")
                    if snap.sleep_hours:
                        s = f"Sleep: {snap.sleep_hours:.1f}h"
                        extras = []
                        if snap.sleep_deep_hours:
                            extras.append(f"deep {snap.sleep_deep_hours:.1f}h")
                        if snap.sleep_rem_hours:
                            extras.append(f"REM {snap.sleep_rem_hours:.1f}h")
                        if extras:
                            s += f" ({', '.join(extras)})"
                        parts.append(s)
                    if snap.strain is not None:
                        parts.append(f"Strain: {snap.strain:.1f}")
                    await bot.send_message(chat_id=notify_id, text="\n".join(parts), parse_mode="HTML")
                else:
                    await bot.send_message(
                        chat_id=notify_id,
                        text="✅ <b>Whoop connected!</b>\n\nPulled your last 7 days. Recovery scores will show once Whoop processes your sleep data — usually by 9am.",
                        parse_mode="HTML"
                    )
                await bot.close()
    except Exception as e:
        logger.error(f"Background Whoop sync failed for user {user_id}: {e}")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """Minimal privacy policy required by Whoop / Apple Health OAuth."""
    return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Arnie — Privacy Policy</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;line-height:1.6;color:#222}h1{font-size:24px}h2{font-size:18px;margin-top:28px}</style>
</head><body>
<h1>Arnie — Privacy Policy</h1>
<p><em>Last updated: 2026</em></p>

<h2>What Arnie collects</h2>
<p>Arnie is a personal fitness and nutrition coaching bot. With your consent, Arnie collects:</p>
<ul>
<li>Profile information you provide during onboarding (name, age, sex, height, weight, goals, training experience, dietary preferences, injuries).</li>
<li>Food, exercise, body-weight, and water entries you log via chat, voice, or photos.</li>
<li>Wearable data you choose to connect (e.g. WHOOP recovery and sleep, Apple Health metrics).</li>
<li>Conversation history with the bot, used to provide context-aware coaching.</li>
</ul>

<h2>How Arnie uses your data</h2>
<p>Your data is used solely to:</p>
<ul>
<li>Track your nutrition, training, and recovery over time.</li>
<li>Provide personalized coaching responses, pacing reminders, and progress insights.</li>
<li>Display your data back to you via the Telegram chat and your personal dashboard.</li>
</ul>
<p>Your data is never sold, shared with advertisers, or used to train any external models.</p>

<h2>Where your data is stored</h2>
<p>Data is stored on a private server (Render.com) in an encrypted database accessible only by you (via your unique Telegram account and personal dashboard token). Conversation history is processed by Anthropic's Claude API to generate coaching responses; per Anthropic's policy, API data is not used for model training.</p>

<h2>Third-party services Arnie uses</h2>
<ul>
<li><strong>Telegram</strong> — the chat platform itself.</li>
<li><strong>Anthropic Claude</strong> — generates coaching responses.</li>
<li><strong>OpenAI</strong> — used for voice transcription (Whisper) and optional image generation (DALL-E).</li>
<li><strong>WHOOP</strong> (if you connect it) — fitness wearable data.</li>
<li><strong>Apple Health</strong> (if you connect it) — fitness wearable data, sent via your own iOS Shortcut.</li>
</ul>

<h2>Your rights</h2>
<p>You can:</p>
<ul>
<li>Clear today's log with <code>/reset today</code>.</li>
<li>Permanently delete all your data with <code>/reset all confirm</code>.</li>
<li>Disconnect WHOOP or revoke its access from your WHOOP account at any time.</li>
<li>Stop using Arnie by blocking the bot in Telegram.</li>
</ul>

<h2>Contact</h2>
<p>For any privacy questions or to request data deletion, contact the Arnie developer through the GitHub repository.</p>
</body></html>""")


# ── Telegram webhook ───────────────────────────────────────────────────────────

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    """Receive updates from Telegram (production webhook mode).

    Returns 200 immediately and processes the update in a background task so
    Telegram doesn't hit its 15s webhook timeout and retry. Deduplicates by
    update_id in case a retry slips through anyway (network blip, the prior
    pod still warming, an old code path).
    """
    if token != os.getenv("TELEGRAM_BOT_TOKEN", ""):
        raise HTTPException(status_code=403, detail="Forbidden")

    ptb_app = getattr(request.app.state, "ptb_app", None)
    if ptb_app is None:
        raise HTTPException(status_code=503, detail="Bot not ready")

    from telegram import Update
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)

    # Dedup by update_id with a 10-min eviction window — same shape as the
    # iMessage _seen_guids gate. Telegram MAY redeliver the same update_id on
    # any retry; processing it twice means two LLM calls and two replies.
    import time as _time
    _now = _time.time()
    _seen = getattr(request.app.state, "_seen_tg_updates", {})
    _seen = {k: v for k, v in _seen.items() if _now - v < 600}
    uid = getattr(update, "update_id", None)
    if uid is not None and (_now - _seen.get(uid, 0)) < 600:
        logger.info(f"Telegram webhook: duplicate update_id={uid} skipped")
        request.app.state._seen_tg_updates = _seen
        return {"ok": True}
    if uid is not None:
        _seen[uid] = _now
    request.app.state._seen_tg_updates = _seen

    # Hold a reference to the task so it isn't garbage-collected mid-run.
    # Without this, Python may collect the task before process_update finishes
    # and the LLM call dies silently. Use a per-app set, prune as tasks finish.
    _tasks = getattr(request.app.state, "_tg_bg_tasks", set())
    task = asyncio.create_task(ptb_app.process_update(update))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    request.app.state._tg_bg_tasks = _tasks
    return {"ok": True}


# ── BlueBubbles / iMessage webhook ────────────────────────────────────────────

@app.post("/imessage")
async def imessage_webhook(request: Request):
    """
    Receive incoming iMessages from BlueBubbles Server.

    BlueBubbles sends a POST to this endpoint for every new message event.
    We return 200 immediately, then process in the background so BlueBubbles
    doesn't retry on slow LLM responses.

    Payload shape (relevant fields):
      {
        "type": "new-message",
        "data": {
          "text": "...",
          "isFromMe": false,
          "handle": { "address": "+15551234567" },
          "chats": [{ "guid": "iMessage;-;+15551234567", "isGroup": false }]
        }
      }
    """
    raw_body = await request.body()

    # Signature verification (optional but recommended in production)
    from bot.imessage_handler import verify_bb_signature
    sig = request.headers.get("X-Bluebubbles-Signature", "")
    if not verify_bb_signature(raw_body, sig):
        logger.warning("BlueBubbles webhook signature mismatch — request rejected")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Debug: log every incoming webhook so we can see what BlueBubbles sends.
    # Includes attachment mimeType/name so voice-note delivery is diagnosable.
    _dbg = payload.get("data", {})
    _atts = _dbg.get("attachments") or []
    _att_dbg = [
        {"mime": a.get("mimeType"), "name": a.get("transferName")}
        for a in _atts if isinstance(a, dict)
    ][:3]
    logger.info(
        f"BB webhook: type={payload.get('type')} keys={list(_dbg.keys())[:8]} "
        f"isFromMe={_dbg.get('isFromMe')} text={str(_dbg.get('text', ''))[:60]} "
        f"attachments={_att_dbg}"
    )

    event_type = payload.get("type", "")
    if event_type != "new-message":
        # Heartbeat, read receipts, etc. — acknowledge and ignore
        return {"ok": True}

    data = payload.get("data", {})

    # Skip messages sent by us
    if data.get("isFromMe"):
        logger.info("BB webhook: skipping isFromMe=True message")
        return {"ok": True}

    # Skip group chats
    chats = data.get("chats", [])
    if not chats or chats[0].get("isGroup"):
        logger.info("BB webhook: skipping group chat or no chats")
        return {"ok": True}

    handle       = data.get("handle", {})
    address      = handle.get("address", "") if handle else ""
    # iMessage stamps an object-replacement char (￼) as the "text" of an
    # attachment-only message — strip it so such messages read as empty text.
    text         = (data.get("text") or "").replace("￼", "").strip()
    chat_guid    = chats[0].get("guid", "")
    message_guid = data.get("guid", "")   # needed for tapback reactions

    # Voice notes (and other audio) arrive as an attachment with no text. Detect
    # one so we can route to transcription instead of dropping the message.
    from bot.imessage_handler import extract_audio_attachment
    audio = extract_audio_attachment(data)

    if not address or not chat_guid or (not text and not audio):
        logger.info(
            f"BB webhook: skipping — address={bool(address)} text={bool(text)} "
            f"audio={bool(audio)} chat_guid={bool(chat_guid)}"
        )
        return {"ok": True}

    # Deduplicate — BlueBubbles re-delivers the same message via several paths
    # (Private API socket + REST polling), sometimes under DIFFERENT message GUIDs,
    # and can retry minutes apart while our pipeline is still running. GUID-only
    # dedup misses the cross-path duplicate, so we suppress on BOTH:
    #   - the message GUID (long window — catches retries of the same event)
    #   - an (address+text) fingerprint (short window — catches the same message
    #     re-delivered under a second GUID). A user genuinely sending identical
    #     text within ~45s is rare and harmless to coalesce.
    import time as _time
    _seen = getattr(app.state, "_seen_guids", {})
    _now = _time.time()
    # Evict on the longest window we use so the dict can't grow unbounded.
    _seen = {k: v for k, v in _seen.items() if _now - v < 600}
    _guid_key = f"guid:{message_guid}" if message_guid else None
    # Fingerprint on the audio attachment guid when there's no text (an empty-text
    # key would collide every voice note within the window and wrongly dedup them).
    _text_key = (f"att:{address}:{audio['guid']}" if (audio and not text)
                 else f"txt:{address}:{text[:120]}")
    _guid_dup = _guid_key is not None and (_now - _seen.get(_guid_key, 0)) < 600
    _text_dup = (_now - _seen.get(_text_key, 0)) < 120
    if _guid_dup or _text_dup:
        _why = "guid" if _guid_dup else "text"
        logger.info(f"BB webhook: duplicate ({_why}) skipped text={text[:40]!r}")
        app.state._seen_guids = _seen
        return {"ok": True}
    if _guid_key is not None:
        _seen[_guid_key] = _now
    _seen[_text_key] = _now
    app.state._seen_guids = _seen

    # Route: text → normal (debounced) pipeline; audio-only → transcription path.
    import asyncio
    if text:
        from bot.imessage_handler import handle_imessage
        asyncio.create_task(
            handle_imessage(address, chat_guid, text, message_guid=message_guid)
        )
    else:  # audio attachment with no text → transcribe then process
        from bot.imessage_handler import handle_imessage_audio
        asyncio.create_task(handle_imessage_audio(
            address, chat_guid, audio["guid"],
            message_guid=message_guid, transfer_name=audio["transfer_name"],
        ))

    return {"ok": True}


# ── iMessage signup from the landing page ──────────────────────────────────────

class IMessageSignup(BaseModel):
    phone: str


@app.post("/imessage/start")
async def imessage_start(payload: IMessageSignup, request: Request):
    """
    Landing-page iMessage signup. User enters their phone → Arnie sends the
    first outreach once. Their reply flows straight into onboarding.
    Rate-limited per IP to curb abuse.
    """
    import time as _t
    # Simple per-IP rate limit: max 5 signups / 10 min
    ip = request.client.host if request.client else "?"
    rl = getattr(app.state, "_signup_rl", {})
    now = _t.time()
    hits = [t for t in rl.get(ip, []) if now - t < 600]
    if len(hits) >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    hits.append(now)
    rl[ip] = hits
    app.state._signup_rl = rl

    from bot.imessage_handler import start_imessage_outreach
    result = await start_imessage_outreach(payload.phone)

    if result["ok"]:
        return {"ok": True, "message": "Arnie is texting you now — check your messages."}

    reasons = {
        "invalid_number": "That doesn't look like a valid phone number.",
        "not_imessage": "That number isn't on iMessage. Use an Apple device or try Telegram.",
        "already_started": "You're already set up — check your messages for Arnie.",
    }
    return {"ok": False, "message": reasons.get(result["reason"], "Something went wrong — try again.")}


# ── Macro split helper ─────────────────────────────────────────────────────────
# Canonical implementation lives in core/targets.py so the dashboard and bot
# share one rule set. Re-exported here for back-compat (bot/telegram_handler.py
# still imports `from api.app import compute_macro_split`).
from core.targets import compute_macro_split  # noqa: E402,F401


# ── Web onboarding pre-registration ───────────────────────────────────────────

class PreRegisterPayload(BaseModel):
    name: str
    age: int
    sex: str                               # "male" | "female" | "other"
    height_cm: float
    weight_kg: float
    primary_goal: str                      # cut | bulk | maintain | performance | health
    training_experience: str              # beginner | intermediate | advanced
    dietary_preferences: Optional[str] = None
    timezone: Optional[str] = None       # IANA tz string, e.g. "America/New_York"
    goal_weight_lbs: Optional[float] = None  # only meaningful for cut/bulk goals
    # Optional targets captured at /join Step 5. Auto-calculated client-side
    # (same math as core/targets.py), editable by the user. Persisted into
    # user_preferences when the SETUP-XXXXXX code is consumed so the bot
    # skips the [COACH NOTE — targets_unset] nudge entirely for these users.
    calorie_target: Optional[int] = None
    protein_target: Optional[int] = None
    carb_target:    Optional[int] = None
    fat_target:     Optional[int] = None


_VALID_GOALS = {"cut", "bulk", "maintain", "performance", "health"}
_VALID_EXPERIENCE = {"beginner", "intermediate", "advanced"}
_VALID_SEX = {"male", "female", "other"}


@app.post("/api/preregister")
async def api_preregister(payload: PreRegisterPayload, request: Request):
    """
    Landing-page onboarding form submission.
    Stores the profile, returns a one-time SETUP-XXXXXX code and the Telegram deep link.
    When the user hits /start SETUP-XXXXXX on Telegram, their profile is pre-loaded
    and they skip conversational onboarding entirely.
    Rate-limited per IP: max 5 per 10 min.
    """
    import time as _t
    ip = request.client.host if request.client else "?"
    rl = getattr(app.state, "_prereg_rl", {})
    now = _t.time()
    hits = [t for t in rl.get(ip, []) if now - t < 600]
    if len(hits) >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts — try again shortly.")
    hits.append(now)
    rl[ip] = hits
    app.state._prereg_rl = rl

    # Validate enum fields
    if payload.primary_goal not in _VALID_GOALS:
        raise HTTPException(status_code=422, detail=f"Invalid goal: {payload.primary_goal}")
    if payload.training_experience not in _VALID_EXPERIENCE:
        raise HTTPException(status_code=422, detail=f"Invalid experience: {payload.training_experience}")
    if payload.sex not in _VALID_SEX:
        raise HTTPException(status_code=422, detail=f"Invalid sex: {payload.sex}")
    if not (1 <= payload.age <= 120):
        raise HTTPException(status_code=422, detail="Age out of range")
    if not (50 <= payload.height_cm <= 280):
        raise HTTPException(status_code=422, detail="Height out of range")
    if not (20 <= payload.weight_kg <= 400):
        raise HTTPException(status_code=422, detail="Weight out of range")

    # Validate target ranges (mirrors the client-side input min/max in /join Step 5).
    # All four are optional — present when the user reaches Step 5, absent for
    # legacy clients posting from an older /join build.
    if payload.calorie_target is not None and not (800 <= payload.calorie_target <= 6000):
        raise HTTPException(status_code=422, detail="Calorie target out of range")
    if payload.protein_target is not None and not (20 <= payload.protein_target <= 500):
        raise HTTPException(status_code=422, detail="Protein target out of range")
    if payload.carb_target is not None and not (0 <= payload.carb_target <= 800):
        raise HTTPException(status_code=422, detail="Carb target out of range")
    if payload.fat_target is not None and not (10 <= payload.fat_target <= 300):
        raise HTTPException(status_code=422, detail="Fat target out of range")

    profile = {
        "name": payload.name.strip()[:80],
        "age": payload.age,
        "sex": payload.sex,
        "height_cm": round(payload.height_cm, 1),
        "weight_kg": round(payload.weight_kg, 2),
        "primary_goal": payload.primary_goal,
        "training_experience": payload.training_experience,
        "dietary_preferences": (payload.dietary_preferences or "").strip()[:200] or None,
        "timezone": payload.timezone or None,
        "goal_weight_lbs": round(payload.goal_weight_lbs, 1) if payload.goal_weight_lbs else None,
        # Targets — None when missing keeps existing behavior intact.
        "calorie_target": payload.calorie_target,
        "protein_target": payload.protein_target,
        "carb_target":    payload.carb_target,
        "fat_target":     payload.fat_target,
    }

    from db.queries import create_pre_registration
    async with AsyncSessionLocal() as db:
        code = await create_pre_registration(db, profile)

    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "Arnie_1026_Bot")
    bot_link = f"tg://resolve?domain={bot_username}&start={code}"

    _tgt = (
        f" targets={profile['calorie_target']}/{profile['protein_target']}/"
        f"{profile['carb_target']}/{profile['fat_target']}"
        if profile.get("calorie_target") else ""
    )
    logger.info(
        f"Pre-registration created: code={code} name={profile['name']} "
        f"goal={profile['primary_goal']}{_tgt}"
    )
    return {"ok": True, "code": code, "bot_link": bot_link}


# ── Local dev: serve landing page from the API ─────────────────────────────────

@app.get("/landing", response_class=HTMLResponse, include_in_schema=False)
async def landing_page():
    """
    Serves the landing page from the FastAPI app for local development.
    In production, the landing is a separate Render static service (arnie-landing).
    Access at http://localhost:10000/landing during local dev.
    """
    landing_path = os.path.join(os.path.dirname(__file__), "..", "landing", "index.html")
    if not os.path.exists(landing_path):
        raise HTTPException(status_code=404, detail="Landing page not found")
    return FileResponse(landing_path, media_type="text/html")


@app.get("/join", response_class=HTMLResponse, include_in_schema=False)
async def join_page():
    """
    Serves the standalone onboarding form page.
    In production this will be accessible at join.tryarnie.com (subdomain on arnie-bot).
    Access at http://localhost:10000/join during local dev.
    """
    join_path = os.path.join(os.path.dirname(__file__), "..", "landing", "join.html")
    if not os.path.exists(join_path):
        raise HTTPException(status_code=404, detail="Join page not found")
    return FileResponse(join_path, media_type="text/html")


# ── Stats API ──────────────────────────────────────────────────────────────────

@app.get("/api/insights/{token}")
async def get_insights_endpoint(token: str, force: bool = False, date: str = None, period: str = "day"):
    """AI coaching insights. period='day' (default) analyses the viewed day;
    period='week' consolidates the last 7 days into weekly trend insights."""
    from api.insights import get_insights, get_week_insights
    from datetime import date as dt_date
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        target = None
        if date:
            try:
                target = dt_date.fromisoformat(date)
            except ValueError:
                pass
        stats = await _build_stats_for_user(db, user, target_date=target)
        if period == "week":
            insights = await get_week_insights(user.id, stats, force=force)
        else:
            insights = await get_insights(user.id, stats, force=force, date_key=date or "")
    return {"insights": insights}


def _compute_analytics(user, prefs, weight_data):
    """TDEE, deficit, protein rec, and goal-pace from user profile."""
    result = {}
    if not all([user.current_weight_kg, user.height_cm, user.age, user.sex]):
        return result

    w, h, a = user.current_weight_kg, user.height_cm, user.age
    sex = (user.sex or "").lower()
    if sex in ("m", "male", "man"):
        bmr = 10 * w + 6.25 * h - 5 * a + 5
    else:
        bmr = 10 * w + 6.25 * h - 5 * a - 161

    exp = (user.training_experience or "").lower()
    if any(k in exp for k in ("advanced", "athlete", "very")):
        factor = 1.725
    elif any(k in exp for k in ("beginner", "new", "start")):
        factor = 1.375
    else:
        factor = 1.55

    tdee = round(bmr * factor)
    result["tdee_estimate"] = tdee
    result["bmr"] = round(bmr)
    result["activity_factor"] = factor

    lbs = w * 2.20462
    result["rec_protein_min"] = round(lbs * 0.7)
    result["rec_protein_max"] = round(lbs * 1.0)

    if prefs and prefs.calorie_target:
        daily_diff = prefs.calorie_target - tdee
        result["daily_vs_tdee"] = daily_diff
        result["pace_label"] = "deficit" if daily_diff < 0 else ("surplus" if daily_diff > 0 else "maintenance")
        result["pace_lbs_per_week"] = round(abs(daily_diff) * 7 / 3500, 1) if daily_diff != 0 else 0

        if user.goal_weight_kg and result.get("pace_lbs_per_week", 0) > 0:
            lbs_to_go = abs(w - user.goal_weight_kg) * 2.20462
            result["lbs_to_goal"] = round(lbs_to_go, 1)
            result["weeks_to_goal"] = round(lbs_to_go / result["pace_lbs_per_week"])

    if len(weight_data) >= 2:
        oldest, newest = weight_data[0], weight_data[-1]
        from datetime import date as dt
        d1, d2 = dt.fromisoformat(oldest["date"]), dt.fromisoformat(newest["date"])
        days = (d2 - d1).days
        if days > 0:
            result["actual_lbs_per_week"] = round((newest["lbs"] - oldest["lbs"]) / (days / 7), 1)

    return result


# Canonical macro calculator lives in core.targets — re-export for any
# existing imports (kept for backward compat after consolidation).
from core.targets import compute_macro_targets as compute_auto_macro_targets  # noqa: E402


async def _build_stats_for_user(db, user, target_date=None):
    """Shared stats-building logic for /api/stats and /api/insights."""
    from datetime import date as dt_date
    prefs = user.preferences
    history = await get_recent_logs(db, user.id, days=60)
    weights = await get_recent_weights(db, user.id, days=90)
    health_snaps = await get_recent_health_snapshots(db, user.id, days=14)

    # Whoop tokens AND health snapshots may be on a linked identity (e.g. Telegram)
    # rather than the canonical (iMessage) row. Check all linked identities.
    from sqlalchemy import select as _sel
    from db.models import User as _U
    _linked_users = (await db.execute(
        _sel(_U).where(_U.linked_to_user_id == user.id)
    )).scalars().all()

    # Merge health snapshots from linked identities (dedup by date, prefer linked)
    if not health_snaps and _linked_users:
        for _lu in _linked_users:
            _linked_snaps = await get_recent_health_snapshots(db, _lu.id, days=14)
            if _linked_snaps:
                health_snaps = _linked_snaps
                break
    elif _linked_users:
        # Merge: add linked snaps for dates not covered by canonical snaps
        _canonical_dates = {s.date for s in health_snaps}
        for _lu in _linked_users:
            _linked_snaps = await get_recent_health_snapshots(db, _lu.id, days=14)
            for _ls in _linked_snaps:
                if _ls.date not in _canonical_dates:
                    health_snaps.append(_ls)
                    _canonical_dates.add(_ls.date)

    _whoop_connected = bool(user.whoop_access_token or user.whoop_refresh_token)
    if not _whoop_connected:
        from sqlalchemy import select as _sel
        from db.models import User as _U
        linked_rows = (await db.execute(
            _sel(_U).where(_U.linked_to_user_id == user.id)
        )).scalars().all()
        _whoop_connected = any(
            bool(u.whoop_access_token or u.whoop_refresh_token) for u in linked_rows
        )

    # Determine which day's entries to return
    if target_date:
        day_log = await get_log_by_date(db, user.id, target_date)
    else:
        day_log = await get_today_log(db, user.id, user.timezone or "UTC")

    # One reading per day, manual preferred — a day with both a manual weigh-in
    # and a passive HealthKit sync collapses to the user's own number, so the
    # trend (and the pace math in _compute_analytics, which reads weight_data[0]
    # and [-1]) isn't skewed by the duplicate. The headline number itself comes
    # from user.current_weight_kg, which add_body_metric keeps manual-wins.
    from api.native_data import _one_per_day_prefer_manual
    weight_data = [
        {"date": w.timestamp.strftime("%Y-%m-%d"),
         "kg": round(w.weight_kg, 1),
         "lbs": round(w.weight_kg * 2.20462, 1)}
        for w in _one_per_day_prefer_manual(weights)
    ]

    def _log_to_day(log):
        if not log:
            return None
        return {
            "date": str(log.date),
            "calories": round(log.total_calories or 0),
            "protein": round(log.total_protein or 0),
            "carbs": round(log.total_carbs or 0),
            "fats": round(log.total_fats or 0),
            "water_ml": round(log.total_water_ml or 0),
            "workout_completed": log.workout_completed,
            "cardio_completed": log.cardio_completed,
            # Chronological order (earliest → latest). `timestamp` is included
            # so the frontend can group entries logged in the same tool-call
            # batch (multi-item photo, multi-line text) into a single
            # collapsible meal card. Fallback to `id` when timestamp is null
            # (very old rows pre-T2.3). Sort uses a key that never raises on
            # missing values.
            "food_entries": [
                {"id": e.id, "name": e.parsed_food_name or "?",
                 "quantity": e.quantity or "",
                 "calories": round(e.calories or 0), "protein": round(e.protein or 0),
                 "carbs": round(e.carbs or 0), "fats": round(e.fats or 0),
                 "estimated": bool(e.estimated_flag),
                 "from_photo": bool(getattr(e, "from_photo", False)),
                 "timestamp": e.timestamp.isoformat() if e.timestamp else None}
                for e in sorted(
                    (log.food_entries or []),
                    key=lambda e: (
                        e.timestamp or datetime.min, e.id or 0,
                    ),
                )
            ],
            "exercise_entries": [
                {"id": e.id, "name": e.exercise_name or "?",
                 "sets": e.sets, "reps": e.reps,
                 "weight": round(e.weight * 2.20462, 1) if e.weight else None,
                 "duration_minutes": e.duration_minutes,
                 "is_cardio": bool(e.cardio_type),
                 "cardio_type": e.cardio_type,
                 # Parity with native_data: surface the time so any surface using
                 # this serializer can place workouts on a timeline (occurred-at,
                 # else logged-at).
                 "timestamp": (e.occurred_at or e.timestamp).isoformat() if (e.occurred_at or e.timestamp) else None}
                for e in sorted(
                    (log.exercise_entries or []),
                    key=lambda e: ((e.occurred_at or e.timestamp) or datetime.min, e.id or 0),
                )
            ],
            # Per-entry hydration (canonical WaterEntry rows) so the dashboard
            # can show the day total first and expand into the individual logs.
            # total_water_ml above stays the cached aggregate. Sorted oldest →
            # latest; key never raises on a null timestamp.
            "water_entries": [
                {"id": w.id, "amount_ml": round(w.amount_ml or 0),
                 "context": w.context,
                 "timestamp": w.timestamp.isoformat() if w.timestamp else None}
                for w in sorted(
                    (log.water_entries or []),
                    key=lambda w: (w.timestamp or datetime.min, w.id or 0),
                )
            ],
        }

    hist_data = [
        {"date": str(log.date),
         "calories": round(log.total_calories or 0),
         "protein": round(log.total_protein or 0),
         "carbs": round(log.total_carbs or 0),
         "fats": round(log.total_fats or 0),
         "water_ml": round(log.total_water_ml or 0),
         "workout": log.workout_completed}
        for log in sorted(history, key=lambda l: l.date)
    ]

    health_data = [
        {"date": str(s.date), "source": s.source,
         "recovery_score": s.recovery_score,
         "hrv": round(s.hrv) if s.hrv else None,
         "resting_hr": round(s.resting_hr) if s.resting_hr else None,
         "avg_hr": round(s.avg_hr) if s.avg_hr else None,
         "sleep_hours": s.sleep_hours,
         "sleep_deep_hours": s.sleep_deep_hours,
         "sleep_rem_hours": s.sleep_rem_hours,
         "sleep_performance_pct": getattr(s, "sleep_performance_pct", None),
         "sleep_need_hours": getattr(s, "sleep_need_hours", None),
         "sleep_efficiency_pct": getattr(s, "sleep_efficiency_pct", None),
         "respiratory_rate": getattr(s, "respiratory_rate", None),
         "spo2_percentage": getattr(s, "spo2_percentage", None),
         "skin_temp_celsius": getattr(s, "skin_temp_celsius", None),
         "strain": s.strain,
         "steps": s.steps,
         "active_calories": s.active_calories,
         "resting_calories": s.resting_calories,
         "stand_hours": s.stand_hours,
         "exercise_minutes": s.exercise_minutes,
         "whoop_workouts": getattr(s, "whoop_workouts", None)}
        for s in health_snaps
    ]

    available_dates = sorted({d["date"] for d in hist_data})
    analytics = _compute_analytics(user, prefs, weight_data)

    # ── Logging streak — consecutive days (walking back from today) with any
    # entry logged. "Logged" = calories > 0 OR workout completed (food or
    # exercise activity). Returned as profile.streak_days; dashboard only
    # surfaces it as a chip when ≥ 3 (see streak chip in api/templates.py).
    def _compute_streak(hist_rows):
        if not hist_rows:
            return 0
        # hist_rows is oldest→newest. Build a set of "logged" date strings.
        logged_set = {h["date"] for h in hist_rows if (h.get("calories") or 0) > 0 or h.get("workout")}
        if not logged_set:
            return 0
        # Walk backward from the user's "today" date by 1-day steps, count
        # consecutive logged days, stop on the first gap.
        from datetime import date as _dt_date, timedelta as _td
        try:
            cur = _dt_date.fromisoformat(_user_today(user.timezone or "UTC").isoformat())
        except Exception:
            cur = _dt_date.fromisoformat(max(logged_set))
        streak = 0
        while cur.isoformat() in logged_set:
            streak += 1
            cur = cur - _td(days=1)
        return streak

    streak_days = _compute_streak(hist_data)

    def _ht():
        if not user.height_cm:
            return ""
        total_in = user.height_cm / 2.54
        return f"{int(total_in // 12)}'{int(total_in % 12)}\""

    # ── Reminder deliverability (honesty) ──────────────────────────────────────
    # reminders_on is just the raw opt-in bool — it can read True while a DURABLE
    # upstream scheduler gate silently drops the user every tick. Surface the FIRST
    # tripped durable gate as reminders_blocked_reason so the dashboard reflects
    # deliverability, not just stored intent. Computed ONLY when the toggle is on
    # (an OFF toggle is already honest). Reuses the real scheduler gate functions —
    # never reimplements gate logic. Precedence mirrors the scheduler's durable
    # gates in order; transient gates (window/live-convo/frequency/silence) are
    # EXCLUDED (surfacing them would flag everyone every evening).
    _reminders_on = bool(prefs.proactive_messaging_enabled) if prefs else False
    _reminders_blocked_reason = None
    if _reminders_on:
        from scheduler.proactive_scheduler import (
            proactive_enabled as _proactive_enabled,
            _should_skip_linked, _allowlist_allows, _has_timezone,
        )
        from db.queries import linking_enabled, resolve_send_target
        if not _proactive_enabled():
            _reminders_blocked_reason = "globally_off"
        elif _should_skip_linked(user, linking_enabled()):
            _reminders_blocked_reason = "linked_secondary"
        elif not _allowlist_allows(
            user.id, user.telegram_id, await resolve_send_target(db, user)
        ):
            _reminders_blocked_reason = "not_on_allowlist"
        elif not _has_timezone(user):
            _reminders_blocked_reason = "no_timezone"

    profile = {
        "name": user.name or "User",
        "age": user.age,
        "sex": user.sex,
        "height_cm": user.height_cm,
        "height_ft": _ht(),
        "current_weight_lbs": round(user.current_weight_kg * 2.20462, 1) if user.current_weight_kg else None,
        "goal_weight_lbs": round(user.goal_weight_kg * 2.20462, 1) if user.goal_weight_kg else None,
        "primary_goal": user.primary_goal,
        "training_experience": user.training_experience,
        "non_training_activity": user.non_training_activity,
        "dietary_preferences": user.dietary_preferences,
        "injuries": user.injuries,
        "timezone": user.timezone,
        "coaching_style": prefs.coaching_style if prefs else None,
        "calorie_target": prefs.calorie_target if prefs else None,
        "protein_target": prefs.protein_target if prefs else None,
        "carb_target": prefs.carb_target if prefs else None,
        "fat_target": prefs.fat_target if prefs else None,
        "reminder_frequency": (prefs.reminder_frequency if prefs else None) or "moderate",
        "reminders_on": _reminders_on,
        "reminders_blocked_reason": _reminders_blocked_reason,
        "food_logging_mode": (getattr(prefs, "food_logging_mode", None) or "moderate") if prefs else "moderate",
        "whoop_connected": _whoop_connected,
        "apple_health_connected": any(s.source == "apple_health" for s in health_snaps),
        "analytics": analytics,
        "streak_days": streak_days,
    }

    # Active-attribute count — the same authoritative number that powers the
    # Brain tab's unlock gate. Including it here lets the dashboard's
    # learning-progress bar tick in lockstep with the brain (both read off
    # /api/stats, so this stays cheap and synchronous with everything else).
    from memory.attribute_store import get_all_attributes as _get_attrs
    _attrs = await _get_attrs(db, user.id)
    _active_attrs = [a for a in _attrs if a.attribute_status == "active"]
    _attribute_count = len(_active_attrs)
    # A compact "what Arnie has learned" block (the brain, Lane 2 durable traits),
    # grouped by category, so the briefing can ground insights in everything known
    # about this client. Archive-tier facts are held back (same as the chat coach).
    _brain_by_cat: dict[str, list[str]] = {}
    for _a in _active_attrs:
        if (getattr(_a, "relevance_tier", None) or "contextual") == "archive":
            continue
        _brain_by_cat.setdefault(_a.category or "custom", []).append(str(_a.value))
    _brain_str = "\n".join(
        f"{_cat}: " + "; ".join(_vals[:14])
        for _cat in ["nutrition", "fitness", "health", "lifestyle", "behavior", "mental", "custom"]
        if (_vals := _brain_by_cat.get(_cat))
    )

    return {
        "profile": profile,
        "targets": {
            "calories": prefs.calorie_target if prefs else None,
            "protein": prefs.protein_target if prefs else None,
            "carbs": prefs.carb_target if prefs else None,
            "fats": prefs.fat_target if prefs else None,
        },
        "day": _log_to_day(day_log),
        "history": hist_data,
        "weights": weight_data,
        "health": health_data,
        "available_dates": available_dates,
        "viewing_date": str(target_date or _user_today(user.timezone or "UTC")),
        "attribute_count": _attribute_count,
        "brain": _brain_str,
        # keep legacy 'today' + 'user' keys so existing insights endpoint works unchanged
        "today": _log_to_day(day_log),
        "user": {"name": user.name or "User", "goal": user.primary_goal or "general fitness",
                 "current_weight_lbs": profile["current_weight_lbs"],
                 "goal_weight_lbs": profile["goal_weight_lbs"]},
        # AI-generated bio — null until profile has been synthesized at least once
        "bio": user.user_bio or None,
    }


@app.get("/api/stats/{token}")
async def get_stats(token: str, date: Optional[str] = Query(None)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        target_date = None
        if date:
            try:
                from datetime import date as dt_date
                target_date = dt_date.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date, use YYYY-MM-DD")
        return await _build_stats_for_user(db, user, target_date=target_date)


def _build_fitness_for_user(logs) -> dict:
    """Aggregate strength-training progression from a user's DailyLogs.

    Canonicalizes every exercise through the catalog so aliases collapse, then
    groups into per-movement session histories (top set, est-1RM, volume, set
    count). Also derives today's session, per-session volume, and muscle-set
    distribution. Shape mirrors the Fitness tab's renderer. Weight is stored in
    kg; surfaced as lbs. Read-only — pure transform over already-loaded rows.
    """
    from collections import defaultdict, OrderedDict
    from skills.fitness.exercise_catalog import canonicalize

    def parse_reps(reps):
        if reps is None:
            return []
        out = []
        for p in str(reps).replace(" ", "").replace("/", ",").split(","):
            try:
                out.append(int(float(p)))
            except ValueError:
                pass
        return [r for r in out if 0 < r <= 40]

    def epley(w, reps):
        if not w or not reps:
            return None
        return round(w * (1 + min(reps, 15) / 30.0), 1)

    def infer_muscle(name, primary):
        if primary and primary != "other":
            return {"abs": "core", "forearms": "arms", "biceps": "arms",
                    "triceps": "arms"}.get(primary, primary)
        n = name.lower()
        if any(k in n for k in ["shrug", "upright", "lateral raise", "front raise",
                                "face pull", "rear delt", "shoulder press", "overhead press"]):
            return "shoulders"
        if any(k in n for k in ["curl", "pushdown", "extension", "tricep", "bicep", "hammer", "forearm"]):
            return "arms"
        if any(k in n for k in ["row", "pulldown", "pull-up", "pullup", "lat "]):
            return "back"
        if any(k in n for k in ["bench", "fly", "press", "chest", "dip"]):
            return "chest"
        if any(k in n for k in ["crunch", "ab ", "abs", "plank", "leg raise"]):
            return "core"
        if any(k in n for k in ["squat", "leg", "lunge", "calf", "glute", "deadlift", "hip"]):
            return "legs"
        return "other"

    KG = 2.20462
    asc = sorted(logs, key=lambda l: l.date)
    mov = OrderedDict()
    cardio = []
    for log in asc:
        d = str(log.date)
        for e in (log.exercise_entries or []):
            if e.cardio_type:
                cardio.append({"date": d, "name": e.exercise_name or "?",
                               "type": e.cardio_type, "min": e.duration_minutes})
                continue
            canon, meta = canonicalize(e.exercise_name)
            if canon not in mov:
                mov[canon] = {"name": canon,
                              "muscle": infer_muscle(canon, (meta or {}).get("primary")),
                              "sessions": defaultdict(list)}
            mov[canon]["sessions"][d].append({
                "sets": e.sets,
                "reps": parse_reps(e.reps),
                "w": round(e.weight * KG, 1) if e.weight else None,
            })

    movements = []
    for canon, m in mov.items():
        sessions = []
        for d in sorted(m["sessions"]):
            entries = m["sessions"][d]
            best_w = top_reps = best_e = None
            vol = 0.0
            nsets = 0
            for e in entries:
                w, reps = e["w"], e["reps"]
                nsets += (e["sets"] or len(reps) or 1)
                for rp in reps:
                    if w:
                        vol += w * rp
                    est = epley(w, rp)
                    if est and (best_e is None or est > best_e):
                        best_e = est
                    if w and (best_w is None or w > best_w or (w == best_w and rp > (top_reps or 0))):
                        best_w, top_reps = w, rp
                if not reps and w and (best_w is None or w > best_w):
                    best_w = w
            sessions.append({"date": d, "w": best_w, "reps": top_reps,
                             "e1rm": best_e, "vol": round(vol) if vol else None,
                             "sets": nsets})
        movements.append({"name": canon, "muscle": m["muscle"], "sessions": sessions,
                          "n": len(sessions), "last": sessions[-1]["date"] if sessions else None})

    movements = [m for m in movements if m["sessions"]]
    movements.sort(key=lambda x: (x["last"], x["n"]), reverse=True)

    # today = latest training date, consolidated per movement from RAW entries
    # (raw pass keeps every set's reps, e.g. [12,10,10], not just the top set)
    today, today_date = [], (str(asc[-1].date) if asc else None)
    if movements:
        latest = max(m["last"] for m in movements)
        today_date = latest
        agg = OrderedDict()
        for log in asc:
            if str(log.date) != latest:
                continue
            for e in (log.exercise_entries or []):
                if e.cardio_type:
                    continue
                canon, _ = canonicalize(e.exercise_name)
                if canon not in agg:
                    agg[canon] = {"name": canon, "sets": 0, "reps": [], "w": []}
                agg[canon]["sets"] += (e.sets or len(parse_reps(e.reps)) or 1)
                agg[canon]["reps"] += parse_reps(e.reps)
                if e.weight:
                    agg[canon]["w"].append(round(e.weight * KG, 1))
        for a in agg.values():
            ws = a["w"]
            wlabel = None
            if ws:
                lo, hi = min(ws), max(ws)
                wlabel = (f"{lo:g}" if lo == hi else f"{lo:g}–{hi:g}")
            today.append({"name": a["name"], "sets": a["sets"],
                          "reps": a["reps"], "w": wlabel})

    vol_by_date = defaultdict(float)
    sets_by_muscle = defaultdict(int)
    for m in movements:
        for s in m["sessions"]:
            if s["vol"]:
                vol_by_date[s["date"]] += s["vol"]
            sets_by_muscle[m["muscle"]] += s.get("sets", 0)
    sessions = [{"date": d, "vol": round(v)} for d, v in sorted(vol_by_date.items())]
    muscle_sets = [{"muscle": k, "sets": v}
                   for k, v in sorted(sets_by_muscle.items(), key=lambda x: -x[1])]

    return {"movements": movements,
            "today_date": str(today_date) if today_date else None,
            "today": today, "sessions": sessions,
            "muscle_sets": muscle_sets, "cardio": cardio}


@app.get("/api/fitness/{token}")
async def get_fitness(token: str):
    """Strength-progression payload for the Fitness tab. Lazy-loaded on tab open."""
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        logs = await get_recent_logs(db, user.id, days=90)
        return _build_fitness_for_user(logs)


@app.get("/api/conversation/{token}")
async def get_conversation(token: str, limit: int = Query(120, ge=1, le=400)):
    """
    Unified conversation thread for the dashboard's live-chat widget.

    Consolidates every turn across ALL of a user's linked identities
    (Telegram + iMessage) into one chronological thread, so the dashboard
    shows the full back-and-forth regardless of which channel it happened on.
    Read-only. Each row is one turn: the user's message + Arnie's reply.
    """
    from sqlalchemy import select, desc
    from db.models import ConversationLog, User as UserModel

    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Resolve to the canonical account, then gather every identity that
        # rolls up to it. The token's user may itself be a linked secondary
        # identity, so normalize to the canonical id first, then collect siblings.
        canonical_id = user.linked_to_user_id or user.id
        linked_ids = (await db.execute(
            select(UserModel.id).where(UserModel.linked_to_user_id == canonical_id)
        )).scalars().all()
        all_ids = list({canonical_id, user.id, *linked_ids})

        rows = (await db.execute(
            select(ConversationLog)
            .where(ConversationLog.user_id.in_(all_ids))
            .order_by(desc(ConversationLog.timestamp))
            .limit(limit)
        )).scalars().all()

        turns = []
        platforms = set()
        for c in reversed(rows):  # oldest → newest for natural reading order
            platform = c.platform or "telegram"
            platforms.add(platform)
            turns.append({
                "user": c.raw_message or "",
                "arnie": c.response or "",
                "ts": c.timestamp.isoformat() if c.timestamp else None,
                "platform": platform,
                "source": c.source_type or "text",
            })
        return {"turns": turns, "platforms": sorted(platforms)}


class ChatBody(BaseModel):
    message: str


@app.post("/api/chat/{token}")
async def post_chat(token: str, body: ChatBody):
    """Dashboard web chat — the SAME brain as Telegram/iMessage.

    Runs the shared run_turn() pipeline with platform="web" (so tools, memory,
    coaching voice are identical to the bots) and logs the turn to
    ConversationLog(platform="web"). Because the read endpoint above consolidates
    every linked identity, the message + Arnie's reply immediately appear in the
    unified thread on every surface. Synchronous (no streaming) for v1.

    Note: we deliberately DON'T wire on_image/on_interim callbacks, so a web turn
    never gets pushed out to Telegram/iMessage — the reply comes back in this HTTP
    response and is recorded once. Proactive nudges still route by channel pref.
    """
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(text) > 4000:
        text = text[:4000]

    from core.conversation import run_turn
    from core.context_builder import build_context
    from core.prompts import build_arnie_system
    from core.history import conversations_to_messages
    from db.queries import (
        get_or_create_today_log, get_recent_conversations, log_conversation,
    )

    async with AsyncSessionLocal() as db:
        # Canonical user (get_user_by_webhook_token follows the link), so the web
        # turn reads/writes the same brain the bots do.
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        tz = getattr(user, "timezone", None) or "UTC"
        today_log = await get_or_create_today_log(db, user.id, tz)

        # Same message assembly the bots use: recent history + this message.
        recent = await get_recent_conversations(db, user.id, limit=8)
        messages = conversations_to_messages(recent)
        messages.append({"role": "user", "content": text})

        context_str = await build_context(user, today_log, db, platform="web",
                                          user_message=text)
        system = f"{build_arnie_system(platform='web')}\n\n{context_str}"

        try:
            turn = await run_turn(
                user, db, messages, system, platform="web",
                in_onboarding=False, was_onboarding=False,
                today_log=today_log, source_type="web",
            )
        except Exception as e:
            logging.getLogger(__name__).error(f"web chat run_turn failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Coach hiccup, resend that")

        bubbles = [b for b in (turn.response.bubbles or []) if b and b.strip()]
        reply = "|||".join(bubbles)
        await log_conversation(
            db, user.id, text, reply, source_type="web", platform="web",
            parsed_intent=(",".join(turn.health_flags) or None),
            skills_fired=turn.skills_fired,
        )

    return {"bubbles": bubbles, "ts": datetime.utcnow().isoformat()}


@app.get("/api/profile/{token}")
async def get_profile(token: str, refresh: bool = False):
    """
    Returns the user's AI-generated bio + all learned attributes organized by category.
    This powers the dashboard AI Profile section.

    ?refresh=true forces bio regeneration (ignores 24h throttle).
    """
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        from memory.attribute_store import get_all_attributes
        from memory.bio_generator import maybe_update_bio
        from memory.profile_view import build_unified_profile

        if refresh or not user.user_bio:
            await maybe_update_bio(user, db, force=refresh)

        attributes = await get_all_attributes(db, user.id)

        # Auto-derive favorites from RECURRENCE in the logs — the standard slots
        # fill themselves from what the user actually does/eats, not just from
        # explicit statements (an explicit learned attribute still wins).
        derived = {}
        from collections import Counter as _Counter
        try:
            from db.models import UserFoodMatch
            from sqlalchemy import select as _sel
            rows = (await db.execute(
                _sel(UserFoodMatch).where(UserFoodMatch.user_id == user.id)
                .order_by(UserFoodMatch.times_used.desc()).limit(6)
            )).scalars().all()
            foods = [r.display_name for r in rows
                     if r.display_name and (r.times_used or 0) >= 2]
            if foods:
                derived["nutrition_staple_foods"] = foods
        except Exception:
            pass
        try:
            # Favorite cardio = most-logged cardio activities (last 90 days).
            from db.models import ExerciseEntry, DailyLog
            from sqlalchemy import select as _sel
            from datetime import date as _date, timedelta as _td
            ex_rows = (await db.execute(
                _sel(ExerciseEntry).join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
                .where(DailyLog.user_id == user.id, DailyLog.date >= _date.today() - _td(days=90))
            )).scalars().all()
            cardio = _Counter()
            for e in ex_rows:
                is_cardio = bool(e.cardio_type) or (e.duration_minutes and not e.sets)
                if is_cardio:
                    name = (e.cardio_type or e.exercise_name or "").strip()
                    if name:
                        cardio[name.lower()] += 1
            fav_cardio = [n.title() for n, c in cardio.most_common(4) if c >= 2]
            if fav_cardio:
                derived["fitness_cardio_habits"] = fav_cardio
        except Exception:
            pass

        # Unified read model — the standard-parameter skeleton (always-present
        # slots, filled from columns/attributes/derived) + a custom bucket. Only
        # powers the dashboard/bio; Arnie's context is untouched.
        unified = build_unified_profile(user, user.preferences, attributes, derived=derived)

        return {
            "name": user.name or "User",
            "bio": user.user_bio or None,
            "bio_updated_at": user.user_bio_updated_at.isoformat() if user.user_bio_updated_at else None,
            "basics": unified["basics"],
            "standard": unified["standard"],
            "custom": unified["custom"],
            "attribute_count": len([a for a in attributes if a.attribute_status == "active"]),
        }


# ── Edit / delete entries from the dashboard ───────────────────────────────────

class FoodPatch(BaseModel):
    food_name: Optional[str] = None
    quantity: Optional[str] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None


class ExercisePatch(BaseModel):
    exercise_name: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight: Optional[float] = None  # in lbs from the dashboard, converted to kg below
    duration_minutes: Optional[float] = None


@app.patch("/api/food/{entry_id}")
async def api_edit_food(entry_id: int, patch: FoodPatch, token: str = Query(...)):
    import asyncio
    notify: dict = {}
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        changes = patch.model_dump(exclude_none=True)
        if "food_name" in changes:
            changes["parsed_food_name"] = changes.pop("food_name")
        entry = await update_food_entry(db, entry_id, user.id, **changes)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        from sqlalchemy import select as _sel
        from db.models import DailyLog
        log = (await db.execute(_sel(DailyLog).where(DailyLog.id == entry.daily_log_id))).scalar_one()
        prefs = user.preferences
        notify = dict(
            send_target=await resolve_send_target(db, user),
            text=_dashboard_msg("food_edit", label=entry.parsed_food_name or "entry",
                                cal=round(log.total_calories or 0),
                                cal_target=prefs.calorie_target if prefs else None),
        )
    asyncio.create_task(_send_dashboard_notification(**notify))
    return {"status": "ok", "id": entry_id}


class AttrHide(BaseModel):
    attribute_key: str


@app.post("/api/profile/attribute/hide")
async def api_hide_attribute(body: AttrHide, token: str = Query(...)):
    """Dashboard 'remove' on a learned attribute → soft-hide it.

    Sets attribute_status='discontinued', which drops the row out of every
    active read path (dashboard, bio, Arnie's context) while preserving history.
    Soft only: if Arnie re-learns the same fact later, upsert re-activates it.
    """
    from memory.attribute_store import set_attribute_status
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        ok = await set_attribute_status(db, user.id, body.attribute_key, "discontinued")
        if not ok:
            raise HTTPException(status_code=404, detail="Attribute not found")
    return {"status": "ok", "attribute_key": body.attribute_key}


@app.delete("/api/food/{entry_id}")
async def api_delete_food(entry_id: int, token: str = Query(...)):
    import asyncio
    notify: dict = {}
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        from sqlalchemy import select as _sel
        from db.models import FoodEntry, DailyLog
        entry = (await db.execute(_sel(FoodEntry).where(FoodEntry.id == entry_id))).scalar_one_or_none()
        food_name = entry.parsed_food_name if entry else "entry"
        log_id = entry.daily_log_id if entry else None
        ok = await delete_food_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
        log = (await db.execute(_sel(DailyLog).where(DailyLog.id == log_id))).scalar_one()
        prefs = user.preferences
        notify = dict(
            send_target=await resolve_send_target(db, user),
            text=_dashboard_msg("food_delete", label=food_name,
                                cal=round(log.total_calories or 0),
                                cal_target=prefs.calorie_target if prefs else None),
        )
    asyncio.create_task(_send_dashboard_notification(**notify))
    return {"status": "ok"}


class WaterPatch(BaseModel):
    amount_ml: float


@app.patch("/api/water/{entry_id}")
async def api_edit_water(entry_id: int, patch: WaterPatch, token: str = Query(...)):
    """Edit a single hydration entry from the dashboard, resyncing the day total."""
    from db.queries import update_water_entry
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        entry = await update_water_entry(db, entry_id, user.id, max(0.0, patch.amount_ml))
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok", "id": entry_id}


@app.delete("/api/water/{entry_id}")
async def api_delete_water(entry_id: int, token: str = Query(...)):
    """Delete a single hydration entry from the dashboard, resyncing the day total."""
    from db.queries import delete_water_entry
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        ok = await delete_water_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok"}


@app.patch("/api/exercise/{entry_id}")
async def api_edit_exercise(entry_id: int, patch: ExercisePatch, token: str = Query(...)):
    import asyncio
    notify: dict = {}
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        changes = patch.model_dump(exclude_none=True)
        if "weight" in changes:
            changes["weight"] = changes["weight"] * 0.453592
        entry = await update_exercise_entry(db, entry_id, user.id, **changes)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        notify = dict(send_target=await resolve_send_target(db, user),
                      text=_dashboard_msg("exercise_edit", label=entry.exercise_name or ""))
    asyncio.create_task(_send_dashboard_notification(**notify))
    return {"status": "ok", "id": entry_id}


@app.delete("/api/exercise/{entry_id}")
async def api_delete_exercise(entry_id: int, token: str = Query(...)):
    import asyncio
    notify: dict = {}
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        from sqlalchemy import select as _sel
        from db.models import ExerciseEntry
        entry = (await db.execute(_sel(ExerciseEntry).where(ExerciseEntry.id == entry_id))).scalar_one_or_none()
        exercise_name = entry.exercise_name if entry else ""
        ok = await delete_exercise_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
        notify = dict(send_target=await resolve_send_target(db, user),
                      text=_dashboard_msg("exercise_delete", label=exercise_name))
    asyncio.create_task(_send_dashboard_notification(**notify))
    return {"status": "ok"}


# ── Profile edit from dashboard ────────────────────────────────────────────────

class ProfilePatch(BaseModel):
    field: str
    value: Optional[str] = None


@app.patch("/api/profile/{token}")
async def api_edit_profile(token: str, patch: ProfilePatch):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        field, raw = patch.field, patch.value

        _str_fields = {"name", "primary_goal", "training_experience",
                       "dietary_preferences", "injuries", "timezone"}
        # Enum allowlist for non_training_activity — values must match the
        # ACSM tier names. Bot-side code can also write via update_profile,
        # so the same vocabulary is enforced in both paths.
        _activity_values = {"sedentary", "lightly_active",
                            "moderately_active", "very_active"}
        _int_fields = {"age"}
        _weight_fields = {
            "current_weight_lbs": "current_weight_kg",
            "goal_weight_lbs":    "goal_weight_kg",
        }
        # Enum field with explicit normalization — keep the allowed values in
        # lockstep with compute_macro_targets() in core/targets.py (which only
        # branches on "male"/"man"/"m"). Anything outside → "other".
        _sex_aliases = {
            "m": "male", "male": "male", "man": "male", "boy": "male",
            "f": "female", "female": "female", "woman": "female", "girl": "female",
        }
        _pref_str = {"coaching_style", "reminder_frequency", "food_logging_mode"}
        _pref_int = {"calorie_target", "protein_target", "carb_target", "fat_target"}
        _pref_bool = {"proactive_messaging_enabled"}

        try:
            if field in _str_fields:
                setattr(user, field, str(raw).strip() if raw else None)
            elif field == "non_training_activity":
                if not raw:
                    user.non_training_activity = None
                else:
                    v = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
                    if v not in _activity_values:
                        raise HTTPException(
                            status_code=400,
                            detail=f"non_training_activity must be one of {sorted(_activity_values)}",
                        )
                    user.non_training_activity = v
            elif field == "sex":
                # Normalize free-text or dropdown values to {male, female, other}
                # so the BMR formula in core/targets.py picks the right branch.
                if raw:
                    v = str(raw).strip().lower()
                    user.sex = _sex_aliases.get(v, "other")
                else:
                    user.sex = None
            elif field == "height_in":
                # Accept inches as a plain number ("70"), feet'inches ("5'10",
                # "5'10\""), or feet-space-inches ("5 10"). Convert to cm.
                if not raw:
                    user.height_cm = None
                else:
                    s = str(raw).strip().lower().replace('"', '').replace("ft", "'").replace("in", "")
                    if "'" in s:
                        a, b = s.split("'", 1)
                        ft = float(a.strip() or "0")
                        ins = float(b.strip() or "0")
                        total_in = ft * 12 + ins
                    elif " " in s:
                        a, b = s.split(" ", 1)
                        total_in = float(a.strip()) * 12 + float(b.strip())
                    else:
                        total_in = float(s)
                    if not (24 <= total_in <= 110):  # 2ft–9ft sanity
                        raise ValueError("Height out of range")
                    user.height_cm = round(total_in * 2.54, 1)
            elif field in _int_fields:
                setattr(user, field, int(raw) if raw else None)
            elif field in _weight_fields:
                db_col = _weight_fields[field]
                setattr(user, db_col, float(raw) * 0.453592 if raw else None)
            elif field in _pref_str and user.preferences:
                _val = str(raw).strip() if raw else None
                # Normalize the tiered prefs onto a valid vocabulary so a non-slider
                # caller (e.g. a future API client sending "less"/"more") can't
                # persist a value frequency_allows / food mode would then silently
                # coerce. Mirrors the LLM update_profile path. The slider already
                # sends exact tiers, so this is a defensive no-op for the dashboard.
                if _val is not None and field == "reminder_frequency":
                    from reminders.eligibility import normalize_reminder_frequency
                    _val = normalize_reminder_frequency(
                        _val, getattr(user.preferences, "reminder_frequency", None))
                elif _val is not None and field == "food_logging_mode":
                    from core.food_intelligence import normalize_food_logging_mode
                    _val = normalize_food_logging_mode(
                        _val, getattr(user.preferences, "food_logging_mode", "moderate") or "moderate")
                setattr(user.preferences, field, _val)
            elif field in _pref_int and user.preferences:
                # Range-check before write — same bands as api_preregister so
                # a "999999" typo can't poison the sync below into computing
                # absurd derived macros (a 250kg-carb target etc.). None/blank
                # clears the field, which the sync gracefully no-ops on.
                _v = int(raw) if raw else None
                if _v is not None:
                    _bounds = {
                        "calorie_target": (800, 6000),
                        "protein_target": (20,  500),
                        "carb_target":    (0,   800),
                        "fat_target":     (10,  300),
                    }[field]
                    if not (_bounds[0] <= _v <= _bounds[1]):
                        raise HTTPException(
                            status_code=400,
                            detail=f"{field.replace('_',' ')} must be between {_bounds[0]} and {_bounds[1]}",
                        )
                setattr(user.preferences, field, _v)
                # Keep the four macro targets self-consistent: whenever one
                # changes, the others recompute so cal = p*4 + c*4 + f*9
                # stays physical. Field-specific behavior lives in targets.py:
                #   calories → re-derive all three macros from goal+weight
                #   protein  → split remainder into carbs/fat (goal ratio)
                #   carbs/fat → the other absorbs the remainder
                if _v is not None:
                    from core.targets import sync_macros_after_change
                    sync_macros_after_change(user, user.preferences, field)
            elif field in _pref_bool and user.preferences:
                setattr(user.preferences, field, str(raw).lower() in ("true", "1", "yes", "on"))
            else:
                raise HTTPException(status_code=400, detail=f"Unknown field: {field}")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid value for {field}")

        await db.commit()

        # Build notification after commit so values are persisted
        import asyncio as _asyncio
        prefs = user.preferences
        if field == "proactive_messaging_enabled":
            _action = "profile_reminders_on" if str(raw).lower() in ("true", "1", "yes", "on") else "profile_reminders_off"
            _label = ""
        elif field == "food_logging_mode":
            _norm = getattr(prefs, "food_logging_mode", "moderate") or "moderate"
            _action = "profile_quick" if _norm == "quick" else ("profile_strict" if _norm == "strict" else "profile_field")
            _label = "food logging mode"
        elif field in ("calorie_target", "protein_target"):
            _action = "profile_targets"
            _cal_t = getattr(prefs, "calorie_target", None) if prefs else None
            _pro_t = getattr(prefs, "protein_target", None) if prefs else None
            _label = f"{_cal_t} cal / {_pro_t}g protein" if _cal_t and _pro_t else (f"{_cal_t} cal" if _cal_t else f"{_pro_t}g protein")
        else:
            _action = "profile_field"
            _label = field.replace("_", " ")
        _send_target = await resolve_send_target(db, user)
        _msg = _dashboard_msg(_action, label=_label)

    if _msg:
        _asyncio.create_task(_send_dashboard_notification(_send_target, _msg))
    return {"status": "ok", "field": field}


@app.post("/api/profile/{token}/auto-targets")
async def api_auto_targets(token: str):
    """Calculate + save calorie and macro targets from BMR, goal, and body
    composition. Driven by the dashboard's "Calculate for me" button under
    Profile → Goals & targets. Overwrites whatever's in user_preferences.
    The bot can call compute_auto_macro_targets() directly to suggest the
    same values in chat without persisting them."""
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        targets = compute_auto_macro_targets(user)
        if not targets:
            # Name the EXACT missing fields so the dashboard can highlight them
            # instead of telling the user to hunt through Demographics.
            _missing = []
            if not user.current_weight_kg: _missing.append("weight")
            if not user.height_cm:         _missing.append("height")
            if not user.age:               _missing.append("age")
            if not user.sex:               _missing.append("sex")
            _list = ", ".join(_missing) if _missing else "weight, height, age, sex"
            raise HTTPException(
                status_code=400,
                detail=f"Add your {_list} in Demographics above and we'll calculate from there.",
            )

        prefs = user.preferences
        if not prefs:
            from db.models import UserPreferences
            prefs = UserPreferences(user_id=user.id)
            db.add(prefs)

        prefs.calorie_target = targets["calorie_target"]
        prefs.protein_target = targets["protein_target"]
        prefs.carb_target    = targets["carb_target"]
        prefs.fat_target     = targets["fat_target"]
        await db.commit()

        logger.info(
            f"Auto-targets set for user {user.id}: "
            f"goal={targets['goal']} cals={targets['calorie_target']} "
            f"P={targets['protein_target']}g C={targets['carb_target']}g F={targets['fat_target']}g "
            f"(BMR={targets['bmr']}, TDEE={targets['tdee']}, deficit={targets['deficit_pct']:+.1f}%)"
        )
        return targets


# ── Admin: per-user consistency audit (read-only) ──────────────────────────────

# ── Admin: one-time iMessage-availability broadcast ─────────────────────────────
# Announce iMessage availability to onboarded Telegram users who aren't already on
# iMessage. DRY-RUN by default (GET) — returns who would receive it + the exact copy,
# sends nothing. Actually sends only on POST with confirm=SEND. Does NOT use the
# scheduler._send path (that's gated by PROACTIVE_MESSAGING_ENABLED, currently off);
# this is a deliberate one-time announcement with its own send path + dedup marker.

_IMSG_BROADCAST_MARKER = "imsg_broadcast"
_IMSG_BROADCAST_COPY = (
    "good news, i'm on imessage now too 📱|||"
    "want me to set you up there? say the word and i'll send the link"
)


async def _imsg_broadcast_recipients(db):
    """
    Onboarded Telegram users (telegram_id not 'im:...') who are NOT already linked
    to an iMessage identity and haven't already received this broadcast.
    """
    from sqlalchemy import select
    from db.models import User
    res = await db.execute(select(User).where(User.onboarding_completed == True))
    users = res.scalars().all()

    # Canonical account ids that an iMessage identity is linked INTO — these
    # Telegram users are already reachable on iMessage, so skip them.
    res_all = await db.execute(select(User))
    linked_canonical_ids = {
        u.linked_to_user_id for u in res_all.scalars().all()
        if str(u.telegram_id).startswith("im:") and u.linked_to_user_id
    }

    out = []
    for u in users:
        if str(u.telegram_id).startswith("im:"):
            continue  # this endpoint targets Telegram identities only
        # already on iMessage? either this row points to an im account, or an im
        # row points back to this one
        if u.linked_to_user_id:
            continue
        if u.id in linked_canonical_ids:
            continue
        sent = set(s for s in (u.nudges_sent or "").split(",") if s)
        if _IMSG_BROADCAST_MARKER in sent:
            continue
        out.append(u)
    return out


@app.get("/admin/broadcast")
async def admin_broadcast_preview(token: str = Query(...)):
    """DRY RUN — list who would receive the iMessage-availability broadcast. Sends nothing."""
    _require_admin(token)
    from fastapi.responses import JSONResponse
    async with AsyncSessionLocal() as db:
        recipients = await _imsg_broadcast_recipients(db)
        return JSONResponse({
            "dry_run": True,
            "message": _IMSG_BROADCAST_COPY,
            "bubbles": _IMSG_BROADCAST_COPY.split("|||"),
            "recipient_count": len(recipients),
            "recipients": [
                {"id": u.id, "name": u.name, "telegram_id": u.telegram_id}
                for u in recipients
            ],
            "note": "Nothing was sent. To send for real: POST /admin/broadcast?token=...&confirm=SEND",
        })


@app.post("/admin/broadcast")
async def admin_broadcast_send(token: str = Query(...), confirm: str = Query("")):
    """ACTUAL SEND — requires confirm=SEND. One-time; marks each recipient so re-runs don't double-send."""
    _require_admin(token)
    from fastapi.responses import JSONResponse
    if confirm != "SEND":
        raise HTTPException(status_code=400,
                            detail="Pass confirm=SEND to actually send. (GET this path for a dry run.)")

    from core.platform import Response, TelegramAdapter
    from telegram import Bot
    import asyncio as _asyncio

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    bot = Bot(token=tg_token)
    sent, failed = 0, 0
    failures = []
    async with AsyncSessionLocal() as db:
        recipients = await _imsg_broadcast_recipients(db)
        for u in recipients:
            try:
                resp = Response.from_text(_IMSG_BROADCAST_COPY)
                await TelegramAdapter(bot, int(u.telegram_id)).send(resp)
                # mark so a re-run never double-sends
                marks = set(s for s in (u.nudges_sent or "").split(",") if s)
                marks.add(_IMSG_BROADCAST_MARKER)
                u.nudges_sent = ",".join(sorted(marks))
                await db.commit()
                sent += 1
                await _asyncio.sleep(0.05)  # gentle on Telegram rate limits
            except Exception as e:
                failed += 1
                failures.append({"id": u.id, "telegram_id": u.telegram_id, "error": str(e)[:120]})
                logger.warning(f"Broadcast send failed → {u.telegram_id}: {e}")
        try:
            await bot.close()
        except Exception:
            pass
    return JSONResponse({"dry_run": False, "sent": sent, "failed": failed, "failures": failures})


@app.get("/admin/audit")
async def admin_audit(token: str = Query(...), name: str = Query(...)):
    """
    Read-only per-user consistency audit. For each user whose name matches
    (case-insensitive) returns: profile (tz, city, link, channel pref, reminders),
    what they SENT (conversation_logs) vs what got LOGGED (food/exercise per day),
    and a per-day check comparing entry sums to the stored DailyLog totals — plus an
    inconsistent_days list. Pinpoints where logs and dashboard diverged. No writes.
    """
    _require_admin(token)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from fastapi.responses import JSONResponse
    from db.models import User, DailyLog, ConversationLog

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(User)
            .where(User.name.ilike(f"%{name}%"))
            .options(selectinload(User.preferences))
        )
        users = res.scalars().all()
        if not users:
            return JSONResponse({"query": name, "matches": 0, "users": []})

        out = []
        for u in users:
            prefs = u.preferences
            cres = await db.execute(
                select(ConversationLog)
                .where(ConversationLog.user_id == u.id)
                .order_by(ConversationLog.timestamp.desc())
                .limit(40)
            )
            convs = list(cres.scalars().all())

            lres = await db.execute(
                select(DailyLog)
                .where(DailyLog.user_id == u.id)
                .options(
                    selectinload(DailyLog.food_entries),
                    selectinload(DailyLog.exercise_entries),
                )
                .order_by(DailyLog.date.desc())
            )
            logs = list(lres.scalars().all())

            days = []
            total_food_entries = 0
            for lg in logs:
                fe = lg.food_entries or []
                ee = lg.exercise_entries or []
                total_food_entries += len(fe)
                sum_cal = round(sum((e.calories or 0) for e in fe))
                sum_pro = round(sum((e.protein or 0) for e in fe))
                cal_ok = abs(sum_cal - round(lg.total_calories or 0)) <= 1
                pro_ok = abs(sum_pro - round(lg.total_protein or 0)) <= 1
                days.append({
                    "date": str(lg.date),
                    "food_count": len(fe),
                    "exercise_count": len(ee),
                    "entry_sum_cal": sum_cal,
                    "stored_total_cal": round(lg.total_calories or 0),
                    "entry_sum_protein": sum_pro,
                    "stored_total_protein": round(lg.total_protein or 0),
                    "totals_consistent": cal_ok and pro_ok,
                    "foods": [
                        {"name": e.parsed_food_name, "qty": e.quantity,
                         "cal": round(e.calories or 0), "protein": round(e.protein or 0)}
                        for e in fe
                    ],
                })

            out.append({
                "id": u.id,
                "name": u.name,
                "telegram_id": u.telegram_id,
                "platform": "imessage" if str(u.telegram_id).startswith("im:") else "telegram",
                "timezone": u.timezone,
                "city": getattr(u, "city", None),
                "onboarded": u.onboarding_completed,
                "linked_to_user_id": getattr(u, "linked_to_user_id", None),
                "channel_preference": getattr(u, "channel_preference", None),
                "reminders_enabled": bool(getattr(prefs, "proactive_messaging_enabled", False)) if prefs else None,
                "counts": {
                    "messages_sent": len(convs),
                    "days_with_logs": len(days),
                    "total_food_entries": total_food_entries,
                },
                "inconsistent_days": [d["date"] for d in days if not d["totals_consistent"]],
                "recent_messages": [
                    {"ts": str(c.timestamp), "sent": (c.raw_message or "")[:160],
                     "intent": c.parsed_intent}
                    for c in convs[:25]
                ],
                "days": days[:30],
            })

        return JSONResponse({"query": name, "matches": len(out), "users": out})


@app.get("/admin/flagged")
async def admin_flagged(token: str = Query(...), hours: int = Query(48),
                        limit: int = Query(100)):
    """
    Read-only turn-health feed: every conversation turn that a deterministic detector
    flagged (truncated, retried, stall_shipped, tool_error, user_frustrated) in the
    last `hours`. This is the 'watch for deviations' surface — the place the screenshots
    used to come from, now automatic. No writes.
    """
    _require_admin(token)

    from sqlalchemy import select, and_
    from fastapi.responses import JSONResponse
    from datetime import datetime, timedelta
    from db.models import ConversationLog, User

    since = datetime.utcnow() - timedelta(hours=hours)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ConversationLog, User.name)
            .join(User, User.id == ConversationLog.user_id)
            .where(and_(
                ConversationLog.parsed_intent.is_not(None),
                ConversationLog.parsed_intent != "",
                ConversationLog.timestamp >= since,
            ))
            .order_by(ConversationLog.timestamp.desc())
            .limit(limit)
        )).all()

    by_flag: dict = {}
    turns = []
    for c, uname in rows:
        flags = [f for f in (c.parsed_intent or "").split(",") if f]
        for f in flags:
            by_flag[f] = by_flag.get(f, 0) + 1
        turns.append({
            "ts": str(c.timestamp), "user": uname, "user_id": c.user_id,
            "platform": c.platform, "flags": flags,
            "sent": (c.raw_message or "")[:200],
            "reply": (c.response or "")[:200],
        })

    return JSONResponse({
        "window_hours": hours, "flagged_turns": len(turns),
        "by_flag": by_flag, "turns": turns,
    })


@app.post("/admin/debug/send-push")
async def admin_debug_send_push(
    token: str = Query(..., description="ADMIN_TOKEN gate"),
    device_token: str = Query(..., description="hex device token; use any fake hex to test credentials"),
    title: str = Query("Arnie test push"),
    body: str = Query("Hello from /admin/debug/send-push"),
    environment: str = Query("production", description="production | sandbox"),
):
    """Fire one APNs push to a specific device token. Validates the .p8 / key
    id / team id / bundle id pipeline end-to-end without depending on a real
    iOS client having registered yet.

    Even with a FAKE device token, Apple's response distinguishes credential
    vs. token problems — a 410 BadDeviceToken means the JWT + topic auth
    pipeline is wired correctly and Apple just doesn't know the token; a 403
    InvalidProviderToken means the .p8 / key id / team id are mismatched.
    Use this to validate Render env vars BEFORE the scheduler hookup
    (slice 2c) starts depending on them.
    """
    _require_admin(token)
    from notifications.apns_client import diagnose_pem, is_configured, send_push
    if not is_configured():
        return JSONResponse(
            {"ok": False, "reason": "APNS env vars not set on this deploy"},
            status_code=503,
        )
    # Catch credential/key parsing errors and surface them as structured JSON
    # plus a non-secret shape diagnostic for the .p8 env var. The normal
    # failure mode (Apple-rejected token) returns ok=False inside `send_push`
    # — a malformed .p8 raises during JWT signing, which would otherwise
    # bubble as an opaque 500. The pem_diagnostic NEVER returns any byte of
    # the key body; only character-class counts and marker presence.
    try:
        result = await send_push(device_token, title, body, environment=environment)
    except Exception as e:
        return JSONResponse(
            {
                "ok": False,
                "error": "send_push raised",
                "exception_type": type(e).__name__,
                "detail": str(e)[:400],
                "pem_diagnostic": diagnose_pem(os.environ.get("APNS_AUTH_KEY_P8", "")),
            },
            status_code=500,
        )
    return {"send_push": result}


@app.post("/admin/run-reminders")
async def admin_run_reminders(token: str = Query(...), test: int = Query(0)):
    """
    Manually fire the proactive scheduler once, for testing the rollout without waiting
    for a time slot. Respects PROACTIVE_MESSAGING_ENABLED and PROACTIVE_ALLOWLIST.

    ?test=1 → send ONE forced check-in ping to each allowlisted user, bypassing the
    time-of-day windows (so you get an instant message). Requires PROACTIVE_ALLOWLIST
    to be set, so it can never blast everyone.

    default → run the real reminder loop once. It still honors the time windows, so it
    sends only what's genuinely due right now (often nothing).
    """
    _require_admin(token)
    from scheduler.proactive_scheduler import (
        _run_reminders, proactive_enabled, _proactive_allowlist, _allowlist_allows, _send,
    )
    if not proactive_enabled():
        return JSONResponse(
            {"ok": False, "reason": "PROACTIVE_MESSAGING_ENABLED is off — nothing will send."},
            status_code=409,
        )

    if test:
        allow = _proactive_allowlist()
        if not allow:
            raise HTTPException(
                status_code=400,
                detail="Refusing test ping: set PROACTIVE_ALLOWLIST first so this can't blast everyone.",
            )
        from db.queries import get_all_active_users, resolve_send_target
        pinged = []
        async with AsyncSessionLocal() as db:
            for u in await get_all_active_users(db):
                send_id = await resolve_send_target(db, u)
                if _allowlist_allows(u.id, u.telegram_id, send_id):
                    await _send(send_id, "quick test ping 👊 your check-ins are live. you can ignore this.")
                    pinged.append(send_id)
        return JSONResponse({"ok": True, "mode": "test", "pinged": pinged})

    await _run_reminders()
    return JSONResponse({
        "ok": True, "mode": "natural",
        "note": "ran the reminder loop once; sent whatever was due now (time-gated).",
    })


@app.post("/admin/profile-sync")
async def admin_profile_sync(token: str = Query(...), name: str = Query(...)):
    """
    Force-sync the Profile Matrix for a user matched by name (case-insensitive).
    Bypasses the 3h throttle. Returns what changed and the resulting markdown head.
    Safe: read/write only to that user's profile file + user_attributes table.
    """
    _require_admin(token)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.models import User

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(User)
            .where(User.name.ilike(f"%{name}%"))
            .options(selectinload(User.preferences))
        )
        users = res.scalars().all()
        if not users:
            return JSONResponse({"ok": False, "reason": f"No user found matching '{name}'"})

        results = []
        for u in users:
            try:
                from memory.profile_updater import maybe_update_profile
                ok = await maybe_update_profile(u, db, force=True)
                from memory.profile_manager import read_profile
                md = await read_profile(u.telegram_id)
                results.append({
                    "user_id": u.id,
                    "telegram_id": u.telegram_id,
                    "name": u.name,
                    "synced": ok,
                    "profile_lines": len(md.splitlines()) if md else 0,
                    "profile_head": "\n".join(md.splitlines()[:8]) if md else None,
                })
            except Exception as e:
                results.append({
                    "user_id": u.id,
                    "name": u.name,
                    "synced": False,
                    "error": str(e),
                })

    return JSONResponse({"ok": True, "matched": len(users), "results": results})


@app.post("/admin/proactive-debug")
async def admin_proactive_debug(
    token: str = Query(...),
    name: str = Query(None),
    telegram_id: str = Query(None),
):
    """
    Per-user proactive deliverability introspector — answers "why is this user
    getting (or not getting) proactive messages right now?" by replaying the EXACT
    scheduler gate chain (reusing the real gate functions, never reimplementing
    them) and reporting the first durable gate that trips.

    Resolve a user by ?name (case-insensitive substring) or ?telegram_id (exact).
    Read-only: no messages are sent, no state is written. Auth via _require_admin.

    Note on "would_send_now": the slot branches carry CONTENT guards (e.g.
    total_calories>0, workout not yet logged) that aren't pure-function-reusable, so
    this reports eligible_slots_now = (time-window match ∩ frequency_allows) labeled
    "content not evaluated". An empty blocked_by means the durable gates all pass —
    not a guaranteed send.
    """
    _require_admin(token)

    if not name and not telegram_id:
        raise HTTPException(status_code=400, detail="Provide ?name or ?telegram_id")

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.models import User
    from scheduler.proactive_scheduler import (
        _should_skip_linked, _allowlist_allows, _proactive_allowlist,
        _is_live_convo, _proactive_pref_on, _clamp_window, _in_window,
        _has_timezone, _last_exchange, _silence_streak, _hours_since_created,
        _is_user_row, proactive_enabled,
    )
    from reminders.eligibility import frequency_allows, gate_decision, _FREQUENCY_SLOTS
    from db.queries import (
        linking_enabled, resolve_send_target, get_recent_conversations,
    )
    import pytz
    from datetime import datetime as _dt

    # Time-window → slot map mirroring the scheduler's slot branches. Used to
    # report which slots match the user's LOCAL clock right now (content not
    # evaluated — see docstring). Kept in this endpoint deliberately: it is a
    # debug projection, not a gate, and must not be a second source of truth the
    # scheduler reads.
    def _time_slots(hour, minute, wake):
        slots = []
        wake_h, wake_m = int(wake.split(":")[0]), int(wake.split(":")[1])
        morn_h, morn_m = wake_h, wake_m + 30
        if morn_m >= 60:
            morn_h += 1
            morn_m -= 60
        if hour == morn_h and 0 <= minute - morn_m < 30:
            slots.append("morning_checkin")
        if hour == 10 and minute < 30:
            slots.append("late_morning_nolog")
        if hour == 12 and minute < 30:
            slots.append("midday_pacing")
        if hour == 15 and 30 <= minute < 60:
            slots.append("preworkout")
        if hour == 16 and 30 <= minute < 60:
            slots.append("workout_check")
        if hour == 19 and minute < 30:
            slots.append("evening_pacing")
        if hour == 21 and minute < 30:
            slots.append("night_closeout")
        return slots

    async with AsyncSessionLocal() as db:
        if telegram_id:
            res = await db.execute(
                select(User).where(User.telegram_id == telegram_id)
                .options(selectinload(User.preferences))
            )
        else:
            res = await db.execute(
                select(User).where(User.name.ilike(f"%{name}%"))
                .options(selectinload(User.preferences))
            )
        users = res.scalars().all()
        if not users:
            ident = telegram_id or name
            return JSONResponse({"ok": False, "reason": f"No user found matching '{ident}'"})

        link_on = linking_enabled()
        allow_set = sorted(_proactive_allowlist())
        global_on = proactive_enabled()

        results = []
        for user in users:
            try:
                prefs = user.preferences

                # Resolve send target FIRST (the scheduler does this before the
                # allowlist gate) so the three candidate id strings are accurate.
                send_id = await resolve_send_target(db, user)

                # Shared window — feeds both _last_exchange and _silence_streak,
                # exactly as the scheduler's single fetch does.
                try:
                    recent_rows = await get_recent_conversations(db, user.id, limit=15)
                except Exception:
                    recent_rows = []
                mins_since, _lu, _la = _last_exchange(recent_rows)
                silence_streak = _silence_streak(recent_rows)
                hours_in = _hours_since_created(user)

                # Local clock + window.
                tz_name = user.timezone or "UTC"
                try:
                    now_local = _dt.now(pytz.timezone(tz_name))
                except Exception:
                    now_local = _dt.now(pytz.utc)
                hhmm = now_local.strftime("%H:%M")
                wake, sleep = _clamp_window(prefs)

                has_tz = _has_timezone(user)
                in_win = _in_window(hhmm, wake, sleep)
                pref_on = _proactive_pref_on(prefs)
                verdict = gate_decision(silence_streak, hours_in, prefs)

                # Durable + transient gates in SCHEDULER ORDER. blocked_by is the
                # ordered list of every gate that trips; overall is would_send_now
                # only when ALL gates pass.
                blocked_by = []
                if not global_on:
                    blocked_by.append("globally_off")
                if _should_skip_linked(user, link_on):
                    blocked_by.append("skip_linked")
                if not _allowlist_allows(user.id, user.telegram_id, send_id):
                    blocked_by.append("allowlist")
                if _is_live_convo(mins_since):
                    blocked_by.append("live_conversation")
                if not has_tz:
                    blocked_by.append("no_timezone")
                if not pref_on:
                    blocked_by.append("proactive_pref_off")
                if not in_win:
                    blocked_by.append("outside_window")
                if verdict == "suppress":
                    blocked_by.append("silence_suppress")
                elif verdict == "consolidate":
                    blocked_by.append("silence_consolidate")

                # Slots whose LOCAL time-window matches AND pass the frequency
                # filter. Content guards NOT evaluated (see docstring).
                eligible_slots_now = []
                if has_tz:
                    for slot in _time_slots(now_local.hour, now_local.minute, wake):
                        if frequency_allows(prefs, slot):
                            eligible_slots_now.append(slot)

                nudges_raw = user.nudges_sent or ""
                nudges_today = sorted(
                    s for s in nudges_raw.split(",")
                    if s and s.endswith(str(now_local.date()))
                )

                results.append({
                    "user_id": user.id,
                    "name": user.name,
                    "telegram_id": user.telegram_id,
                    "send_id": send_id,
                    "linked_to_user_id": user.linked_to_user_id,
                    "overall": "would_send_now" if not blocked_by else "BLOCKED",
                    "blocked_by": blocked_by,
                    "gates": {
                        "globally_enabled": global_on,
                        "skip_linked": _should_skip_linked(user, link_on),
                        "linking_enabled": link_on,
                        "allowlist_set": bool(allow_set),
                        "allowlist": allow_set,
                        "allowlist_candidates": [
                            str(user.id), str(user.telegram_id), str(send_id),
                        ],
                        "allowlist_allows": _allowlist_allows(
                            user.id, user.telegram_id, send_id),
                        "live_conversation": _is_live_convo(mins_since),
                        "mins_since_last_user_msg": mins_since,
                        "timezone": tz_name,
                        "has_timezone": has_tz,
                        "local_now": hhmm,
                        "window": [wake, sleep],
                        "in_window": in_win,
                        "proactive_pref_on": pref_on,
                        "silence_streak": silence_streak,
                        "hours_since_created": round(hours_in, 1),
                        "gate_verdict": verdict,
                    },
                    "eligible_slots_now": eligible_slots_now,
                    "eligible_slots_note": "time-window ∩ frequency only; content NOT evaluated",
                    "nudges_sent_raw": nudges_raw,
                    "nudges_sent_today": nudges_today,
                })
            except Exception as e:
                results.append({"user_id": getattr(user, "id", None), "error": str(e)})

    return JSONResponse({
        "ok": True,
        "proactive_enabled": global_on,
        "allowlist": allow_set,
        "matched": len(results),
        "results": results,
    })


@app.post("/admin/profile-consolidate")
async def admin_profile_consolidate(token: str = Query(...), name: str = Query(...)):
    """
    Force-run the nightly profile consolidator for a user matched by name.
    Discontinues redundant/superseded attributes and shortens verbose values.
    Safe: only touches non-confirmed attributes; confirmed facts are never removed.
    """
    _require_admin(token)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.models import User

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(User)
            .where(User.name.ilike(f"%{name}%"))
            .options(selectinload(User.preferences))
        )
        users = res.scalars().all()
        if not users:
            return JSONResponse({"ok": False, "reason": f"No user found matching '{name}'"})

        results = []
        for u in users:
            try:
                from memory.profile_consolidator import consolidate_user_profile
                result = await consolidate_user_profile(u, db)
                results.append({
                    "user_id": u.id,
                    "telegram_id": u.telegram_id,
                    "name": u.name,
                    "discontinued": result["discontinued"],
                    "shortened": result["shortened"],
                })
            except Exception as e:
                results.append({
                    "user_id": u.id,
                    "name": u.name,
                    "error": str(e),
                })

    return JSONResponse({"ok": True, "matched": len(users), "results": results})


# ── Admin dashboard ───────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(token: str = Query(...)):
    _require_admin(token)

    from sqlalchemy import select, func as sqlfunc
    from sqlalchemy.orm import selectinload
    from db.models import (User, DailyLog, ConversationLog, Feedback,
                           FoodEntry, ExerciseEntry, BodyMetric)
    from datetime import datetime, timezone

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    today = date.today()

    async with AsyncSessionLocal() as db:
        users_result = await db.execute(
            select(User)
            .options(selectinload(User.preferences))
            .order_by(User.created_at.desc())
        )
        users = users_result.scalars().all()

        # Feedback — all entries newest first
        fb_result = await db.execute(
            select(Feedback, User.name)
            .join(User, Feedback.user_id == User.id)
            .order_by(Feedback.created_at.desc())
        )
        feedbacks = fb_result.all()

        now = datetime.now(timezone.utc)

        def _aware(dt):
            if not dt:
                return None
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

        rows = []
        for u in users:
            today_log = (await db.execute(
                select(DailyLog).where(DailyLog.user_id == u.id, DailyLog.date == today)
            )).scalar_one_or_none()

            last_conv = (await db.execute(
                select(ConversationLog).where(ConversationLog.user_id == u.id)
                .order_by(ConversationLog.timestamp.desc()).limit(1)
            )).scalar_one_or_none()

            msg_count = (await db.execute(
                select(sqlfunc.count()).where(ConversationLog.user_id == u.id)
            )).scalar() or 0

            # Last ACTIVITY across every signal (not just chat) — a user logging food
            # without messaging is still active.
            dl_ids = select(DailyLog.id).where(DailyLog.user_id == u.id)
            last_food = (await db.execute(
                select(sqlfunc.max(FoodEntry.timestamp)).where(FoodEntry.daily_log_id.in_(dl_ids)))).scalar()
            last_ex = (await db.execute(
                select(sqlfunc.max(ExerciseEntry.timestamp)).where(ExerciseEntry.daily_log_id.in_(dl_ids)))).scalar()
            last_wt = (await db.execute(
                select(sqlfunc.max(BodyMetric.timestamp)).where(BodyMetric.user_id == u.id))).scalar()
            cand = [_aware(t) for t in
                    [last_conv.timestamp if last_conv else None, last_food, last_ex, last_wt] if t]
            last_act = max(cand) if cand else None

            rows.append({
                "user": u,
                "today_log": today_log,
                "last_conv": last_conv,
                "msg_count": msg_count,
                "last_act": last_act,
                "dash_url": dashboard_url(u.webhook_token) if u.webhook_token else None,
            })

        # Activity-first: most recently active users on top.
        rows.sort(key=lambda r: r["last_act"] or datetime(1970, 1, 1, tzinfo=timezone.utc),
                  reverse=True)

    def _ago(ts):
        if not ts:
            return "—"
        delta = date.today() - ts.date()
        if delta.days == 0:
            return "today"
        if delta.days == 1:
            return "yesterday"
        return f"{delta.days}d ago"

    def _goal_badge(goal):
        colors = {"cut": "#e74c3c", "bulk": "#2ecc71", "maintain": "#3498db",
                  "performance": "#9b59b6", "health": "#1abc9c"}
        c = colors.get(goal or "", "#888")
        return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px">{goal or "—"}</span>'

    def _cal_bar(log, target):
        if not log or not target:
            return "—"
        pct = min(100, int((log.total_calories or 0) / target * 100))
        color = "#2ecc71" if 85 <= pct <= 110 else "#e74c3c" if pct > 115 else "#f39c12"
        return (f'<div style="display:flex;align-items:center;gap:6px">'
                f'<div style="width:60px;height:6px;background:#333;border-radius:3px">'
                f'<div style="width:{pct}%;height:100%;background:{color};border-radius:3px"></div></div>'
                f'<span style="font-size:11px">{int(log.total_calories or 0)}/{target}</span></div>')

    STATUS_META = {
        "active": ("Active", "#2ecc71"), "idle": ("Idle", "#f1c40f"),
        "dormant": ("Dormant", "#e74c3c"), "deactivated": ("Deactivated", "#7f8c8d"),
        "onboarding": ("Onboarding", "#e67e22"),
    }

    def _hours_since(dt):
        return (now - dt).total_seconds() / 3600 if dt else None

    def _status_key(u, last_act):
        if (u.subscription_status or "") == "inactive":
            return "deactivated"
        if not u.onboarding_completed:
            return "onboarding"
        h = _hours_since(last_act)
        if h is None:
            return "dormant"
        return "active" if h <= 24 else "idle" if h <= 96 else "dormant"

    def _recency(last_act):
        h = _hours_since(last_act)
        if h is None:
            return ("never", "#e74c3c")
        if h < 1:
            return ("just now", "#2ecc71")
        if h < 24:
            return (f"{int(h)}h ago", "#2ecc71")
        d = h / 24
        return (f"{int(d)}d ago", "#f1c40f" if d <= 4 else "#e74c3c")

    from collections import Counter
    status_counts = Counter()
    tbody = ""
    for r in rows:
        u = r["user"]
        p = u.preferences
        log = r["today_log"]
        last = r["last_conv"]
        dash = r["dash_url"]

        skey = _status_key(u, r["last_act"])
        status_counts[skey] += 1
        slabel, scolor = STATUS_META[skey]
        rec_label, rec_color = _recency(r["last_act"])
        status_badge = (f'<span style="background:{scolor};color:#fff;padding:2px 8px;'
                        f'border-radius:10px;font-size:10px;font-weight:600">{slabel}</span>')

        last_msg_snippet = (_esc(last.raw_message or "")[:48] + "…") if last and last.raw_message and len(last.raw_message) > 48 else _esc(last.raw_message if last else "")
        today_calories = _cal_bar(log, p.calorie_target if p else None)
        today_protein = f'{int(log.total_protein or 0)}g / {p.protein_target or "?"}g' if log else "—"
        workout_dot = '<span style="color:#2ecc71">✓</span>' if (log and log.workout_completed) else '<span style="color:#555">✗</span>'
        dash_link = f'<a href="{dash}" target="_blank" style="color:#3498db;text-decoration:none">↗ dash</a>' if dash else "—"
        whoop = '<span style="color:#2ecc71">●</span>' if (u.whoop_access_token or u.whoop_refresh_token) else '<span style="color:#555">○</span>'
        created = u.created_at.strftime("%b %d") if u.created_at else "—"
        search_blob = _esc(((u.name or "") + " " + (u.telegram_id or "")).lower())

        convo_link = f'<a href="/admin/user/{u.id}?token={token}" style="color:#f39c12">💬 convo</a>'
        tbody += f"""<tr data-status="{skey}" data-s="{search_blob}">
          <td><b>{_esc(u.name or "?")}</b><br><span style="color:#888;font-size:10px">{_esc(u.telegram_id)}</span></td>
          <td>{status_badge}</td>
          <td>{_goal_badge(u.primary_goal)}<br><span style="color:#888;font-size:10px">{u.training_experience or "?"}</span></td>
          <td style="font-size:11px">{today_calories}<br><span style="color:#aaa">{today_protein} P &nbsp;{workout_dot}</span></td>
          <td style="font-size:11px;max-width:200px;overflow:hidden"><span style="color:{rec_color};font-weight:600">{rec_label}</span><br><span style="color:#888">{last_msg_snippet}</span></td>
          <td style="color:#aaa;font-size:11px">{r['msg_count']}</td>
          <td style="font-size:11px">{whoop}<br><span style="color:#555">whoop</span></td>
          <td style="font-size:11px">{created}</td>
          <td style="white-space:nowrap">{dash_link}<br>{convo_link}</td>
        </tr>"""

    # ── Feedback panel HTML ──────────────────────────────────────────────────
    open_fb = [f for f, _ in feedbacks if not f.resolved]
    done_fb = [f for f, _ in feedbacks if f.resolved]
    user_name_map = {f.id: name for f, name in feedbacks}

    def _fb_badge(kind):
        return f'<span class="badge-{kind}">{kind}</span>'

    def _fb_rows(items):
        if not items:
            return '<tr><td colspan="5" style="color:#555;padding:16px">None</td></tr>'
        out = ""
        for f in items:
            uname = _esc(user_name_map.get(f.id, "?"))
            ts = f.created_at.strftime("%b %d %H:%M") if f.created_at else "—"
            resolve_ctrl = (
                f'<form method="post" action="/admin/feedback/{f.id}/resolve?token={token}" style="display:inline">'
                f'<button class="resolve-btn" type="submit">✓ resolve</button></form>'
                if not f.resolved else '<span class="resolved-label">✓ resolved</span>'
            )
            out += (f'<tr><td>{_fb_badge(f.kind or "other")}</td>'
                    f'<td style="font-size:12px;color:#aaa">{uname}</td>'
                    f'<td style="max-width:600px;font-size:13px">{_esc(f.text)}</td>'
                    f'<td style="font-size:11px;color:#666;white-space:nowrap">{ts}</td>'
                    f'<td>{resolve_ctrl}</td></tr>')
        return out

    feedback_html = f"""
<h2 style="margin-top:0">Open ({len(open_fb)})</h2>
<table>
<thead><tr><th>Type</th><th>User</th><th>Feedback</th><th>Date</th><th></th></tr></thead>
<tbody>{_fb_rows(open_fb)}</tbody>
</table>
<h2>Resolved ({len(done_fb)})</h2>
<table>
<thead><tr><th>Type</th><th>User</th><th>Feedback</th><th>Date</th><th></th></tr></thead>
<tbody>{_fb_rows(done_fb)}</tbody>
</table>"""

    open_fb_count = len(open_fb)
    _card_defs = [
        ("all", "All", len(rows), "#3498db"),
        ("active", "Active", status_counts.get("active", 0), "#2ecc71"),
        ("idle", "Idle", status_counts.get("idle", 0), "#f1c40f"),
        ("dormant", "Dormant", status_counts.get("dormant", 0), "#e74c3c"),
        ("deactivated", "Deactivated", status_counts.get("deactivated", 0), "#7f8c8d"),
        ("onboarding", "Onboarding", status_counts.get("onboarding", 0), "#e67e22"),
    ]
    cards_html = "".join(
        f'<div class="card{" active" if k == "all" else ""}" data-filter="{k}" '
        f'onclick="filterStatus(\'{k}\',this)">'
        f'<div class="card-n" style="color:{c}">{n}</div>'
        f'<div class="card-l">{lbl}</div></div>'
        for k, lbl, n, c in _card_defs
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arnie Admin</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#111;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px;max-width:1400px;margin:0 auto}}
  h1{{font-size:20px;font-weight:700;margin-bottom:4px}}
  h2{{font-size:15px;font-weight:600;margin:32px 0 12px}}
  .sub{{color:#888;font-size:13px;margin-bottom:24px}}
  .tabs{{display:flex;gap:4px;margin-bottom:20px;border-bottom:1px solid #222;padding-bottom:0}}
  .tab{{padding:8px 16px;cursor:pointer;font-size:13px;color:#888;border-bottom:2px solid transparent;margin-bottom:-1px}}
  .tab.active{{color:#fff;border-bottom-color:#3498db}}
  .panel{{display:none}}.panel.active{{display:block}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{text-align:left;padding:8px 12px;border-bottom:1px solid #2a2a2a;color:#888;font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
  td{{padding:10px 12px;border-bottom:1px solid #1e1e1e;vertical-align:middle}}
  tr:hover td{{background:#1a1a1a}}
  .stat{{color:#aaa;font-size:11px;margin-top:16px}}
  .badge-bug{{background:#e74c3c;color:#fff;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}}
  .badge-feature{{background:#9b59b6;color:#fff;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}}
  .badge-other{{background:#555;color:#fff;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}}
  .resolve-btn{{background:#1e3a1e;color:#2ecc71;border:1px solid #2ecc71;padding:3px 10px;border-radius:6px;font-size:11px;cursor:pointer}}
  .resolved-label{{color:#555;font-size:11px}}
  a{{color:#3498db;text-decoration:none}}a:hover{{text-decoration:underline}}
  .cards{{display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap}}
  .card{{background:#181818;border:1px solid #262626;border-radius:10px;padding:10px 16px;cursor:pointer;min-width:92px;transition:border-color .15s}}
  .card:hover{{border-color:#444}}
  .card.active{{border-color:#3498db;background:#1a2230}}
  .card-n{{font-size:22px;font-weight:700;line-height:1}}
  .card-l{{font-size:10px;color:#888;margin-top:3px;text-transform:uppercase;letter-spacing:.04em}}
  .search{{width:100%;max-width:320px;background:#181818;border:1px solid #262626;color:#e0e0e0;padding:8px 12px;border-radius:8px;font-size:13px;margin-bottom:14px}}
  .search:focus{{outline:none;border-color:#3498db}}
  tr.hidden{{display:none}}
</style>
</head>
<body>
<h1>⚡ Arnie Admin</h1>
<p class="sub">{len(rows)} users &nbsp;·&nbsp; <span style="color:#2ecc71">{status_counts.get('active',0)} active</span> &nbsp;·&nbsp; {status_counts.get('idle',0)} idle &nbsp;·&nbsp; {status_counts.get('dormant',0)} dormant &nbsp;·&nbsp; {status_counts.get('deactivated',0)} deactivated &nbsp;·&nbsp; {open_fb_count} open feedback &nbsp;·&nbsp; <a href="/admin?token={token}">↻ refresh</a></p>

<div class="tabs">
  <div class="tab active" onclick="switchTab('users',this)">Users</div>
  <div class="tab" onclick="switchTab('feedback',this)">Feedback</div>
</div>

<div id="panel-users" class="panel active">
<div class="cards">{cards_html}</div>
<input id="search" class="search" placeholder="🔍 search name or contact…" oninput="applyFilters()">
<table>
<thead><tr>
  <th>User</th><th>Status</th><th>Goal</th>
  <th>Today</th><th>Last active</th><th>Msgs</th>
  <th>Devices</th><th>Joined</th><th>Links</th>
</tr></thead>
<tbody id="user-rows">{tbody}</tbody>
</table>
<p id="empty-note" style="color:#555;padding:16px;display:none">No users match.</p>
</div>

<div id="panel-feedback" class="panel">
{feedback_html}
</div>

<p class="stat">Arnie Admin &nbsp;·&nbsp; {today}</p>
<script>
function switchTab(name,el){{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('panel-'+name).classList.add('active');
}}
var statusFilter='all';
function filterStatus(key,el){{
  statusFilter=key;
  document.querySelectorAll('.card').forEach(c=>c.classList.remove('active'));
  if(el) el.classList.add('active');
  applyFilters();
}}
function applyFilters(){{
  var q=(document.getElementById('search').value||'').trim().toLowerCase();
  var shown=0;
  document.querySelectorAll('#user-rows tr').forEach(function(tr){{
    var okS=(statusFilter==='all')||(tr.dataset.status===statusFilter);
    var okQ=!q||(tr.dataset.s||'').indexOf(q)>=0;
    var vis=okS&&okQ;
    tr.classList.toggle('hidden',!vis);
    if(vis) shown++;
  }});
  document.getElementById('empty-note').style.display=shown?'none':'block';
}}
</script>
</body>
</html>"""
    return HTMLResponse(html)


# ── Admin: resolve feedback ────────────────────────────────────────────────────

@app.post("/admin/feedback/{feedback_id}/resolve", response_class=HTMLResponse)
async def admin_resolve_feedback(feedback_id: int, token: str = Query(...)):
    _require_admin(token)
    from sqlalchemy import select
    from db.models import Feedback
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
        fb = result.scalar_one_or_none()
        if fb:
            fb.resolved = True
            await db.commit()
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/admin?token={token}#feedback", status_code=303)


# ── Admin: user conversation history ──────────────────────────────────────────

@app.get("/admin/user/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(user_id: int, token: str = Query(...)):
    _require_admin(token)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.models import User, ConversationLog

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(
            select(User).where(User.id == user_id)
            .options(selectinload(User.preferences))
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return HTMLResponse("<h2>User not found</h2>", status_code=404)

        convos_result = await db.execute(
            select(ConversationLog)
            .where(ConversationLog.user_id == user_id)
            .order_by(ConversationLog.timestamp.desc())
            .limit(200)
        )
        convos = convos_result.scalars().all()

    def _src_badge(src):
        colors = {"text": "#3498db", "voice": "#e67e22", "image": "#9b59b6", "photo": "#9b59b6"}
        c = colors.get(src or "text", "#555")
        return f'<span style="background:{c};color:#fff;padding:1px 6px;border-radius:8px;font-size:10px">{src or "text"}</span>'

    def _platform_badge(p):
        if not p:
            return ""
        colors = {"telegram": "#229ED9", "imessage": "#34C759", "ios": "#000000"}
        c = colors.get(p, "#555")
        return f'<span style="background:{c};color:#fff;padding:1px 6px;border-radius:8px;font-size:10px">{p}</span>'

    rows = ""
    prev_date = None
    for c in convos:
        ts = c.timestamp
        day = ts.strftime("%A, %B %d %Y") if ts else "?"
        time_str = ts.strftime("%H:%M") if ts else "—"

        if day != prev_date:
            rows += f'<tr><td colspan="2" style="background:#1a1a1a;color:#666;font-size:11px;padding:8px 16px;letter-spacing:.05em">{day}</td></tr>'
            prev_date = day

        user_msg = _esc(c.raw_message or "")
        arnie_msg = _esc(c.response or "")
        rows += f"""<tr>
          <td style="width:50%;padding:12px 16px;vertical-align:top;border-bottom:1px solid #1a1a1a">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <span style="font-size:11px;color:#888">{time_str}</span>
              {_src_badge(c.source_type)}
              {_platform_badge(c.platform)}
            </div>
            <div style="background:#1e2a3a;border-radius:12px 12px 12px 2px;padding:10px 14px;font-size:13px;line-height:1.5;white-space:pre-wrap">{user_msg}</div>
          </td>
          <td style="width:50%;padding:12px 16px;vertical-align:top;border-bottom:1px solid #1a1a1a">
            <div style="margin-bottom:6px"><span style="font-size:11px;color:#f39c12">⚡ Arnie</span></div>
            <div style="background:#1a2a1a;border-radius:12px 12px 2px 12px;padding:10px 14px;font-size:13px;line-height:1.5;white-space:pre-wrap">{arnie_msg}</div>
          </td>
        </tr>"""

    dash_link = f'<a href="{dashboard_url(user.webhook_token)}" target="_blank">↗ Dashboard</a>' if user.webhook_token else ""
    goal = user.primary_goal or "—"
    exp = user.training_experience or "—"
    joined = user.created_at.strftime("%b %d, %Y") if user.created_at else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(user.name or "User")} — Arnie Admin</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#111;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
  .header{{padding:20px 24px;border-bottom:1px solid #222;display:flex;align-items:center;gap:16px}}
  .back{{color:#888;font-size:13px;text-decoration:none}}
  .back:hover{{color:#fff}}
  .name{{font-size:18px;font-weight:700}}
  .meta{{font-size:12px;color:#888;margin-top:2px}}
  table{{width:100%;border-collapse:collapse}}
  a{{color:#3498db;text-decoration:none}}
</style>
</head>
<body>
<div class="header">
  <a class="back" href="/admin?token={token}">← Admin</a>
  <div>
    <div class="name">{_esc(user.name or "Unknown")}</div>
    <div class="meta">{goal} · {exp} · {len(convos)} messages · joined {joined} &nbsp; {dash_link}</div>
  </div>
</div>
<table>
<thead><tr>
  <th style="padding:8px 16px;border-bottom:1px solid #222;color:#888;font-size:11px;text-transform:uppercase">User</th>
  <th style="padding:8px 16px;border-bottom:1px solid #222;color:#888;font-size:11px;text-transform:uppercase">Arnie</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
    return HTMLResponse(html)


# ── Dashboard log endpoints ────────────────────────────────────────────────────

@app.get("/api/food/search")
async def api_food_search(q: str = Query(..., min_length=2), token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
    results = await _usda_search(q, page_size=8)
    return {"results": [
        {
            "name": r["description"],
            "brand": r.get("brand", ""),
            "per100g": r["per100g"],
            "fdc_id": r["fdc_id"],
        }
        for r in results
    ]}


class FoodLogBody(BaseModel):
    name: str
    quantity: Optional[str] = None
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fats: float = 0
    estimated: bool = True
    log_date: Optional[str] = None  # YYYY-MM-DD, defaults to viewing date


@app.post("/api/food/log")
async def api_log_food(body: FoodLogBody, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        tz = getattr(user, "timezone", None) or "UTC"
        if body.log_date:
            log = await get_or_create_log_for_date(db, user.id, date.fromisoformat(body.log_date))
        else:
            log = await get_or_create_today_log(db, user.id, tz)
        entry = await add_food_entry(
            db, log.id,
            parsed_food_name=body.name,
            quantity=body.quantity,
            calories=round(body.calories),
            protein=round(body.protein, 1),
            carbs=round(body.carbs, 1),
            fats=round(body.fats, 1),
            estimated_flag=body.estimated,
        )
    return {"status": "ok", "id": entry.id}


class WaterLogBody(BaseModel):
    amount_ml: float
    log_date: Optional[str] = None  # YYYY-MM-DD, defaults to today


@app.post("/api/water/log")
async def api_log_water(body: WaterLogBody, token: str = Query(...)):
    """Manual hydration log from the dashboard. Adds a canonical WaterEntry row
    and bumps the cached DailyLog.total_water_ml aggregate (the tile/context read
    it)."""
    from db.queries import add_water_entry
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        tz = getattr(user, "timezone", None) or "UTC"
        if body.log_date:
            log = await get_or_create_log_for_date(db, user.id, date.fromisoformat(body.log_date))
        else:
            log = await get_or_create_today_log(db, user.id, tz)
        amount = max(0.0, body.amount_ml)
        entry = await add_water_entry(
            db, user.id, log.id, amount_ml=amount, source_type="dashboard",
        )
        # add_water_entry leaves the aggregate to the caller — bump it here.
        log.total_water_ml = (log.total_water_ml or 0) + amount
        await db.commit()
    return {"status": "ok", "id": entry.id}


class ExerciseLogBody(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight_lbs: Optional[float] = None
    duration_minutes: Optional[float] = None
    is_cardio: bool = False
    log_date: Optional[str] = None


class WeightLogBody(BaseModel):
    weight: float            # value as the user typed it
    unit: str = "lbs"        # "lbs" or "kg"


@app.post("/api/weight/log")
async def api_log_weight(body: WeightLogBody, token: str = Query(...)):
    """Persist a dashboard weigh-in and ping the user's chat with a short,
    goal-aware Arnie reaction. Same reactive-confirmation pattern as the
    food/exercise edit endpoints — no proactive gate."""
    import asyncio
    unit = (body.unit or "lbs").lower()
    if unit not in ("lbs", "kg"):
        raise HTTPException(status_code=400, detail="unit must be 'lbs' or 'kg'")
    weight_kg = body.weight * 0.453592 if unit == "lbs" else body.weight
    if not (20.0 <= weight_kg <= 410.0):
        raise HTTPException(status_code=400, detail="weight out of range")

    notify: dict = {}
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        prior = await get_recent_weights(db, user.id, days=120)
        # get_recent_weights returns newest-first; pick the most recent prior
        # reading BEFORE we insert this one.
        prev_lbs = None
        if prior:
            prev_lbs = round(prior[0].weight_kg * 2.20462, 1)

        # Web/webhook weigh-in is a deliberate user-entered number → "manual".
        metric = await add_body_metric(db, user.id, weight_kg=weight_kg, source="manual")

        current_lbs = round(weight_kg * 2.20462, 1)
        delta_lbs = round(current_lbs - prev_lbs, 1) if prev_lbs is not None else None

        goal_kg = getattr(user, "goal_weight_kg", None)
        to_goal_lbs = None
        if goal_kg:
            to_goal_lbs = round(abs(weight_kg - goal_kg) * 2.20462, 1)

        goal_v = (user.primary_goal or "").strip()

        # Show the weight in the unit the user entered — feels native.
        label = f"{body.weight:.1f} {unit}"
        text = _dashboard_msg(
            "weight_log",
            label=label,
            goal=goal_v,
            prev_lbs=prev_lbs,
            delta_lbs=delta_lbs,
            to_goal=to_goal_lbs,
        )
        notify = dict(
            send_target=await resolve_send_target(db, user),
            text=text,
        )
        entry_id = metric.id

    asyncio.create_task(_send_dashboard_notification(**notify))
    return {"status": "ok", "id": entry_id,
            "weight_lbs": current_lbs, "weight_kg": round(weight_kg, 2)}


@app.post("/api/exercise/log")
async def api_log_exercise(body: ExerciseLogBody, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        tz = getattr(user, "timezone", None) or "UTC"
        if body.log_date:
            log = await get_or_create_log_for_date(db, user.id, date.fromisoformat(body.log_date))
        else:
            log = await get_or_create_today_log(db, user.id, tz)
        weight_kg = body.weight_lbs * 0.453592 if body.weight_lbs else None
        entry = await add_exercise_entry(
            db, log.id,
            is_cardio=body.is_cardio,
            parsed_exercise_name=body.name,
            sets=body.sets,
            reps=body.reps,
            weight_kg=weight_kg,
            duration_minutes=body.duration_minutes,
        )
    return {"status": "ok", "id": entry.id}


# ── Whoop sync (dashboard-triggered) ──────────────────────────────────────────

@app.post("/api/whoop/sync/{token}")
async def dashboard_whoop_sync(token: str):
    """Pull latest 30 days of Whoop data for the dashboard user."""
    from api.whoop import sync_user_whoop
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        # If tokens are on a linked identity, use that user for the sync
        if not (user.whoop_access_token or user.whoop_refresh_token):
            from sqlalchemy import select as _sel
            from db.models import User as _U
            linked = (await db.execute(
                _sel(_U).where(_U.linked_to_user_id == user.id)
            )).scalars().all()
            whoop_user = next(
                (u for u in linked if u.whoop_access_token or u.whoop_refresh_token), None
            )
            if not whoop_user:
                return {"status": "not_connected", "days": 0}
        else:
            whoop_user = user

        # Save snapshots to canonical user so stats API finds them
        synced = await sync_user_whoop(db, whoop_user, days=30,
                                       snapshot_user_id=user.id)
        return {"status": "ok", "days": synced}


# ── Workout Program ────────────────────────────────────────────────────────────

@app.get("/api/workout/{token}")
async def get_workout_program(token: str):
    """Return the user's structured workout program, or null if not set."""
    import json
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        from db.models import WorkoutProgram
        from sqlalchemy import select
        row = (await db.execute(select(WorkoutProgram).where(WorkoutProgram.user_id == user.id))).scalar_one_or_none()
        if not row:
            return {"program": None}
        try:
            return {"program": json.loads(row.program_json), "raw_text": row.raw_text}
        except Exception:
            return {"program": None}


class WorkoutParseBody(BaseModel):
    raw_text: str


@app.post("/api/workout/{token}/parse")
async def parse_and_save_workout(token: str, body: WorkoutParseBody):
    """AI-parse raw workout text into structured JSON, then save it."""
    import json
    from core.llm import _get_anthropic, DEFAULT_MODEL, ANTHROPIC_API_KEY

    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        if not ANTHROPIC_API_KEY():
            raise HTTPException(status_code=503, detail="AI unavailable")

        prompt = f"""Parse this workout program description into structured JSON. Return ONLY valid JSON, no prose.

Required structure:
{{
  "split_name": "short descriptive name (e.g. Upper-Focus PPL)",
  "focus": "one sentence summary",
  "rotation": ["Day 1 name", "Day 2 name", ...],
  "days": [
    {{
      "name": "muscle group label",
      "priority": "primary | secondary | optional",
      "goals": ["goal 1", "goal 2"],
      "exercises": [
        {{
          "name": "Exercise Name",
          "category": "main | accessory | cardio",
          "recent_performance": "e.g. 200 × 14 (PR), 200 × 12" or null,
          "notes": null
        }}
      ],
      "notes": "any extra context about this day"
    }}
  ]
}}

Workout description:
{body.raw_text}
"""
        client = _get_anthropic()
        resp = await client.messages.create(
            model=DEFAULT_MODEL(),
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()

        try:
            program = json.loads(text)
        except Exception:
            raise HTTPException(status_code=422, detail="AI returned unparseable JSON")

        from db.models import WorkoutProgram
        from sqlalchemy import select
        row = (await db.execute(select(WorkoutProgram).where(WorkoutProgram.user_id == user.id))).scalar_one_or_none()
        if row:
            row.raw_text = body.raw_text
            row.program_json = json.dumps(program)
        else:
            db.add(WorkoutProgram(user_id=user.id, raw_text=body.raw_text, program_json=json.dumps(program)))
        await db.commit()

        # Bridge: mirror the split summary into the fitness attributes so it shows
        # in the AI Profile + feeds the bio. Full program stays in WorkoutProgram.
        from memory.attribute_store import sync_program_to_attributes
        await sync_program_to_attributes(db, user.id, program)

        return {"program": program}


@app.post("/api/workout/{token}/auto-fill")
async def auto_fill_workout_program(token: str):
    """
    Synthesize a workout program from the user's Arnie memory + recent
    conversation history across ALL linked platforms (Telegram + iMessage).
    """
    import json
    from sqlalchemy import select, desc
    from core.llm import _get_anthropic, DEFAULT_MODEL, ANTHROPIC_API_KEY
    from memory.memory_manager import read_memory

    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        if not ANTHROPIC_API_KEY():
            raise HTTPException(status_code=503, detail="AI unavailable")

        from db.models import ConversationLog, User as UserModel

        # Collect ALL user IDs for this identity (canonical + any linked platforms)
        # iMessage identities: linked_to_user_id == user.id
        linked_users = (await db.execute(
            select(UserModel).where(UserModel.linked_to_user_id == user.id)
        )).scalars().all()
        all_user_ids = [user.id] + [u.id for u in linked_users]
        all_telegram_ids = [user.telegram_id] + [u.telegram_id for u in linked_users]

        # Pull memory from ALL linked identities and merge
        memory_parts = []
        for tid in all_telegram_ids:
            try:
                m = await read_memory(tid)
                if m and m.strip():
                    platform_label = "iMessage" if str(tid).startswith("im:") else "Telegram"
                    memory_parts.append(f"[{platform_label} memory]\n{m}")
            except Exception:
                pass
        memory_text = "\n\n".join(memory_parts) or ""

        # Pull last 80 conversation turns across all platforms
        rows = (await db.execute(
            select(ConversationLog)
            .where(ConversationLog.user_id.in_(all_user_ids))
            .order_by(desc(ConversationLog.timestamp))
            .limit(80)
        )).scalars().all()

        # Filter to messages that mention workout/exercise keywords
        kw = ("workout", "gym", "lift", "press", "pull", "push", "squat", "chest",
              "back", "shoulder", "arm", "leg", "cardio", "set", "rep", "exercise",
              "train", "split", "day", "pr", "bench", "deadlift", "curl", "incline",
              "flat", "fly", "row", "pulldown", "lateral", "shrug", "curl", "lunge")
        relevant = []
        for r in reversed(rows):
            combined = ((r.raw_message or "") + " " + (r.response or "")).lower()
            if any(k in combined for k in kw):
                platform = r.platform or "telegram"
                relevant.append(f"[{platform}] User: {r.raw_message or ''}\nArnie: {r.response or ''}")

        convo_context = "\n\n---\n\n".join(relevant[-35:]) if relevant else "(no workout conversations found)"

        prompt = f"""You are extracting a user's workout program from their fitness coaching history.

Read the memory notes and conversation snippets below, then produce a structured JSON workout program.

IMPORTANT: Only include information that is actually present in the context. If something is unclear or missing, omit it. Do not invent exercises or details.

Memory notes:
{memory_text or '(empty)'}

Recent workout-related conversations (most recent first):
{convo_context}

Return ONLY valid JSON in this structure:
{{
  "split_name": "descriptive name based on what you found",
  "focus": "one sentence summary of their training focus",
  "rotation": ["Day 1 name", "Day 2 name", ...],
  "days": [
    {{
      "name": "muscle group / session name",
      "priority": "primary | secondary | optional",
      "goals": ["goal 1", "goal 2"],
      "exercises": [
        {{
          "name": "Exercise Name",
          "category": "main | accessory | cardio",
          "recent_performance": "e.g. 225 × 5 (PR)" or null,
          "notes": null
        }}
      ],
      "notes": "any extra context"
    }}
  ]
}}

If there is not enough workout information to build a meaningful program, return:
{{"insufficient_data": true, "reason": "brief explanation"}}
"""
        client = _get_anthropic()
        resp = await client.messages.create(
            model=DEFAULT_MODEL(),
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()

        try:
            program = json.loads(text)
        except Exception:
            raise HTTPException(status_code=422, detail="AI returned unparseable JSON")

        if program.get("insufficient_data"):
            return {"program": None, "reason": program.get("reason", "Not enough workout data in your conversation history yet.")}

        # Save it
        from db.models import WorkoutProgram
        row = (await db.execute(select(WorkoutProgram).where(WorkoutProgram.user_id == user.id))).scalar_one_or_none()
        raw_summary = f"[Auto-filled from Arnie conversation history]\n\n{memory_text}"
        if row:
            row.raw_text = raw_summary
            row.program_json = json.dumps(program)
        else:
            db.add(WorkoutProgram(user_id=user.id, raw_text=raw_summary, program_json=json.dumps(program)))
        await db.commit()

        from memory.attribute_store import sync_program_to_attributes
        await sync_program_to_attributes(db, user.id, program)

        return {"program": program}


@app.delete("/api/workout/{token}")
async def delete_workout_program(token: str):
    """Remove the user's workout program."""
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        from db.models import WorkoutProgram
        from sqlalchemy import select, delete as sql_delete
        from memory.attribute_store import clear_program_attributes
        await db.execute(sql_delete(WorkoutProgram).where(WorkoutProgram.user_id == user.id))
        await clear_program_attributes(db, user.id)
        await db.commit()
    return {"status": "ok"}


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

@app.get("/dashboard/{token}", response_class=HTMLResponse)
async def dashboard(token: str):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=401)
        name = user.name or ""

    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "Arnie_1026_Bot")
    # Brain tab feature flag — default OFF so production never paints the
    # half-built /brain/{token} iframe. Flip BRAIN_TAB_ENABLED=true in the
    # Render env (or any other deploy target) when the route + page are
    # ready to ship.
    _brain_enabled = os.getenv("BRAIN_TAB_ENABLED", "").lower() in ("true", "1", "yes", "on")
    return HTMLResponse(_dashboard_html(
        token, name=name, bot_username=bot_username, brain_enabled=_brain_enabled,
    ))


# ── Brain tab — env-gated. Same BRAIN_TAB_ENABLED flag that hides the UI
#    chrome in the dashboard also gates the routes themselves. When the env
#    var is unset (the default in prod), both routes return 404 so direct
#    URL access to the half-built page is impossible even with a valid
#    token. Flip BRAIN_TAB_ENABLED=true on Render to expose everything.

def _brain_routes_enabled() -> bool:
    return os.getenv("BRAIN_TAB_ENABLED", "").lower() in ("true", "1", "yes", "on")


@app.get("/brain/{token}", response_class=HTMLResponse)
async def brain(token: str):
    """Arnie's Brain — live mindmap of learned facts. Renders the React page;
    data is fetched client-side from /api/profile/{token} (same endpoint the
    Profile tab uses). Embedded as an iframe in panel-brain on the dashboard."""
    if not _brain_routes_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=401)
    return HTMLResponse(_brain_html(token))


class _BrainInsightRequest(BaseModel):
    """Payload from the Brain page when a lobe panel opens."""
    lobe_id: str
    lobe_name: Optional[str] = None     # human-readable, falls back to id
    lobe_short: Optional[str] = None    # uppercase short, e.g. "NUTRITION"
    nodes: list[dict]                   # [{label, value or chips, state}, ...]


@app.post("/api/brain/insights/{token}")
async def brain_insight(token: str, payload: _BrainInsightRequest):
    """Generate a personalized 2–4 sentence coaching paragraph for the
    given lobe, in Arnie's voice, referencing the user's actual parameter
    values. Falls through with {ok: false} on any LLM failure so the
    frontend can drop back to its static `coaching:` string. Caches by
    lobe signature so re-opening the same lobe is instant."""
    if not _brain_routes_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

    result = await generate_lobe_insight(
        user_id=user.id,
        lobe_id=payload.lobe_id,
        lobe_name=payload.lobe_name or payload.lobe_id.title(),
        lobe_short=payload.lobe_short or payload.lobe_id.upper(),
        nodes=payload.nodes or [],
    )
    if not result:
        return JSONResponse({"ok": False}, status_code=200)
    return {"ok": True, **result}


# ── Apple Health webhook ────────────────────────────────────────────────────────

class AppleWorkout(BaseModel):
    """One Apple Watch workout record from the iOS Shortcut."""
    name: Optional[str] = None           # e.g. "Running", "Cycling", user-visible label
    workout_type: Optional[str] = None   # raw HKWorkoutActivityType name if name not set
    duration_minutes: Optional[float] = None
    active_calories: Optional[float] = None
    distance_km: Optional[float] = None
    start_time: Optional[str] = None     # ISO datetime — used as display metadata


class AppleHealthPayload(BaseModel):
    date: Optional[str] = None
    steps: Optional[int] = None
    active_calories: Optional[float] = None
    resting_calories: Optional[float] = None
    sleep_hours: Optional[float] = None       # already in hours (advanced users)
    sleep_seconds: Optional[float] = None     # raw iOS value — auto-converted to sleep_hours
    sleep_deep_hours: Optional[float] = None
    sleep_rem_hours: Optional[float] = None
    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hrv: Optional[float] = None
    stand_hours: Optional[int] = None
    exercise_minutes: Optional[int] = None
    workouts: Optional[list[AppleWorkout]] = None  # Apple Watch workout records
    @staticmethod
    def _numeric_parts(value) -> list[float]:
        """
        iOS Shortcuts sometimes serializes Health Samples as newline-separated
        text, e.g. "2376\n0". Treat blank strings as missing and parse the
        numeric pieces so the webhook stays forgiving.
        """
        if value is None or value == "":
            return []
        if isinstance(value, (int, float)):
            return [float(value)]
        if isinstance(value, list):
            parts: list[float] = []
            for item in value:
                parts.extend(AppleHealthPayload._numeric_parts(item))
            return parts
        if isinstance(value, str):
            raw_parts = value.replace(",", "").splitlines()
            parts = []
            for raw in raw_parts:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    parts.append(float(raw))
                except ValueError:
                    continue
            return parts
        return []

    @field_validator("steps", "stand_hours", "exercise_minutes", mode="before")
    @classmethod
    def _coerce_int_field(cls, value):
        parts = cls._numeric_parts(value)
        if not parts:
            return None
        return int(round(sum(parts)))

    @field_validator(
        "active_calories",
        "resting_calories",
        "sleep_hours",
        "sleep_seconds",
        "sleep_deep_hours",
        "sleep_rem_hours",
        mode="before",
    )
    @classmethod
    def _coerce_summed_float_field(cls, value):
        parts = cls._numeric_parts(value)
        if not parts:
            return None
        return float(sum(parts))

    @field_validator("resting_hr", "avg_hr", "hrv", mode="before")
    @classmethod
    def _coerce_single_float_field(cls, value):
        parts = cls._numeric_parts(value)
        if not parts:
            return None
        non_zero = [p for p in parts if p != 0]
        return float(non_zero[0] if non_zero else parts[0])

async def _process_apple_workouts(db, user_id: int, snap_date, workouts: list) -> None:
    """
    Replace this day's Apple-Health-sourced exercise entries with the incoming batch.
    Uses replace-on-sync: stale entries for the day are deleted first, then the fresh
    set is inserted. This means a re-sync never double-counts workouts.
    """
    from db.queries import get_or_create_log_for_date, recompute_log_totals
    from db.models import ExerciseEntry
    from sqlalchemy import delete as sql_delete

    log = await get_or_create_log_for_date(db, user_id, snap_date)

    # Delete existing apple_health exercise entries for this day only
    await db.execute(
        sql_delete(ExerciseEntry).where(
            ExerciseEntry.daily_log_id == log.id,
            ExerciseEntry.source_type == "apple_health",
        )
    )
    await db.flush()

    for w in workouts:
        d = w.model_dump(exclude_none=True) if hasattr(w, "model_dump") else dict(w)
        name = d.get("name") or d.get("workout_type") or "Workout"
        entry = ExerciseEntry(
            daily_log_id=log.id,
            exercise_name=name,
            duration_minutes=d.get("duration_minutes"),
            calories_burned_estimate=d.get("active_calories"),
            # cardio_type set so recompute_log_totals marks cardio_completed=True
            cardio_type="apple_health",
            source_type="apple_health",
            notes=d.get("start_time") or "",
        )
        db.add(entry)

    await db.flush()
    await recompute_log_totals(db, log.id)
    await db.commit()


async def _notify_apple_health_connected(telegram_id: str, snap_date, data: dict) -> None:
    """
    Send a one-time "Apple Health connected!" message when the first sync arrives.
    Only fires for Telegram users (skips im: identities).
    """
    if str(telegram_id).startswith("im:"):
        return
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not tg_token:
        return

    parts = ["✅ <b>Apple Health connected!</b>", ""]
    bullets = []
    if data.get("steps"):
        bullets.append(f"Steps: {int(data['steps']):,}")
    if data.get("active_calories"):
        bullets.append(f"Active cals: {int(data['active_calories'])}")
    if data.get("resting_hr"):
        bullets.append(f"Resting HR: {int(data['resting_hr'])}bpm")
    if data.get("hrv"):
        bullets.append(f"HRV: {int(data['hrv'])}ms")
    if data.get("sleep_hours"):
        bullets.append(f"Sleep: {data['sleep_hours']:.1f}h")
    if bullets:
        parts.append("First sync received — " + " · ".join(bullets))
    else:
        parts.append("Your first sync arrived.")
    parts += ["", "Steps, activity, and sleep will update automatically each morning. 🌅"]

    try:
        from telegram import Bot
        bot = Bot(token=tg_token)
        await bot.send_message(
            chat_id=int(telegram_id),
            text="\n".join(parts),
            parse_mode="HTML",
        )
        await bot.close()
    except Exception as e:
        logger.warning(f"Apple Health connected notify failed for {telegram_id}: {e}")


async def _process_apple_health(payload: "AppleHealthPayload", token: str) -> dict:
    """
    Shared handler for both GET and POST Apple Health endpoints.
    Upserts the health snapshot, processes workouts, and fires the one-time
    "connected" Telegram notification on first sync.
    """
    import asyncio as _asyncio
    _notify_tg_id: Optional[str] = None
    _notify_data: Optional[dict] = None

    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        from datetime import date as _date
        snap_date = _date.today()
        if payload.date:
            try:
                snap_date = _date.fromisoformat(payload.date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Use YYYY-MM-DD")

        # Snapshot fields only — exclude date, workouts, and sleep_seconds (handled below)
        data = payload.model_dump(
            exclude={"date", "workouts", "sleep_seconds"}, exclude_none=True
        )
        # Auto-convert sleep_seconds → sleep_hours so users never have to divide by 3600
        if payload.sleep_seconds is not None and payload.sleep_hours is None:
            data["sleep_hours"] = round(payload.sleep_seconds / 3600, 2)
        data.setdefault("source", "apple_health")
        await upsert_health_snapshot(db, user.id, snap_date, **data)

        if payload.workouts:
            await _process_apple_workouts(db, user.id, snap_date, payload.workouts)

        # First-sync detection — fire a Telegram notification exactly once
        is_first = "apple_health_connected" not in (user.nudges_sent or "").split(",")
        if is_first:
            marks = set(s for s in (user.nudges_sent or "").split(",") if s)
            marks.add("apple_health_connected")
            user.nudges_sent = ",".join(sorted(marks))
            await db.commit()
            _notify_tg_id = user.telegram_id
            _notify_data = dict(data)

    if _notify_tg_id:
        _asyncio.create_task(
            _notify_apple_health_connected(_notify_tg_id, snap_date, _notify_data)
        )

    return {"status": "ok", "date": str(snap_date)}


@app.post("/health/apple")
async def receive_apple_health(payload: AppleHealthPayload, token: str = Query(...)):
    """POST endpoint — accepts a JSON body (advanced / original format)."""
    return await _process_apple_health(payload, token)


@app.get("/health/apple")
async def receive_apple_health_get(
    token: str = Query(...),
    date: Optional[str] = Query(None),
    steps: Optional[str] = Query(None),
    active_calories: Optional[str] = Query(None),
    resting_calories: Optional[str] = Query(None),
    sleep_seconds: Optional[str] = Query(None),
    sleep_hours: Optional[str] = Query(None),
    exercise_minutes: Optional[str] = Query(None),
):
    """
    GET endpoint — simpler for iOS Shortcuts users.
    No JSON body or Dictionary action needed; all values are URL query params.
    Example:
      GET /health/apple?token=X&steps=9000&active_calories=400&sleep_seconds=27000

    Accepts params as strings so we can return a helpful error when a Shortcut
    sends the variable *name* as text (e.g. &steps=steps) instead of the value.
    """
    # ── Detect the common setup mistake ───────────────────────────────────────
    # If Shortcuts variables weren't inserted properly, iOS sends the literal
    # variable name as the value (e.g. &steps=steps, &active_calories=cals).
    _PLACEHOLDER_NAMES = {
        "steps", "cals", "active_calories", "calories",
        "rest", "resting_calories", "resting",
        "sleep", "sleep_seconds", "sleep_hours",
        "exercise", "exercise_minutes",
    }
    _raw = {
        "steps": steps,
        "active_calories": active_calories,
        "resting_calories": resting_calories,
        "sleep_seconds": sleep_seconds,
    }
    bad = [k for k, v in _raw.items() if v is not None and v.lower() in _PLACEHOLDER_NAMES]
    if bad:
        from fastapi.responses import JSONResponse as _JSONResponse
        return _JSONResponse(
            status_code=422,
            content={
                "error": "shortcut_setup_incomplete",
                "message": (
                    "Your Shortcut sent the variable name as text instead of the actual value. "
                    f"Problem parameters: {', '.join(bad)}. "
                    "In the Shortcuts URL action, after typing &steps= (etc.) you must tap "
                    "the {x} icon above the keyboard and SELECT the variable — do not type "
                    "the name manually. Open your setup guide and re-read Step 3."
                ),
                "affected_params": bad,
            },
        )

    # ── Parse strings to numeric types ────────────────────────────────────────
    def _int(v: Optional[str]) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None

    def _float(v: Optional[str]) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    payload = AppleHealthPayload(
        date=date,
        steps=_int(steps),
        active_calories=_float(active_calories),
        resting_calories=_float(resting_calories),
        sleep_seconds=_float(sleep_seconds),
        sleep_hours=_float(sleep_hours),
        exercise_minutes=_int(exercise_minutes),
    )
    return await _process_apple_health(payload, token)


# ── Apple Health status check (polled by the guide page) ──────────────────────

@app.get("/health/apple/status")
async def apple_health_status(token: str = Query(...)):
    """
    Return connection state for the Apple Health guide page.
    Called by the guide's JavaScript to show a live "connected" indicator.
    """
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        snaps = await get_recent_health_snapshots(db, user.id, days=7)
        ah_snaps = [s for s in snaps if s.source == "apple_health"]
        if not ah_snaps:
            return {"connected": False, "last_sync": None}
        latest = ah_snaps[0]
        return {
            "connected": True,
            "last_sync": str(latest.date),
            "steps": latest.steps,
            "active_calories": latest.active_calories,
            "resting_hr": round(latest.resting_hr) if latest.resting_hr else None,
            "hrv": round(latest.hrv) if latest.hrv else None,
            "sleep_hours": latest.sleep_hours,
        }


# ── Apple Health setup guide ───────────────────────────────────────────────────

@app.get("/health/apple/guide", response_class=HTMLResponse)
async def apple_health_guide(token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=401)

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    endpoint = f"{base_url}/health/apple?token={token}"
    status_url = f"{base_url}/health/apple/status?token={token}"
    shortcut_url = f"{base_url}/health/apple/shortcut?token={token}"
    return HTMLResponse(_apple_guide_html(endpoint, status_url, shortcut_url))


# ── Personalized .shortcut file download ───────────────────────────────────────

@app.get("/health/apple/shortcut/test-health-actions")
async def test_health_actions_shortcut(token: str = Query(...)):
    """
    Diagnostic: serves the Apple-Gallery-approved 'Energy Balance' shortcut
    which uses the same is.workflow.actions.filter.health.quantity action.
    If this ALSO shows Unknown Action on device, the identifier is wrong for
    that iOS version. If it works, the issue is in the Arnie plist.
    """
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return JSONResponse({"error": "Invalid or expired token."}, status_code=401)

    # Re-fetch fresh signed copy from iCloud (URL expires, so fetch each time)
    import httpx
    from fastapi.responses import Response as _Response
    try:
        meta = (await httpx.AsyncClient().get(
            "https://www.icloud.com/shortcuts/api/records/cc22c46649d3428bbf181f1ea7f623b4",
            timeout=10,
        )).json()
        dl_url = meta["fields"]["signedShortcut"]["value"]["downloadURL"]
        data = (await httpx.AsyncClient().get(dl_url, timeout=15)).content
    except Exception as exc:
        return JSONResponse({"error": f"Could not fetch test shortcut: {exc}"}, status_code=502)

    return _Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="HealthTest.shortcut"',
                 "Cache-Control": "no-store"},
    )


@app.get("/health/apple/shortcut")
async def download_apple_shortcut(token: str = Query(...)):
    """
    Serve the signed Arnie Health .shortcut file.
    The file is a pre-signed template — users paste their personal sync URL
    (shown with a Copy button on the guide page) when iOS prompts them on import.
    Token is validated so the endpoint isn't publicly crawlable, but the same
    signed binary is served to every valid user.
    """
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return JSONResponse({"error": "Invalid or expired token."}, status_code=401)

    from fastapi.responses import Response as _Response

    signed_path = os.path.join(
        os.path.dirname(__file__), "..", "wearables", "arnie_health.shortcut"
    )
    try:
        with open(signed_path, "rb") as fh:
            shortcut_bytes = fh.read()
    except FileNotFoundError:
        return JSONResponse(
            {"error": "Shortcut file not found on server. Contact support."},
            status_code=500,
        )

    return _Response(
        content=shortcut_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="Arnie Health.shortcut"',
            "Cache-Control": "no-store",
        },
    )


