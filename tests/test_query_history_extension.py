"""
Tests for the query_history extension — natural-language periods and the
new per-entry metrics (food_entries, exercise_entries, water, body_metrics,
day_detail). Backward compatibility with the legacy metric set is also
verified so old callers can't silently break.
"""
import pytest
from datetime import date, datetime, timedelta

from db.queries import parse_natural_period, query_history_stats


# ── parse_natural_period — exhaustive ────────────────────────────────────────


_TODAY = date(2026, 6, 9)  # a Tuesday


@pytest.mark.parametrize("period_str,expected", [
    # Existing legacy formats — must keep working.
    ("last_7", (_TODAY - timedelta(days=7), _TODAY)),
    ("last_14", (_TODAY - timedelta(days=14), _TODAY)),
    ("last_30", (_TODAY - timedelta(days=30), _TODAY)),
    ("last_60", (_TODAY - timedelta(days=60), _TODAY)),
    ("last_90", (_TODAY - timedelta(days=90), _TODAY)),
    ("2026-06-07", (date(2026, 6, 7), date(2026, 6, 7))),
    # New: natural language single days
    ("today", (_TODAY, _TODAY)),
    ("now", (_TODAY, _TODAY)),
    ("yesterday", (date(2026, 6, 8), date(2026, 6, 8))),
    ("yday", (date(2026, 6, 8), date(2026, 6, 8))),
    # New: N days ago (digits + word numbers)
    ("2 days ago", (date(2026, 6, 7), date(2026, 6, 7))),
    ("3 days ago", (date(2026, 6, 6), date(2026, 6, 6))),
    ("10 days ago", (date(2026, 5, 30), date(2026, 5, 30))),
    ("one day ago", (date(2026, 6, 8), date(2026, 6, 8))),
    ("three days ago", (date(2026, 6, 6), date(2026, 6, 6))),
    # New: weekday names — most recent occurrence
    ("monday", (date(2026, 6, 8), date(2026, 6, 8))),  # yesterday was Mon
    ("sunday", (date(2026, 6, 7), date(2026, 6, 7))),
    ("sun", (date(2026, 6, 7), date(2026, 6, 7))),
    ("saturday", (date(2026, 6, 6), date(2026, 6, 6))),
    ("tuesday", (_TODAY, _TODAY)),  # today IS Tuesday
    # "last <weekday>" — ALWAYS 7 days back when day matches today
    ("last tuesday", (_TODAY - timedelta(days=7), _TODAY - timedelta(days=7))),
    ("last monday", (date(2026, 6, 8), date(2026, 6, 8))),  # same as plain "monday"
    # New: week windows
    ("this week", (date(2026, 6, 8), _TODAY)),   # Mon-today
    ("last week", (date(2026, 6, 1), date(2026, 6, 7))),  # Mon-Sun prior
    # New: month-day
    ("june 7", (date(2026, 6, 7), date(2026, 6, 7))),
    ("june 7, 2026", (date(2026, 6, 7), date(2026, 6, 7))),
    ("jun 7", (date(2026, 6, 7), date(2026, 6, 7))),
    # If no year given and date is in the future relative to today, prior year
    ("december 31", (date(2025, 12, 31), date(2025, 12, 31))),
    # New: date ranges
    ("2026-06-01:2026-06-07", (date(2026, 6, 1), date(2026, 6, 7))),
    # Range with reversed dates — auto-correct
    ("2026-06-07:2026-06-01", (date(2026, 6, 1), date(2026, 6, 7))),
    # Garbage / forward-looking — return None
    ("asdfasdf", None),
    ("tomorrow", None),
    ("", None),
])
def test_parse_natural_period_matrix(period_str, expected):
    assert parse_natural_period(period_str, _TODAY) == expected


def test_parse_natural_period_none_input():
    assert parse_natural_period(None, _TODAY) is None


# ── query_history_stats — new per-entry metrics ──────────────────────────────


