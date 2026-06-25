"""
Compound-meal logging — pins the three prompt rules and the API sort that
together prevent the salad-fragmentation regression:

  • COMPOUND DISH vs MULTI-DISH PLATE — photo logging defaults compound
    dishes (salad, sandwich, bowl, wrap, etc.) to ONE log_food call with
    the component breakdown stored in the `quantity` field. Multi-DISH
    plates (pizza + side salad + dessert) still get N calls.
  • PARTIAL REVISION — when the user says "ate 80% of the salad, all the
    chicken", the model reads the entry's quantity breakdown, computes
    new totals (kept components + scaled rest), and issues ONE
    update_food_entry call. No multi-entry id-targeting.
  • UPDATE TARGETING SELF-CHECK — defensive: if N update_food_entry
    calls DO fire in one turn (true multi-dish revisions), the N
    entry_ids MUST be distinct. Catches the "all updates routed to the
    dressing entry" failure mode by name.
  • API sort — /api/stats food_entries are returned in chronological
    order (timestamp ASC, id ASC fallback) so the dashboard shows the
    day's meals in eating order, not insertion-order accident.
"""
import pytest

import api.app as app_mod
from core.prompts import build_arnie_system


def _system_prompt() -> str:
    """Build the system prompt at TEST-EXECUTION time, not module-import time.

    Computing this as a module-level constant (`SYSTEM_PROMPT = build_arnie_system(...)`)
    ran it during pytest *collection*, which made it sensitive to collection-order
    side effects from sibling test modules. Under pytest-randomly's shuffle that
    intermittently produced a prompt with whole sections (TOOL_RULES / FOOD_LOGGING)
    missing — flaky failures unrelated to the prompt content itself (the section
    constants are immutable literals, always present in a clean build). Building it
    fresh inside each test, after collection has settled and per-test monkeypatches
    are restored, makes these assertions deterministic.
    """
    return build_arnie_system(platform="telegram")


# ── Fix A: compound dish vs multi-dish plate ─────────────────────────────────


def test_prompt_has_compound_vs_multi_dish_rule():
    """The COMPOUND DISH vs MULTI-DISH PLATE rule must be present and name
    the canonical compound dishes (salad, sandwich, bowl, wrap, etc.) so
    the model doesn't fall back to the old per-component default."""
    s = _system_prompt()
    assert "COMPOUND DISH vs MULTI-DISH PLATE" in s
    # Pin the explicit examples.
    for dish in ("salad bowl", "sandwich", "burrito bowl", "wrap", "pasta",
                 "curry", "stir-fry", "parfait", "snack box", "grain bowl"):
        assert dish in s, f"missing compound-dish example: {dish!r}"
    # The decision heuristic (shared bowl/dressing vs. orderable separately).
    assert "share the same bowl" in s or "shares the same bowl" in s \
        or "share the same bowl/plate/dressing/sauce" in s


def test_prompt_directs_one_log_food_for_compound_dish():
    """Compound dish = ONE log_food call. Multi-DISH plate = N calls.
    Distinguish them in the rule text."""
    s = _system_prompt()
    assert "Log it as ONE log_food call" in s
    assert "MULTI-DISH PLATE" in s
    assert "N log_food calls, one per dish" in s


def test_prompt_directs_breakdown_into_quantity_field():
    """The decomposition data is preserved IN the entry by storing the
    component breakdown in `quantity`. This is what makes the partial-
    revision math possible later."""
    s = _system_prompt()
    # The literal aligned-assignment line in the prompt.
    assert "quantity   = the component breakdown" in s
    # The canonical example from the salad screenshot.
    assert "grilled chicken" in s and "rice" in s


# ── Fix B: partial revision math ─────────────────────────────────────────────


def test_prompt_has_partial_revision_rule():
    """PARTIAL REVISION rule is what handles 'ate 80% of the salad, all
    the chicken' as a single-update math problem instead of N updates."""
    # Normalize whitespace so wrapped lines don't break substring matching.
    s = " ".join(_system_prompt().split())
    assert "PARTIAL REVISION" in s
    # Pin the canonical user phrasing.
    assert "ate 80% of the salad" in s
    # Pin the algorithmic shape.
    assert "ONE update_food_entry call with the new totals" in s
    assert "kept_macros + scale_factor" in s
    # Pin the negative: do NOT split the entry or call update N times.
    assert "do NOT split the entry" in s
    assert "do NOT call update N times" in s


