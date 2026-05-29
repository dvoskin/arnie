"""
SyncManager — orchestrates wearable syncs across all connected providers.

Responsibilities:
    - Know which providers are connected for a user
    - Track data freshness and trigger re-syncs when stale
    - Route webhook events to the correct provider
    - Aggregate coaching signals from multiple devices
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# How stale data can be before we consider it "needs refresh"
STALE_THRESHOLD_HOURS = 6


class SyncManager:
    """Orchestrates multi-device wearable sync for a single user."""

    def __init__(self, user, db):
        self.user = user
        self.db = db

    def get_connected_providers(self) -> list:
        """Return list of active WearableProvider instances for this user."""
        from wearables import PROVIDERS

        connected = []
        for device_type, provider_class in PROVIDERS.items():
            provider = provider_class()
            if provider.is_connected(self.user):
                connected.append(provider)
        return connected

    async def sync_all(self, days: int = 7) -> dict[str, int]:
        """
        Sync all connected providers.
        Returns {device_type: days_synced}.
        """
        results = {}
        for provider in self.get_connected_providers():
            try:
                await provider.refresh_tokens_if_needed(self.db, self.user)
                n = await provider.sync(self.db, self.user, days=days)
                results[provider.device_type] = n
                logger.info(f"Synced {provider.name} for user {self.user.id}: {n} days")
            except Exception as e:
                logger.error(f"Sync failed for {provider.name}, user {self.user.id}: {e}")
                results[provider.device_type] = 0
        return results

    async def sync_provider(self, device_type: str, days: int = 1) -> int:
        """Sync a specific provider by device_type. Used after webhook events."""
        from wearables import PROVIDERS

        provider_class = PROVIDERS.get(device_type)
        if not provider_class:
            logger.warning(f"Unknown provider: {device_type}")
            return 0

        provider = provider_class()
        try:
            await provider.refresh_tokens_if_needed(self.db, self.user)
            return await provider.sync(self.db, self.user, days=days)
        except Exception as e:
            logger.error(f"Sync failed for {device_type}, user {self.user.id}: {e}")
            return 0

    def get_data_freshness(self, health_snapshots: list) -> str:
        """
        Determine how fresh the wearable data is.
        Returns: "live" | "today" | "yesterday" | "stale"
        """
        if not health_snapshots:
            return "stale"

        latest = health_snapshots[0]
        from datetime import date
        today = date.today()

        if latest.date == today:
            return "today"
        elif latest.date == today - timedelta(days=1):
            return "yesterday"
        else:
            return "stale"

    async def handle_webhook_event(self, device_type: str, payload: dict) -> bool:
        """Route a webhook event to the correct provider."""
        from wearables import PROVIDERS

        provider_class = PROVIDERS.get(device_type)
        if not provider_class:
            return False

        provider = provider_class()
        return await provider.handle_webhook(self.db, self.user, payload)
