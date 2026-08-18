"""Deterministic conversational undo/restore on the event ledger
(FOOD_LEDGER_V2 Phase 2, Danny 2026-07-24: "implement instant undo
everywhere" / "undo/delete: deterministic and immediate").

"Undo" / "bring back the fries" is a LEDGER operation with a known inverse —
no model call, no interpretation risk. The last event (or a name-matched
deleted event) is inverted into ordinary executor tool calls:

    created  → delete the entry
    updated  → write the event's captured `before` state back
    deleted  → restore the entry from the event's payload (restore_* branch)

The plan feeds the SAME structured pipeline as the interpreter (execution,
snapshot, renderer), so cards, totals, history — a restore appends its own
created event — and narration stay consistent. Domains: food and exercise
(the ones with full mutation branches); water/weight events are not yet
invertible, and an uninvertible LAST event refuses rather than skipping past
it — silently undoing the wrong thing is worse than handing the turn to the
conversational brain.

Bounded to recent events (default 12h; name-restores 24h): "undo" days later
is a conversation, not a reflex.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional
from core import clock

logger = logging.getLogger(__name__)

UNDO_SOURCE = "ledger_undo:v1"

_UNDO_RE = re.compile(
    r"^(?:undo|undo\s+(?:that|it|last|the\s+last\s+(?:one|log|entry)))[.!\s]*$",
    re.I)
_RESTORE_RE = re.compile(
    r"\b(?:bring\s+(?:back|it\s+back|that\s+back)|restore|re-?add|"
    r"put\s+(?:it|that)\s+back)\b", re.I)
_RESTORE_NAME_RE = re.compile(
    r"(?:bring\s+back|restore|re-?add)\s+(?:the\s+|my\s+)?([a-z0-9][\w\s%'-]{1,40}?)[.!?\s]*$",
    re.I)


def _undo_ttl_hours() -> float:
    return float(os.getenv("LEDGER_UNDO_TTL_H", "12"))


def _restore_ttl_hours() -> float:
    return float(os.getenv("LEDGER_RESTORE_TTL_H", "24"))


def detect(text: str) -> Optional[dict]:
    """Conservative shape detection. Returns {"kind": "undo"} for a bare undo,
    {"kind": "restore", "name": str|None} for a bring-back, else None."""
    t = (text or "").strip()
    if not t or len(t) > 120:
        return None
    if _UNDO_RE.match(t):
        return {"kind": "undo"}
    if _RESTORE_RE.search(t):
        m = _RESTORE_NAME_RE.search(t)
        name = (m.group(1).strip() if m else "") or None
        if name and name.lower() in ("it", "that", "them", "the last one"):
            name = None
        return {"kind": "restore", "name": name}
    return None


def _payload(event) -> dict:
    try:
        return json.loads(event.payload_json or "{}") or {}
    except Exception:
        return {}


def _fresh(event, hours: float) -> bool:
    ts = getattr(event, "created_at", None)
    if ts is None:
        return False
    try:
        return (clock.now() - ts) <= timedelta(hours=hours)
    except Exception:
        return False


_DAY_TAIL = "You're at {day_cal} with {cal_left} left and {protein_left}g protein to go."


def _invert(event) -> Optional[dict]:
    """One event → its inverse plan, or None when it has no safe inverse."""
    p = _payload(event)
    dom, etype = event.domain, event.event_type
    if dom == "food":
        name = p.get("food_name") or "that"
        if etype == "created" and event.entry_id:
            return {"action": "delete", "kinds": ["delete"],
                    "tool_calls": [{"name": "delete_food_entry",
                                    "input": {"entry_id": event.entry_id,
                                              "food_hint": name,
                                              "source": UNDO_SOURCE}}],
                    "say": f"Undone, took the {name} off the board. {_DAY_TAIL}"}
        if etype == "deleted":
            return _restore_plan(event)
        if etype == "updated" and event.entry_id and isinstance(p.get("before"), dict):
            before = p["before"]
            # ⭐ B-1.8d #4 — THE INVERSE NAMES THE EVENT IT UNDOES. A lock
            # serialises writers; it does not make an OLD inverse valid
            # against a NEWER row. The restore checks this id is still the
            # row's newest event, or refuses (StaleUndo) — so a tap on A's
            # card after correction B cannot silently erase B.
            inp = {"entry_id": event.entry_id, "source": UNDO_SOURCE,
                   "undoes_event_id": int(event.id)}
            # ⭐ B-1.8d — THE WHOLE BEFORE-STATE, IDENTITY INCLUDED *(review
            # #3)*. This restored quantity + four macros and nothing else, so
            # "chicken breast -> chicken thigh -> undo" left the THIGH's name
            # and receipt over the BREAST's macros: a hybrid row. The
            # before-state now carries the panel, the receipt and the row
            # metadata (see _entry_event_payload); every field it recorded is
            # restored, and a field it did NOT record is restored to None so
            # a value the correction ADDED (a new resolved_grams, a new
            # snapshot) does not survive its own undo. `food_name` maps back
            # to the row's column name at the executor.
            _RESTORABLE = ("food_name", "quantity", "calories", "protein",
                           "carbs", "fats", "fiber", "sugar", "sodium",
                           "micronutrients_json", "pricing_rung",
                           "nutrition_evidence_id", "source_basis",
                           "basis_evidence_id", "conversion_evidence_ids_json",
                           "source_amount", "source_unit", "scaling_factor",
                           "resolved_grams", "product_evidence_id",
                           "estimated_flag", "micros_estimated",
                           "alcohol_units", "processing_level")
            changed = set((p.get("changes") or {}).keys())
            for k in _RESTORABLE:
                if k in before:
                    inp[k] = before[k]
                elif k in changed or (k == "food_name"
                                      and "parsed_food_name" in changed):
                    # the correction SET a field the before-state lacked;
                    # undo must CLEAR it, not preserve the corrected value
                    inp[k] = None
            if len(inp) <= 2:
                return None
            hint = before.get("food_name") or "that"
            return {"action": "update", "kinds": ["update"],
                    "tool_calls": [{"name": "update_food_entry", "input": inp}],
                    "say": (f"Rolled the {hint} back to how it was. {_DAY_TAIL}")}
        return None
    if dom == "exercise":
        name = p.get("exercise_name") or "that"
        if etype == "created" and event.entry_id:
            return {"action": "delete", "kinds": ["delete"],
                    "tool_calls": [{"name": "delete_exercise_entry",
                                    "input": {"entry_id": event.entry_id,
                                              "source": UNDO_SOURCE}}],
                    "say": f"Undone, scratched the {name} from today."}
        if etype == "deleted" and p:
            return {"action": "commit", "kinds": ["log"],
                    "tool_calls": [{"name": "restore_exercise_entry",
                                    "input": {"payload": p,
                                              "exercise_name": name,
                                              "source": UNDO_SOURCE}}],
                    "say": f"The {name} is back on today's log."}
        if etype == "updated" and event.entry_id and isinstance(p.get("before"), dict):
            before = p["before"]
            # ⭐ B-1.8d #4 — THE INVERSE NAMES THE EVENT IT UNDOES. A lock
            # serialises writers; it does not make an OLD inverse valid
            # against a NEWER row. The restore checks this id is still the
            # row's newest event, or refuses (StaleUndo) — so a tap on A's
            # card after correction B cannot silently erase B.
            inp = {"entry_id": event.entry_id, "source": UNDO_SOURCE,
                   "undoes_event_id": int(event.id)}
            for k in ("sets", "reps", "weight", "duration_minutes"):
                if before.get(k) is not None:
                    inp[k] = before[k]
            if len(inp) <= 2:
                return None
            return {"action": "update", "kinds": ["update"],
                    "tool_calls": [{"name": "update_exercise_entry", "input": inp}],
                    "say": (f"Rolled the {before.get('exercise_name') or 'set'} "
                            f"back to how it was.")}
        return None
    if dom == "water":
        # A pour is undoable (delete the entry, totals recompute); weight
        # stays uninvertible for now — its per-day source upsert makes
        # delete-as-undo lossy without a captured before-state.
        if etype == "created" and event.entry_id:
            _ml = p.get("amount_ml")
            inp = {"entry_id": event.entry_id, "source": UNDO_SOURCE}
            if _ml is not None:
                inp["amount_ml"] = _ml
            return {"action": "delete", "kinds": ["delete"],
                    "tool_calls": [{"name": "delete_water_entry", "input": inp}],
                    "say": "Undone, took that water back off. Hydration total corrected."}
        return None
    return None


def _restore_plan(event) -> Optional[dict]:
    p = _payload(event)
    name = p.get("food_name")
    if not name:
        return None
    return {"action": "commit", "kinds": ["log"],
            "tool_calls": [{"name": "restore_food_entry",
                            "input": {"payload": p, "food_name": name,
                                      "source": UNDO_SOURCE}}],
            "say": (f"{name} is back on the board, {{batch_cal}} cal restored. "
                    + _DAY_TAIL)}


async def plan_for_event(db, user, event_id: int) -> Optional[dict]:
    """The inverse of ONE named event — the tap-to-undo backend.

    Every food macro_card already carries the `event_id` of the write behind
    it (`tool_executor` stashes it, `conversation._logged_entry_card` puts it
    on the payload), so the client can render "· Undo" against a specific
    write. Nothing accepted that token: the affordance shipped with no server
    side, which is why the card could offer an undo it could not perform.

    Deliberately the same `_invert` and the same TTLs as the conversational
    path. "Undo" typed and "Undo" tapped must reach the same inverse, or the
    two ways of taking something back drift into different behaviour — which
    is the failure this codebase keeps finding (one policy, two lanes).

    Differs from `build_plan` in ONE way, and it is the point: this targets
    the event the user pointed at, not the newest one. Tapping undo on the
    third card down must not silently reverse the most recent write instead.

    Returns None when the event is not theirs, too old, or has no safe
    inverse. Never raises.
    """
    try:
        from db.models import LedgerEvent
        event = await db.get(LedgerEvent, int(event_id))
        if event is None:
            return None
        # Ownership across the linked-account family, matching how every other
        # read resolves a user — a phone and a desktop login are one person.
        family = {user.id, getattr(user, "linked_to_user_id", None) or user.id}
        if event.user_id not in family:
            logger.warning("event=ledger_undo outcome=refused reason=not_owner "
                           "event=%s", event_id)
            return None
        ttl = (_restore_ttl_hours() if event.event_type == "deleted"
               else _undo_ttl_hours())
        if not _fresh(event, ttl):
            logger.info("event=ledger_undo outcome=expired event=%s", event_id)
            return None
        plan = _invert(event)
        if plan is None:
            logger.info("event=ledger_undo outcome=uninvertible domain=%s "
                        "type=%s", event.domain, event.event_type)
        return plan
    except Exception as e:
        logger.warning(f"ledger undo by event failed: {e}")
        return None


async def build_plan(db, user, text: str) -> Optional[dict]:
    """Detect an undo/restore shape and build its inverse plan from the event
    ledger. Returns an interpreter-shaped plan dict (action/tool_calls/say)
    that feeds the normal structured pipeline, or None (legacy path). Never
    raises."""
    shape = detect(text)
    if shape is None:
        return None
    try:
        from db.queries import get_ledger_events
        if shape["kind"] == "undo":
            events = await get_ledger_events(db, user.id, limit=8)
            # Undo the SPECIFIC last action, never a skipped-past one — except
            # that an undo's own bookkeeping (a restore's created event with
            # our source) points at the same logical action chain, which is
            # exactly what "undo" after an undo should target (redo semantics
            # fall out naturally).
            last = next(iter(events), None)
            if last is None or not _fresh(last, _undo_ttl_hours()):
                return None
            plan = _invert(last)
            if plan is None:
                logger.info(f"event=ledger_undo outcome=uninvertible "
                            f"domain={last.domain} type={last.event_type}")
            return plan
        # restore by (optional) name: newest deleted food event that matches.
        events = await get_ledger_events(db, user.id, domain="food", limit=25)
        name = (shape.get("name") or "").lower()
        for ev in events:
            if ev.event_type != "deleted" or not _fresh(ev, _restore_ttl_hours()):
                continue
            food = str(_payload(ev).get("food_name") or "").lower()
            if not name or name in food or food in name:
                return _restore_plan(ev)
        return None
    except Exception as e:
        logger.warning(f"ledger undo plan failed, legacy path: {e}")
        return None
