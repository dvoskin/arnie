"""
Apple Health provider — wraps the existing Apple Health shortcut webhook logic.
Data arrives via POST /health/apple from the user's iOS Shortcut.
"""

import logging
from typing import Any

from wearables.base import WearableProvider

logger = logging.getLogger(__name__)


class AppleHealthProvider(WearableProvider):
    name = "Apple Health"
    device_type = "apple_health"

    def is_connected(self, user) -> bool:
        # Apple Health is "connected" if we have any health snapshots from it
        return True  # Determined at query time — no persistent token

    async def sync(self, db, user, days: int = 7) -> int:
        """
        Apple Health is push-only (shortcut sends data to us).
        Pull sync is not supported — return 0 to indicate no active pull.
        """
        return 0

    async def handle_webhook(self, db, user, payload: dict[str, Any]) -> bool:
        """
        Process incoming Apple Health data from the iOS Shortcut.
        The existing api/app.py POST /health/apple endpoint handles this.
        This method is here for architectural completeness.
        """
        logger.info(f"Apple Health data received for user {user.id}")
        return True
