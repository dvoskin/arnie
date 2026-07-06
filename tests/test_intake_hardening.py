"""
Intake hardening — the two prod-user failures from 2026-07-06 triage:

1. Marina (user 76) typed "Naples, USA" into the onboarding timezone field; the
   raw string landed in users.timezone and pytz.timezone() raised on EVERY chat
   turn → each message 500'd ("Arnie's temporarily unavailable"). Guarded at
   both ends: normalize_timezone gates every write, safe_timezone/_user_today
   degrade to UTC on legacy junk instead of raising.

2. Dean (user 78): the iOS submit's completeOnboarding() call is fire-and-forget
   (`try?`) — when it silently failed he landed in chat half-onboarded, typed
   first, and the greeting later seeded MID-conversation. PATCH /profile now
   auto-flips when the required set completes, and the seed skips a thread
   that's already live.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from core.timezones import normalize_timezone, safe_timezone
from db.models import ConversationLog, User
from db.queries import _user_today, has_real_conversation, log_conversation


# ── normalize_timezone (intake gate) ─────────────────────────────────────────

def test_normalize_accepts_iana_and_corrects_case():
    assert normalize_timezone("America/New_York") == "America/New_York"
    assert normalize_timezone("america/new_york") == "America/New_York"
    assert normalize_timezone(" Europe/Kyiv ") == "Europe/Kyiv"


def test_normalize_salvages_confident_locations():
    # The exact string Marina typed — Naples FL, not Naples Italy.
    assert normalize_timezone("Naples, USA") == "America/New_York"
    assert normalize_timezone("NYC") == "America/New_York"
    assert normalize_timezone("Naples, Italy") == "Europe/Rome"


def test_normalize_rejects_junk():
    assert normalize_timezone("gibberish xyz") is None
    assert normalize_timezone("") is None
    assert normalize_timezone(None) is None
    assert normalize_timezone(123) is None


# ── safe_timezone + _user_today (legacy junk must never crash a turn) ────────

def test_safe_timezone_falls_back_to_utc():
    assert str(safe_timezone("Naples, USA")) == "UTC"
    assert str(safe_timezone(None)) == "UTC"
    assert str(safe_timezone("America/New_York")) == "America/New_York"


def test_user_today_survives_junk_timezone():
    # Pre-fix this raised UnknownTimeZoneError and 500'd the whole chat turn.
    d = _user_today("Naples, USA")
    assert d == _user_today("UTC")


# ── seed guard: has_real_conversation ────────────────────────────────────────

@pytest.mark.asyncio
async def test_has_real_conversation_ignores_start_seed(db, make_user):
    u = await make_user(telegram_id="ios:seed-guard-1")
    assert not await has_real_conversation(db, u.id)
    await log_conversation(db, u.id, "[start]", "hey|||welcome",
                           source_type="text", platform="ios")
    assert not await has_real_conversation(db, u.id)
    await log_conversation(db, u.id, "ate a bagel", "logged it",
                           source_type="ios", platform="ios")
    assert await has_real_conversation(db, u.id)


# ── PATCH /profile: timezone gate + server-side completion ───────────────────

@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import profile_edit
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(profile_edit, "AsyncSessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_patch_profile_drops_junk_timezone(patched_session_local, db, make_user):
    from api.profile_edit import ProfileEditBody, patch_profile
    u = await make_user(telegram_id="ios:tz-junk", timezone="America/New_York")
    resp = await patch_profile(
        ProfileEditBody(timezone="Planet Xyzzy 9"),
        identity="ios:tz-junk",
    )
    assert resp["ok"]
    assert "timezone" in resp.get("skipped_fields", [])
    db.expire_all()
    row = (await db.execute(
        select(User).where(User.telegram_id == "ios:tz-junk"))).scalar_one()
    assert row.timezone == "America/New_York"  # junk never overwrote it


@pytest.mark.asyncio
async def test_patch_profile_normalizes_timezone(patched_session_local, db, make_user):
    from api.profile_edit import ProfileEditBody, patch_profile
    await make_user(telegram_id="ios:tz-norm")
    resp = await patch_profile(
        ProfileEditBody(timezone="Naples, USA"), identity="ios:tz-norm",
    )
    assert resp["ok"] and "timezone" in resp["updated_fields"]
    db.expire_all()
    row = (await db.execute(
        select(User).where(User.telegram_id == "ios:tz-norm"))).scalar_one()
    assert row.timezone == "America/New_York"


@pytest.mark.asyncio
async def test_patch_profile_autoflips_onboarding_and_seeds(
    patched_session_local, db, make_user,
):
    """The save that completes the required set flips the bit itself — even if
    the client's separate completeOnboarding() call never arrives — and seeds
    the intro into the empty thread."""
    from api.profile_edit import ProfileEditBody, patch_profile
    u = await make_user(telegram_id="ios:autoflip", onboarded=False,
                        age=30, sex="male", height_cm=180.0)
    resp = await patch_profile(
        ProfileEditBody(current_weight_kg=80.0, primary_goal="bulk"),
        identity="ios:autoflip",
    )
    assert resp["onboarding_completed"] is True
    db.expire_all()
    row = (await db.execute(
        select(User).where(User.telegram_id == "ios:autoflip"))).scalar_one()
    assert row.onboarding_completed is True
    seeds = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == u.id,
                                      ConversationLog.raw_message == "[start]")
    )).scalars().all()
    assert len(seeds) == 1


@pytest.mark.asyncio
async def test_late_completion_skips_seed_when_thread_live(
    patched_session_local, db, make_user,
):
    """Dean's exact failure: the completion signal arrives AFTER the user
    already started talking. The bit still flips, but no greeting lands
    mid-conversation."""
    from api.profile_edit import ProfileEditBody, patch_profile
    u = await make_user(telegram_id="ios:late-flip", onboarded=False,
                        age=27, sex="male", height_cm=170.0)
    await log_conversation(db, u.id, "Ate a bacon egg and cheese", "logged",
                           source_type="ios", platform="ios")
    resp = await patch_profile(
        ProfileEditBody(current_weight_kg=67.0, primary_goal="bulk"),
        identity="ios:late-flip",
    )
    assert resp["onboarding_completed"] is True
    seeds = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == u.id,
                                      ConversationLog.raw_message == "[start]")
    )).scalars().all()
    assert seeds == []


@pytest.mark.asyncio
async def test_patch_profile_no_flip_while_fields_missing(
    patched_session_local, db, make_user,
):
    from api.profile_edit import ProfileEditBody, patch_profile
    u = await make_user(telegram_id="ios:incomplete", onboarded=False, age=30)
    resp = await patch_profile(
        ProfileEditBody(sex="female"), identity="ios:incomplete",
    )
    assert resp["onboarding_completed"] is False
    seeds = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == u.id)
    )).scalars().all()
    assert seeds == []
