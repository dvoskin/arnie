"""
Tests for /api/v1/preferences, /api/v1/feedback, /api/v1/auth/signout
(slice 8 — Settings tab backend).
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.settings_api import (
    FeedbackBody,
    PreferencesEditBody,
    patch_preferences,
    post_feedback,
    signout,
)
from db.models import Feedback, UserPreferences


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    from api import settings_api
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(settings_api, "AsyncSessionLocal", factory)
    return factory


# ── Preferences ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_preferences_writes_canonical_fields(
    patched_session_local, db, make_user,
):
    """All UserPreferences columns iOS can edit round-trip cleanly."""
    user = await make_user(telegram_id="ios:prefs")
    resp = await patch_preferences(
        PreferencesEditBody(
            coaching_style="strict",
            reminder_frequency="light",
            proactive_messaging_enabled=False,
            wake_time="06:30",
            sleep_time="22:30",
            food_logging_mode="strict",
        ),
        identity="ios:prefs",
    )

    assert resp["ok"] is True
    assert set(resp["updated_fields"]) == {
        "coaching_style", "reminder_frequency", "proactive_messaging_enabled",
        "wake_time", "sleep_time", "food_logging_mode",
    }
    prefs = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )).scalar_one()
    await db.refresh(prefs)
    assert prefs.coaching_style == "strict"
    assert prefs.reminder_frequency == "light"
    assert prefs.proactive_messaging_enabled is False
    assert prefs.wake_time == "06:30"
    assert prefs.sleep_time == "22:30"
    assert prefs.food_logging_mode == "strict"


@pytest.mark.asyncio
async def test_patch_preferences_rejects_invalid_enum_values():
    """Pydantic Literal types refuse unknown strings before the route
    runs — protects against client typos / outdated builds sending
    enum values the model has since deprecated."""
    with pytest.raises(Exception):
        PreferencesEditBody(coaching_style="aggressive")
    with pytest.raises(Exception):
        PreferencesEditBody(reminder_frequency="extreme")
    with pytest.raises(Exception):
        PreferencesEditBody(food_logging_mode="loose")


@pytest.mark.asyncio
async def test_patch_preferences_rejects_invalid_time_format():
    """wake_time / sleep_time must be HH:MM. Frees the coaching engine
    from defensive parsing in dozens of downstream call sites."""
    with pytest.raises(Exception):
        PreferencesEditBody(wake_time="6:30 AM")
    with pytest.raises(Exception):
        PreferencesEditBody(wake_time="6")


@pytest.mark.asyncio
async def test_patch_preferences_empty_body_is_quiet_noop(
    patched_session_local, make_user,
):
    await make_user(telegram_id="ios:empty-prefs")
    resp = await patch_preferences(PreferencesEditBody(), identity="ios:empty-prefs")
    assert resp == {"ok": True, "updated_fields": []}


# ── Feedback ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_feedback_creates_row_tied_to_user(
    patched_session_local, db, make_user,
):
    user = await make_user(telegram_id="ios:feedback-user")
    resp = await post_feedback(
        FeedbackBody(text="The Today tab calorie ring is rendering as a square", kind="bug"),
        identity="ios:feedback-user",
    )

    assert resp["ok"] is True
    assert resp["feedback_id"] > 0

    rows = (await db.execute(
        select(Feedback).where(Feedback.user_id == user.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "bug"
    assert rows[0].text.startswith("The Today tab")
    assert rows[0].resolved is False


@pytest.mark.asyncio
async def test_post_feedback_defaults_kind_to_other(
    patched_session_local, db, make_user,
):
    """When iOS omits the kind, it lands as 'other' — same default the
    chat /feedback command uses."""
    user = await make_user(telegram_id="ios:feedback-default")
    await post_feedback(
        FeedbackBody(text="Love the app, just want to say so."),
        identity="ios:feedback-default",
    )
    row = (await db.execute(
        select(Feedback).where(Feedback.user_id == user.id)
    )).scalar_one()
    assert row.kind == "other"


@pytest.mark.asyncio
async def test_post_feedback_rejects_empty_text():
    """min_length=1 — an empty submission is almost always a UI bug
    (e.g. submit pressed before keyboard committed). Surface as 422
    before the row lands."""
    with pytest.raises(Exception):
        FeedbackBody(text="")


@pytest.mark.asyncio
async def test_post_feedback_rejects_huge_text():
    """max_length=10000 — DoS guard against a runaway client paste."""
    with pytest.raises(Exception):
        FeedbackBody(text="x" * 20_000)


@pytest.mark.asyncio
async def test_post_feedback_invalid_kind_rejected():
    """Literal["bug","feature","other"] — anything else refused."""
    with pytest.raises(Exception):
        FeedbackBody(text="hi", kind="praise")


# ── Sign-out ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signout_echoes_identity_and_succeeds(patched_session_local):
    """The placeholder endpoint returns {ok, identity}; the client clears
    its keychain on receiving 200. Real revocation is a future slice."""
    resp = await signout(identity="ios:signout-user")
    assert resp == {"ok": True, "identity": "ios:signout-user"}
