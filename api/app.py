"""
FastAPI app — runs alongside the Telegram bot in the same process.
Exposes:
  GET  /health                  — health check
  GET  /dashboard/{token}       — read-only user dashboard (HTML)
  GET  /api/stats/{token}       — dashboard data (JSON)
  POST /health/apple?token=...  — Apple Health inbound webhook
"""
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
from core.urls import dashboard_url
from pydantic import BaseModel

from db.database import AsyncSessionLocal
from db.queries import (
    get_user_by_webhook_token, upsert_health_snapshot,
    get_today_log, get_log_by_date, get_recent_logs, get_recent_weights,
    get_recent_health_snapshots,
    update_food_entry, delete_food_entry,
    update_exercise_entry, delete_exercise_entry,
    add_food_entry, add_exercise_entry,
    get_or_create_today_log, get_or_create_log_for_date,
    _user_today,
    set_subscription_active, set_subscription_cancelled,
)
from api.usda import search_food as _usda_search

logger = logging.getLogger(__name__)

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
    ],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


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
            existing_user = await get_user_by_webhook_token(db, state)
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
        user = await get_user_by_webhook_token(db, state)
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
    """Receive updates from Telegram (production webhook mode)."""
    if token != os.getenv("TELEGRAM_BOT_TOKEN", ""):
        raise HTTPException(status_code=403, detail="Forbidden")

    ptb_app = getattr(request.app.state, "ptb_app", None)
    if ptb_app is None:
        raise HTTPException(status_code=503, detail="Bot not ready")

    from telegram import Update
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
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


# ── Stats API ──────────────────────────────────────────────────────────────────

