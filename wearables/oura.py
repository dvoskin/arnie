"""
Oura Ring provider — stub.

Metrics available from Oura API v2:
    readiness_score, sleep_score, activity_score,
    hrv (rmssd), resting_heart_rate, body_temperature_deviation,
    respiratory_average, sleep_efficiency, sleep_latency,
    rem_sleep_duration, deep_sleep_duration, light_sleep_duration,
    total_sleep_duration, steps, active_calories, met_minutes,
    spo2_percentage (Oura Gen 3+)

Webhook events: daily_readiness, daily_sleep, daily_activity, daily_spo2

To activate:
    1. Register app at https://cloud.ouraring.com/oauth/applications
    2. Add OURA_CLIENT_ID + OURA_CLIENT_SECRET to Render env vars
    3. Implement sync() and handle_webhook() below
    4. Add POST /wearables/oura endpoint in api/app.py
    5. Update PROVIDERS in wearables/__init__.py
"""

import logging
from typing import Any

from wearables.base import WearableProvider

logger = logging.getLogger(__name__)

ENABLED = False  # Set to True when implementing


class OuraProvider(WearableProvider):
    name = "Oura"
    device_type = "oura"

    def is_connected(self, user) -> bool:
        # Check WearableDevice table for connected Oura device
        return False

    async def sync(self, db, user, days: int = 7) -> int:
        """TODO: implement Oura API sync."""
        raise NotImplementedError("Oura sync not yet implemented")

    async def handle_webhook(self, db, user, payload: dict[str, Any]) -> bool:
        """TODO: implement Oura webhook processing."""
        raise NotImplementedError("Oura webhook not yet implemented")
