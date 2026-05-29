"""
Fitbit / Google Health provider — stub.

Metrics available via Fitbit Web API:
    activity_score, sleep_score, hrv_daily_rmssd,
    spo2, skin_temperature, resting_heart_rate,
    steps, floors, calories, active_zone_minutes,
    sleep_stages, sleep_efficiency, breathing_rate

Webhook events (Fitbit Subscriptions API):
    activities, body, foods, sleep, userRevokedAccess

To activate:
    1. Register app at https://dev.fitbit.com/apps/new
    2. Add FITBIT_CLIENT_ID + FITBIT_CLIENT_SECRET to Render env vars
    3. Implement sync() and handle_webhook() below
    4. Add POST /wearables/fitbit endpoint in api/app.py
"""

import logging
from typing import Any

from wearables.base import WearableProvider

logger = logging.getLogger(__name__)

ENABLED = False  # Set to True when implementing


class FitbitProvider(WearableProvider):
    name = "Fitbit"
    device_type = "fitbit"

    def is_connected(self, user) -> bool:
        return False

    async def sync(self, db, user, days: int = 7) -> int:
        raise NotImplementedError("Fitbit sync not yet implemented")

    async def handle_webhook(self, db, user, payload: dict[str, Any]) -> bool:
        raise NotImplementedError("Fitbit webhook not yet implemented")
