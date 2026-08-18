"""⭐ WHAT THE FOOD INTERPRETER IS HANDED — one definition, both lanes.

MEASURED IN PRODUCTION 2026-08-18 (the B-1.8 canary, user 26, turn
ios:4DB2A7D6): "actually the grilled chicken breast was 8 oz" reached the
NATIVE lane, `FoodPlanStage` called the interpreter with

    board=None  day_line=""  last_assistant=""  regulars=None  thread_active=False

because `build_request` never put any of them on the request — the legacy
`run_turn` computes all five inline (~conversation.py 1355-1650) and the
native stage read keys nobody wrote. Blind to the board, the interpreter could
not name entry 3026, produced ZERO operations, the coordinator delegated
(`native_no_plan`), legacy re-interpreted WITH its own board, emitted
update_food_entry(3026, "8 oz") under INFERRED_INTERPRETATION, and the
ownership firewall refused it (ledger event 2105, mutation_rejected). The
correction lane B-1.8 built and proved never received an op, and the user was
told the board had "shifted".

So the planner's inputs are computed HERE, from the same handles legacy uses
(today's log, the user, the thread), and `FoodPlanStage` calls this when the
request does not already carry them. The shapes are legacy's exactly — the
board rows carry id / food / qty / mins_ago / cal — because the interpreter
prompt reads those keys, and a native board that named them differently would
be another blind spot with a nicer origin story.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def board_for(today_log) -> list:
    """Today's board as the interpreter reads it: one dict per committed row
    with its REAL entry id, so a correction ("actually 8 oz") can name the row
    it corrects and a repeat can be recognised as one."""
    out = []
    try:
        from core import clock as _clock
        now = _clock.now()
        for fe in (getattr(today_log, "food_entries", None) or []):
            if getattr(fe, "id", None) is None:
                continue
            age = None
            ts = getattr(fe, "timestamp", None)
            if ts is not None:
                try:
                    age = max(0, int((now - ts).total_seconds() // 60))
                except Exception:               # noqa: BLE001 — tz-naive mix
                    age = None
            out.append({"id": fe.id,
                        "food": getattr(fe, "parsed_food_name", "") or "",
                        "qty": getattr(fe, "quantity", "") or "",
                        "mins_ago": age,
                        "cal": getattr(fe, "calories", 0) or 0})
    except Exception:                            # noqa: BLE001
        logger.warning("planner board could not be built", exc_info=True)
        return []
    return out


def minutes_since_last_write(today_log) -> Optional[float]:
    try:
        from core import clock as _clock
        latest = max((getattr(fe, "timestamp", None)
                      for fe in (getattr(today_log, "food_entries", None) or [])
                      if getattr(fe, "timestamp", None) is not None),
                     default=None)
        if latest is None:
            return None
        return (_clock.now() - latest).total_seconds() / 60.0
    except Exception:                            # noqa: BLE001
        return None


def day_line_for(today_log, user) -> str:
    """The one sentence of day context the interpreter's own coach line uses."""
    try:
        p = getattr(user, "preferences", None)
        if today_log is None or p is None:
            return ""
        return (f"before this meal they were at "
                f"{int(today_log.total_calories or 0)} of "
                f"{int(getattr(p, 'calorie_target', 0) or 0)} cal and "
                f"{int(today_log.total_protein or 0)} of "
                f"{int(getattr(p, 'protein_target', 0) or 0)}g protein.")
    except Exception:                            # noqa: BLE001
        return ""


def last_assistant_of(messages) -> str:
    try:
        return next((m.get("content", "") for m in reversed(messages or ())
                     if m.get("role") == "assistant"
                     and isinstance(m.get("content"), str)), "")
    except Exception:                            # noqa: BLE001
        return ""


def thread_is_active(text: str, today_log, *, has_pending: bool) -> bool:
    """Legacy's `_route_mid`: is this message continuing a food thread —
    a correction seconds after a write, an answer to an open question?"""
    try:
        from core.food_turn import thread_relevance
        return bool(thread_relevance(text or "", minutes_since_last_write(today_log),
                                     bool(has_pending)))
    except Exception:                            # noqa: BLE001
        return False


async def regulars_for(db, user_id) -> list:
    if db is None or not user_id:
        return []
    try:
        from db.queries import frequent_foods
        return list(await frequent_foods(db, int(user_id)) or [])
    except Exception:                            # noqa: BLE001
        return []


async def planner_inputs(*, text: str, db, user, today_log, messages=None,
                         has_pending: bool = False) -> dict:
    """Everything the interpreter is handed, computed once, from the handles
    every turn already carries. Keys match `core.food_turn.run` kwargs."""
    return {
        "board": board_for(today_log),
        "day_line": day_line_for(today_log, user),
        "last_assistant": last_assistant_of(messages),
        "regulars": await regulars_for(db, getattr(user, "id", None)),
        "thread_active": thread_is_active(text, today_log, has_pending=has_pending),
    }
