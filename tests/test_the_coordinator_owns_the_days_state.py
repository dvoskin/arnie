"""
The state vocabulary, and the rules that pick it.

Every feed section switches on `overall_state` and the domain states, so these
words are a contract. What is pinned here is not the phrasing — that belongs to
the briefing layer — but the CONDITIONS: what makes a day at risk, what makes it
secured, and the several things that must never happen (a day judged before
there is evidence, a session Arnie can't see counted as missed, a closed day
still being coached at).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.coach_live import (
    DayHistory,
    LiveInput,
    MealEvent,
    TrainingEvent,
    compute,
    qualifies,
    replay_before,
)

TZ = ZoneInfo("America/New_York")


def at(hour: int, minute: int = 0, day: int = 3) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=TZ)


def day(**kw) -> LiveInput:
    base = dict(
        now=at(13, 0),
        calorie_target=2100, protein_target=180,
        tracks_weight=True, wearable_connected=False,
    )
    base.update(kw)
    return LiveInput(**base)


# ── The pass mark is shared with the client ──────────────────────────────────

def test_the_pass_mark_matches_what_the_app_already_promises():
    """iOS states these in words in the adherence popover. Two copies of the
    rule is how the dots and the coach disagree about one finished day."""
    assert qualifies("calories", 1800, 2000)
    assert qualifies("calories", 2300, 2000)
    assert not qualifies("calories", 1699, 2000)
    assert not qualifies("calories", 2301, 2000)
    assert qualifies("protein", 135, 150)
    assert not qualifies("protein", 134, 150)


def test_calories_are_a_band_so_undereating_misses_too():
    assert not qualifies("calories", 900, 2000)
    assert qualifies("protein", 900, 150)


def test_an_unlogged_day_is_absent_not_failed():
    assert not qualifies("protein", 0, 150)


# ── Never judge a day with no evidence ───────────────────────────────────────

def test_a_day_with_nothing_logged_is_never_at_risk():
    for hour in (6, 9, 13, 17, 21):
        state = compute(day(now=at(hour)))
        assert state.overall_state == "calibrating", hour


def test_no_targets_means_no_nutrition_judgement():
    """A user mid-onboarding is not failing at a target they don't have."""
    state = compute(day(calorie_target=None, protein_target=None,
                        meals=(MealEvent(at=at(12), calories=600, protein=40),),
                        calories_consumed=600, protein_consumed=40))
    assert state.domains["protein"].state == "not_calibrated"
    assert state.overall_state != "at_risk"


# ── Training is never invented ───────────────────────────────────────────────

def test_a_session_arnie_cannot_see_is_never_overdue():
    """`planned_workout=None` means unknown. Reading it as 'no workout done'
    turns a coach into a nag about training that may not be scheduled."""
    state = compute(day(now=at(21), planned_workout=None,
                        meals=(MealEvent(at=at(12), calories=900, protein=100),),
                        calories_consumed=900, protein_consumed=100))
    assert state.domains["training"].state == "unscheduled"
    assert state.domains["training"].risk is None


def test_a_declared_rest_day_is_not_a_missed_workout():
    state = compute(day(now=at(21), planned_workout="Legs", is_rest_day=True,
                        meals=(MealEvent(at=at(12), calories=1900, protein=170),),
                        calories_consumed=1900, protein_consumed=170))
    assert state.domains["training"].state == "rest_day"


def test_an_open_session_late_in_the_day_becomes_the_focus():
    """Training can't be caught up tomorrow the way a macro can, so a narrowing
    window outranks a nutrition gap that still has meals left in it."""
    state = compute(day(now=at(19), planned_workout="Chest",
                        meals=(MealEvent(at=at(12), calories=1200, protein=90),),
                        calories_consumed=1200, protein_consumed=90))
    assert state.focus.domain == "training"
    assert state.focus.minimum is not None      # a fallback preserves momentum


# ── Reachable vs at risk ─────────────────────────────────────────────────────

def test_a_gap_that_fits_in_the_meals_left_is_reachable_not_lost():
    """The distinction the whole intervention layer rests on: 'behind' is a plan,
    'behind with nowhere to put it' is a fact."""
    state = compute(day(now=at(13), planned_workout=None,
                        meals=(MealEvent(at=at(12), calories=800, protein=40),),
                        calories_consumed=800, protein_consumed=40))
    # Pace projects ~86g against a 162g line, so it IS short. But 122g across the
    # two meals the clock still allows is 61g a sitting — a plan, not a loss.
    assert state.domains["protein"].state == "reachable"


def test_the_same_gap_with_no_meals_left_is_at_risk():
    state = compute(day(now=at(23), planned_workout=None,
                        meals=(MealEvent(at=at(12), calories=800, protein=80),),
                        calories_consumed=800, protein_consumed=80))
    assert state.domains["protein"].state == "at_risk"


def test_overshooting_calories_is_a_miss_too():
    state = compute(day(now=at(15), planned_workout=None,
                        meals=(MealEvent(at=at(14), calories=2600, protein=120),),
                        calories_consumed=2600, protein_consumed=120))
    assert state.domains["calories"].state == "at_risk"


# ── Secured and complete ─────────────────────────────────────────────────────