@pytest.mark.asyncio
async def test_food_entries_returns_individual_rows(make_user, db):
    """metric='food_entries' must return one row per logged food, with name,
    quantity, calories, protein, carbs, fats, estimated flag, date."""
    from db.queries import get_or_create_today_log, add_food_entry
    user = await make_user(telegram_id="t-fe-1")
    log = await get_or_create_today_log(db, user.id)
    await add_food_entry(
        db, log.id, parsed_food_name="banana", quantity="1 medium",
        calories=105, protein=1, carbs=27, fats=0, estimated_flag=False,
    )
    await add_food_entry(
        db, log.id, parsed_food_name="oikos shake", quantity="1 bottle",
        calories=150, protein=15, carbs=12, fats=3, estimated_flag=False,
    )

    out = await query_history_stats(
        db, user.id, period="today", metric="food_entries",
        user_timezone="UTC",
    )
    assert out["metric"] == "food_entries"
    assert out["entries"] == 2
    names = sorted(r["food_name"] for r in out["rows"])
    assert names == ["banana", "oikos shake"]
    # The exact macros must round-trip
    banana = [r for r in out["rows"] if r["food_name"] == "banana"][0]
    assert banana["calories"] == 105
    assert banana["protein"] == 1
    assert banana["quantity"] == "1 medium"
    assert banana["estimated"] is False


@pytest.mark.asyncio
async def test_exercise_entries_returns_individual_sets(make_user, db):
    from db.queries import get_or_create_today_log, add_exercise_entry
    user = await make_user(telegram_id="t-ex-1")
    log = await get_or_create_today_log(db, user.id)
    await add_exercise_entry(
        db, log.id, exercise_name="bench press", sets=4, reps=5, weight=84,
    )
    await add_exercise_entry(
        db, log.id, exercise_name="squat", sets=3, reps=8, weight=102,
    )

    out = await query_history_stats(
        db, user.id, period="today", metric="exercise_entries",
    )
    assert out["metric"] == "exercise_entries"
    assert out["entries"] == 2
    names = sorted(r["exercise_name"] for r in out["rows"])
    assert names == ["bench press", "squat"]
    bench = [r for r in out["rows"] if r["exercise_name"] == "bench press"][0]
    assert int(bench["sets"]) == 4
    assert int(bench["reps"]) == 5
    # 84 kg ≈ 185.2 lb
    assert 184 <= bench["weight_lbs"] <= 186


@pytest.mark.asyncio
async def test_day_detail_returns_comprehensive_view(make_user, db):
    """metric='day_detail' returns food + exercise + totals + workout/cardio
    completion for the period. The recap-friendly metric."""
    from db.queries import (
        get_or_create_today_log, add_food_entry, add_exercise_entry,
    )
    user = await make_user(telegram_id="t-dd-1")
    log = await get_or_create_today_log(db, user.id)
    await add_food_entry(
        db, log.id, parsed_food_name="banana", quantity="1 medium",
        calories=105, protein=1, carbs=27, fats=0, estimated_flag=False,
    )
    await add_exercise_entry(
        db, log.id, exercise_name="bench press", sets=4, reps=5, weight=84,
    )

    out = await query_history_stats(
        db, user.id, period="today", metric="day_detail",
    )
    assert out["metric"] == "day_detail"
    assert len(out["days"]) == 1
    day = out["days"][0]
    assert day["totals"]["calories"] == 105
    assert len(day["food"]) == 1
    assert day["food"][0]["food_name"] == "banana"
    assert len(day["exercise"]) == 1
    assert day["exercise"][0]["exercise_name"] == "bench press"


@pytest.mark.asyncio
async def test_food_entries_for_specific_past_date(make_user, db):
    """The canonical Sunday-recap scenario: log food today, query by an ISO
    date, get the per-entry list back."""
    from db.queries import get_or_create_today_log, add_food_entry
    user = await make_user(telegram_id="t-fe-past")
    log = await get_or_create_today_log(db, user.id)
    await add_food_entry(
        db, log.id, parsed_food_name="chicken sandwich", quantity="~10in",
        calories=550, protein=38, carbs=45, fats=22, estimated_flag=True,
    )
    today_iso = str(log.date)
    out = await query_history_stats(
        db, user.id, period=today_iso, metric="food_entries",
    )
    assert out["entries"] == 1
    assert out["rows"][0]["food_name"] == "chicken sandwich"


@pytest.mark.asyncio
async def test_water_returns_daily_totals_at_minimum(make_user, db):
    """Even with no WaterEntry rows (just the cached aggregate on DailyLog),
    the water metric must return the daily total so the recap is complete."""
    from db.queries import get_or_create_today_log
    user = await make_user(telegram_id="t-water")
    log = await get_or_create_today_log(db, user.id)
    log.total_water_ml = 1500
    await db.commit()
    out = await query_history_stats(db, user.id, period="today", metric="water")
    assert out["metric"] == "water"
    assert any(d["total_water_ml"] == 1500 for d in out["daily_totals"])


