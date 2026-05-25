"""
Arnie v0.1 — entry point.
"""
import logging
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
)

if __name__ == "__main__":
    from bot.telegram_handler import run_bot
    run_bot()
