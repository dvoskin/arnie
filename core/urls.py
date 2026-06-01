"""
Canonical URL builders.

Dashboard links live on their OWN base (DASHBOARD_BASE_URL) so the user-facing
dashboard can move to a branded domain (app.tryarnie.com) independently of the app's
service host. Webhooks and OAuth redirects must keep using RENDER_EXTERNAL_URL (the
URL registered with Telegram / Whoop / Apple Health / Stripe), so those are NOT routed
through here.

Resolution order for dashboard links:
  1. DASHBOARD_BASE_URL   — set this in prod once app.tryarnie.com is live + verified
  2. RENDER_EXTERNAL_URL  — current behavior (the app's own host); safe default
  3. http://localhost:10000 — local dev
This ordering means shipping the code is a no-op until DASHBOARD_BASE_URL is set, so
there's no window where links point at a domain that doesn't resolve yet.
"""
import os


def dashboard_base_url() -> str:
    return (
        os.getenv("DASHBOARD_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or "http://localhost:10000"
    ).rstrip("/")


def dashboard_url(token: str) -> str:
    return f"{dashboard_base_url()}/dashboard/{token}"
