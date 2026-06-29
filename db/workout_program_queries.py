"""
Persistence helpers for the science-based program builder.

Separates the builder's DB lifecycle from db/queries.py (which is already large)
and the pure-skill program_builder.py (which has no DB access).

Three operations:
  • save_generated_program(db, user_id, spec) — write a new program + sessions,
    flip any prior active program inactive. Atomic per user.
  • get_active_generated_program(db, user_id) — eager-loads sessions; None if
    the user has no active program.
  • list_generated_programs(db, user_id, limit=10) — history view for the
    iOS Coach page or "show me my past programs" intent. Newest first.

All helpers commit themselves (matching the conversation-layer convention
elsewhere in queries.py). Each writes a `event=workout_program_saved` /
`event=workout_program_loaded` line for greppable telemetry.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import GeneratedWorkoutProgram, GeneratedWorkoutSession

logger = logging.getLogger(__name__)


async def save_generated_program(
    db: AsyncSession,
    user_id: int,
    spec: dict,
    *,
    notes: str = "",
) -> GeneratedWorkoutProgram:
    """Persist a program spec (output of skills.fitness.program_builder.build_program)
    and its per-day sessions. Marks any prior active program inactive. Commits.

    Returns the new GeneratedWorkoutProgram row with `sessions` eager-loaded.
    """
    # 1) flip prior active rows
    await db.execute(
        update(GeneratedWorkoutProgram)
        .where(
            GeneratedWorkoutProgram.user_id == user_id,
            GeneratedWorkoutProgram.active == True,  # noqa: E712
        )
        .values(active=False)
    )

    # 2) insert the new program
    weekly_volume = spec.get("weekly_volume") or {}
    equipment = spec.get("equipment") or []
    weak = spec.get("weak_points") or []
    new_program = GeneratedWorkoutProgram(
        user_id=user_id,
        name=str(spec.get("name") or "Workout Program"),
        goal=str(spec.get("goal") or "hypertrophy"),
        days_per_week=int(spec.get("days_per_week") or 4),
        split=str(spec.get("split") or "ppl"),
        equipment_csv=",".join(equipment),
        experience_level=str(spec.get("experience") or "intermediate"),
        weak_points_csv=",".join(weak),
        rationale=str(spec.get("rationale") or ""),
        weekly_volume_json=json.dumps(weekly_volume),
        notes=notes or "",
        active=True,
    )
    db.add(new_program)
    await db.flush()  # need the id for the children

    # 3) insert the sessions
    from skills.fitness.program_builder import serialize_sessions_for_db
    sessions_payload = serialize_sessions_for_db(spec.get("sessions") or [])
    for i, s in enumerate(sessions_payload, start=1):
        db.add(GeneratedWorkoutSession(
            program_id=new_program.id,
            position=i,
            name=s["name"],
            focus_csv=",".join(s.get("focus") or []),
            exercises_json=json.dumps(s.get("exercises") or []),
        ))

    await db.commit()

    # 4) reload with sessions eager-loaded for the caller
    result = await db.execute(
        select(GeneratedWorkoutProgram)
        .where(GeneratedWorkoutProgram.id == new_program.id)
        .options(selectinload(GeneratedWorkoutProgram.sessions))
    )
    program = result.scalar_one()
    logger.info(
        f"event=workout_program_saved user_id={user_id} "
        f"program_id={program.id} split={program.split} "
        f"days={program.days_per_week} sessions={len(program.sessions)}"
    )
    return program


async def get_active_generated_program(
    db: AsyncSession, user_id: int,
) -> Optional[GeneratedWorkoutProgram]:
    """Return the user's currently-active builder program, or None.

    Sessions are eager-loaded (ordered by position) so the caller can iterate
    them without a lazy-load.

    Order: created_at DESC, id DESC. The id tiebreaker matters: SQLite's
    `datetime('now')` only has second resolution, so two saves in the same
    test second can share a created_at and the natural insertion order is
    lost without the id fallback.
    """
    result = await db.execute(
        select(GeneratedWorkoutProgram)
        .where(
            GeneratedWorkoutProgram.user_id == user_id,
            GeneratedWorkoutProgram.active == True,  # noqa: E712
        )
        .options(selectinload(GeneratedWorkoutProgram.sessions))
        .order_by(desc(GeneratedWorkoutProgram.created_at),
                  desc(GeneratedWorkoutProgram.id))
    )
    return result.scalars().first()


async def list_generated_programs(
    db: AsyncSession, user_id: int, limit: int = 10,
) -> list[GeneratedWorkoutProgram]:
    """All builder programs for this user, newest first.

    Order: created_at DESC, id DESC (id tiebreaker, see
    get_active_generated_program for why)."""
    result = await db.execute(
        select(GeneratedWorkoutProgram)
        .where(GeneratedWorkoutProgram.user_id == user_id)
        .options(selectinload(GeneratedWorkoutProgram.sessions))
        .order_by(desc(GeneratedWorkoutProgram.created_at),
                  desc(GeneratedWorkoutProgram.id))
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_generated_program_by_id(
    db: AsyncSession, user_id: int, program_id: int,
) -> Optional[GeneratedWorkoutProgram]:
    """Fetch a specific program (user-scoped — never returns another user's
    program, even with a guessed id)."""
    result = await db.execute(
        select(GeneratedWorkoutProgram)
        .where(
            GeneratedWorkoutProgram.id == program_id,
            GeneratedWorkoutProgram.user_id == user_id,
        )
        .options(selectinload(GeneratedWorkoutProgram.sessions))
    )
    return result.scalars().first()


def program_to_dict(program: GeneratedWorkoutProgram) -> dict:
    """Serialize a GeneratedWorkoutProgram row + its sessions into the
    JSON-able shape iOS expects (see iOS contract sketch in the handoff
    note)."""
    if program is None:
        return None  # type: ignore[return-value]
    try:
        weekly_volume = json.loads(program.weekly_volume_json or "{}")
    except Exception:
        weekly_volume = {}
    sessions_out = []
    for s in (program.sessions or []):
        try:
            exercises = json.loads(s.exercises_json or "[]")
        except Exception:
            exercises = []
        sessions_out.append({
            "id":        s.id,
            "position":  s.position,
            "name":      s.name,
            "focus":     [m for m in (s.focus_csv or "").split(",") if m],
            "exercises": exercises,
        })
    equipment = [t for t in (program.equipment_csv or "").split(",") if t]
    weak_points = [t for t in (program.weak_points_csv or "").split(",") if t]
    return {
        "id":            program.id,
        "name":          program.name,
        "goal":          program.goal,
        "days_per_week": program.days_per_week,
        "split":         program.split,
        "equipment":     equipment,
        "experience":    program.experience_level,
        "weak_points":   weak_points,
        "rationale":     program.rationale or "",
        "weekly_volume": weekly_volume,
        "active":        bool(program.active),
        "created_at":    program.created_at.isoformat() if program.created_at else None,
        "notes":         program.notes or "",
        "sessions":      sessions_out,
    }
