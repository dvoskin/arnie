"""
Tests for the query_history extension — natural-language periods and the
new per-entry metrics (food_entries, exercise_entries, water, body_metrics,
day_detail). Backward compatibility with the legacy metric set is also
verified so old callers can't silently break.
"""
import pytest
from datetime import date, datetime, timedelta

from freezegun import freeze_time

from db.queries import parse_natural_period, query_history_stats


# ── parse_natural_period — exhaustive ────────────────────────────────────────


_TODAY = date(2026, 6, 9)  # a Tuesday
# Frozen wall clock for the tests below that derive a target date from the real
# clock (date.today()) and then re-derive it inside query_history_stats, which
# computes its own "today" from datetime.now(). Without a frozen clock those two
# reads can land on different calendar days (UTC-midnight straddle, or a
# pytest-randomly shuffle that runs them on a later day than module import),
# pushing the relative-date math off by one and dropping the just-logged row.
# Noon, mid-month — equals _TODAY at midday, far from any date boundary.
_FROZEN_NOW = "2026-06-09 12:00:00"


@pytest.mark.parametrize("period_str,expected", [
    # Existing legacy formats — must keep working.
    ("last_7", (_TODAY - timedelta(days=7), _TODAY)),
    ("last_14", (_TODAY - timedelta(days=14), _TODAY)),
    ("last_30", (_TODAY - timedelta(days=30), _TODAY)),
    ("last_60", (_TODAY - timedelta(days=60), _TODAY)),
    ("last_90", (_TODAY - timedelta(days=90), _TODAY)),
    # NEW: unlimited last_<N> window — DB stores entries indefinitely.
    ("last_120", (_TODAY - timedelta(days=120), _TODAY)),
    ("last_180", (_TODAY - timedelta(days=180), _TODAY)),
    ("last_365", (_TODAY - timedelta(days=365), _TODAY)),
    ("last_1000", (_TODAY - timedelta(days=1000), _TODAY)),
    # NEW: weeks ago and months ago
    ("1 week ago", (_TODAY - timedelta(days=7), _TODAY - timedelta(days=7))),
    ("3 weeks ago", (_TODAY - timedelta(days=21), _TODAY - timedelta(days=21))),
    ("two weeks ago", (_TODAY - timedelta(days=14), _TODAY - timedelta(days=14))),
    ("1 month ago", (_TODAY - timedelta(days=30), _TODAY - timedelta(days=30))),
    ("4 months ago", (_TODAY - timedelta(days=120), _TODAY - timedelta(days=120))),
    ("six months ago", (_TODAY - timedelta(days=180), _TODAY - timedelta(days=180))),
    # 120 days ago — the user's canonical "go back far" case
    ("120 days ago", (_TODAY - timedelta(days=120), _TODAY - timedelta(days=120))),
    ("365 days ago", (_TODAY - timedelta(days=365), _TODAY - timedelta(days=365))),
    # NEW: open-ended "whole history" phrasings — the natural way users ask for
    # the last time / full history of a lift or food. Previously returned None
    # (a hard error) → movement/food recall across months silently failed.
    ("last time", (_TODAY - timedelta(days=365), _TODAY)),
    ("ever", (_TODAY - timedelta(days=365), _TODAY)),
    ("all time", (_TODAY - timedelta(days=365), _TODAY)),
    ("all-time", (_TODAY - timedelta(days=365), _TODAY)),
    ("history", (_TODAY - timedelta(days=365), _TODAY)),
    ("my bench history", (_TODAY - timedelta(days=365), _TODAY)),   # endswith " history"
    ("squat history", (_TODAY - timedelta(days=365), _TODAY)),
    # NEW: calendar-year + "last/past N <unit>" RANGES (distinct from "N ago")
    ("this year", (date(2026, 1, 1), _TODAY)),
    ("last year", (date(2025, 1, 1), date(2025, 12, 31))),
    ("last 3 months", (_TODAY - timedelta(days=90), _TODAY)),
    ("past 2 weeks", (_TODAY - timedelta(days=14), _TODAY)),
    ("last 10 days", (_TODAY - timedelta(days=10), _TODAY)),
    ("last six months", (_TODAY - timedelta(days=180), _TODAY)),
    # ISO dates work for any date in the past
    ("2026-06-07", (date(2026, 6, 7), date(2026, 6, 7))),
    ("2024-03-15", (date(2024, 3, 15), date(2024, 3, 15))),
    ("2020-01-01", (date(2020, 1, 1), date(2020, 1, 1))),
    # Month-day with explicit year for years-back lookups
    ("march 15 2024", (date(2024, 3, 15), date(2024, 3, 15))),
    ("march 15, 2024", (date(2024, 3, 15), date(2024, 3, 15))),
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
@freeze_time(_FROZEN_NOW)
async def test_body_metrics_returns_snapshots(make_user, db):
    # Frozen clock: the snapshot's date.today() must equal the "today" that
    # query_history_stats computes internally, or period="today" misses the row.
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


def test_query_history_tool_description_mentions_unlimited_lookback():
    """The model must know it CAN reach back 120+ days, otherwise it may
    refuse or hallucinate that the data isn't available."""
    from core.tools import build_tools
    tools = build_tools()
    qh = next(t for t in tools if t["name"] == "query_history")
    desc = qh["description"] + qh["input_schema"]["properties"]["period"]["description"]
    assert "120 days ago" in desc or "last_120" in desc
    assert "indefinitely" in desc.lower() or "NO upper limit" in desc


# ── 120-day lookback round-trip (the user's canonical ask) ───────────────────


@pytest.mark.asyncio
@freeze_time(_FROZEN_NOW)
async def test_food_entry_120_days_back_is_retrievable(make_user, db):
    """Log a food on a DailyLog 120 days in the past, then query for it.
    Must return the exact entry — no upper-bound cap on lookback.

    Frozen clock: target_date (date.today() - 120) must equal the date that
    query_history_stats resolves "120 days ago" to from its own now()."""
    from db.models import DailyLog, FoodEntry
    from db.queries import recompute_log_totals

    user = await make_user(telegram_id="t-120d")
    target_date = date.today() - timedelta(days=120)
    log = DailyLog(user_id=user.id, date=target_date)
    db.add(log)
    await db.flush()
    db.add(FoodEntry(
        daily_log_id=log.id, parsed_food_name="chicken sandwich",
        quantity="~10in", calories=550, protein=38, carbs=45, fats=22,
        estimated_flag=True,
    ))
    await db.flush()
    await recompute_log_totals(db, log.id)
    await db.commit()

    # Query by ISO date — should retrieve the entry exactly.
    out = await query_history_stats(
        db, user.id, period=str(target_date), metric="food_entries",
    )
    assert out["entries"] == 1
    assert out["rows"][0]["food_name"] == "chicken sandwich"
    assert out["rows"][0]["calories"] == 550

    # Query by "120 days ago" — should retrieve the same entry.
    out2 = await query_history_stats(
        db, user.id, period="120 days ago", metric="food_entries",
    )
    assert out2["entries"] == 1
    assert out2["rows"][0]["food_name"] == "chicken sandwich"


@pytest.mark.asyncio
@freeze_time(_FROZEN_NOW)
async def test_day_detail_4_months_back_is_retrievable(make_user, db):
    """Same check, via 'day_detail' metric and '4 months ago' phrasing.

    Frozen clock: target_date (date.today() - 120) must equal the date that
    query_history_stats resolves "4 months ago" to from its own now()."""
    from db.models import DailyLog, FoodEntry
    from db.queries import recompute_log_totals

    user = await make_user(telegram_id="t-4mo")
    target_date = date.today() - timedelta(days=120)
    log = DailyLog(user_id=user.id, date=target_date)
    db.add(log)
    await db.flush()
    db.add(FoodEntry(
        daily_log_id=log.id, parsed_food_name="oatmeal", quantity="1 cup",
        calories=150, protein=5, carbs=27, fats=3, estimated_flag=False,
    ))
    await db.flush()
    await recompute_log_totals(db, log.id)
    await db.commit()

    out = await query_history_stats(
        db, user.id, period="4 months ago", metric="day_detail",
    )
    # 4 months ≈ 120 days — should match this log
    assert len(out["days"]) == 1
    assert out["days"][0]["food"][0]["food_name"] == "oatmeal"


@pytest.mark.asyncio
async def test_last_365_window_covers_full_year(make_user, db):
    """A 'last_365' query must cover a date logged 200 days ago. Verifies the
    rolling-window upper bound is genuinely unlimited."""
    from db.models import DailyLog, FoodEntry
    from db.queries import recompute_log_totals

    user = await make_user(telegram_id="t-365")
    target_date = date.today() - timedelta(days=200)
    log = DailyLog(user_id=user.id, date=target_date)
    db.add(log)
    await db.flush()
    db.add(FoodEntry(
        daily_log_id=log.id, parsed_food_name="banana", quantity="1 medium",
        calories=105, protein=1, carbs=27, fats=0, estimated_flag=False,
    ))
    await db.flush()
    await recompute_log_totals(db, log.id)
    await db.commit()

    out = await query_history_stats(
        db, user.id, period="last_365", metric="food_entries",
    )
    assert out["entries"] == 1
    assert out["rows"][0]["food_name"] == "banana"


# ── query_history is a voiced-result tool: heads-up + tool result must always
#    reach the user via a forced follow-up. Prevents the "On it, pulling that
#    now." dead-air regression. ──────────────────────────────────────────────


def test_query_history_voices_its_result():
    """query_history's answer lives ONLY in the tool result (the first LLM
    pass runs BEFORE the tool fires, so the model can never write the data
    in pass 1 — only a heads-up bubble). Under voice-by-default it MUST voice
    its result (not be SILENT), so the follow-up is forced even when the first
    pass already wrote heads-up text. Without this, response_text stays as
    'pulling that up' and the user gets dead air after — the screenshot
    regression."""
    import core.conversation as C
    assert C._voices_result("query_history"), (
        "query_history must voice its result — otherwise a first-pass heads-up "
        "('pulling that up') becomes the whole reply and the actual history data "
        "is silently dropped."
    )
    assert "query_history" not in C._SILENT_TOOLS


@pytest.mark.asyncio
async def test_query_history_with_heads_up_text_still_runs_follow_up(
        make_user, db, monkeypatch):
    """The exact regression from the screenshot: model writes a heads-up bubble
    ('On it, pulling that now.') AND emits a query_history tool call in the
    same first pass. The follow-up MUST still fire so the structured recap
    reaches the user. Before the fix, need_followup=False because response_text
    existed and query_history wasn't in _VOICED_RESULT_TOOLS — the result was
    dropped and the user only saw the heads-up."""
    import core.conversation as C

    user = await make_user(telegram_id="t-qh-headsup")
    calls = {"follow_up": 0, "execute": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None,
                         stream_handler=None):
        return {
            "text": "On it, pulling that now.",
            "tool_calls": [{"name": "query_history", "id": "qh1",
                            "input": {"metric": "food_entries",
                                      "period": "last saturday"}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system,
                              max_tokens=512, stream_handler=None):
        calls["follow_up"] += 1
        # The structured coached recap — the answer the user actually came for.
        return ("saturday, june 6:|||"
                "• banana, 105 calories, 1g protein|||"
                "105 calories total for the day.")

    async def _fake_execute(tool_calls, user, log, db, source_type, **_kw):
        calls["execute"] += 1
        return {"query_history": "HISTORY QUERY — period=last saturday\n• banana 105 cal"}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "what did I eat last saturday?"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
    )

    # The follow-up MUST have run despite the first pass writing heads-up text.
    assert calls["follow_up"] == 1, (
        "follow-up did not fire — query_history result was dropped on the floor"
    )
    assert calls["execute"] == 1, "tool execution must run before the follow-up"
    # The final response is the COACHED RECAP, not the heads-up.
    final = " ".join(result.response.bubbles).lower()
    assert "saturday, june 6" in final, "structured recap missing from response"
    assert "banana" in final, "tool result data missing from response"
    # The heads-up text must NOT be the entire reply (dead-air regression).
    assert "on it, pulling that now" not in final, (
        "heads-up leaked into the final response (would mean follow-up was skipped)"
    )


@pytest.mark.asyncio
async def test_query_history_with_NO_heads_up_text_still_runs_follow_up(
        make_user, db, monkeypatch):
    """Sanity: the no-heads-up path was always correct and must stay correct
    after the fix. Empty first-pass text → need_followup is True via the
    'not response_text' term; adding query_history to VOICED must not regress
    this. Both paths converge on follow-up running."""
    import core.conversation as C

    user = await make_user(telegram_id="t-qh-noheadsup")
    calls = {"follow_up": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None,
                         stream_handler=None):
        return {
            "text": "",  # no heads-up text — the previously-working path
            "tool_calls": [{"name": "query_history", "id": "qh2",
                            "input": {"metric": "calories", "period": "last_7"}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system,
                              max_tokens=512, stream_handler=None):
        calls["follow_up"] += 1
        return "averaged 1,800 cal/day last week. solid pacing."

    async def _fake_execute(tool_calls, user, log, db, source_type, **_kw):
        return {"query_history": "Calories: avg 1800/day over 7 days"}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "what's my weekly average?"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
    )

    assert calls["follow_up"] == 1
    final = " ".join(result.response.bubbles).lower()
    assert "1,800" in final


@pytest.mark.asyncio
async def test_log_food_turn_unaffected_by_query_history_voiced_addition(
        make_user, db, monkeypatch):
    """Pin that adding query_history to _VOICED_RESULT_TOOLS does NOT change
    behavior on a pure log_food turn. The logging branch is reached first
    (has_logging=True), so the voiced-result check is never consulted."""
    import core.conversation as C

    user = await make_user(telegram_id="t-logfood-unaffected")
    calls = {"follow_up": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None,
                         stream_handler=None):
        return {
            "text": "banana logged.",
            "tool_calls": [{"name": "log_food", "id": "f1",
                            "input": {"food_name": "banana", "quantity": "1 medium",
                                      "calories": 105, "protein": 1, "carbs": 27,
                                      "fats": 0, "confidence": 0.9}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system,
                              max_tokens=512, stream_handler=None):
        calls["follow_up"] += 1
        return "banana, 105 cal.|||1,205 / 2,000 for the day."

    async def _fake_execute(tool_calls, user, log, db, source_type, **_kw):
        return {"log_food": "Logged banana: 105 cal. DAY TOTAL: 1205 cal."}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "had a banana"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
    )

    # Logging branch already forces the follow-up — same as before the fix.
    assert calls["follow_up"] == 1


# ── native-card tools: the actionable close must survive (iOS teaser bug) ─────
#    Regression for the iOS "teaser with no answer" report: the model writes a
#    lead-in bubble and calls a card tool (suggest_meals / suggest_workout /
#    show_*). Generation stops at the tool_use, so the actionable CLOSE is meant
#    to land in a follow-up pass. Before the fix, need_followup was False whenever
#    a lead-in existed (card tools weren't in any forced-follow-up set), so the
#    close was dropped and the user saw only the dangling lead-in. Same dead-air
#    shape as the query_history bug above — different tool family.


@pytest.mark.asyncio
async def test_card_tool_with_lead_in_still_runs_follow_up_for_close(
        make_user, db, monkeypatch):
    """suggest_meals turn: first pass writes a lead-in + the card tool call. The
    follow-up MUST still fire so the actionable close reaches the user, and the
    meal card must be attached to the response. Before the fix the follow-up
    never ran (need_followup=False with a non-empty lead-in) and the reply was a
    bare teaser ('here's what fits your last 900:')."""
    import core.conversation as C

    user = await make_user(telegram_id="t-card-meals")
    calls = {"follow_up": 0, "execute": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None,
                         stream_handler=None):
        return {
            "text": "here's what fits your last 900:",  # lead-in only — close deferred
            "tool_calls": [{"name": "suggest_meals", "id": "sm1",
                            "input": {"title": "dinner ideas",
                                      "meals": [
                                          {"name": "chicken + rice", "calories": 600},
                                          {"name": "salmon bowl", "calories": 550},
                                      ]}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system,
                              max_tokens=512, stream_handler=None):
        calls["follow_up"] += 1
        # The actionable close — the part the teaser was missing.
        return "either works for your macros. want me to log it after you eat?"

    async def _fake_execute(tool_calls, user, log, db, source_type, **_kw):
        calls["execute"] += 1
        return {"suggest_meals": "Showed 2 meal ideas as a carousel — keep your reply short."}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "what should I eat tonight?"}],
        system="SYS", platform="ios",
        in_onboarding=False, was_onboarding=False,
    )

    # The follow-up MUST have fired despite the first pass writing a lead-in.
    assert calls["follow_up"] == 1, (
        "follow-up did not fire — the card-tool close was dropped, leaving a teaser"
    )
    assert calls["execute"] == 1, "tool execution must run before the follow-up"
    # The actionable close reached the user.
    final = " ".join(result.response.bubbles).lower()
    assert "want me to log it" in final, "actionable close missing from response"
    # The meal card is attached so the substance still renders on iOS.
    assert any(c.get("type") == "meal_suggestions_card" for c in result.response.cards), (
        "meal_suggestions_card not attached to the response"
    )


@pytest.mark.asyncio
async def test_suggest_workout_card_is_in_card_close_tools(make_user, db, monkeypatch):
    """Sibling coverage: suggest_workout follows the same lead-in + card + close
    contract and must also force the follow-up."""
    import core.conversation as C

    user = await make_user(telegram_id="t-card-workout")
    calls = {"follow_up": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None,
                         stream_handler=None):
        return {
            "text": "here's a push day that fits your week:",
            "tool_calls": [{"name": "suggest_workout", "id": "sw1",
                            "input": {"title": "push day", "split_day": "push",
                                      "exercises": [{"name": "bench", "sets": 4},
                                                    {"name": "ohp", "sets": 3}]}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system,
                              max_tokens=512, stream_handler=None):
        calls["follow_up"] += 1
        return "start with bench while you're fresh. log each set as you go?"

    async def _fake_execute(tool_calls, user, log, db, source_type, **_kw):
        return {"suggest_workout": "Showed 2 exercises (push) as a plan carousel — keep your reply short."}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "give me a push workout"}],
        system="SYS", platform="ios",
        in_onboarding=False, was_onboarding=False,
    )

    assert calls["follow_up"] == 1, "suggest_workout must force the follow-up close"
    final = " ".join(result.response.bubbles).lower()
    assert "log each set" in final
    assert any(c.get("type") == "workout_plan_card" for c in result.response.cards)
    # The card payload must honor the wire contract — the model emitted exercises
    # WITHOUT is_cardio (the prod case), so normalization must add it. A native
    # decoder that treats is_cardio as required drops the WHOLE card on a missing
    # key (iOS workout_plan_card rendered 0% — "you didn't send anything").
    plan = next(c for c in result.response.cards if c.get("type") == "workout_plan_card")
    exs = plan["payload"]["exercises"]
    assert len(exs) == 2
    assert all("is_cardio" in e for e in exs), "every plan exercise must carry is_cardio"
    assert all(e["is_cardio"] is False for e in exs)
    assert all(isinstance(e["name"], str) for e in exs)


def test_normalize_plan_exercises_contract():
    """_normalize_plan_exercises pins the workout_plan_card wire contract: every
    exercise carries is_cardio, name/reps are strings, extra keys pass through,
    and cardio signals map to is_cardio=True."""
    import core.conversation as C
    out = C._normalize_plan_exercises([
        {"name": "bench", "sets": 4, "reps": "10,10,8"},          # no is_cardio → False
        {"name": "row", "reps": 12},                               # reps int → str
        {"name": "bike", "cardio_type": "stationary", "duration_minutes": 15},  # cardio → True
        {"name": "treadmill", "is_cardio": True},                  # explicit True
        "not a dict",                                              # skipped
    ])
    assert len(out) == 4
    assert all("is_cardio" in e for e in out)
    assert out[0]["is_cardio"] is False
    assert out[1]["reps"] == "12" and isinstance(out[1]["reps"], str)
    assert out[2]["is_cardio"] is True
    assert out[2]["duration_minutes"] == 15            # extra keys preserved
    assert out[3]["is_cardio"] is True


def test_normalize_plan_exercises_empty_and_none():
    import core.conversation as C
    assert C._normalize_plan_exercises(None) == []
    assert C._normalize_plan_exercises([]) == []
