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


async def test_ios_first_link_code_generation(make_user, db, monkeypatch, engine):
    """iOS-first direction (2026-07-06): POST /auth/link-code mints a code on the
    CALLING user's canonical row and returns the t.me deep link the bot's
    /start LINK-XXXX handler consumes. The iOS row stays canonical."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from api import auth_routes
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(auth_routes, "AsyncSessionLocal", factory)

    ios = await make_user(telegram_id="ios:LINKGEN-1", name="Firstie")
    resp = await auth_routes.create_link_code(identity="ios:LINKGEN-1")
    assert resp.code.startswith("LINK-")
    assert resp.telegram_deep_link.endswith(f"?start={resp.code}")

    # A fresh Telegram identity consuming it binds INTO the iOS account.
    tg = await get_or_create_user(db, "990001")
    canonical = await consume_link_code(db, resp.code, tg)
    assert canonical is not None and canonical.id == ios.id
    db.expire_all()
    resolved = await resolve_user(db, "990001")
    assert resolved.id == ios.id
