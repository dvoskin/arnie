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

#: Compared on both the meal and the day. Calories alone would miss a lane that
#: prices energy correctly and splits the macros wrong — which is most of the
#: ways a resolver can be subtly incorrect.
_MACROS = ("calories", "protein", "carbs", "fats")


# Operation identity lives with the writer now — it outlives the shadow phase.
from core.canonical_writer import DirectOperation, operation_id_for  # noqa: F401,E402


def shadow_enabled() -> bool:
    return (os.getenv("CANONICAL_WRITER_SHADOW", "false") or "").strip().lower() \
        in ("1", "true", "yes", "on")





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

    legacy_meal = legacy.get("totals", {}) or {}
    for key in _MACROS:
        a = round(float(result.meal_totals.get(key, 0.0)), 1)
        b = round(float(legacy_meal.get(key, 0.0) or 0.0), 1)
        if abs(a - b) > 0.5:
            out.append(f"{key} {a} != {b}")

    # THE SHADOW IS ADDITIVE, AND RUNS AFTER THE LEGACY ROW COMMITTED.
    #
    # `_day_totals` reads the log, which `recompute_log_totals` derives from
    # every entry — so at this moment the day contains BOTH the legacy row and
    # the canonical copy of it, and a raw comparison reports a divergence
    # exactly equal to the shadow meal on every single tap. Measured before
    # fixing: 1440 vs 1120 on a day that started at 800.
    #
    # Removing the legacy meal asks the question that was actually intended:
    # what would the day be if the canonical row REPLACED the one already
    # committed? Equivalently, D_before + canonical_meal vs D_before +
    # legacy_meal.
    #
    # Note the symmetric-looking alternative does NOT work here — subtracting
    # each side's own meal leaves `D_before + legacy_meal` against `D_before`,
    # because the canonical baseline already contains the legacy row. That is a
    # consequence of shadowing after the authoritative write, which is itself
    # deliberate: running first would put the shadow between the user and their
    # own commit.
    legacy_day = legacy.get("day_totals") or {}
    for key in _MACROS:
        if key not in legacy_day:
            continue
        expected = round(float(result.day_totals.get(key, 0.0))
                         - float(legacy_meal.get(key, 0.0) or 0.0), 1)
        actual = round(float(legacy_day.get(key) or 0.0), 1)
        if abs(expected - actual) > 0.5:
            out.append(f"day_{key} {expected} != {actual}")
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
                    db, operation=DirectOperation(meal), resolved_meal=meal,
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
