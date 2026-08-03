"""
The first closed loop, end to end.

Morning with nothing logged → log a meal → the whole read changes. This is the
scenario that proves the coordinator: one set of facts in, one interpretation
out, and the transition between the two states derived rather than stored.

If this file passes, every surface can be built against `/api/v1/coach/live`
knowing the sections cannot contradict each other, because there is only one
place the day is interpreted.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.coach_live import (
    DayHistory,
    LiveInput,
    MealEvent,
    compute,
    to_wire,
)

TZ = ZoneInfo("America/New_York")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 3, hour, minute, tzinfo=TZ)


def history(days: int = 10, protein: int = 170) -> tuple[DayHistory, ...]:
    """Finished days behind the user, ending yesterday."""
    return tuple(
        DayHistory(
            date=(datetime(2026, 8, 3) - timedelta(days=n)).date().isoformat(),
            calories=2050, protein=protein, trained=n % 2 == 0,
        )
        for n in range(1, days + 1)
    )


def morning_with_nothing_logged() -> LiveInput:
    return LiveInput(
        now=at(8, 0),
        calorie_target=2100, protein_target=180,
        planned_workout="Chest",
        tracks_weight=True,
        wearable_connected=True,
        wearable_updated_at=at(7, 45),
        wearable_source="apple_health",
        history=history(),
    )


# ── Beat one: nothing has happened yet ───────────────────────────────────────

def test_a_morning_with_nothing_logged_is_calibrating():
    state = compute(morning_with_nothing_logged())
    assert state.overall_state == "calibrating"


def test_calibrating_does_not_judge_the_day():
    """Nothing is logged, so nothing can be at risk. A day with no evidence must
    never be reported as failing — that is the fastest way to lose someone at
    8am."""
    state = compute(morning_with_nothing_logged())
    assert state.domains["protein"].state == "not_calibrated"
    assert state.domains["calories"].state == "not_calibrated"
    assert state.overall_state != "at_risk"


def test_the_first_focus_is_to_establish_a_trajectory():
    state = compute(morning_with_nothing_logged())
    assert state.focus is not None
    assert state.focus.domain == "nutrition"
    assert state.focus.action == "log_first_meal"


def test_a_day_with_no_events_has_no_recent_change():
    """Nothing has happened, so there is nothing to reinforce. A change row on an
    empty day would be the reinforcement layer reinforcing nothing."""
    assert compute(morning_with_nothing_logged()).recent_change is None


def test_nothing_limits_a_day_that_has_not_started():
    """`limiting_domain` fell through to whichever domain happened to carry a
    risk score, reporting 'training' on a day whose focus was 'log your first
    meal'. A contract that contradicts itself in two adjacent fields is exactly
    what this endpoint exists to prevent."""
    state = compute(morning_with_nothing_logged())
    assert state.limiting_domain is None


def test_an_unstarted_day_is_not_described_as_behind():
    """Before anything is logged the 'gap' is the whole daily target, and running
    it through the shortfall copy produced 'carrying 162g into tonight makes the
    target unreliable' — at eight in the morning, to someone who has simply not
    eaten yet."""
    insight = compute(morning_with_nothing_logged()).insight
    assert insight is not None
    assert insight.kind == "tradeoff"
    assert "carrying" not in insight.detail


def test_a_finish_we_do_not_trust_is_not_published():
    """The engine withholds `expected_finish` below the extrapolation floor
    rather than printing a number next to a caveat saying not to believe it."""
    protein = compute(after_first_meal()).domains["protein"]
    assert protein.detail == "Too early to project a finish."
    assert protein.expected_finish is None


def test_the_primary_command_carries_enough_context_to_act():
    """A command that opens a blank chat has saved the user nothing."""
    state = compute(morning_with_nothing_logged())
    primary = [c for c in state.commands if c.slot == "primary"]
    assert len(primary) == 1
    assert primary[0].type == "log_first_meal"
    assert primary[0].context["domain"] == "nutrition"


# ── Beat two: the meal lands ─────────────────────────────────────────────────

def after_first_meal() -> LiveInput:
    base = morning_with_nothing_logged()
    meal = MealEvent(at=at(8, 20), calories=520, protein=45, meal_type="breakfast")
    return LiveInput(
        **{**base.__dict__,
           "now": at(8, 40),
           "meals": (meal,),
           "calories_consumed": 520,
           "protein_consumed": 45}
    )


def test_the_first_meal_moves_the_day_to_building():
    assert compute(after_first_meal()).overall_state == "building"


def test_nutrition_now_has_a_trajectory():
    """The point of the first meal: the day becomes readable. It must not be
    called 'ahead' off one breakfast — that is linear extrapolation from a
    sliver of the day wearing a confident face."""
    state = compute(after_first_meal())
    protein = state.domains["protein"]
    assert protein.state == "on_pace"
    assert protein.current == 45
    assert protein.intervention == 117      # 90% of 180 = 162, less 45


def test_the_focus_moves_to_the_workout_window():
    """With nutrition on a trajectory, the session becomes the day's variable —
    it is the one commitment that cannot be caught up tomorrow."""
    state = compute(after_first_meal())
    assert state.focus is not None
    assert state.focus.domain == "training"
    assert state.focus.action == "start_workout"


def test_the_insight_explains_what_stopped_being_the_problem():
    """Never a restatement of the focus. When the limiting domain changes hands,
    the useful sentence is about what was released, not a fresh lecture."""
    state = compute(after_first_meal())
    assert state.insight is not None
    assert state.insight.kind == "cause"
    assert "no longer the largest risk" in state.insight.detail


def test_the_transition_is_reported_with_its_cause():
    """The reinforcement layer: behaviour connected to consequence. Derived by
    replay — there is no event table, so this cannot drift from the live read."""
    change = compute(after_first_meal()).recent_change
    assert change is not None
    assert change.before == "calibrating"
    assert change.after == "building"
    assert change.cause == "breakfast"
    assert change.summary == "Breakfast established today's trajectory"


def test_the_client_is_told_when_to_come_back():
    """The return trigger. The next moment the coordinator would reach a
    different conclusion for reasons of time alone."""
    state = compute(after_first_meal())
    assert state.next_reassessment is not None
    assert state.next_reassessment.startswith("2026-08-03T11:00")


# ── The loop, as one assertion ───────────────────────────────────────────────

def test_the_whole_loop_changes_every_section_at_once():
    """The architectural claim: ONE event, and every section moves together.

    This is what the shared contract buys. Before it, a meal updated the macro
    strip while the verdict card kept quoting a state computed from a different
    read of the same day.
    """
    before = compute(morning_with_nothing_logged())
    after = compute(after_first_meal())

    assert before.overall_state != after.overall_state
    assert before.focus.domain != after.focus.domain
    assert before.domains["protein"].state != after.domains["protein"].state
    assert before.recent_change is None and after.recent_change is not None
    # And the commands re-point at the new highest-leverage action.
    assert ([c.type for c in before.commands if c.slot == "primary"]
            != [c.type for c in after.commands if c.slot == "primary"])


def test_the_wire_shape_carries_every_section():
    """One contract. A section missing from here is a section that will go and
    derive its own interpretation instead."""
    wire = to_wire(compute(after_first_meal()), generated_at=at(8, 40))
    for key in ("v", "generated_at", "freshness", "overall_state", "commands",
                "focus", "insight", "domains", "recent_change",
                "next_reassessment", "limiting_domain"):
        assert key in wire, f"missing {key}"
    for domain in ("protein", "calories", "training", "activity",
                   "recovery", "weight"):
        assert domain in wire["domains"]
    # 7:45 sync read at 8:40 is 55 minutes old — current enough to trust, not
    # current enough to call live.
    assert wire["freshness"]["state"] == "recently_updated"
    assert wire["freshness"]["primary_source"] == "apple_health"


def test_freshness_reports_presence_not_a_verdict():
    """The header answers 'is Arnie working with fresh information', and nothing
    else. Every branch is a statement about the SYNC, never about the day."""
    base = morning_with_nothing_logged()

    def freshness_at(**kw):
        return compute(LiveInput(**{**base.__dict__, **kw})).freshness

    assert freshness_at(now=at(8, 0), wearable_updated_at=at(7, 45)) == "live"
    assert freshness_at(now=at(9, 0), wearable_updated_at=at(7, 45)) == "recently_updated"
    assert freshness_at(now=at(20, 0), wearable_updated_at=at(7, 45)) == "partially_current"
    assert freshness_at(now=at(8, 0), wearable_updated_at=at(8, 0) - timedelta(days=2)) == "waiting_for_sync"
    assert freshness_at(wearable_updated_at=None) == "waiting_for_sync"
    assert freshness_at(wearable_connected=False) == "no_wearable"
