"""Run the canonical spine beside a legacy write, compare, throw it away.

The migration's first step for each mutation owner. The canonical path executes
FOR REAL — claim, write rows, record the result — inside a SAVEPOINT that is
always rolled back, so what is compared is what would actually have been
committed rather than a projection of it. A shadow that models the write
instead of performing it measures the model.

    legacy write (committed)
        │
        ├── shadow: claim -> write -> result   (savepoint)
        │              │
        │              └── compare -> log -> ROLLBACK
        ▼
    the request, unaffected

THE SHADOW MAY NEVER AFFECT THE REQUEST. Every failure inside is caught and
logged, including one that would be a genuine canonical bug: a user's tap must
not fail because the path being evaluated could not handle it. That is the
whole point of running it in shadow first, and it is also why the divergence
count matters more than the error count — an exception here is a finding, not
an outage.

Read the results with `event=canonical_shadow` via /admin/food-traces.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def shadow_enabled() -> bool:
    return (os.getenv("CANONICAL_WRITER_SHADOW", "false") or "").strip().lower() \
        in ("1", "true", "yes", "on")


class _Operation:
    """What the coordinator claims under. For a direct tap there is no pending
    operation, so the request's own turn is the operation — which is exactly
    what it is: one user action, one mutation, one revision."""

    def __init__(self, meal):
        self.id = meal.operation_id
        self.revision = meal.revision
        self.user_id = meal.user_id


def _divergences(result, legacy: dict) -> list:
    """What the canonical path would have written versus what legacy did.

    Compares the FACTS a user could notice — how many items, what they are
    called, what they cost — not the shape of the objects, which are meant to
    differ.
    """
    out = []
    got = list(result.committed_items)
    if len(got) != int(legacy.get("item_count", 0)):
        out.append(f"item_count {len(got)} != {legacy.get('item_count')}")

    names_a = sorted(str(i.get("name", "")).lower() for i in got)
    names_b = sorted(str(n).lower() for n in legacy.get("names", ()))
    if names_a != names_b:
        out.append(f"names {names_a} != {names_b}")

    for key in ("calories", "protein", "carbs", "fats"):
        a = round(float(result.meal_totals.get(key, 0.0)), 1)
        b = round(float(legacy.get("totals", {}).get(key, 0.0) or 0.0), 1)
        if abs(a - b) > 0.5:
            out.append(f"{key} {a} != {b}")

    a_day = round(float(result.day_totals.get("calories", 0.0)), 1)
    b_day = legacy.get("day_calories")
    if b_day is not None and abs(a_day - round(float(b_day), 1)) > 0.5:
        out.append(f"day_calories {a_day} != {b_day}")
    return out


async def compare_with_legacy(db, *, meal, legacy: dict,
                              lane: str = "quick_log") -> Optional[list]:
    """Execute the canonical spine in a savepoint and report the difference.

    Returns the divergence list (empty when they agree), or None if the shadow
    did not run. Never raises.
    """
    if not shadow_enabled():
        return None
    from core.commit_coordinator import commit_or_load_existing
    from core.canonical_writer import write_canonical_meal

    try:
        async with db.begin_nested() as savepoint:
            try:
                result = await commit_or_load_existing(
                    db, operation=_Operation(meal), resolved_meal=meal,
                    writer=write_canonical_meal)
                diffs = _divergences(result, legacy)
            finally:
                # ALWAYS. The rollback is not conditional on success, because
                # a partially written shadow left behind would be a phantom
                # meal on the user's board — the exact class of bug this
                # architecture exists to remove, introduced by its own test.
                await savepoint.rollback()
    except Exception as exc:
        logger.warning(
            "event=canonical_shadow lane=%s outcome=error operation=%s "
            "error=%s: %s — the legacy write is unaffected",
            lane, getattr(meal, "operation_id", "?"),
            type(exc).__name__, str(exc)[:200])
        return None

    if diffs:
        logger.warning(
            "event=canonical_shadow lane=%s outcome=diverged operation=%s "
            "diffs=%s", lane, meal.operation_id, "; ".join(diffs)[:400])
    else:
        logger.info(
            "event=canonical_shadow lane=%s outcome=agreed operation=%s "
            "items=%d", lane, meal.operation_id, len(meal.items))
    return diffs
