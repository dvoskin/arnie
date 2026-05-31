"""Cross-platform linking + channel-preference routing (one message per user)."""
import os
import pytest
from db.queries import (
    get_or_create_user, generate_link_code, consume_link_code,
    resolve_send_target, resolve_user,
)


async def test_link_code_lifecycle(make_user, db):
    tg = await make_user(telegram_id="100", name="Danny")
    im = await get_or_create_user(db, "im:+15551234567")
    code = await generate_link_code(db, tg)
    assert code.startswith("LINK-")
    canonical = await consume_link_code(db, code, im)
    assert canonical is not None and canonical.id == tg.id
    # iMessage identity now resolves to the canonical Telegram account
    resolved = await resolve_user(db, "im:+15551234567")
    assert resolved.id == tg.id


async def test_bad_code_rejected(make_user, db):
    im = await get_or_create_user(db, "im:+1")
    assert await consume_link_code(db, "LINK-ZZZZ", im) is None


async def test_resolve_send_target_routes_by_preference(make_user, db):
    tg = await make_user(telegram_id="100", name="Danny")
    im = await get_or_create_user(db, "im:+15551234567")
    im.onboarding_completed = True
    await db.commit()
    code = await generate_link_code(db, tg)
    await consume_link_code(db, code, im)

    tg.channel_preference = "telegram"; await db.commit()
    assert await resolve_send_target(db, tg) == "100"

    tg.channel_preference = "imessage"; await db.commit()
    assert await resolve_send_target(db, tg) == "im:+15551234567"

    tg.channel_preference = None; await db.commit()
    assert await resolve_send_target(db, tg) == "100"  # falls back to canonical