def test_a_day_is_secured_by_what_moves_the_outcome():
    """Not by every box. A secured day does not require a weigh-in or a step
    goal — requiring everything is how a good day gets reported as incomplete."""
    state = compute(day(
        now=at(20), planned_workout="Chest", workout_completed=True,
        training_events=(TrainingEvent(at=at(18), name="Chest"),),
        meals=(MealEvent(at=at(19), calories=2000, protein=175),),
        calories_consumed=2000, protein_consumed=175,
        weight_logged_today=False,
    ))
    assert state.overall_state == "secured"


def test_an_open_session_holds_the_day_back_from_secured():
    state = compute(day(
        now=at(17), planned_workout="Chest",
        meals=(MealEvent(at=at(16), calories=2000, protein=175),),
        calories_consumed=2000, protein_consumed=175))
    assert state.overall_state != "secured"


def test_past_the_day_boundary_the_day_is_complete_not_coached():
    """After the 4am rollover the day is closed. A closed day still being told to
    'fix protein' is the coordinator arguing with a clock it already lost."""
    state = compute(day(now=at(1, 30, day=4), planned_workout="Chest",
                        meals=(MealEvent(at=at(20), calories=1400, protein=90),),
                        calories_consumed=1400, protein_consumed=90))
    assert state.overall_state == "complete"
    assert state.focus is None


def test_a_reviewed_day_is_complete_whatever_the_clock_says():
    state = compute(day(now=at(21), day_reviewed=True,
                        meals=(MealEvent(at=at(20), calories=1400, protein=90),),
                        calories_consumed=1400, protein_consumed=90))
    assert state.overall_state == "complete"


# ── Recovering, and the replay it rests on ───────────────────────────────────

def test_replay_rolls_back_the_clock_as_well_as_the_facts():
    """Replaying at the CURRENT hour would compare a 2pm state against an 8pm one
    and blame the whole difference on the meal."""
    inp = day(now=at(20), meals=(MealEvent(at=at(19), calories=900, protein=95),),
              calories_consumed=900, protein_consumed=95)
    before = replay_before(inp, at(19))
    assert before.now < at(19)
    assert before.meals == ()
    assert before.protein_consumed == 0


def test_a_rescue_is_reported_as_recovering():
    """At risk at 4pm, a big dinner lands, and the day is pulled back. This is
    the state that makes intervention feel worth doing."""
    inp = day(
        now=at(19, 30), planned_workout=None,
        meals=(
            MealEvent(at=at(9), calories=200, protein=8, meal_type="breakfast"),
            MealEvent(at=at(19), calories=1500, protein=120, meal_type="dinner"),
        ),
        calories_consumed=1700, protein_consumed=128,
    )
    state = compute(inp)
    assert state.recent_change is not None
    assert state.recent_change.before == "at_risk"
    assert state.overall_state in ("recovering", "secured", "on_track")


def test_an_event_that_changes_nothing_reports_nothing():
    """A row saying 'you logged a snack and nothing happened' is noise. The
    reinforcement layer only earns its place by reporting consequences."""
    inp = day(
        now=at(13), planned_workout=None,
        meals=(
            MealEvent(at=at(8), calories=500, protein=45, meal_type="breakfast"),
            MealEvent(at=at(12), calories=60, protein=2, meal_type="snack"),
        ),
        calories_consumed=560, protein_consumed=47,
    )
    assert compute(inp).recent_change is None


# ── The insight never restates the focus ─────────────────────────────────────

def test_the_insight_adds_a_fact_the_card_does_not_already_show():
    """'Eat more protein because protein is low' is the failure mode."""
    hist = tuple(
        DayHistory(date=(datetime(2026, 8, 3) - timedelta(days=n)).date().isoformat(),
                   calories=2050, protein=170)
        for n in range(1, 11)
    )
    state = compute(day(now=at(15), planned_workout=None, history=hist,
                        meals=(MealEvent(at=at(12), calories=900, protein=60),),
                        calories_consumed=900, protein_consumed=60))
    assert state.focus.domain == "nutrition"
    assert state.insight is not None
    assert state.insight.kind == "pattern"
    assert state.insight.typical_value is not None
    assert state.insight.evidence_n == 10
    # The number the user could not have read off the card.
    assert str(state.insight.typical_value) in state.insight.detail


def test_thin_history_states_the_constraint_instead_of_inventing_a_pattern():
    state = compute(day(now=at(15), planned_workout=None, history=(),
                        meals=(MealEvent(at=at(12), calories=900, protein=60),),
                        calories_consumed=900, protein_consumed=60))
    assert state.insight is not None
    assert state.insight.kind == "constraint"
    assert state.insight.typical_value is None


# ── One divisor ──────────────────────────────────────────────────────────────

def test_the_next_meal_ask_uses_the_one_divisor():
    """iOS `DayTargets.proteinBand` divides the same remainder by the same
    `meals_remaining`. Two divisors is how one screen printed 'land 110g' beside
    '168g left'."""
    state = compute(day(now=at(13), planned_workout=None,
                        meals=(MealEvent(at=at(12), calories=800, protein=62),),
                        calories_consumed=800, protein_consumed=62))
    assert state.focus.domain == "nutrition"
    # 162 - 62 = 100 needed, lunch window → 2 meals left → 50 a sitting.
    assert "50g at the next meal" == state.focus.minimum
