"""Dashboard ↔ bot consistency for linked accounts.

Regression for: deleting water (or any entry) on the dashboard didn't show up
when asking the bot in Telegram. Root cause was an asymmetry — the bot resolves
the user via resolve_user() (which follows linked_to_user_id to the canonical
account), while the dashboard's get_user_by_webhook_token() did NOT, so the two
surfaces could read/write different DailyLog rows.

The fix makes get_user_by_webhook_token() canonicalize by default, while still
exposing the raw token-owner row via follow_link=False (used by the Whoop OAuth
flow). These tests pin both behaviors plus the end-to-end water round-trip.
"""
import datetime
import pytest

from db.queries import (
    get_or_create_user, generate_link_code, consume_link_code, resolve_user,
    get_user_by_webhook_token, get_or_create_today_log, get_today_log,
    add_water_entry, delete_water_entry,
)

CANON_TG = "211302570"   # canonical Telegram account (the real reporter's id)
SECOND_IM = "im:+15550001111"  # linked iMessage identity


async def _link_imessage_to_telegram(make_user, db):
    """Canonical = Telegram user; secondary = iMessage identity linked into it.

    Mirrors test_linking.py: the code OWNER is canonical, the code CONSUMER
    becomes the secondary (consumer.linked_to_user_id = canonical.id)."""
    tg = await make_user(telegram_id=CANON_TG, name="Denys")
    im = await get_or_create_user(db, SECOND_IM)
    code = await generate_link_code(db, tg)
    canonical = await consume_link_code(db, code, im)
    assert canonical.id == tg.id
    return tg, im


async def test_unlinked_token_returns_same_user(make_user, db):
    """No link → no behavior change (the common case)."""
    u = await make_user(telegram_id=CANON_TG, name="Denys")
    u.webhook_token = "tok-solo"
    await db.commit()
    got = await get_user_by_webhook_token(db, "tok-solo")
    assert got is not None and got.id == u.id


async def test_linked_token_resolves_to_canonical(make_user, db):
    """A linked identity's dashboard token now resolves to the canonical brain."""
    tg, im = await _link_imessage_to_telegram(make_user, db)
    im.webhook_token = "tok-secondary"
    await db.commit()

    # Default (follow_link=True): canonical — same as what the bot reads.
    canon = await get_user_by_webhook_token(db, "tok-secondary")
    assert canon.id == tg.id

    # follow_link=False: raw token-owner row preserved (Whoop OAuth path).
    raw = await get_user_by_webhook_token(db, "tok-secondary", follow_link=False)
    assert raw.id == im.id


async def test_water_delete_on_dashboard_visible_to_bot(make_user, db):
    """End-to-end: water logged via the bot (canonical), deleted on a linked
    identity's dashboard, must read back as gone for the bot."""
    tg, im = await _link_imessage_to_telegram(make_user, db)
    im.webhook_token = "tok-secondary"
    await db.commit()

    # Bot logs 500ml: resolve_user → canonical, so it lands on the canonical log.
    bot_user = await resolve_user(db, SECOND_IM)
    assert bot_user.id == tg.id
    log = await get_or_create_today_log(db, bot_user.id, "UTC")
    log.total_water_ml = (log.total_water_ml or 0) + 500
    await db.commit()
    entry = await add_water_entry(db, bot_user.id, log.id, amount_ml=500)

    # Dashboard delete: opened via the secondary identity's token.
    dash_user = await get_user_by_webhook_token(db, "tok-secondary")
    ok = await delete_water_entry(db, entry.id, dash_user.id)
    assert ok is True  # would be False (404) before the canonicalization fix

    # Bot re-reads today: water is gone.
    fresh = await get_today_log(db, (await resolve_user(db, SECOND_IM)).id, "UTC")
    assert round(fresh.total_water_ml or 0) == 0


async def test_delete_with_raw_secondary_id_would_miss(make_user, db):
    """Pins the OLD failure mode: scoping the delete to the raw secondary row
    (the pre-fix behavior) does NOT remove the canonical entry."""
    tg, im = await _link_imessage_to_telegram(make_user, db)

    bot_user = await resolve_user(db, SECOND_IM)
    log = await get_or_create_today_log(db, bot_user.id, "UTC")
    log.total_water_ml = 500
    await db.commit()
    entry = await add_water_entry(db, bot_user.id, log.id, amount_ml=500)

    # Pre-fix: dashboard used the secondary row's id → ownership check fails.
    ok = await delete_water_entry(db, entry.id, im.id)
    assert ok is False
    refreshed = await get_today_log(db, tg.id, "UTC")
    assert round(refreshed.total_water_ml or 0) == 500
