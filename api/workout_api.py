"""
Workout-program REST API — backs the iOS Coach-page program card.

GET  /api/v1/workout_program        → active program (or {"program": null})
GET  /api/v1/workout_program/history → list past programs (newest first)
POST /api/v1/workout_program        → build a new program from explicit params
                                       (the iOS app's "Build a program" form)
DELETE /api/v1/workout_program      → deactivate the current active program

The chat tool (propose_workout_program) is the primary creation surface; this
endpoint exists so the iOS app can show the current program WITHOUT a chat
round-trip, and so a user can rebuild from a settings screen.

Same identity → resolve_user → fetch pattern as the other /api/v1 dashboard
endpoints (see api/recovery_api.py).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import json

from db.database import AsyncSessionLocal
from db.queries import resolve_user
from db.workout_program_queries import (
    get_active_generated_program,
    list_generated_programs,
    save_generated_program,
    program_to_dict,
)
from sqlalchemy import update, select
from db.models import GeneratedWorkoutProgram, WorkoutProgram
from api.auth import current_identity
from skills.fitness.program_builder import build_program

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["workout_program"])


# ── Unified program shape ─────────────────────────────────────────────────────
# iOS and the web Client page used to read DIFFERENT tables (generated_workout_
# programs vs workout_programs), so they showed different programs. Now both read
# the SAME rich shape via this serializer:
#   { split_name, focus, rotation[], days[{name, priority, goals[], exercises[
#       {name, category, recent_performance, notes, sets, reps}]}], source }
# Preference order: the user's PERSONAL parsed program (workout_programs — the
# rich split they set up themselves) wins; the science-builder output is the
# fallback, converted into the same shape so the iOS card renders it identically.

def _builder_to_rich(d: dict | None) -> Optional[dict]:
    """Convert a generated (builder) program dict into the rich unified shape."""
    if not d:
        return None
    days = []
    for s in d.get("sessions", []):
        exs = []
        for e in s.get("exercises", []):
            note = e.get("notes") or ""
            cat = "main" if "main" in note else ("isolation" if "isolation" in note else "accessory")
            exs.append({
                "name": e.get("canonical"),
                "category": cat,
                "recent_performance": None,
                "notes": note or None,
                "sets": e.get("sets"),
                "reps": e.get("reps"),
            })
        days.append({
            "name": s.get("name"),
            "priority": "primary",
            "goals": [],
            "exercises": exs,
        })
    return {
        "split_name": d.get("name") or "Your program",
        "focus": d.get("rationale") or "",
        "rotation": [s.get("name") for s in d.get("sessions", [])],
        "days": days,
        "source": "builder",
    }


async def unified_active_program(db, user_id: int) -> Optional[dict]:
    """The single source of truth for a user's program. Personal parsed split
    first (rich), else the builder output converted to the same shape."""
    row = (await db.execute(
        select(WorkoutProgram).where(WorkoutProgram.user_id == user_id)
    )).scalars().first()
    if row and row.program_json:
        try:
            p = json.loads(row.program_json)
            if isinstance(p, dict) and p.get("days"):
                p.setdefault("source", "personal")
                return p
        except Exception as e:
            logger.warning(f"workout_programs.program_json parse failed (user {user_id}): {e}")
    gen = await get_active_generated_program(db, user_id)
    return _builder_to_rich(program_to_dict(gen)) if gen else None


class BuildProgramBody(BaseModel):
    """Request body for POST /api/v1/workout_program — the iOS Build form."""
    goal: Optional[str] = None
    days_per_week: Optional[int] = 4
    split: Optional[str] = None
    equipment: Optional[list[str]] = None
    experience: Optional[str] = None
    weak_points: Optional[list[str]] = None
    notes: Optional[str] = ""


@router.get("/workout_program")
async def get_workout_program(identity: str = Depends(current_identity)):
    """Return the user's active program in the unified rich shape, or null —
    PERSONAL parsed split first, builder output (converted) as fallback. Same
    source the web Client page reads, so iOS + web finally match.

    Response shape:
        {"program": {split_name, focus, rotation[], days[...], source} | null}
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        program = await unified_active_program(db, user.id)
        if program:
            # "Today" for the card, 4am-aware (Danny 2026-07-23): a finished day
            # shows as COMPLETED until the logging-day rollover, then the
            # rotation's next day takes over. A user-set today_override (set_
            # program_day, stamped with the same logging-day date) wins — the
            # chat context already honors it; the card must agree.
            try:
                from core.program_rotation import infer_today, recent_entries_by_day
                from db.queries import _user_today
                _today_iso = _user_today(
                    getattr(user, "timezone", None) or "UTC").isoformat()
                _day, _done = infer_today(
                    program, await recent_entries_by_day(db, user.id), _today_iso)
                _ov = (program.get("today_override") or {})
                if _ov.get("date") == _today_iso and _ov.get("day"):
                    _ov_day = None if _ov["day"] == "__rest__" else _ov["day"]
                    # Completed only carries over if the override IS the day
                    # the history shows finished (never "done" on a re-pin).
                    _done = bool(_done and _ov_day and _day
                                 and _ov_day.strip().lower() == _day.strip().lower())
                    _day = _ov_day
                program["today_day"] = _day
                program["today_completed"] = _done
            except Exception as e:
                logger.warning(f"today_day inference failed (user {user.id}): {e}")
    return {"program": program}


