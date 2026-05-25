"""
Arnie — entry point.
Runs the Telegram bot and FastAPI server concurrently in a single asyncio process.
Render (web service type) exposes $PORT; FastAPI binds to it.
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


async def run():
    import uvicorn
    from api.app import app as fastapi_app
    from bot.telegram_handler import build_app

    port = int(os.getenv("PORT", 10000))
    ptb_app = build_app()

    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    async with ptb_app:
        await ptb_app.start()
        await ptb_app.updater.start_polling(drop_pending_updates=True)
        logger.info(f"Arnie bot + dashboard running on port {port}")

        await server.serve()  # blocks until SIGINT/SIGTERM

        await ptb_app.updater.stop()
        await ptb_app.stop()


if __name__ == "__main__":
    asyncio.run(run())
