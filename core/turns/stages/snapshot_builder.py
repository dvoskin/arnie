"""The universal committed snapshot (P0.2 Phase 4, review step 3).

One rule: everything downstream of a write — narration, the card, the iOS
payload, the coaching question — reads from THIS, and only this.

The food lane already proved the shape (core.food_ledger.TransactionSnapshot):
render from the committed database state, never from the plan's own numbers,
because enrichment moves them and a refused write moves them further. This
generalizes that across every domain the ledger covers — food, exercise,
water, weight — so a fitness turn gets the same guarantee a food turn does.

What makes it universal rather than food-with-extra-fields:
  • totals are read back after commit, per domain, from the day row;
  • affected entities are reported per domain with the action that touched
    them, so a renderer never has to infer "what changed" from call names;
  • day_revision is a monotonic token, so a card can be detected as stale;
  • remaining targets are computed once, here, instead of in each renderer.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.turns.models import TurnSnapshot

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = "turn_snapshot_v1"

#: Which domain a tool call touches. The renderer must never re-derive this
#: from a name prefix — a rename would silently reclassify the write.
_CALL_DOMAINS = {
    "log_food": ("food", "created"),
    "update_food_entry": ("food", "updated"),
    "delete_food_entry": ("food", "deleted"),
    "restore_food_entry": ("food", "created"),
    "log_exercise": ("exercise", "created"),
    "update_exercise_entry": ("exercise", "updated"),
    "delete_exercise_entry": ("exercise", "deleted"),
    "restore_exercise_entry": ("exercise", "created"),
    "log_water": ("water", "created"),
    "delete_water_entry": ("water", "deleted"),
    "log_weight": ("weight", "created"),
}


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def day_totals(log) -> dict:
    """Committed totals for the day, every domain. Absent columns read 0
    rather than going missing, so a renderer can rely on the keys."""
    if log is None:
        return {}
    out = {
        "calories": _num(getattr(log, "total_calories", 0)),
        "protein": _num(getattr(log, "total_protein", 0)),
        "carbs": _num(getattr(log, "total_carbs", 0)),
        "fats": _num(getattr(log, "total_fats", 0)),
        "water_ml": _num(getattr(log, "total_water_ml", 0)),
        "steps": _num(getattr(log, "total_steps", 0)),
    }
    try:
        out["calories_burned"] = float(sum(
            _num(getattr(e, "calories_burned_estimate", 0))
            for e in (getattr(log, "exercise_entries", None) or [])))
    except Exception:
        out["calories_burned"] = 0.0
    return out


def remaining_targets(prefs, totals: dict) -> dict:
    """What's left today. Never negative — "you're 200 over" is the coach's
    line to write, not a negative number for a progress ring to render. A
    target the user has not set is simply absent, which is different from
    zero remaining."""
    out = {}
    for key, attr in (("calories", "calorie_target"), ("protein", "protein_target"),
                      ("carbs", "carb_target"), ("fats", "fat_target")):
        target = getattr(prefs, attr, None) if prefs is not None else None
        if target in (None, 0):
            continue
        out[key] = max(0.0, float(target) - _num(totals.get(key)))
    return out


def _preferences(user):
    """Targets, if they are already loaded. Touching an unloaded relationship
    from async code raises MissingGreenlet, and a snapshot must never be the
    thing that fails a turn — a missing target simply omits that target."""
    if user is None:
        return None
    try:
        return user.preferences
    except Exception:
        return None


def affected_entities(execution) -> tuple:
    """What this turn actually changed, per domain — SUCCESSFUL calls only.
    A dedup-blocked log or a refused CAS update did not affect anything, and
    must not appear here or the card will show a row that isn't in the day."""
    out = []
    for call in (getattr(execution, "calls", None) or ()):
        if not getattr(call, "committed", False):
            continue
        mapped = _CALL_DOMAINS.get(getattr(call, "name", ""))
        if mapped is None:
            continue
        domain, action = mapped
        out.append({"domain": domain, "action": action,
                    "entry_id": getattr(call, "entry_id", None),
                    "event_id": getattr(call, "event_id", None)})
    return tuple(out)


class CommittedSnapshotStage:
    """Builds the one snapshot every renderer reads. Reads back committed
    state rather than trusting the plan; degrades to the execution-only
    snapshot if the day row is unavailable, never to invented numbers."""

    async def run(self, request, execution=None) -> TurnSnapshot:
        meta = request.metadata or {}
        log = meta.get("today_log")
        db, user = meta.get("db"), meta.get("user")

        entities = affected_entities(execution)
        event_ids = tuple(e["event_id"] for e in entities
                          if e.get("event_id") is not None)
        totals = day_totals(log)
        targets = remaining_targets(_preferences(user), totals) if totals else {}

        revision: Optional[int] = None
        if db is not None and user is not None:
            try:
                from datetime import datetime, time as _time
                from db.queries import ledger_revision
                day = getattr(log, "date", None)
                since = datetime.combine(day, _time.min) if day else None
                revision = await ledger_revision(db, user.id, since)
            except Exception as e:
                logger.debug(f"day revision unavailable: {e}")

        return TurnSnapshot(
            turn_id=request.turn_id,
            execution=execution,
            affected_entities=entities,
            ledger_event_ids=event_ids,
            day_revision=revision,
            day_totals=totals or None,
            remaining_targets=targets or None,
            snapshot_version=SNAPSHOT_VERSION)
