"""
Arnie — entry point.
Production (Render web service): Telegram webhooks + FastAPI on $PORT
Local dev: polling + FastAPI on port 10000

Webhooks eliminate the polling-conflict error when multiple instances
or deploys overlap. Telegram pushes updates to our HTTPS endpoint.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


async def run():
    import uvicorn
    from api.app import app as fastapi_app
    from bot.telegram_handler import build_app

    port = int(os.getenv("PORT", 10000))
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    use_webhook = bool(base_url)

    ptb_app = build_app()

    # Share ptb_app with FastAPI so the webhook endpoint can process updates
    fastapi_app.state.ptb_app = ptb_app

    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    async with ptb_app:
        # async with calls initialize() → triggers _post_init (init_db, scheduler, set_my_commands)
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


if __name__ == "__main__":
    asyncio.run(run())
