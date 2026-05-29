"""
WearableProvider — abstract base class for all wearable integrations.

Every provider must implement:
    sync(db, user, days)       — fetch recent data, upsert into DB
    handle_webhook(db, payload) — process real-time webhook event

Optionally override:
    refresh_tokens(db, user)   — refresh OAuth tokens if expiring
    get_auth_url(user)         — OAuth2 authorization URL
    exchange_code(code, ...)   — exchange auth code for tokens
"""

from abc import ABC, abstractmethod
from typing import Any

import logging

logger = logging.getLogger(__name__)


class WearableProvider(ABC):
    """Base class for all wearable integrations."""

    #: Human-readable name shown in UI / logs
    name: str = "unknown"

    #: Identifier matching WearableDevice.device_type
    device_type: str = "unknown"

    @abstractmethod
    async def sync(self, db, user, days: int = 7) -> int:
        """
        Fetch data from the provider API and upsert into the DB.
        Returns number of days successfully synced.
        Writes to both HealthSnapshot (daily summary) and WearableMetric (time-series).
        """
        ...

    async def handle_webhook(self, db, user, payload: dict[str, Any]) -> bool:
        """
        Process a real-time webhook event from the provider.
        Returns True if the event was handled, False if ignored.
        Default implementation triggers a fresh sync.
        """
        logger.info(f"{self.name} webhook received for user {user.id} — triggering sync")
        try:
            synced = await self.sync(db, user, days=1)
            return synced > 0
        except Exception as e:
            logger.error(f"{self.name} webhook sync failed for user {user.id}: {e}")
            return False

    async def refresh_tokens_if_needed(self, db, user) -> bool:
        """
        Refresh OAuth tokens if they're expiring within 5 minutes.
        Override in providers that use OAuth.
        Returns True if tokens are valid (refreshed or not needed).
        """
        return True

    def is_connected(self, user) -> bool:
        """
        Check if this provider is connected for the given user.
        Override for providers using the new WearableDevice table.
        Default: check legacy user fields.
        """
        return False

    async def upsert_metrics(self, db, user_id: int, device_type: str,
                              metrics: list[dict]) -> None:
        """
        Bulk upsert time-series metrics into WearableMetric table.
        metrics: list of {metric_type, value, unit, recorded_at}
        """
        from db.models import WearableMetric
        from datetime import datetime, timezone

        for m in metrics:
            metric = WearableMetric(
                user_id=user_id,
                device_type=device_type,
                metric_type=m["metric_type"],
                value=m["value"],
                unit=m.get("unit", ""),
                recorded_at=m.get("recorded_at", datetime.now(timezone.utc)),
            )
            db.add(metric)

        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to upsert wearable metrics: {e}")