@app.get("/api/insights/{token}")
async def get_insights_endpoint(token: str, force: bool = False, date: str = None):
    """Return 3-5 AI-generated coaching insights for the given date (defaults to today)."""
    from api.insights import get_insights
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

    weight_data = [
        {"date": w.timestamp.strftime("%Y-%m-%d"),
         "kg": round(w.weight_kg, 1),
         "lbs": round(w.weight_kg * 2.20462, 1)}
        for w in sorted(weights, key=lambda w: w.timestamp)
    ]

    def _log_to_day(log):
        if not log:
            return None
        return {
            "date": str(log.date),
            "status": log.status,
            "calories": round(log.total_calories or 0),
            "protein": round(log.total_protein or 0),
            "carbs": round(log.total_carbs or 0),
            "fats": round(log.total_fats or 0),
            "water_ml": round(log.total_water_ml or 0),
            "workout_completed": log.workout_completed,
            "cardio_completed": log.cardio_completed,
            "food_entries": [
                {"id": e.id, "name": e.parsed_food_name or "?",
                 "quantity": e.quantity or "",
                 "calories": round(e.calories or 0), "protein": round(e.protein or 0),
                 "carbs": round(e.carbs or 0), "fats": round(e.fats or 0),
                 "estimated": bool(e.estimated_flag)}
                for e in (log.food_entries or [])
            ],
            "exercise_entries": [
                {"id": e.id, "name": e.exercise_name or "?",
                 "sets": e.sets, "reps": e.reps,
                 "weight": round(e.weight * 2.20462, 1) if e.weight else None,
                 "duration_minutes": e.duration_minutes,
                 "is_cardio": bool(e.cardio_type),
                 "cardio_type": e.cardio_type}
                for e in (log.exercise_entries or [])
            ],
        }

    hist_data = [
        {"date": str(log.date),
         "calories": round(log.total_calories or 0),
         "protein": round(log.total_protein or 0),
         "carbs": round(log.total_carbs or 0),
         "fats": round(log.total_fats or 0),
         "workout": log.workout_completed,
         "status": log.status}
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
         "whoop_workouts": getattr(s, "whoop_workouts", None)}
        for s in health_snaps
    ]

    available_dates = sorted({d["date"] for d in hist_data})
    analytics = _compute_analytics(user, prefs, weight_data)

    def _ht():
        if not user.height_cm:
            return ""
        total_in = user.height_cm / 2.54
        return f"{int(total_in // 12)}'{int(total_in % 12)}\""

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
        "dietary_preferences": user.dietary_preferences,
        "injuries": user.injuries,
        "timezone": user.timezone,
        "coaching_style": prefs.coaching_style if prefs else None,
        "calorie_target": prefs.calorie_target if prefs else None,
        "protein_target": prefs.protein_target if prefs else None,
        "whoop_connected": _whoop_connected,
        "apple_health_connected": any(s.source == "apple_health" for s in health_snaps),
        "analytics": analytics,
    }

    return {
        "profile": profile,
        "targets": {
            "calories": prefs.calorie_target if prefs else None,
            "protein": prefs.protein_target if prefs else None,
        },
        "day": _log_to_day(day_log),
        "history": hist_data,
        "weights": weight_data,
        "health": health_data,
        "available_dates": available_dates,
        "viewing_date": str(target_date or _user_today(user.timezone or "UTC")),
        # keep legacy 'today' + 'user' keys so existing insights endpoint works unchanged
        "today": _log_to_day(day_log),
        "user": {"name": user.name or "User", "goal": user.primary_goal or "—",
                 "current_weight_lbs": profile["current_weight_lbs"],
                 "goal_weight_lbs": profile["goal_weight_lbs"]},
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
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        changes = patch.model_dump(exclude_none=True)
        # Map external "food_name" → internal column "parsed_food_name"
        if "food_name" in changes:
            changes["parsed_food_name"] = changes.pop("food_name")
        entry = await update_food_entry(db, entry_id, user.id, **changes)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok", "id": entry_id}


@app.delete("/api/food/{entry_id}")
async def api_delete_food(entry_id: int, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        ok = await delete_food_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok"}


@app.patch("/api/exercise/{entry_id}")
async def api_edit_exercise(entry_id: int, patch: ExercisePatch, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        changes = patch.model_dump(exclude_none=True)
        # Dashboard sends weight in lbs; DB stores kg
        if "weight" in changes:
            changes["weight"] = changes["weight"] * 0.453592
        entry = await update_exercise_entry(db, entry_id, user.id, **changes)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "ok", "id": entry_id}


@app.delete("/api/exercise/{entry_id}")
async def api_delete_exercise(entry_id: int, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        ok = await delete_exercise_entry(db, entry_id, user.id)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
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
        _int_fields = {"age"}
        _weight_fields = {
            "current_weight_lbs": "current_weight_kg",
            "goal_weight_lbs":    "goal_weight_kg",
        }
        _pref_str = {"coaching_style"}
        _pref_int = {"calorie_target", "protein_target"}

        try:
            if field in _str_fields:
                setattr(user, field, str(raw).strip() if raw else None)
            elif field in _int_fields:
                setattr(user, field, int(raw) if raw else None)
            elif field in _weight_fields:
                db_col = _weight_fields[field]
                setattr(user, db_col, float(raw) * 0.453592 if raw else None)
            elif field in _pref_str and user.preferences:
                setattr(user.preferences, field, str(raw).strip() if raw else None)
            elif field in _pref_int and user.preferences:
                setattr(user.preferences, field, int(raw) if raw else None)
            else:
                raise HTTPException(status_code=400, detail=f"Unknown field: {field}")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid value for {field}")

        await db.commit()
    return {"status": "ok", "field": field}


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
                    "status": lg.status,
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


# ── Admin dashboard ───────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(token: str = Query(...)):
    _require_admin(token)

    from sqlalchemy import select, func as sqlfunc
    from sqlalchemy.orm import selectinload
    from db.models import User, DailyLog, ConversationLog, Feedback

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

        rows = []
        for u in users:
            # Today's log
            log_result = await db.execute(
                select(DailyLog).where(DailyLog.user_id == u.id, DailyLog.date == today)
            )
            today_log = log_result.scalar_one_or_none()

            # Last message timestamp + snippet
            conv_result = await db.execute(
                select(ConversationLog)
                .where(ConversationLog.user_id == u.id)
                .order_by(ConversationLog.timestamp.desc())
                .limit(1)
            )
            last_conv = conv_result.scalar_one_or_none()

            # Total message count
            count_result = await db.execute(
                select(sqlfunc.count()).where(ConversationLog.user_id == u.id)
            )
            msg_count = count_result.scalar() or 0

            rows.append({
                "user": u,
                "today_log": today_log,
                "last_conv": last_conv,
                "msg_count": msg_count,
                "dash_url": dashboard_url(u.webhook_token) if u.webhook_token else None,
            })

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

    def _esc(s):
        return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _cal_bar(log, target):
        if not log or not target:
            return "—"
        pct = min(100, int((log.total_calories or 0) / target * 100))
        color = "#2ecc71" if 85 <= pct <= 110 else "#e74c3c" if pct > 115 else "#f39c12"
        return (f'<div style="display:flex;align-items:center;gap:6px">'
                f'<div style="width:60px;height:6px;background:#333;border-radius:3px">'
                f'<div style="width:{pct}%;height:100%;background:{color};border-radius:3px"></div></div>'
                f'<span style="font-size:11px">{int(log.total_calories or 0)}/{target}</span></div>')

    tbody = ""
    for r in rows:
        u = r["user"]
        p = u.preferences
        log = r["today_log"]
        last = r["last_conv"]
        dash = r["dash_url"]

        last_msg_time = _ago(last.timestamp) if last else "—"
        last_msg_snippet = (_esc(last.raw_message or "")[:50] + "…") if last and last.raw_message and len(last.raw_message) > 50 else _esc(last.raw_message if last else "")
        today_calories = _cal_bar(log, p.calorie_target if p else None)
        today_protein = f'{int(log.total_protein or 0)}g / {p.protein_target or "?"}g' if log else "—"
        workout_dot = '<span style="color:#2ecc71">✓</span>' if (log and log.workout_completed) else '<span style="color:#555">✗</span>'
        onboard = '<span style="color:#2ecc71">✓</span>' if u.onboarding_completed else '<span style="color:#e74c3c">pending</span>'
        dash_link = f'<a href="{dash}" target="_blank" style="color:#3498db;text-decoration:none">↗ dash</a>' if dash else "—"
        whoop = '<span style="color:#2ecc71">●</span>' if (u.whoop_access_token or u.whoop_refresh_token) else '<span style="color:#555">○</span>'
        created = u.created_at.strftime("%b %d") if u.created_at else "—"

        convo_link = f'<a href="/admin/user/{u.id}?token={token}" style="color:#f39c12">💬 convo</a>'
        tbody += f"""<tr>
          <td><b>{_esc(u.name or "?")}</b><br><span style="color:#888;font-size:10px">{_esc(u.telegram_id)}</span></td>
          <td>{onboard}</td>
          <td>{_goal_badge(u.primary_goal)}<br><span style="color:#888;font-size:10px">{u.training_experience or "?"}</span></td>
          <td style="font-size:11px">{today_calories}<br><span style="color:#aaa">{today_protein} P &nbsp;{workout_dot}</span></td>
          <td style="font-size:11px;max-width:180px;overflow:hidden">{last_msg_snippet}<br><span style="color:#888">{last_msg_time}</span></td>
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
</style>
</head>
<body>
<h1>⚡ Arnie Admin</h1>
<p class="sub">{len(rows)} users &nbsp;·&nbsp; {today} &nbsp;·&nbsp; <a href="/admin?token={token}">↻ refresh</a></p>

<div class="tabs">
  <div class="tab active" onclick="switchTab('users',this)">Users</div>
  <div class="tab" onclick="switchTab('feedback',this)">Feedback</div>
</div>

<div id="panel-users" class="panel active">
<table>
<thead><tr>
  <th>User</th><th>Onboard</th><th>Goal</th>
  <th>Today</th><th>Last message</th><th>Msgs</th>
  <th>Devices</th><th>Joined</th><th>Links</th>
</tr></thead>
<tbody>{tbody}</tbody>
</table>
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

    def _esc(s):
        return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _src_badge(src):
        colors = {"text": "#3498db", "voice": "#e67e22", "image": "#9b59b6", "photo": "#9b59b6"}
        c = colors.get(src or "text", "#555")
        return f'<span style="background:{c};color:#fff;padding:1px 6px;border-radius:8px;font-size:10px">{src or "text"}</span>'

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
            estimated=body.estimated,
        )
    return {"status": "ok", "id": entry.id}


class ExerciseLogBody(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[str] = None
    weight_lbs: Optional[float] = None
    duration_minutes: Optional[float] = None
    is_cardio: bool = False
    log_date: Optional[str] = None


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
            return {{"program": None, "reason": program.get("reason", "Not enough workout data in your conversation history yet.")}}

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

        return {{"program": program}}


@app.delete("/api/workout/{token}")
async def delete_workout_program(token: str):
    """Remove the user's workout program."""
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        from db.models import WorkoutProgram
        from sqlalchemy import select, delete as sql_delete
        await db.execute(sql_delete(WorkoutProgram).where(WorkoutProgram.user_id == user.id))
        await db.commit()
    return {{"status": "ok"}}


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

@app.get("/dashboard/{token}", response_class=HTMLResponse)
async def dashboard(token: str):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=401)
        name = user.name or ""

    return HTMLResponse(_dashboard_html(token, name=name))





# ── Apple Health webhook ────────────────────────────────────────────────────────

class AppleHealthPayload(BaseModel):
    date: Optional[str] = None
    steps: Optional[int] = None
    active_calories: Optional[float] = None
    resting_calories: Optional[float] = None
    sleep_hours: Optional[float] = None
    sleep_deep_hours: Optional[float] = None
    sleep_rem_hours: Optional[float] = None
    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hrv: Optional[float] = None
    stand_hours: Optional[int] = None
    exercise_minutes: Optional[int] = None


@app.post("/health/apple")
async def receive_apple_health(
    payload: AppleHealthPayload,
    token: str = Query(...),
):
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

        data = payload.model_dump(exclude={"date"}, exclude_none=True)
        data.setdefault("source", "apple_health")
        await upsert_health_snapshot(db, user.id, snap_date, **data)

    return {"status": "ok", "date": str(snap_date)}


# ── Apple Health setup guide ───────────────────────────────────────────────────

@app.get("/health/apple/guide", response_class=HTMLResponse)
async def apple_health_guide(token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_webhook_token(db, token)
        if not user:
            return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=401)

    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000").rstrip("/")
    endpoint = f"{base_url}/health/apple?token={token}"
    return HTMLResponse(_apple_guide_html(endpoint))


