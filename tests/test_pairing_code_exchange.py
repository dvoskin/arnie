"""
Tests for POST /api/v1/auth/exchange-pairing-code (iOS-side landing-form handoff).

Mirrors the Telegram bot's SETUP-XXX consumption (bot/telegram_handler.py:754):
consume the code, apply the profile, set onboarding_completed=True, issue a
session token. Distinct from the Telegram path: structured HTTP status codes
(404 / 410 / 409 / 401) instead of conversational replies.
"""
import json
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.auth_routes import PairingCodeRequest, exchange_pairing_code
from db.models import PreRegistration, User


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    """Point api.auth_routes.AsyncSessionLocal at the test engine so the handler's
    `async with AsyncSessionLocal() as db:` reads/writes the same in-memory DB
    the `db` fixture exposes for assertions."""
    from api import auth_routes
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(auth_routes, "AsyncSessionLocal", session_factory)
    return session_factory


@pytest_asyncio.fixture
async def make_pre_reg(db):
    """Factory: persist a PreRegistration row with the given profile + code."""

    async def _make(code="SETUP-ABC123", profile=None, expires_in_hours=48, consumed=False):
        profile = profile if profile is not None else _full_form_profile()
        entry = PreRegistration(
            code=code,
            profile_json=json.dumps(profile),
            expires_at=datetime.utcnow() + timedelta(hours=expires_in_hours),
            consumed_at=datetime.utcnow() if consumed else None,
        )
        db.add(entry)
        await db.commit()
        return entry

    return _make


def _full_form_profile() -> dict:
    """Representative landing-form payload — name + stats + targets + bonuses."""
    return {
        "name": "Danny",
        "age": 32,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82.0,
        "primary_goal": "cut",
        "training_experience": "advanced",
        "dietary_preferences": "no shellfish",
        "goal_weight_lbs": 175,
        "calorie_target": 2180,
        "protein_target": 175,
        "carb_target": 200,
        "fat_target": 70,
    }


# ── Happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_applies_profile_marks_onboarded_returns_welcome(
    patched_session_local, db, make_pre_reg,
):
    await make_pre_reg(code="SETUP-HAPPY1", profile=_full_form_profile())

    resp = await exchange_pairing_code(
        PairingCodeRequest(
            code="SETUP-HAPPY1", provider="device", credential="ios:dev-1",
        )
    )

    assert resp.identity == "ios:dev-1"
    assert resp.token  # signed session token

    # Welcome payload carries the iOS welcome-card data.
    assert resp.welcome.name == "Danny"
    assert resp.welcome.primary_goal == "cut"
    assert resp.welcome.goal_phrase == "leaning out"  # from GOAL_PHRASE_MAP
    assert resp.welcome.calorie_target == 2180
    assert resp.welcome.protein_target == 175
    assert resp.welcome.carb_target == 200
    assert resp.welcome.fat_target == 70

    # Persisted profile reflects the form payload + onboarding flipped.
    user = (await db.execute(
        select(User).where(User.telegram_id == "ios:dev-1")
    )).scalar_one()
    assert user.name == "Danny"
    assert user.age == 32
    assert user.sex == "male"
    assert user.height_cm == 178
    assert user.current_weight_kg == 82.0
    assert user.primary_goal == "cut"
    assert user.training_experience == "advanced"
    assert user.dietary_preferences == "no shellfish"
    assert user.onboarding_completed is True
    # goal_weight_lbs → goal_weight_kg conversion (mirrors bot handler).
    assert user.goal_weight_kg == round(175 / 2.20462, 2)


@pytest.mark.asyncio
async def test_happy_path_consumes_code_so_second_call_410s(
    patched_session_local, db, make_pre_reg,
):
    await make_pre_reg(code="SETUP-ONCE01")

    await exchange_pairing_code(
        PairingCodeRequest(
            code="SETUP-ONCE01", provider="device", credential="ios:dev-2",
        )
    )

    # Replay → 410 Gone (code already consumed).
    with pytest.raises(HTTPException) as exc:
        await exchange_pairing_code(
            PairingCodeRequest(
                code="SETUP-ONCE01", provider="device", credential="ios:dev-other",
            )
        )
    assert exc.value.status_code == 410