@router.get("/workout_program/history")
async def get_workout_program_history(
    identity: str = Depends(current_identity),
    limit: int = 10,
):
    """Return up to `limit` past programs for the user, newest first.

    Response shape:
        {"programs": [iOS-contract dict, ...]}
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        programs = await list_generated_programs(db, user.id, limit=max(1, min(50, limit)))
    return {"programs": [program_to_dict(p) for p in programs]}


@router.post("/workout_program")
async def build_workout_program(
    body: BuildProgramBody,
    identity: str = Depends(current_identity),
):
    """Build a new program from explicit params (replaces the active one).

    The iOS app's "Build a program" form posts here. The chat tool
    (propose_workout_program) is the conversational surface — both paths
    converge on the same skills/fitness/program_builder.build_program.
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        try:
            spec = build_program(
                goal=body.goal,
                days_per_week=body.days_per_week or 4,
                split=body.split,
                equipment=body.equipment,
                experience=body.experience,
                weak_points=body.weak_points,
            )
            program = await save_generated_program(
                db, user.id, spec, notes=body.notes or "",
            )
            # Brain attribute sync — durable training-preference traits.
            try:
                from memory.attribute_store import sync_builder_program_to_attributes
                await sync_builder_program_to_attributes(db, user.id, spec)
                await db.commit()
            except Exception as e:
                logger.warning(f"sync_builder_program_to_attributes failed: {e}")
            payload = program_to_dict(program)
            logger.info(
                f"event=workout_program_built_rest user_id={user.id} "
                f"program_id={program.id} split={program.split} "
                f"days={program.days_per_week}"
            )
            return {"program": payload}
        except Exception as e:
            logger.error(f"build_workout_program failed: {e}", exc_info=True)
            raise HTTPException(status_code=422, detail=f"build failed: {e}")


@router.delete("/workout_program")
async def deactivate_workout_program(identity: str = Depends(current_identity)):
    """Soft-deactivate the active program (history preserved). Returns the
    same shape as GET on success — `program: null` once the active row is
    flipped."""
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        await db.execute(
            update(GeneratedWorkoutProgram)
            .where(
                GeneratedWorkoutProgram.user_id == user.id,
                GeneratedWorkoutProgram.active == True,  # noqa: E712
            )
            .values(active=False)
        )
        await db.commit()
    return {"program": None, "status": "ok"}
