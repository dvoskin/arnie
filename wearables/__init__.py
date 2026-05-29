"""
Wearables integration layer.

Supports multiple simultaneous wearable providers per user.
Each provider implements the WearableProvider base class.

Connected providers:
    whoop        — Whoop 4.0 / Whoop 5 (OAuth2, webhook-ready)
    apple_health — Apple Health via iOS Shortcut webhook

Stubbed (structure in place, webhook endpoints ready to wire):
    oura         — Oura Ring 3/4
    garmin       — Garmin Connect
    fitbit       — Fitbit / Google Health

Adding a new provider:
    1. Create wearables/your_provider.py extending WearableProvider
    2. Register in PROVIDERS dict below
    3. Add webhook endpoint in api/app.py → POST /wearables/your_provider
"""

from wearables.base import WearableProvider
from wearables.sync_manager import SyncManager

PROVIDERS: dict[str, type] = {}

try:
    from wearables.whoop import WhoopProvider
    PROVIDERS["whoop"] = WhoopProvider
except ImportError:
    pass

try:
    from wearables.apple_health import AppleHealthProvider
    PROVIDERS["apple_health"] = AppleHealthProvider
except ImportError:
    pass

__all__ = ["WearableProvider", "SyncManager", "PROVIDERS"]