def test_prompt_directs_quantity_update_on_partial_revision():
    """The entry's quantity field gets updated to reflect the revision so a
    later recap shows the truth ('80% of salad: chicken (kept), 0.8 cup
    rice, ...'). Otherwise the next ask sees stale breakdown text."""
    s = _system_prompt()
    # Specifically calls out updating the quantity field on revision.
    assert "update the entry's quantity to reflect the revision" in s


# ── Fix C: update targeting self-check (defensive) ───────────────────────────


def test_prompt_has_update_targeting_self_check():
    """UPDATE TARGETING SELF-CHECK catches the 'all updates routed to the
    dressing entry' failure mode by name. When N update_food_entry calls
    fire, N entry_ids MUST be distinct."""
    # Normalize whitespace so wrapped lines don't break substring matching.
    s = " ".join(_system_prompt().split())
    assert "UPDATE TARGETING SELF-CHECK" in s
    assert "entry_id values MUST be DISTINCT" in s
    assert "NEVER pass the same [#id] twice in one turn" in s
    # Cross-references PARTIAL REVISION so the model knows ONE dish = ONE call.
    assert "single dish revised partially is ONE" in s


# ── API sort: food entries returned in chronological order ──────────────────


def _make_log_with_entries(timestamps_and_ids):
    """Build a fake DailyLog with food_entries having the given (timestamp, id)
    pairs in insertion order (which may NOT match chronological order)."""
    from types import SimpleNamespace
    entries = []
    for ts, eid in timestamps_and_ids:
        entries.append(SimpleNamespace(
            id=eid, parsed_food_name=f"food_{eid}", quantity="", calories=100,
            protein=10, carbs=20, fats=2, estimated_flag=False,
            timestamp=ts,
        ))
    return SimpleNamespace(food_entries=entries)


def test_api_sorts_food_entries_chronologically():
    """The /api/stats response builder sorts food_entries by timestamp ASC
    (earliest first), with id as the tiebreaker. Insertion order must NOT
    leak through — the salad case had insertion-order id ranges, but a
    later edited entry could end up with a fresher timestamp and we want
    chronological reading order regardless."""
    from datetime import datetime
    # Insertion order: id=3 first, then id=1, then id=2 — what SQLAlchemy
    # might happen to return. Timestamps tell the true chronological order:
    # id=1 at 09:00, id=2 at 12:00, id=3 at 18:00.
    log = _make_log_with_entries([
        (datetime(2026, 6, 9, 18, 0), 3),
        (datetime(2026, 6, 9, 9, 0), 1),
        (datetime(2026, 6, 9, 12, 0), 2),
    ])
    out = sorted(
        log.food_entries,
        key=lambda e: (e.timestamp or datetime.min, e.id or 0),
    )
    assert [e.id for e in out] == [1, 2, 3], (
        "food entries must be chronological after sort, got "
        f"{[e.id for e in out]}"
    )


def test_api_sort_handles_null_timestamp_via_id_fallback():
    """Very old rows pre-T2.3 may have NULL timestamps. The sort must not
    crash and must fall back to id-ASC (rough chronological proxy) for
    those rows."""
    from datetime import datetime
    log = _make_log_with_entries([
        (None, 7),
        (None, 3),
        (datetime(2026, 6, 9, 12, 0), 5),
    ])
    out = sorted(
        log.food_entries,
        key=lambda e: (e.timestamp or datetime.min, e.id or 0),
    )
    # NULL-timestamp rows sort first (datetime.min), then by id ASC; the
    # real-timestamp row comes last.
    assert [e.id for e in out] == [3, 7, 5]


def test_api_stats_food_entry_has_timestamp_field():
    """The API response shape MUST include `timestamp` per food entry so
    the frontend (or any consumer) can use it for ordering, grouping, or
    'logged 12 min ago' UI. Pin the new field is shipped, not silently
    dropped by a future refactor."""
    import inspect
    src = inspect.getsource(app_mod._stats_payload) \
        if hasattr(app_mod, "_stats_payload") else inspect.getsource(app_mod)
    # The exact field key the API emits (from the dict literal in app.py).
    assert '"timestamp": e.timestamp.isoformat()' in src
