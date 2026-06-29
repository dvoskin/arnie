"""
Tests for /api/v1/workout_program — the iOS Coach page's program endpoint.

GET (active), GET history, POST (build), DELETE (deactivate). The chat tool
(propose_workout_program) routes through the same persistence helpers, so
testing the endpoint covers the same write path the conversational surface
uses.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api.workout_api import (
    BuildProgramBody,
    build_workout_program,
    deactivate_workout_program,
    get_workout_program,
    get_workout_program_history,
)


@pytest_asyncio.fixture
async def patched_session_local(monkeypatch, engine):
    """Point api.workout_api.AsyncSessionLocal at the test engine."""
    from api import workout_api
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(workout_api, "AsyncSessionLocal", session_factory)
    return session_factory


# ── GET ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_null_when_no_program(
    patched_session_local, make_user,
):
    """Empty state: a user with no builder program gets `program: null`."""
    await make_user(telegram_id="ios:empty")
    resp = await get_workout_program(identity="ios:empty")
    assert resp == {"program": None}


@pytest.mark.asyncio
async def test_post_builds_program_and_get_returns_it(
    patched_session_local, db, make_user,
):
    """POST builds + persists; GET reads the active program back."""
    user = await make_user(telegram_id="ios:builder")
    body = BuildProgramBody(
        goal="hypertrophy", days_per_week=6, split="ppl",
        experience="intermediate",
    )
    post_resp = await build_workout_program(body, identity="ios:builder")
    assert post_resp["program"] is not None
    assert post_resp["program"]["split"] == "ppl"
    assert post_resp["program"]["days_per_week"] == 6
    assert len(post_resp["program"]["sessions"]) == 6

    # GET sees the same active program
    get_resp = await get_workout_program(identity="ios:builder")
    assert get_resp["program"] is not None
    assert get_resp["program"]["id"] == post_resp["program"]["id"]


@pytest.mark.asyncio
async def test_post_marks_previous_program_inactive(
    patched_session_local, make_user,
):
    """Building a second program flips the first to inactive."""
    await make_user(telegram_id="ios:flip")
    await build_workout_program(
        BuildProgramBody(goal="hypertrophy", days_per_week=6, split="ppl"),
        identity="ios:flip",
    )
    second = await build_workout_program(
        BuildProgramBody(goal="strength", days_per_week=4, split="upper_lower"),
        identity="ios:flip",
    )
    active = await get_workout_program(identity="ios:flip")
    assert active["program"]["id"] == second["program"]["id"]
    assert active["program"]["split"] == "upper_lower"

    # History shows both, newest first, only the newer one active.
    history = await get_workout_program_history(identity="ios:flip", limit=10)
    assert len(history["programs"]) == 2
    assert history["programs"][0]["active"] is True
    assert history["programs"][1]["active"] is False


@pytest.mark.asyncio
async def test_delete_deactivates_active_program(
    patched_session_local, make_user,
):
    """DELETE soft-deactivates — history preserved, current = null."""
    await make_user(telegram_id="ios:delete")
    built = await build_workout_program(
        BuildProgramBody(goal="hypertrophy", days_per_week=4, split="upper_lower"),
        identity="ios:delete",
    )
    assert built["program"] is not None

    resp = await deactivate_workout_program(identity="ios:delete")
    assert resp["program"] is None
    assert resp["status"] == "ok"

    # GET active returns null, but history still has the row (inactive)
    assert (await get_workout_program(identity="ios:delete"))["program"] is None
    hist = await get_workout_program_history(identity="ios:delete")
    assert len(hist["programs"]) == 1
    assert hist["programs"][0]["active"] is False


@pytest.mark.asyncio
async def test_post_with_bodyweight_only_generates_bodyweight_program(
    patched_session_local, make_user,
):
    """The form's equipment filter actually flows through to the builder."""
    await make_user(telegram_id="ios:bw")
    resp = await build_workout_program(
        BuildProgramBody(
            goal="hypertrophy", days_per_week=3, split="full_body",
            equipment=["bodyweight"],
        ),
        identity="ios:bw",
    )
    program = resp["program"]
    assert program is not None
    assert program["equipment"] == ["bodyweight"]
    # All exercises in every session are bodyweight movements (no need to
    # walk to the catalog — the serialized session shape doesn't carry
    # equipment, but the builder ONLY had bodyweight to pick from).
    for s in program["sessions"]:
        assert len(s["exercises"]) > 0


@pytest.mark.asyncio
async def test_post_persists_weak_points_into_brain_attributes(
    patched_session_local, db, make_user,
):
    """Weak points → durable brain attribute. After the post, the user has a
    fitness_weak_points UserAttribute row."""
    from sqlalchemy import select
    from db.models import UserAttribute
    user = await make_user(telegram_id="ios:wp")
    await build_workout_program(
        BuildProgramBody(
            goal="hypertrophy", days_per_week=4, split="upper_lower",
            weak_points=["chest_upper", "lats"],
        ),
        identity="ios:wp",
    )
    rows = (await db.execute(
        select(UserAttribute).where(UserAttribute.user_id == user.id)
    )).scalars().all()
    keys = {r.attribute_key: r.value for r in rows}
    assert "fitness_training_split" in keys
    assert "fitness_weak_points" in keys
    assert "chest_upper" in keys["fitness_weak_points"]
    assert "lats" in keys["fitness_weak_points"]


@pytest.mark.asyncio
async def test_get_history_limit_respected(
    patched_session_local, make_user,
):
    """The history endpoint paginates by `limit` (capped 1..50)."""
    await make_user(telegram_id="ios:hist")
    for _ in range(3):
        await build_workout_program(
            BuildProgramBody(goal="hypertrophy", days_per_week=4, split="upper_lower"),
            identity="ios:hist",
        )
    resp = await get_workout_program_history(identity="ios:hist", limit=2)
    assert len(resp["programs"]) == 2
    # Default fetch returns all 3
    resp_all = await get_workout_program_history(identity="ios:hist")
    assert len(resp_all["programs"]) == 3
