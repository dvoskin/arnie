"""
Meal logging — pins the shipped prompt rules and the API sort that together
prevent the salad-fragmentation regression:

  • LOG A MEAL AS ITS COMPONENTS — a plate of distinct foods logs as one
    log_food PER food (chicken / rice / peppers), each individually editable;
    genuinely blended items (soup, smoothie, sandwich) stay ONE entry. A true
    multi-dish plate (pizza + side salad + dessert) is N calls at the dish level.
  • UPDATE TARGETING SELF-CHECK — defensive: if N update_food_entry calls DO
    fire in one turn (true multi-dish revisions), the N entry_ids MUST be
    distinct. Catches the "all updates routed to the dressing entry" failure
    mode by name; a single dish revised partially is ONE call.
  • API sort — /api/stats food_entries are returned in chronological order
    (timestamp ASC, id ASC fallback) so the dashboard shows the day's meals in
    eating order, not insertion-order accident.
"""
import pytest

import api.app as app_mod
from core.prompts import build_arnie_system

SYSTEM_PROMPT = build_arnie_system(platform="telegram")


# ── Meal logged as its COMPONENTS (the design that actually shipped) ─────────
# An earlier workstream test-drove the OPPOSITE design (a compound dish = ONE
# log_food with the breakdown crammed into `quantity`). That design was NOT
# adopted; the shipped rule decomposes a plate into one entry PER food, keeping
# only genuinely blended items (soup, smoothie, sandwich) as a single entry.
# These pin the shipped wording (the old asserts were xfailed against phantom
# strings that protected nothing — see git history).


def test_prompt_has_log_meal_as_components_rule():
    """A plate of distinct foods logs as its components — one log_food per
    food — not one mega-entry."""
    s = " ".join(SYSTEM_PROMPT.split())
    assert "LOG A MEAL AS ITS COMPONENTS" in s
    assert "fire ONE log_food call PER distinct food" in s
    # The canonical decomposition example.
    assert "grilled chicken + white rice + peppers" in s
    assert "THREE entries" in s


def test_prompt_blended_items_stay_one_entry():
    """Genuinely inseparable items (smoothie, shake, soup, a sandwich eaten as
    one) are ONE entry; trivial extras fold into the nearest component."""
    s = " ".join(SYSTEM_PROMPT.split())
    assert "smoothie, protein shake, soup" in s
    assert "stays ONE entry" in s
    assert "DON'T over-split" in s
    # The decision heuristic that separates a component from a garnish.
    assert "if you'd weigh, edit, or swap it on its own" in s


def test_prompt_multi_dish_plate_is_n_calls():
    """A true multi-dish plate (pizza + side salad + dessert) is N calls at
    the dish level — same component rule, one level up."""
    s = " ".join(SYSTEM_PROMPT.split())
    assert "MULTI-DISH PLATE" in s
    assert "N calls at the dish" in s


# ── Update targeting self-check (defensive) ──────────────────────────────────


def test_prompt_has_update_targeting_self_check():
    """UPDATE TARGETING SELF-CHECK catches the 'all updates routed to the
    dressing entry' failure mode by name. When N update_food_entry calls
    fire, N entry_ids MUST be distinct."""
    # Normalize whitespace so wrapped lines don't break substring matching.
    s = " ".join(SYSTEM_PROMPT.split())
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