# ── Failure modes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_code_returns_410(patched_session_local):
    """consume_pre_registration returns None for unknown OR expired OR consumed —
    endpoint can't distinguish and surfaces 410 for all three. 410 chosen over
    404 because the most common iOS-side cause is a re-entry attempt."""
    with pytest.raises(HTTPException) as exc:
        await exchange_pairing_code(
            PairingCodeRequest(
                code="SETUP-NOPE00", provider="device", credential="ios:dev-3",
            )
        )
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_expired_code_returns_410(patched_session_local, make_pre_reg):
    await make_pre_reg(code="SETUP-EXPRD1", expires_in_hours=-1)

    with pytest.raises(HTTPException) as exc:
        await exchange_pairing_code(
            PairingCodeRequest(
                code="SETUP-EXPRD1", provider="device", credential="ios:dev-4",
            )
        )
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_already_consumed_code_returns_410(patched_session_local, make_pre_reg):
    await make_pre_reg(code="SETUP-USED01", consumed=True)

    with pytest.raises(HTTPException) as exc:
        await exchange_pairing_code(
            PairingCodeRequest(
                code="SETUP-USED01", provider="device", credential="ios:dev-5",
            )
        )
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_already_onboarded_user_returns_409_and_consumes_code(
    patched_session_local, db, make_pre_reg, make_user,
):
    """Replay protection — the code is consumed BEFORE the onboarded check,
    mirroring the Telegram bot's SETUP-XXX flow. Existing account is untouched."""
    existing = await make_user(telegram_id="ios:already-set", name="Original")
    existing.onboarding_completed = True
    await db.commit()

    await make_pre_reg(code="SETUP-DUPE01")

    with pytest.raises(HTTPException) as exc:
        await exchange_pairing_code(
            PairingCodeRequest(
                code="SETUP-DUPE01", provider="device", credential="ios:already-set",
            )
        )
    assert exc.value.status_code == 409

    # Existing account left as-is (name not overwritten by the form's "Danny").
    user = (await db.execute(
        select(User).where(User.telegram_id == "ios:already-set")
    )).scalar_one()
    assert user.name == "Original"

    # Code WAS consumed → a fresh attempt with the same code now hits the 410 path.
    entry = (await db.execute(
        select(PreRegistration).where(PreRegistration.code == "SETUP-DUPE01")
    )).scalar_one()
    assert entry.consumed_at is not None


@pytest.mark.asyncio
async def test_unknown_provider_propagates_400_before_consuming_code(
    patched_session_local, db, make_pre_reg,
):
    """verify_provider_credential rejects unknown providers with 400 BEFORE the
    handler touches the pre_registration. A validation failure must not consume
    the code (the user gets to retry with a valid provider)."""
    await make_pre_reg(code="SETUP-VALID1")

    with pytest.raises(HTTPException) as exc:
        await exchange_pairing_code(
            PairingCodeRequest(
                code="SETUP-VALID1", provider="not-a-real-provider", credential="anything",
            )
        )
    assert exc.value.status_code == 400

    # Code NOT consumed — a subsequent valid call still works.
    entry = (await db.execute(
        select(PreRegistration).where(PreRegistration.code == "SETUP-VALID1")
    )).scalar_one()
    assert entry.consumed_at is None


@pytest.mark.asyncio
async def test_lowercase_code_normalized_to_upper(
    patched_session_local, make_pre_reg,
):
    """The iOS app may not uppercase user input — the endpoint should accept
    "setup-abc123" the same as "SETUP-ABC123" (matches consume_pre_registration's
    upper() normalization)."""
    await make_pre_reg(code="SETUP-LOWER1", profile={"name": "Casey", "primary_goal": "bulk"})

    resp = await exchange_pairing_code(
        PairingCodeRequest(
            code="setup-lower1", provider="device", credential="ios:dev-6",
        )
    )
    assert resp.welcome.name == "Casey"
    assert resp.welcome.goal_phrase == "putting on size"
