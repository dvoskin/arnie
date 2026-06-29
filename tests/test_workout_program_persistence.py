"""DB-layer tests for the science-based program builder persistence.

Covers save_generated_program, get_active_generated_program, list_generated_programs,
program_to_dict — the lifecycle the chat tool + REST endpoint sit on top of.
"""
from __future__ import annotations

import pytest

from db.workout_program_queries import (
    save_generated_program,
    get_active_generated_program,
    list_generated_programs,
    get_generated_program_by_id,
    program_to_dict,
)
from skills.fitness.program_builder import build_program


@pytest.mark.asyncio
async def test_save_creates_program_and_sessions(db, make_user):
    user = await make_user(telegram_id="500")
    spec = build_program(goal="hypertrophy", days_per_week=6, split="ppl")
    program = await save_generated_program(db, user.id, spec)
    assert program.id is not None
    assert program.active is True
    assert program.days_per_week == 6
    assert program.split == "ppl"
    assert len(program.sessions) == 6


@pytest.mark.asyncio
async def test_saving_second_program_marks_first_inactive(db, make_user):
    user = await make_user(telegram_id="501")
    p1 = await save_generated_program(
        db, user.id, build_program(days_per_week=6, split="ppl"),
    )
    p2 = await save_generated_program(
        db, user.id, build_program(days_per_week=4, split="upper_lower"),
    )
    # The new program is active; the old one is flipped.
    assert p2.active is True
    # Reload p1 from the DB (its cached `active` field is stale)
    found = await get_generated_program_by_id(db, user.id, p1.id)
    assert found is not None
    assert found.active is False
    # Active getter returns the newest
    active = await get_active_generated_program(db, user.id)
    assert active is not None
    assert active.id == p2.id


@pytest.mark.asyncio
async def test_get_active_returns_none_for_user_without_program(db, make_user):
    user = await make_user(telegram_id="502")
    active = await get_active_generated_program(db, user.id)
    assert active is None


@pytest.mark.asyncio
async def test_list_returns_history_newest_first(db, make_user):
    user = await make_user(telegram_id="503")
    p1 = await save_generated_program(db, user.id, build_program(split="ppl", days_per_week=6))
    p2 = await save_generated_program(db, user.id, build_program(split="upper_lower", days_per_week=4))
    p3 = await save_generated_program(db, user.id, build_program(split="full_body", days_per_week=3))
    history = await list_generated_programs(db, user.id)
    assert len(history) == 3
    ids_newest_first = [p.id for p in history]
    assert ids_newest_first == [p3.id, p2.id, p1.id]


@pytest.mark.asyncio
async def test_get_by_id_is_user_scoped(db, make_user):
    """A user must not be able to fetch another user's program by id."""
    alice = await make_user(telegram_id="600")
    bob = await make_user(telegram_id="601")
    a_prog = await save_generated_program(db, alice.id, build_program())
    # Bob asking for Alice's program by id gets None, not a leak.
    leaked = await get_generated_program_by_id(db, bob.id, a_prog.id)
    assert leaked is None
    # Alice's own fetch still works.
    own = await get_generated_program_by_id(db, alice.id, a_prog.id)
    assert own is not None
    assert own.id == a_prog.id


@pytest.mark.asyncio
async def test_program_to_dict_shape(db, make_user):
    user = await make_user(telegram_id="700")
    spec = build_program(goal="hypertrophy", days_per_week=6, split="ppl",
                         weak_points=["chest_upper"])
    program = await save_generated_program(db, user.id, spec, notes="knee tweaky")
    d = program_to_dict(program)
    # Top-level keys iOS expects
    for k in ("id", "name", "goal", "days_per_week", "split", "equipment",
             "experience", "weak_points", "rationale", "weekly_volume",
             "active", "created_at", "notes", "sessions"):
        assert k in d, f"missing key {k} in program_to_dict"
    assert d["goal"] == "hypertrophy"
    assert d["days_per_week"] == 6
    assert d["split"] == "ppl"
    assert "chest_upper" in d["weak_points"]
    assert d["notes"] == "knee tweaky"
    assert d["active"] is True
    # Sessions carry the prescription, ordered by position
    assert len(d["sessions"]) == 6
    positions = [s["position"] for s in d["sessions"]]
    assert positions == sorted(positions)
    first = d["sessions"][0]
    for k in ("id", "position", "name", "focus", "exercises"):
        assert k in first
    assert isinstance(first["exercises"], list)
    assert len(first["exercises"]) > 0
    first_ex = first["exercises"][0]
    for k in ("canonical", "sets", "reps", "rir", "rest_seconds", "notes"):
        assert k in first_ex


@pytest.mark.asyncio
async def test_serializing_program_with_no_sessions_is_safe(db, make_user):
    """Defensive: a program row with zero sessions still serializes cleanly."""
    from db.models import GeneratedWorkoutProgram
    user = await make_user(telegram_id="701")
    db.add(GeneratedWorkoutProgram(
        user_id=user.id, name="Empty", goal="hypertrophy",
        days_per_week=4, split="ppl", active=True,
    ))
    await db.commit()
    active = await get_active_generated_program(db, user.id)
    d = program_to_dict(active)
    assert d["sessions"] == []
