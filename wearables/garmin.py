"""
Garmin Connect provider — stub.

Metrics available via Garmin Health API:
    body_battery, stress_score, training_load, training_status,
    vo2max_running, vo2max_cycling, hrv_weekly_average,
    sleep_score, sleep_stages, resting_heart_rate,
    steps, active_calories, intensity_minutes,
    respiration_rate, spo2, sweat_loss (Fenix/Forerunner)

Webhook events: DAILY_SUMMARY, SLEEP, ACTIVITIES, BODY_COMPOSITION

To activate:
    1. Apply for Garmin Health API access at https://developer.garmin.com/health-api/
    2. Add GARMIN_CLIENT_ID + GARMIN_CLIENT_SECRET to Render env vars
    3. Implement sync() and handle_webhook() below
    4. Add POST /wearables/garmin endpoint in api/app.py
"""

import logging
from typing import Any

from wearables.base import WearableProvider

logger = logging.getLogger(__name__)

ENABLED = False  # Set to True when implementing


class GarminProvider(WearableProvider):
    name = "Garmin"
    device_type = "garmin"

    def is_connected(self, user) -> bool:
        return False

    async def sync(self, db, user, days: int = 7) -> int:
        raise NotImplementedError("Garmin sync not yet implemented")

    async def handle_webhook(self, db, user, payload: dict[str, Any]) -> bool:
        raise NotImplementedError("Garmin webhook not yet implemented")
