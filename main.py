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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


async def run():
    import uvicorn
    from api.app import app as fastapi_app
    from bot.telegram_handler import build_app, _post_init, _post_shutdown

    port = int(os.getenv("PORT", 10000))
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    use_webhook = bool(base_url)

    ptb_app = build_app()
    fastapi_app.state.ptb_app = ptb_app

    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

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
            await ptb_app.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
            logger.info(f"Webhook mode: {webhook_url}")
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
