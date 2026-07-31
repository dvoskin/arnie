"""
Arnie — entry point.
Production (Render web service): Telegram webhooks + FastAPI on $PORT
Local dev: polling + FastAPI on port 10000
"""
import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv(override=True)

# ── Error monitoring — Sentry (no-op if SENTRY_DSN not set) ──────────────────
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            traces_sample_rate=0.1,   # 10% of transactions traced
            profiles_sample_rate=0.1,
        )
    except ImportError:
        pass  # sentry-sdk not installed — silently skip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

# Say so, at boot, if a flag is set to something the code will ignore. On
# 2026-07-31 NUTRITION_RESOLVER_MODE was `true` — not a value the parser
# accepts — so production ran in shadow for six days while the repo recorded it
# as live for all users. Nothing failed; nothing logged. This is the line that
# would have said so, on the first deploy after the typo.
try:
    from core.config_guard import report as _report_config
    _report_config()
except Exception:            # never let a diagnostic stop the boot
    pass

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


async def run():
    import uvicorn
    from api.app import app as fastapi_app

    port = int(os.getenv("PORT", 10000))
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    use_webhook = bool(base_url)

    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    # API-only mode: when TELEGRAM_BOT_TOKEN is unset, skip the bot half entirely
    # and just serve the FastAPI app. This is the right shape for a staging /
    # preview environment that only exercises /api/v1/* (the iOS surface).
    # Endpoints in api/app.py that touch `app.state.ptb_app` will fail in this
    # mode, but iOS doesn't call any of them.
    if not TELEGRAM_TOKEN:
        from db.database import init_db
        await init_db()
        logger.info("API-only mode (TELEGRAM_BOT_TOKEN unset) — Telegram disabled")
        await server.serve()
        return

    # Bot + API mode (normal prod path).
    from bot.telegram_handler import build_app, _post_init, _post_shutdown
    ptb_app = build_app()
    fastapi_app.state.ptb_app = ptb_app

    # NOTE: `async with ptb_app` calls initialize() but does NOT call post_init.
    # post_init is only auto-invoked by run_polling() / run_webhook(). Since we
    # drive the lifecycle manually here, we must call _post_init ourselves —
    # otherwise init_db() never runs and the tables don't exist.
    await ptb_app.initialize()
    try:
        await _post_init(ptb_app)
        await ptb_app.start()

        if use_webhook:
            webhook_url = f"{base_url}/webhook/{TELEGRAM_TOKEN}"
            # When set, Telegram echoes this secret back in the
            # X-Telegram-Bot-Api-Secret-Token header on every call, so the
            # webhook can authenticate updates without relying only on the
            # in-URL token (which lands in access logs). The endpoint enforces
            # it when the same env var is present; leaving it unset preserves
            # the prior token-only behaviour.
            webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "") or None
            await ptb_app.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                secret_token=webhook_secret,
            )
            # Never log the full URL — it contains the bot token. Redact it.
            logger.info(
                "Webhook mode: %s/webhook/<bot-token-redacted>  secret_token=%s",
                base_url, "set" if webhook_secret else "unset",
            )
        else:
            await ptb_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Polling mode (local dev)")

        await server.serve()  # blocks until shutdown signal

        if use_webhook:
            await ptb_app.bot.delete_webhook()
        else:
            await ptb_app.updater.stop()

        await ptb_app.stop()
    finally:
        await _post_shutdown(ptb_app)
        await ptb_app.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
