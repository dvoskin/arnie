"""Supplement stack + daily adherence — Coach "Stack" card.

The supplement REGIMEN lives in the brain as active `health_supplement_*`
UserAttributes (Arnie learns them from chat, so the card grows itself as new
supplements are mentioned). This module layers a per-day adherence log on top
(SupplementIntake) and serves both to iOS:

    GET  /api/v1/supplements          → active stack + today's taken state + streak
    POST /api/v1/supplements/toggle   → flip "taken today" for one supplement

Same identity → resolve_user → fetch pattern as the other /api/v1 endpoints.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_, delete

from db.database import AsyncSessionLocal
from db.queries import resolve_user, _user_today
from db.models import UserAttribute, SupplementIntake
from api.auth import current_identity

logger = logging.getLogger("arnie.supplements")
router = APIRouter(prefix="/api/v1", tags=["supplements"])

# A handful of `health_supplement_*` keys are really biomarkers/labels, not
# something you "take" — never list them as a trackable supplement.
_NON_SUPPLEMENT_SUFFIXES = ("ferritin", "vitamin_d_level", "biometric")
_STREAK_LOOKBACK = 30   # days scanned for the consecutive-day streak / mini history


def _is_real_supplement(key: str) -> bool:
    k = (key or "").lower()
    if not k.startswith("health_supplement_"):
        return False
    return not any(s in k for s in _NON_SUPPLEMENT_SUFFIXES)


async def _active_supplements(db, user_id: int) -> list[UserAttribute]:
    rows = (await db.execute(
        select(UserAttribute).where(and_(
            UserAttribute.user_id == user_id,
            UserAttribute.attribute_status == "active",
            UserAttribute.attribute_key.like("health_supplement_%"),
        )).order_by(UserAttribute.attribute_key)
    )).scalars().all()
    return [a for a in rows if _is_real_supplement(a.attribute_key)]


async def _intake_dates(db, user_id: int, key: str, since) -> set:
    rows = (await db.execute(
        select(SupplementIntake.intake_date).where(and_(
            SupplementIntake.user_id == user_id,
            SupplementIntake.supplement_key == key,
            SupplementIntake.intake_date >= since,
        ))
    )).scalars().all()
    return set(rows)


def _streak_to(today, taken: set) -> int:
    """Consecutive days ending today (or yesterday) that have an intake."""
    n, d = 0, today
    # allow the streak to "hold" if today isn't logged yet but yesterday was
    if today not in taken and (today - timedelta(days=1)) in taken:
        d = today - timedelta(days=1)
    while d in taken:
        n += 1
        d -= timedelta(days=1)
    return n


def _clean_name(attr: UserAttribute) -> str:
    """A tidy supplement label. Strips the bookkeeping "Health Supplement "
    prefix some stored display names carry; falls back to the key."""
    name = (attr.display_name or "").strip()
    for pre in ("Health Supplement ", "Nutrition Supplement ", "Supplement "):
        if name.startswith(pre):
            name = name[len(pre):]
    if not name:
        name = attr.attribute_key.replace("health_supplement_", "").replace("_", " ").title()
    return name


def _supplement_dict(attr: UserAttribute, today, taken: set) -> dict:
    last7 = [(today - timedelta(days=i)) in taken for i in range(6, -1, -1)]
    return {
        "key": attr.attribute_key,
        "name": _clean_name(attr),
        "detail": attr.value or "",
        "taken_today": today in taken,
        "streak": _streak_to(today, taken),
        "last7": last7,
    }


@router.get("/supplements")
async def get_supplements(identity: str = Depends(current_identity)):
    """The active stack with today's adherence. Response:
        {"supplements": [{key, name, detail, taken_today, streak, last7[7]}, ...]}
    """
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        today = _user_today(getattr(user, "timezone", None))
        since = today - timedelta(days=_STREAK_LOOKBACK)
        supps = await _active_supplements(db, user.id)
        out = []
        for a in supps:
            taken = await _intake_dates(db, user.id, a.attribute_key, since)
            out.append(_supplement_dict(a, today, taken))
    return {"supplements": out}


class ToggleBody(BaseModel):
    key: str


@router.post("/supplements/toggle")
async def toggle_supplement(body: ToggleBody, identity: str = Depends(current_identity)):
    """Flip today's "taken" state for one supplement. Idempotent per day."""
    if not _is_real_supplement(body.key):
        raise HTTPException(status_code=422, detail="not a trackable supplement")
    async with AsyncSessionLocal() as db:
        user = await resolve_user(db, identity)
        today = _user_today(getattr(user, "timezone", None))
        existing = (await db.execute(
            select(SupplementIntake).where(and_(
                SupplementIntake.user_id == user.id,
                SupplementIntake.supplement_key == body.key,
                SupplementIntake.intake_date == today,
            ))
        )).scalars().first()

        if existing is not None:
            await db.execute(delete(SupplementIntake).where(SupplementIntake.id == existing.id))
            await db.commit()
        else:
            # snapshot the current display name for history
            attr = (await db.execute(
                select(UserAttribute).where(and_(
                    UserAttribute.user_id == user.id,
                    UserAttribute.attribute_key == body.key,
                ))
            )).scalars().first()
            db.add(SupplementIntake(
                user_id=user.id, supplement_key=body.key,
                supplement_name=(attr.display_name if attr else None),
                intake_date=today,
            ))
            await db.commit()

        # return the refreshed single-supplement state
        since = today - timedelta(days=_STREAK_LOOKBACK)
        taken = await _intake_dates(db, user.id, body.key, since)
    return {"key": body.key, "taken_today": today in taken, "streak": _streak_to(today, taken)}
