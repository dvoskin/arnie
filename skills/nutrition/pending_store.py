"""Pending clarification state: expiry and concurrency (build order 17, 18).

A held meal is state that outlives its turn, which makes it subject to the two
problems all such state has.

**It goes stale.** "Which Fairlife was it?" answered twenty minutes later is a
live answer. Answered tomorrow morning, it is an answer about yesterday's food,
and applying it silently to today is a wrong-day write nobody asked for. So
there are three windows, not one:

    active       ~2 hours — binds a bare answer with no confirmation
    recoverable  until the end of the logging day — binds, but says which meal
    stale        after day rollover — never applied silently; confirm first

The logical meal DATE is stored alongside the timestamps, because "yesterday's
bagel" is a question about the meal's date, not about how long the row has sat
there. A user in a different timezone crossing midnight is the normal case, not
the edge case.

**It races.** "Elite" and "half bottle" sent two seconds apart both target the
same pending row, and without a guard both apply, or worse, both commit. So the
row carries a version and a status, and consuming it is a compare-and-swap:
exactly one caller wins, and the loser is told it lost rather than silently
proceeding.

This module is pure — no DB. The store adapter is at the bottom and is
deliberately thin, so the expiry and CAS rules are testable without a database
and cannot drift between the two.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any, Mapping, Optional

#: Answers arriving inside this window bind with no ceremony.
ACTIVE_WINDOW = timedelta(hours=2)

PENDING_KIND = "food_meal_clarification"
STATE_VERSION = "pending_meal_v1"


class PendingStatus(str, Enum):
    ACTIVE = "active"
    CONSUMED = "consumed"       # an answer was applied; the row is spent
    CANCELLED = "cancelled"     # the user dropped it
    EXPIRED = "expired"         # aged out without an answer

    @property
    def is_open(self) -> bool:
        return self is PendingStatus.ACTIVE


class Freshness(str, Enum):
    ACTIVE = "active"
    RECOVERABLE = "recoverable"
    STALE = "stale"

    @property
    def binds_silently(self) -> bool:
        """Whether an answer may be applied without saying which meal it is
        about. Only the active window earns that."""
        return self is Freshness.ACTIVE

    @property
    def needs_confirmation(self) -> bool:
        return self is Freshness.STALE


class ConcurrencyLost(RuntimeError):
    """Another message already consumed this pending state. The caller must
    NOT proceed — proceeding is the double-write this exists to prevent."""


@dataclass(frozen=True)
class PendingClarification:
    """One held meal awaiting an answer.

    `version` and `status` together are the concurrency guard; `logical_meal_date`
    and `created_at` together are the staleness guard. Both pairs are stored
    rather than derived, because deriving either from the other loses the case
    that matters — a late answer about an early meal.
    """
    clarification_id: str
    user_id: int
    meal_group_id: str
    logical_meal_date: date
    created_at: datetime
    question_ids: tuple = ()
    held_item_ids: tuple = ()
    requested_fields: Mapping[str, tuple] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    version: int = 1
    status: PendingStatus = PendingStatus.ACTIVE
    attempt_count: int = 0
    turn_id: str = ""
    state_version: str = STATE_VERSION

    # ── staleness ─────────────────────────────────────────────────────────────
    def freshness(self, now: datetime, *, day_start_hour: int = 0) -> Freshness:
        """Which window this answer is arriving in.

        Day rollover is checked BEFORE the elapsed window: an answer at 00:30
        about a 23:50 meal is forty minutes old and still about yesterday.
        Elapsed time alone would call that fresh and write it to the wrong day.
        """
        if _logical_date(now, day_start_hour) != self.logical_meal_date:
            return Freshness.STALE
        if now - self.created_at <= ACTIVE_WINDOW:
            return Freshness.ACTIVE
        return Freshness.RECOVERABLE

    def is_answerable(self, now: datetime, *,
                      day_start_hour: int = 0) -> bool:
        """Open, and not so old that applying it would be a guess. A stale row
        is still answerable — it just has to ask which meal first."""
        return self.status.is_open

    def expires_at(self, *, day_start_hour: int = 0) -> datetime:
        """End of the logging day. Past this the row is recoverable only with
        confirmation."""
        return datetime.combine(
            self.logical_meal_date + timedelta(days=1),
            time(hour=day_start_hour))

    def confirmation_prompt(self) -> str:
        label = self.payload.get("label") or "that"
        when = self.logical_meal_date.strftime("%A")
        return f"Was that for {when}'s {label}?"

    # ── concurrency ───────────────────────────────────────────────────────────
    def consume(self, *, expected_version: int,
                status: PendingStatus = PendingStatus.CONSUMED
                ) -> "PendingClarification":
        """Local staleness guard — NOT the atomic one.

        This rejects an answer written against a version this row has already
        moved past, and an answer to a row that is already closed. What it
        cannot do is arbitrate a genuine race: two callers holding the same
        snapshot both see the same `self.version`, and a frozen value object has
        no way to know one of them already won.

        The authoritative guard is `claim()` below, which is a conditional
        UPDATE the database resolves. Use this for the cheap in-process check
        and claim() before doing anything that writes.

        Raises rather than returning a flag, because the failure mode of a
        missed check is a double commit — the caller should have to handle it
        explicitly rather than remember to read a boolean.
        """
        if not self.status.is_open:
            raise ConcurrencyLost(
                f"{self.clarification_id} already {self.status.value}")
        if expected_version != self.version:
            raise ConcurrencyLost(
                f"{self.clarification_id} moved from v{expected_version} "
                f"to v{self.version}")
        return replace(self, status=status, version=self.version + 1)

    def with_attempt(self) -> "PendingClarification":
        """Another round asked. Bumps the version too, so a stale in-flight
        answer from before the re-ask cannot land."""
        return replace(self, attempt_count=self.attempt_count + 1,
                       version=self.version + 1)

    def partially_answered(self, filled_fields: Mapping[str, Any],
                           *, expected_version: int) -> "PendingClarification":
        """Some fields landed but the row stays open — "Elite" without a
        portion. Still a CAS: the version moves, so a second message racing the
        first is rejected rather than applied twice."""
        if not self.status.is_open:
            raise ConcurrencyLost(
                f"{self.clarification_id} already {self.status.value}")
        if expected_version != self.version:
            raise ConcurrencyLost(
                f"{self.clarification_id} moved from v{expected_version} "
                f"to v{self.version}")
        merged = dict(self.payload or {})
        merged.setdefault("answered", {})
        merged["answered"] = {**merged["answered"], **dict(filled_fields)}
        return replace(self, payload=merged, version=self.version + 1)

    # ── persistence ───────────────────────────────────────────────────────────
    def to_payload(self) -> str:
        return json.dumps({
            "kind": "meal",
            "state_version": self.state_version,
            "clarification_id": self.clarification_id,
            "meal_group_id": self.meal_group_id,
            "logical_meal_date": self.logical_meal_date.isoformat(),
            "created_at": self.created_at.isoformat(),
            "question_ids": list(self.question_ids),
            "held_item_ids": list(self.held_item_ids),
            "requested_fields": {k: list(v) for k, v
                                 in (self.requested_fields or {}).items()},
            "payload": dict(self.payload or {}),
            "version": self.version,
            "status": self.status.value,
            "attempt_count": self.attempt_count,
            "turn_id": self.turn_id,
        })


def from_payload(raw, *, user_id: int = 0) -> Optional[PendingClarification]:
    """Parse a stored row. Returns None for anything that is not a meal
    clarification, so the entity-bound nutrient kind and the plan-confirm kind
    can never be mistaken for one."""
    try:
        data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("kind") != "meal":
        return None
    try:
        return PendingClarification(
            clarification_id=str(data.get("clarification_id") or ""),
            user_id=user_id,
            meal_group_id=str(data.get("meal_group_id") or ""),
            logical_meal_date=date.fromisoformat(data["logical_meal_date"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            question_ids=tuple(data.get("question_ids") or ()),
            held_item_ids=tuple(data.get("held_item_ids") or ()),
            requested_fields={k: tuple(v) for k, v
                              in (data.get("requested_fields") or {}).items()},
            payload=dict(data.get("payload") or {}),
            version=int(data.get("version") or 1),
            status=PendingStatus(data.get("status") or "active"),
            attempt_count=int(data.get("attempt_count") or 0),
            turn_id=str(data.get("turn_id") or ""),
            state_version=str(data.get("state_version") or STATE_VERSION))
    except (KeyError, ValueError, TypeError):
        return None


def make_clarification_id(user_id: int, meal_group_id: str,
                          turn_id: str = "") -> str:
    digest = hashlib.sha1(
        f"{user_id}|{meal_group_id}|{turn_id}".encode("utf-8")).hexdigest()[:12]
    return f"clarify_{digest}"


def open_clarification(*, user_id: int, meal_group_id: str, now: datetime,
                       resolution=None, questions=(), turn_id: str = "",
                       day_start_hour: int = 0,
                       label: str = "") -> PendingClarification:
    """Build the pending row for a meal that ended with held items."""
    held = tuple(p.staged_item_id for p in getattr(resolution, "pending", ())
                 ) if resolution is not None else ()
    return PendingClarification(
        clarification_id=make_clarification_id(user_id, meal_group_id, turn_id),
        user_id=user_id, meal_group_id=meal_group_id,
        logical_meal_date=_logical_date(now, day_start_hour), created_at=now,
        question_ids=tuple(q.question_id for q in questions),
        held_item_ids=held,
        requested_fields={q.question_id: tuple(q.requested_fields)
                          for q in questions},
        payload={"label": label} if label else {},
        turn_id=turn_id)


def _logical_date(moment: datetime, day_start_hour: int = 0) -> date:
    """The logging day a moment belongs to. A non-zero start hour lets a 1am
    snack count as the previous day, which is what users mean."""
    if day_start_hour and moment.hour < day_start_hour:
        return (moment - timedelta(days=1)).date()
    return moment.date()


# ── the DB adapter ────────────────────────────────────────────────────────────
async def load_open(db, user_id: int) -> Optional[PendingClarification]:
    """The newest open meal clarification for this user, or None. Never
    raises — a missing pending row means a cold turn, not a failure."""
    try:
        from db.queries import get_open_pending_question
        row = await get_open_pending_question(db, user_id, PENDING_KIND)
        if row is None:
            return None
        return from_payload(row.payload_json, user_id=user_id)
    except Exception:
        return None


async def save(db, pending: PendingClarification) -> bool:
    """Persist the row. Returns False rather than raising when the write is
    unavailable — losing a clarification is recoverable; failing the turn that
    produced it is not."""
    try:
        from db.queries import record_pending_question
        row = await record_pending_question(
            db, pending.user_id, kind=PENDING_KIND,
            question=(pending.payload or {}).get("label", "") or "clarify",
            tier="casual", hook_style="question")
        row.payload_json = pending.to_payload()
        row.item_referenced = pending.meal_group_id
        await db.commit()
        return True
    except Exception:
        return False


async def claim(db, pending: PendingClarification) -> bool:
    """THE atomic guard. True for exactly one caller.

    Two messages arriving two seconds apart both read an open row and both hold
    a snapshot at the same version — no amount of in-process checking can
    arbitrate that, because both snapshots are equally valid until one of them
    writes. So the decision is a single conditional UPDATE and the database
    resolves it:

        UPDATE pending_questions SET answered_at = now()
        WHERE id = :id AND answered_at IS NULL

    `answered_at IS NULL` is the guard rather than a version column because it
    is the column the existing schema already makes atomic. Exactly one caller
    sees rowcount 1; everyone else sees 0 and must not proceed.

    Returns False when the claim is lost OR when it cannot be attempted — a
    caller that cannot prove it won must behave as though it lost.
    """
    try:
        from sqlalchemy import update
        from db.models import PendingQuestion
        result = await db.execute(
            update(PendingQuestion)
            .where(PendingQuestion.user_id == pending.user_id,
                   PendingQuestion.kind == PENDING_KIND,
                   PendingQuestion.item_referenced == pending.meal_group_id,
                   PendingQuestion.answered_at.is_(None))
            .values(answered_at=datetime.utcnow(),
                    payload_json=replace(
                        pending, status=PendingStatus.CONSUMED,
                        version=pending.version + 1).to_payload()))
        await db.commit()
        return (result.rowcount or 0) == 1
    except Exception:
        return False


async def close(db, pending: PendingClarification,
                status: PendingStatus = PendingStatus.CONSUMED) -> bool:
    """Mark the row answered/cancelled/expired. Best effort."""
    try:
        from db.queries import get_open_pending_question
        row = await get_open_pending_question(db, pending.user_id, PENDING_KIND)
        if row is None:
            return False
        row.payload_json = replace(pending, status=status).to_payload()
        row.answered_at = datetime.utcnow()
        await db.commit()
        return True
    except Exception:
        return False
