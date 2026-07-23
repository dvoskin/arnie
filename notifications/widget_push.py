"""
Widget-reload push — wake the iOS app to refresh its Home / Lock Screen widgets.

WidgetKit timelines are BUDGETED: a widget refreshes on its own schedule (iOS
allots a limited number of reloads per day), not the instant new data lands. That
is fine when the user logs IN the app — the app calls
`WidgetCenter.reloadAllTimelines()` itself right after the write. It is NOT fine
for a log made on another surface: a meal logged via Telegram, a weigh-in from the
web app. The iOS app never saw that turn, so its widget stays stale until the next
launch or the next scheduled reload.

This module closes that gap. After a cross-surface log write, fire a SILENT
`content-available` push to every one of the user's active devices; iOS wakes the
app in the background and it reloads its widget timelines against the lean
`/api/v1/widget` endpoint. No banner, no sound — the user just sees a fresh widget
the next time they glance at it.

Fan-out mirrors the proactive scheduler's `_send_ios`: per-token send, a
cross-environment retry (a token minted for the other APNs host still bounces
`BadDeviceToken` on the wrong one), and revoke-on-dead so the active set stays
clean. INERT when APNs isn't configured (the `is_configured()` gate) — a dev or
test deploy without credentials no-ops with a log line and never raises into the
caller.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Tag the iOS client can branch on in `didReceiveRemoteNotification` to know this
# silent push means "reload your widget timelines" (vs. any other data push).
_WIDGET_RELOAD_EXTRA = {"purpose": "widget-reload"}

# APNs failure signals that mean the token is permanently dead (app uninstalled /
# token rotated) — mirror the proactive scheduler's revoke conditions.
_DEAD_TOKEN_REASONS = ("BadDeviceToken", "Unregistered")
_DEAD_TOKEN_STATUSES = (400, 410)


def _is_dead_token(result: dict) -> bool:
    return (
        result.get("reason") in _DEAD_TOKEN_REASONS
        or result.get("status") in _DEAD_TOKEN_STATUSES
    )


async def notify_widget_reload(user_id: int) -> dict:
    """Fan a silent widget-reload push out to every active device for `user_id`.

    Opens its OWN DB session: this is called fire-and-forget, after the request /
    turn that triggered it may already have closed its session. Reads the active
    device tokens, sends a silent push to each (with a cross-environment retry),
    and revokes any token APNs reports dead so the next reload skips it.

    Best-effort and total: every per-token failure is swallowed + logged; the
    function returns a small summary dict (`{"ok", "sent", ...}`) that exists
    mainly for tests and log lines, not for callers to act on.
    """
    from notifications.apns_client import is_configured, send_background_push

    if not is_configured():
        logger.info("apns not configured — widget reload for user %s skipped", user_id)
        return {"ok": False, "error": "not_configured"}

    from db.database import AsyncSessionLocal
    from db.queries import active_device_tokens_for_user, revoke_device_token

    sent = 0
    async with AsyncSessionLocal() as db:
        tokens = await active_device_tokens_for_user(db, user_id)
        if not tokens:
            logger.info("no active APNs tokens for user %s — widget reload skipped", user_id)
            return {"ok": True, "sent": 0, "no_devices": True}

        for row in tokens:
            env = row.environment or "production"
            result = await send_background_push(
                row.token, environment=env, payload_extra=_WIDGET_RELOAD_EXTRA
            )

            # Cross-environment retry: a token registered under one APNs
            # environment but actually minted for the other bounces on the wrong
            # host (the common case is a RELEASE-built dev sideload whose
            # `apsEnvironment` reports production while its provisioning profile
            # makes the token sandbox-only). Try the OTHER host before writing it
            # off — only a failure on BOTH means the token is genuinely dead.
            if _is_dead_token(result):
                other = "sandbox" if env == "production" else "production"
                alt = await send_background_push(
                    row.token, environment=other, payload_extra=_WIDGET_RELOAD_EXTRA
                )
                if alt.get("ok"):
                    result = alt

            if result.get("ok"):
                sent += 1
                continue

            # Dead on both hosts → revoke so the next reload doesn't waste a
            # round-trip. The iOS client re-registers a fresh token on next launch.
            if _is_dead_token(result):
                await revoke_device_token(db, user_id, row.token)
                logger.info(
                    "widget reload: revoked dead token for user %s (status=%s reason=%s)",
                    user_id, result.get("status"), result.get("reason"),
                )

    return {"ok": True, "sent": sent}


def schedule_widget_reload(user_id: int | None) -> None:
    """Fire-and-forget `notify_widget_reload` without blocking the caller.

    Log writes happen on the request / turn hot path; a widget reload must never
    add APNs round-trip latency to that. Schedule the coroutine on the running
    loop and return immediately (mirrors
    `native_data._kick_whoop_refresh_if_stale`). Any push failure is swallowed —
    the caller shouldn't know or care whether the silent push actually went out.

    No running loop (a sync context, or some tests) → silent no-op: the in-app
    `WidgetCenter` reload still covers the user-logs-in-the-app case, so a missed
    background push here only costs cross-surface freshness, never correctness.
    """
    if user_id is None:
        return

    # Check for a running loop BEFORE creating the coroutine, so the no-loop path
    # never leaves an un-awaited coroutine behind (which would warn).
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run():
        try:
            await notify_widget_reload(user_id)
        except Exception:  # never let a push failure surface into a log turn
            logger.debug("widget reload push failed for user %s", user_id, exc_info=True)

    loop.create_task(_run())