@pytest.mark.asyncio
async def test_body_metrics_returns_snapshots(make_user, db):
    from db.models import HealthSnapshot
    user = await make_user(telegram_id="t-bm")
    snap = HealthSnapshot(
        user_id=user.id, date=date.today(), sleep_hours=7.5, hrv=55,
        resting_hr=58, recovery_score=72, source="whoop",
    )
    db.add(snap)
    await db.commit()
    out = await query_history_stats(db, user.id, period="today", metric="body_metrics")
    assert out["metric"] == "body_metrics"
    assert out["entries"] == 1
    r = out["rows"][0]
    assert r["sleep_hours"] == 7.5
    assert r["recovery_score"] == 72


# ── legacy metrics still work (no regression) ────────────────────────────────


@pytest.mark.asyncio
async def test_calories_aggregate_legacy_still_works(make_user, db):
    """The original aggregate metric path must keep returning the same shape."""
    from db.queries import get_or_create_today_log, add_food_entry
    user = await make_user(telegram_id="t-leg-cal")
    log = await get_or_create_today_log(db, user.id)
    await add_food_entry(
        db, log.id, parsed_food_name="x", quantity="1", calories=500,
        protein=30, carbs=40, fats=20, estimated_flag=False,
    )
    out = await query_history_stats(db, user.id, period="last_7", metric="calories")
    assert out["metric"] == "calories"
    assert "avg_calories" in out
    assert "rows" in out


@pytest.mark.asyncio
async def test_natural_period_works_with_legacy_metrics(make_user, db):
    """Natural-language periods must work with the legacy aggregate metrics
    too — no special-casing per metric."""
    from db.queries import get_or_create_today_log, add_food_entry
    user = await make_user(telegram_id="t-leg-nat")
    log = await get_or_create_today_log(db, user.id)
    await add_food_entry(
        db, log.id, parsed_food_name="y", quantity="1", calories=300,
        protein=20, carbs=30, fats=10, estimated_flag=False,
    )
    out = await query_history_stats(db, user.id, period="today", metric="calories")
    assert "error" not in out
    assert out["metric"] == "calories"


@pytest.mark.asyncio
async def test_bad_period_returns_error_not_crash(make_user, db):
    user = await make_user(telegram_id="t-bad")
    out = await query_history_stats(db, user.id, period="asdfasdf", metric="calories")
    assert "error" in out


@pytest.mark.asyncio
async def test_unknown_metric_returns_error(make_user, db):
    user = await make_user(telegram_id="t-bad-metric")
    out = await query_history_stats(db, user.id, period="today", metric="not_a_metric")
    assert "error" in out


# ── tool schema reflects the extension ───────────────────────────────────────


def test_query_history_tool_lists_new_metrics():
    """The tool's metric enum must include the new per-entry metrics so the
    LLM can call them."""
    from core.tools import build_tools
    tools = build_tools()
    qh = next(t for t in tools if t["name"] == "query_history")
    enum = qh["input_schema"]["properties"]["metric"]["enum"]
    for new in ("food_entries", "exercise_entries", "water",
                "body_metrics", "day_detail"):
        assert new in enum, f"{new!r} missing from query_history metric enum"
    # Legacy metrics still listed
    for legacy in ("calories", "protein", "weight", "workouts", "exercise", "all"):
        assert legacy in enum, f"legacy metric {legacy!r} regressed out"


def test_query_history_tool_description_mentions_natural_periods():
    """The description must teach the LLM that natural-language periods are
    accepted, so it doesn't reach for ISO-only formats by default."""
    from core.tools import build_tools
    tools = build_tools()
    qh = next(t for t in tools if t["name"] == "query_history")
    desc = qh["description"]
    assert "yesterday" in desc
    assert "sunday" in desc.lower() or "weekday" in desc.lower()
    # Mentions ranges
    assert "range" in desc.lower()


def test_query_history_tool_period_description_mentions_natural_language():
    from core.tools import build_tools
    tools = build_tools()
    qh = next(t for t in tools if t["name"] == "query_history")
    period_desc = qh["input_schema"]["properties"]["period"]["description"]
    assert "yesterday" in period_desc.lower()
    assert "last_7" in period_desc
