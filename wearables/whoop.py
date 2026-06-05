"""
Whoop provider — wraps the existing api/whoop.py logic behind the WearableProvider interface.

All Whoop-specific API calls stay in api/whoop.py.
This class is the integration adapter.
"""

import logging
from typing import Any

from wearables.base import WearableProvider

logger = logging.getLogger(__name__)


class WhoopProvider(WearableProvider):
    name = "Whoop"
    device_type = "whoop"

    def is_connected(self, user) -> bool:
        return bool(user.whoop_access_token and user.whoop_refresh_token)

    async def sync(self, db, user, days: int = 7) -> int:
        """Delegate to existing api/whoop.sync_user_whoop."""
        from api.whoop import sync_user_whoop
        try:
            return await sync_user_whoop(db, user, days=days)
        except Exception as e:
            logger.error(f"Whoop sync failed for user {user.id}: {e}")
            return 0

    async def handle_webhook(self, db, user, payload: dict[str, Any]) -> bool:
        """
        Handle real-time Whoop webhook events.
        Whoop sends events for: workout.updated, recovery.updated, sleep.updated, cycle.updated
        """
        event_type = payload.get("type", "")
        logger.info(f"Whoop webhook: {event_type} for user {user.id}")

        # Trigger a 1-day sync on any Whoop event to get fresh data
        synced = await self.sync(db, user, days=1)
        return synced > 0

    async def refresh_tokens_if_needed(self, db, user) -> bool:
        """Refresh Whoop OAuth tokens if expiring soon.

        Delegates to api/whoop._ensure_fresh_token, which checks expiry
        (35-min buffer), refreshes via the refresh token, and persists the
        new tokens. Returns True if a usable access token is available.
        """
        from api.whoop import _ensure_fresh_token
        return bool(await _ensure_fresh_token(db, user))
