"""
The coach coordinator — one interpretation of the day, owned by the server.

WHY THIS EXISTS AT ALL.

Every feed section used to interpret the day for itself. The verdict card decided
what kind of day it was, the focus card independently decided what mattered most,
the macro strip decided whether protein was behind, and the briefing LLM decided
all three again in prose. Four interpretations of one day, joined by nothing, is
how a screen ends up telling a user their day is on track directly above a card
telling them it is at risk.

So the state is computed HERE, once, deterministically, and every surface reads
it. The briefing layer may PHRASE what this decides; it may not decide it.

THE SHAPE, AND WHY IT IS THIS SHAPE.

`LiveInput` is flat and constructible in two lines. Nothing in this module touches
the database, the clock, or an LLM. That is what makes "morning, nothing logged"
and "8pm, protein rescued by lunch" each a two-line test rather than a fixture
farm — and it is what makes REPLAY possible, which is the whole trick behind
`recovering` and `recent_change` (see `replay_before`).

WHAT IS DELIBERATELY NOT HERE.

No probability is exposed. The trajectory math computes one internally to rank
the domains, but the contract publishes a CATEGORY — a percentage implies a
calibration nobody has validated against real outcomes yet, and a number is much
harder to walk back than a word.

Optionality is meaningful throughout: `None` means UNKNOWN, never zero and never
false. An unknown signal must never produce a scolding state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from typing import Literal, Optional

# ─────────────────────────────────────────────────────────────────────────────
# The pass mark
# ─────────────────────────────────────────────────────────────────────────────
#
# What it means for a day to LAND. These two numbers are already published to the
# user — the iOS adherence strip states them in words ("within 15% of your
# target", "at least 90%") — and they are what the trajectory is measured
# against. They live here so the server and the client cannot drift apart about
# whether a finished day counted.

CALORIE_TOLERANCE = 0.15
PROTEIN_FLOOR = 0.90

# How far into the day before a linear finish estimate is worth categorising on.
# ~30% ≈ 10:40am. Before that, one meal divided by a sliver of elapsed day says
# whatever you want it to say.
_EXTRAPOLATION_FLOOR = 0.30

# The biggest single sitting worth asking for, per metric. This is what turns
# "behind" into either "reachable" or "at risk" — a 40g gap with two meals left
# is a plan, the same gap with none is a fact.
_PLAUSIBLE_PER_MEAL = {"protein": 65, "calories": 900}

# Meal windows. MUST match `MealWindow` in the iOS `DailyPlan.swift` — the client
# divides remaining protein by `meals_remaining` to size a next-meal ask, and if
# the two disagree the phone and the server print different grams for the same
# question.
_MEAL_WINDOWS = (
    ("breakfast", 4, 11, 3),
    ("lunch", 11, 16, 2),
    ("dinner", 16, 22, 1),
    ("late_night", 22, 28, 0),   # 22:00–03:59, wrapping midnight
)

# The day's end. Past this the day is CLOSED and the coordinator stops coaching
# toward it. Matches the production LOGGING_DAY_ROLLOVER_HOUR=4 so "today" means
# the same span here as it does at the write path.
DAY_ROLLOVER_HOUR = 4

OverallState = Literal[
    "calibrating", "building", "on_track", "at_risk",
    "recovering", "secured", "complete",
]

Trajectory = Literal[
    "not_calibrated", "ahead", "on_pace", "reachable", "at_risk", "secured",
]

Freshness = Literal[
    "live", "recently_updated", "partially_current",
    "waiting_for_sync", "no_wearable",
]


# ─────────────────────────────────────────────────────────────────────────────
# Input
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MealEvent:
    """One food entry, reduced to what the coordinator reasons about.

    `at` is what makes replay work — without a timestamp there is no way to ask
    "what did the day look like before this landed", and therefore no honest way
    to say a meal RESCUED anything.
    """
    at: datetime
    calories: int = 0
    protein: int = 0
    meal_type: Optional[str] = None


@dataclass(frozen=True)
class TrainingEvent:
    at: datetime
    name: str = ""
    is_cardio: bool = False


@dataclass(frozen=True)
class DayHistory:
    """A finished day. Evidence, never today."""
    date: str          # yyyy-mm-dd in the user's zone
    calories: int = 0
    protein: int = 0
    trained: bool = False


@dataclass(frozen=True)
class LiveInput:
    # `now` MUST be timezone-aware in the user's own zone. Every hour-of-day rule
    # below reads it, so a naive UTC datetime silently coaches someone in the
    # wrong part of their day — the exact class of bug that zeroed a user's day
    # at 12:15am once already.
    now: datetime

    calorie_target: Optional[int] = None
    calories_consumed: int = 0
    protein_target: Optional[int] = None
    protein_consumed: int = 0
    meals: tuple[MealEvent, ...] = ()

    workout_completed: bool = False
    cardio_completed: bool = False
    training_events: tuple[TrainingEvent, ...] = ()
    # `None` = Arnie knows of no planned session. NEVER read as "no workout
    # today" — silence is the correct response to a session it cannot see.
    planned_workout: Optional[str] = None
    # `None` = unknown. Only an explicit True suppresses training advice.
    is_rest_day: Optional[bool] = None

    weight_logged_today: bool = False
    tracks_weight: bool = True

    # Wearable / sync
    wearable_source: Optional[str] = None          # "whoop" | "oura" | "apple_health"
    wearable_updated_at: Optional[datetime] = None
    wearable_connected: bool = False
    # Straight from core.coaching_state — the recovery domain is ALREADY solved
    # there and re-deriving readiness here would be a second opinion nobody asked
    # for.
    readiness: Optional[str] = None                # optimal|good|moderate|reduced|recovery
    training_rec: Optional[str] = None             # full|moderate|light|rest|normal

    steps: Optional[int] = None
    steps_goal: Optional[int] = None

    history: tuple[DayHistory, ...] = ()
    # The user explicitly closed the day out.
    day_reviewed: bool = False

    # ── Derived ──────────────────────────────────────────────────────────────

    @property
    def hour(self) -> int:
        return self.now.hour

    @property
    def meal_window(self) -> str:
        h = self.hour if self.hour >= 4 else self.hour + 24
        for name, lo, hi, _ in _MEAL_WINDOWS:
            if lo <= h < hi:
                return name
        return "late_night"

    @property
    def meals_remaining(self) -> int:
        window = self.meal_window
        for name, _, _, remaining in _MEAL_WINDOWS:
            if name == window:
                return remaining
        return 0

    @property
    def trained_today(self) -> bool:
        return self.workout_completed or self.cardio_completed

    @property
    def day_progress(self) -> float:
        """How far through the WAKING day, 0…1, against a 05:00–24:00 span.

        Coarse on purpose. It positions a mark and scales a pace estimate; it is
        not a calculation anyone should read three decimals off.
        """
        h = self.hour + self.now.minute / 60
        if h < 5:
            return 1.0        # past midnight — the day is effectively spent
        return min(1.0, max(0.0, (h - 5) / 19))

    @property
    def eating_progress(self) -> float:
        """How far through the EATING day, 0…1, against 06:00–21:00.

        NOT `day_progress`, and the difference is not cosmetic. Nutrition
        extrapolated against a midnight denominator projects someone who has
        eaten 2,000 calories by 8pm to finish at 2,535 — because it assumes they
        keep eating at the day's average rate for four more hours. They don't;
        they finish dinner and stop. Measuring intake against the window in which
        intake actually happens is what stops the coordinator flagging a
        perfectly good evening as at risk.

        Steps keep the waking denominator — those really do accumulate until bed.
        """
        h = self.hour + self.now.minute / 60
        if h < 4:
            return 1.0        # past midnight: whatever is in, is in
        return min(1.0, max(0.0, (h - 6) / 15))

    @property
    def is_late_day(self) -> bool:
        return self.hour >= 18 or self.hour < 4

    @property
    def past_day_boundary(self) -> bool:
        return self.hour < DAY_ROLLOVER_HOUR

    @property
    def has_any_evidence(self) -> bool:
        """Anything at all Arnie can read about today."""
        return bool(
            self.meals
            or self.calories_consumed
            or self.weight_logged_today
            or self.trained_today
            or self.steps
        )


# ─────────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DomainState:
    """One domain's read. `state` is the vocabulary the UI switches on; every
    other field is context it may render but must never re-derive."""
    domain: str
    state: str
    current: Optional[int] = None
    target: Optional[int] = None
    expected_finish: Optional[int] = None
    # What still has to happen for this to land, in the domain's own units.
    intervention: Optional[int] = None
    # Rank among domains — lower is more limiting. `None` when not applicable.
    risk: Optional[float] = None
    detail: str = ""


@dataclass(frozen=True)
class Focus:
    domain: str
    action: str
    reason: str
    deadline: Optional[str] = None
    minimum: Optional[str] = None


@dataclass(frozen=True)
class Command:
    slot: str           # primary | explanation | planning
    type: str
    label: str
    context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RecentChange:
    type: str
    occurred_at: str
    before: str
    after: str
    cause: str
    summary: str


@dataclass(frozen=True)
class InsightBasis:
    """The CAUSAL material behind the focus — never the focus restated.

    Deliberately structured rather than prose: the coordinator establishes what
    is true and why, and the briefing layer writes the sentence. That split is
    what stops the LLM inventing a pattern the data does not support.
    """
    kind: str                    # pattern | constraint | tradeoff | cause
    subject: str
    evidence_n: int = 0
    evidence_window: str = ""
    typical_value: Optional[int] = None
    detail: str = ""


@dataclass(frozen=True)
class LiveState:
    overall_state: OverallState
    freshness: Freshness
    freshness_source: Optional[str]
    freshness_updated_at: Optional[str]
    domains: dict[str, DomainState]
    focus: Optional[Focus]
    commands: tuple[Command, ...]
    recent_change: Optional[RecentChange]
    insight: Optional[InsightBasis]
    next_reassessment: Optional[str]
    # The limiting domain — what the day currently hinges on.
    limiting_domain: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Qualification
# ─────────────────────────────────────────────────────────────────────────────

def qualifying_range(metric: str, target: Optional[int]):
    """The window a finished day must land in. `None` when there is no target —
    a user without one is not failing at it."""
    if not target or target <= 0:
        return None
    t = float(target)
    if metric == "protein":
        return (PROTEIN_FLOOR * t, None)
    return ((1 - CALORIE_TOLERANCE) * t, (1 + CALORIE_TOLERANCE) * t)


def qualifies(metric: str, value: int, target: Optional[int]) -> bool:
    """Did a FINISHED day land? `value == 0` is unlogged, not a catastrophic
    miss — an absent day must not drag a base rate down."""
    rng = qualifying_range(metric, target)
    if not rng or value <= 0:
        return False
    lo, hi = rng
    if value < lo:
        return False
    return hi is None or value <= hi


# ─────────────────────────────────────────────────────────────────────────────
# Nutrition trajectory
# ─────────────────────────────────────────────────────────────────────────────

def _trajectory(metric: str, consumed: int, target: Optional[int],
                inp: LiveInput) -> DomainState:
    """Where a nutrition metric is HEADING.

    Categorical by instruction: the internal pace ratio is precise enough to rank
    domains against each other, and nowhere near validated enough to print as a
    percentage.

    Protein is a FLOOR (more is never a miss); calories are a BAND (undereating
    misses as surely as overeating). Modelling both as "get to the number" tells
    someone at 900 of 2,200 they are doing fine at noon.
    """
    rng = qualifying_range(metric, target)
    if not rng:
        return DomainState(domain=metric, state="not_calibrated",
                           current=consumed, target=target,
                           detail="No target set.")
    lo, hi = rng

    if not inp.has_any_evidence:
        return DomainState(domain=metric, state="not_calibrated",
                           current=consumed, target=target,
                           intervention=int(max(0, lo - consumed)),
                           detail="Nothing logged yet today.")

    progress = inp.eating_progress
    expected = int(round(consumed / progress)) if progress >= 0.10 else None
    remaining = int(max(0, round(lo - consumed)))

    # Already decided, either way.
    if metric == "protein" and consumed >= lo:
        return DomainState(domain=metric, state="secured", current=consumed,
                           target=target, expected_finish=consumed,
                           intervention=0, risk=1.0,
                           detail="Banked for today.")
    if metric == "calories" and hi is not None and consumed > hi:
        return DomainState(domain=metric, state="at_risk", current=consumed,
                           target=target, expected_finish=consumed,
                           intervention=0, risk=0.0,
                           detail="Past the ceiling for today.")
    # Past the day boundary nothing more is being eaten — whatever it is now, it
    # is. A band metric can only settle here; before this, dinner is still ahead.
    if inp.past_day_boundary:
        landed = qualifies(metric, consumed, target)
        return DomainState(domain=metric,
                           state="secured" if landed else "at_risk",
                           current=consumed, target=target,
                           expected_finish=consumed, intervention=0,
                           risk=1.0 if landed else 0.0,
                           detail="The day is closed.")

    if expected is None:
        # Too early to extrapolate. An extrapolation from a sliver of the day is
        # a number with the shape of information and none of the content.
        return DomainState(domain=metric, state="not_calibrated",
                           current=consumed, target=target,
                           intervention=remaining,
                           detail="Too early to read a trajectory.")

    # EARLY IN THE DAY, PACE IS NOT A TRAJECTORY.
    #
    # Dividing one breakfast by 18% of the day extrapolates 45g of protein into
    # a 245g finish and reports it as "ahead" at 8:30 in the morning. The same
    # arithmetic in the other direction calls a late breakfast a crisis. Before
    # the day is far enough along, the only honest categories are "nothing has
    # gone wrong yet" and the HARD facts above (already past a ceiling, already
    # banked), which are checked before we get here.
    if progress < _EXTRAPOLATION_FLOOR:
        # And the estimate is WITHHELD, not merely disbelieved. Publishing
        # `expected_finish: 253` beside "too early to project a finish" invites
        # a client to render the number and ignore the caveat — the contract
        # would be contradicting itself in two adjacent fields.
        return DomainState(domain=metric, state="on_pace", current=consumed,
                           target=target, expected_finish=None,
                           intervention=remaining, risk=0.7,
                           detail="Too early to project a finish.")

    if hi is not None and expected > hi:
        # Overshooting. A band metric misses upward too.
        state, risk = "at_risk", 0.15
    elif expected >= lo:
        if hi is None and expected >= lo * 1.15:
            state, risk = "ahead", 0.85
        else:
            state, risk = "on_pace", 0.75
    else:
        # SHORT — but "short" is not the same as "lost". The question is whether
        # the remaining gap still fits in the meals the clock allows, which is
        # what separates a day worth intervening in from one worth writing off.
        per_meal = (remaining / inp.meals_remaining) if inp.meals_remaining else None
        if per_meal is not None and per_meal <= _PLAUSIBLE_PER_MEAL[metric]:
            state, risk = "reachable", 0.45
        else:
            state, risk = "at_risk", 0.2

    return DomainState(domain=metric, state=state, current=consumed,
                       target=target, expected_finish=expected,
                       intervention=remaining, risk=risk,
                       detail="")


# ─────────────────────────────────────────────────────────────────────────────
# Training / activity / recovery / weight
# ─────────────────────────────────────────────────────────────────────────────

def _training(inp: LiveInput) -> DomainState:
    """Training is a COMMITMENT domain: it is either done, open, or not asked
    for. It never scolds about a session Arnie cannot see."""
    if inp.trained_today:
        return DomainState(domain="training", state="complete", risk=1.0,
                           detail="Recorded for today.")
    if inp.is_rest_day is True:
        return DomainState(domain="training", state="rest_day", risk=1.0,
                           detail="Declared a rest day.")
    if inp.planned_workout is None:
        # Unknown, not overdue.
        return DomainState(domain="training", state="unscheduled", risk=None,
                           detail="No session on the program for today.")
    # A planned session that hasn't happened. The window narrowing is what makes
    # it urgent, not the mere fact of being unstarted.
    if inp.past_day_boundary:
        return DomainState(domain="training", state="missed", risk=0.0,
                           detail=f"{inp.planned_workout} did not happen.")
    risk = 0.25 if inp.is_late_day else 0.6
    return DomainState(domain="training", state="open", risk=risk,
                       detail=f"{inp.planned_workout} is still open.")


def _activity(inp: LiveInput) -> DomainState:
    """Activity is the RECOVERABLE domain — it is what keeps a day from
    collapsing when the planned session doesn't happen."""
    if inp.steps is None:
        return DomainState(domain="activity", state="unknown", risk=None,
                           detail="No step data synced.")
    goal = inp.steps_goal or 0
    if goal <= 0:
        return DomainState(domain="activity", state="tracking",
                           current=inp.steps, risk=None)
    progress = max(inp.day_progress, 0.01)
    expected = int(round(inp.steps / progress))
    if inp.steps >= goal:
        state, risk = "complete", 1.0
    elif expected >= goal:
        state, risk = "on_pace", 0.8
    elif expected >= goal * 0.7:
        state, risk = "behind", 0.5
    else:
        state, risk = "stalled", 0.3
    return DomainState(domain="activity", state=state, current=inp.steps,
                       target=goal, expected_finish=expected,
                       intervention=max(0, goal - inp.steps), risk=risk)


def _recovery(inp: LiveInput) -> DomainState:
    """Recovery MODIFIES the plan; it does not report biometrics.

    Reads `core.coaching_state`'s verdict rather than re-deriving readiness.
    """
    if not inp.readiness or inp.readiness == "unknown":
        return DomainState(domain="recovery", state="unknown", risk=None,
                           detail="No readiness signal today.")
    rec = (inp.training_rec or "normal").lower()
    modification = {
        "full": "plan_supported",
        "normal": "plan_supported",
        "moderate": "reduce_volume",
        "light": "reduce_intensity",
        "rest": "rest",
    }.get(rec, "plan_supported")
    return DomainState(domain="recovery", state=modification, risk=None,
                       detail=f"Readiness {inp.readiness}.")


def _weight(inp: LiveInput) -> DomainState:
    if not inp.tracks_weight:
        return DomainState(domain="weight", state="not_tracked", risk=None)
    if inp.weight_logged_today:
        return DomainState(domain="weight", state="logged", risk=1.0)
    # A missing weigh-in is only ACTIONABLE in the morning. By evening it is a
    # fact about the day, not a task, and the coordinator should stop asking.
    if inp.is_late_day or inp.hour >= 12:
        return DomainState(domain="weight", state="missed_window", risk=None,
                           detail="The comparable window has passed.")
    return DomainState(domain="weight", state="open", risk=0.7,
                       detail="The morning reading is the comparable one.")


# ─────────────────────────────────────────────────────────────────────────────
# Overall state
# ─────────────────────────────────────────────────────────────────────────────

def _minimums_met(domains: dict[str, DomainState], inp: LiveInput) -> bool:
    """The MINIMUM MEANINGFUL requirements for the day.

    Nutrition must have landed, and training must be either done, declared off,
    or never asked for. Deliberately does NOT require a weigh-in or a step goal:
    a day is secured by the things that move the outcome, not by every box.
    """
    nutrition_ok = all(
        domains[m].state in ("secured", "on_pace", "ahead")
        for m in ("protein", "calories")
        if domains[m].state != "not_calibrated"
    )
    # …but "not_calibrated everywhere" is not a secured day.
    if all(domains[m].state == "not_calibrated" for m in ("protein", "calories")):
        return False
    training_ok = domains["training"].state in ("complete", "rest_day", "unscheduled")
    return nutrition_ok and training_ok


def _overall(domains: dict[str, DomainState], inp: LiveInput,
             previous: Optional[OverallState]) -> OverallState:
    """The day's character, in one word.

    Order matters: the terminal states are checked first so a closed-out day
    can never be reported as `at_risk` and coached at.
    """
    if inp.day_reviewed:
        return "complete"
    if inp.past_day_boundary and inp.has_any_evidence:
        return "complete"

    if not inp.has_any_evidence:
        return "calibrating"

    # Any nutrition read still uncalibrated this early means we are still
    # gathering, not yet judging.
    if all(domains[m].state == "not_calibrated" for m in ("protein", "calories")):
        return "calibrating"

    if _minimums_met(domains, inp):
        return "secured"

    at_risk = any(
        d.state == "at_risk" for d in
        (domains["protein"], domains["calories"])
    ) or domains["training"].state == "missed"

    if at_risk:
        return "at_risk"

    # RECOVERING is only meaningful against a previous read. A day cannot
    # recover from nothing — see `replay_before`, which is where `previous`
    # comes from and why this needs no stored state.
    if previous == "at_risk":
        return "recovering"

    # Started, nothing broken, but real commitments still open.
    open_commitments = (
        domains["training"].state == "open"
        or any(domains[m].state in ("reachable",) for m in ("protein", "calories"))
    )
    if open_commitments:
        return "building"

    return "on_track"


# ─────────────────────────────────────────────────────────────────────────────
# Focus
# ─────────────────────────────────────────────────────────────────────────────

def _focus(domains: dict[str, DomainState], inp: LiveInput,
           overall: OverallState) -> Optional[Focus]:
    """The single action with the greatest expected benefit NOW.

    One commitment, never a checklist. Chosen by which domain is most limiting
    AND still actionable — a domain that cannot be changed today never becomes
    the focus, however bad it looks.
    """
    if overall == "complete":
        return None

    if not inp.has_any_evidence:
        return Focus(
            domain="nutrition", action="log_first_meal",
            reason="Nothing is logged yet, so today has no trajectory to coach against.",
            minimum="Anything protein-forward",
        )

    # A planned session with the window closing outranks a nutrition gap that
    # still has meals left to fix it — training cannot be caught up tomorrow the
    # way a macro can.
    training = domains["training"]
    if training.state == "open" and inp.is_late_day:
        return Focus(
            domain="training", action="start_workout",
            reason="The window to train is closing and the session is still open.",
            deadline=_clock(inp, 19, 30),
            minimum="A 20-minute version still counts",
        )

    candidates = [
        (domains["protein"], "nutrition", "log_meal"),
        (domains["calories"], "nutrition", "log_meal"),
        (domains["training"], "training", "start_workout"),
        (domains["weight"], "weight", "log_weight"),
    ]
    actionable = [
        (d, dom, act) for d, dom, act in candidates
        if d.risk is not None and d.state not in
        ("secured", "complete", "rest_day", "unscheduled", "logged",
         "missed_window", "not_tracked", "missed")
    ]
    if not actionable:
        if training.state == "open":
            return Focus(domain="training", action="start_workout",
                         reason="Nutrition is handled; the session is what is left.",
                         minimum="A 20-minute version still counts")
        return None

    worst, domain, action = min(actionable, key=lambda c: c[0].risk)

    if domain == "nutrition":
        need = worst.intervention or 0
        per_meal = _per_meal_ask(need, inp.meals_remaining)
        unit = "g" if worst.domain == "protein" else " cal"
        reason = (
            f"{worst.domain.capitalize()} is the limiting signal — "
            f"{need}{unit} still changes today's outcome."
        )
        return Focus(
            domain="nutrition", action=action, reason=reason,
            deadline=_clock(inp, 21, 0) if inp.meals_remaining <= 1 else None,
            minimum=(f"{per_meal}{unit} at the next meal" if per_meal else None),
        )

    if domain == "training":
        return Focus(domain="training", action="start_workout",
                     reason="The planned session hasn't been recorded yet.",
                     minimum="A 20-minute version still counts")

    return Focus(domain="weight", action="log_weight",
                 reason="The morning reading is the one that's comparable.",
                 deadline=_clock(inp, 12, 0))


def _per_meal_ask(remaining: int, meals_remaining: int) -> Optional[int]:
    """Round the remaining need across the meals the clock still allows.

    THE ONLY DIVISOR. iOS `DayTargets.proteinBand` divides by the same
    `meals_remaining`, which is why both surfaces print the same ask.
    """
    if remaining <= 0 or meals_remaining <= 0:
        return None
    return int(round(remaining / meals_remaining / 5.0) * 5)


def _clock(inp: LiveInput, hour: int, minute: int) -> str:
    return inp.now.replace(hour=hour, minute=minute, second=0,
                           microsecond=0).isoformat(timespec="minutes")


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

def _commands(domains: dict[str, DomainState], inp: LiveInput,
              focus: Optional[Focus], overall: OverallState) -> tuple[Command, ...]:
    """Three slots: do the thing, ask why, plan the next decision.

    Every command carries enough context to invoke a FOCUSED operation. A
    command that opens a blank chat has not saved the user anything.
    """
    out: list[Command] = []

    if focus:
        label = {
            "log_first_meal": "Log first meal",
            "log_meal": "Log meal",
            "start_workout": "Start workout",
            "log_weight": "Weigh in",
        }.get(focus.action, "Open")
        ctx: dict = {"domain": focus.domain}
        if focus.domain == "nutrition":
            protein = domains["protein"]
            ctx.update({
                "meal": inp.meal_window,
                "protein_needed": protein.intervention,
                "meals_remaining": inp.meals_remaining,
            })
        out.append(Command(slot="primary", type=focus.action,
                           label=label, context=ctx))

    # EXPLANATION — only when there is a live interpretation worth interrogating.
    # "Why is everything fine?" is not a question anyone asks.
    if overall in ("at_risk", "recovering", "building") and focus:
        limiting = focus.domain
        out.append(Command(
            slot="explanation", type="explain_state",
            label={
                "nutrition": "Why is this at risk?",
                "training": "Why does the session matter?",
                "weight": "Why weigh in now?",
            }.get(limiting, "Why this?"),
            context={"domain": limiting, "state": overall},
        ))

    # PLANNING — the next decision, not the current one.
    if inp.meals_remaining > 0 and domains["protein"].state != "secured":
        next_meal = {"breakfast": "lunch", "lunch": "dinner",
                     "dinner": "tomorrow", "late_night": "tomorrow"}[inp.meal_window]
        if next_meal != "tomorrow":
            protein = domains["protein"]
            out.append(Command(
                slot="planning", type="plan_meal",
                label=f"Plan {next_meal}",
                context={
                    "meal": next_meal,
                    "protein_needed": _per_meal_ask(protein.intervention or 0,
                                                    inp.meals_remaining),
                },
            ))
    elif overall in ("secured", "complete"):
        out.append(Command(slot="planning", type="prepare_tomorrow",
                           label="Prepare tomorrow", context={}))

    return tuple(out)


# ─────────────────────────────────────────────────────────────────────────────
# Insight basis
# ─────────────────────────────────────────────────────────────────────────────

def _insight(domains: dict[str, DomainState], inp: LiveInput,
             focus: Optional[Focus],
             previous: Optional[OverallState] = None) -> Optional[InsightBasis]:
    """WHY the focus was chosen — never the focus restated.

    "You should eat more protein because protein is low" is the failure mode.
    What earns its place is a fact the user could not read off the card: what
    their evening typically contributes, how many days back that holds, what
    that implies about the gap they are carrying.
    """
    if not focus:
        return None

    # A focus that MOVED deserves the explanation of why it moved. When the
    # limiting domain has just changed hands, the useful thing to say is what
    # stopped being the problem — not a fresh lecture about the new one.
    if focus.domain == "training" and previous is not None:
        protein = domains["protein"]
        if protein.state in ("secured", "on_pace", "ahead", "reachable"):
            return InsightBasis(
                kind="cause", subject="training",
                detail=("Protein is no longer the largest risk, so the session "
                        "is what the day now turns on."),
            )
        return InsightBasis(
            kind="constraint", subject="training",
            detail="The session is the only commitment that can't be caught up tomorrow.",
        )

    if focus.domain != "nutrition":
        return None

    protein = domains["protein"]
    need = protein.intervention or 0
    if need <= 0:
        return None

    # A DAY THAT HASN'T STARTED IS NOT A DAY THAT IS BEHIND.
    #
    # Before anything is logged, `need` is the entire daily target, and running
    # it through the gap analysis produced "carrying 162g into tonight makes the
    # target unreliable" at eight in the morning. That is technically arithmetic
    # and completely wrong as coaching: nothing has gone wrong, the user simply
    # hasn't eaten yet. What is true and useful at this hour is the LEVERAGE of
    # starting early, which is a different sentence entirely.
    if not inp.has_any_evidence:
        return InsightBasis(
            kind="tradeoff", subject="protein",
            detail=("Protein taken early costs nothing and shrinks what dinner "
                    "has to carry; left late it becomes the whole evening's job."),
        )

    typical = _typical_evening_protein(inp)
    if typical is not None and typical > 0:
        return InsightBasis(
            kind="pattern", subject="protein",
            evidence_n=len(_finished_days(inp)),
            evidence_window=f"last {len(_finished_days(inp))} days logged",
            typical_value=typical,
            detail=(
                f"Your evening typically contributes about {typical}g, "
                f"so carrying {need}g into tonight makes the target unreliable."
                if need > typical else
                f"Your evening typically contributes about {typical}g, "
                f"which covers the {need}g still outstanding."
            ),
        )

    # No history to lean on — say the constraint instead of inventing a pattern.
    return InsightBasis(
        kind="constraint", subject="protein",
        detail=(
            f"{need}g across {inp.meals_remaining} remaining "
            f"{'meal' if inp.meals_remaining == 1 else 'meals'}."
            if inp.meals_remaining else
            f"{need}g outstanding with no meal left to place it in."
        ),
    )


def _finished_days(inp: LiveInput) -> list[DayHistory]:
    """History excluding today. A partial day is not evidence about finished
    ones, and counting it drags every average down all morning."""
    today = inp.now.date().isoformat()
    return [d for d in inp.history if d.date < today and d.protein > 0]


def _typical_evening_protein(inp: LiveInput) -> Optional[int]:
    """What this user's day usually still has left to give after mid-afternoon.

    Approximated from finished-day TOTALS rather than from meal timestamps,
    because history carries totals only. Stated as a share of the daily total,
    which is honest about being an estimate and degrades to `None` rather than
    to a made-up number when there is too little to average.
    """
    days = _finished_days(inp)
    if len(days) < 4:
        return None
    avg_total = sum(d.protein for d in days) / len(days)
    # Dinner-share assumption, held as one named constant rather than sprinkled
    # through the copy. Deliberately conservative: over-promising the evening is
    # what would make the coordinator tell someone a gap is fine when it isn't.
    return int(round(avg_total * 0.35 / 5) * 5)


# ─────────────────────────────────────────────────────────────────────────────
# Freshness
# ─────────────────────────────────────────────────────────────────────────────

def _freshness(inp: LiveInput) -> tuple[Freshness, Optional[str], Optional[str]]:
    """Is Arnie working with current information?

    Presence and continuity — NOT the day's health verdict. The header must not
    become a second place the day gets judged.
    """
    if not inp.wearable_connected:
        return "no_wearable", None, None
    updated = inp.wearable_updated_at
    if updated is None:
        return "waiting_for_sync", inp.wearable_source, None
    age = inp.now - updated
    stamp = updated.isoformat(timespec="minutes")
    if age <= timedelta(minutes=30):
        return "live", inp.wearable_source, stamp
    if age <= timedelta(hours=4):
        return "recently_updated", inp.wearable_source, stamp
    if age <= timedelta(hours=24):
        return "partially_current", inp.wearable_source, stamp
    return "waiting_for_sync", inp.wearable_source, stamp


# ─────────────────────────────────────────────────────────────────────────────
# Replay — how `recovering` and `recent_change` work without stored state
# ─────────────────────────────────────────────────────────────────────────────

def replay_before(inp: LiveInput, moment: datetime) -> LiveInput:
    """The same day as it stood immediately BEFORE `moment`.

    THE TRICK THIS MODULE TURNS ON. Because `compute` is a pure function of the
    facts, "what was the state before lunch landed" is answerable by removing
    lunch and running it again. No event table, no writer, no migration, and —
    the part that matters — no possibility of the stored history disagreeing
    with the live computation, because there is no stored history.

    The clock is rolled back too. Replaying at the CURRENT hour would compare a
    2pm state against an 8pm one and attribute the whole difference to the meal.
    """
    kept = tuple(m for m in inp.meals if m.at < moment)
    kept_training = tuple(t for t in inp.training_events if t.at < moment)
    return replace(
        inp,
        now=moment - timedelta(seconds=1),
        meals=kept,
        calories_consumed=sum(m.calories for m in kept),
        protein_consumed=sum(m.protein for m in kept),
        training_events=kept_training,
        workout_completed=any(not t.is_cardio for t in kept_training),
        cardio_completed=any(t.is_cardio for t in kept_training),
    )


def _last_event(inp: LiveInput) -> Optional[tuple[datetime, str, str]]:
    """The most recent thing that could have changed the day."""
    events: list[tuple[datetime, str, str]] = []
    for m in inp.meals:
        events.append((m.at, "meal_logged", m.meal_type or "meal"))
    for t in inp.training_events:
        events.append((t.at, "training_logged", t.name or "training"))
    if not events:
        return None
    return max(events, key=lambda e: e[0])


_STATE_SUMMARY = {
    ("calibrating", "building"): "{cause} established today's trajectory",
    ("at_risk", "recovering"): "{cause} pulled the day back on pace",
    ("at_risk", "on_track"): "{cause} pulled the day back on pace",
    ("at_risk", "secured"): "{cause} secured the day",
    ("building", "secured"): "{cause} secured the day",
    ("building", "at_risk"): "the day drifted after {cause}",
    ("on_track", "at_risk"): "the day drifted after {cause}",
    ("building", "on_track"): "{cause} put the day on pace",
    ("recovering", "secured"): "{cause} secured the day",
}


def _recent_change(inp: LiveInput, current: OverallState,
                   previous: Optional[OverallState],
                   moment: Optional[datetime],
                   cause: Optional[str]) -> Optional[RecentChange]:
    """The last event that CHANGED the day.

    An event that changed nothing produces no entry: a feed row saying "you
    logged a snack and nothing happened" is noise, and the reinforcement layer
    only reinforces if it reports consequences.
    """
    if previous is None or moment is None or previous == current:
        return None
    label = (cause or "the last entry").replace("_", " ")
    template = _STATE_SUMMARY.get((previous, current))
    summary = (template.format(cause=label).capitalize() if template
               else f"{label.capitalize()} moved the day from {previous} to {current}")
    return RecentChange(
        type="overall_state_changed",
        occurred_at=moment.isoformat(timespec="minutes"),
        before=previous, after=current,
        cause=cause or "entry",
        summary=summary,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _domains(inp: LiveInput) -> dict[str, DomainState]:
    return {
        "protein": _trajectory("protein", inp.protein_consumed,
                               inp.protein_target, inp),
        "calories": _trajectory("calories", inp.calories_consumed,
                                inp.calorie_target, inp),
        "training": _training(inp),
        "activity": _activity(inp),
        "recovery": _recovery(inp),
        "weight": _weight(inp),
    }


def _state_only(inp: LiveInput, previous: Optional[OverallState] = None) -> OverallState:
    return _overall(_domains(inp), inp, previous)


def compute(inp: LiveInput) -> LiveState:
    """The one interpretation of the day."""
    domains = _domains(inp)

    # Replay to the moment before the last event, so `recovering` and
    # `recent_change` both rest on a real prior read rather than on stored state.
    previous: Optional[OverallState] = None
    last = _last_event(inp)
    if last is not None:
        moment, _kind, cause = last
        previous = _state_only(replay_before(inp, moment))
    else:
        moment, cause = None, None

    overall = _overall(domains, inp, previous)
    focus = _focus(domains, inp, overall)
    commands = _commands(domains, inp, focus, overall)
    insight = _insight(domains, inp, focus, previous)
    freshness, source, updated = _freshness(inp)

    # THE LIMITING DOMAIN, AND WHEN THERE ISN'T ONE.
    #
    # On a calibrating day the nutrition domains carry no risk score (there is
    # nothing to score), so the ranking fell through to whichever domain
    # happened to have one — reporting `limiting_domain: training` on a day whose
    # focus was "log your first meal". Nothing limits a day that hasn't started,
    # and nothing limits one that is already closed.
    limiting = None
    if overall not in ("calibrating", "complete"):
        ranked = [d for d in domains.values() if d.risk is not None]
        if ranked:
            limiting = min(ranked, key=lambda d: d.risk).domain

    return LiveState(
        overall_state=overall,
        freshness=freshness,
        freshness_source=source,
        freshness_updated_at=updated,
        domains=domains,
        focus=focus,
        commands=commands,
        recent_change=_recent_change(inp, overall, previous, moment, cause),
        insight=insight,
        next_reassessment=_next_reassessment(inp),
        limiting_domain=limiting,
    )


def _next_reassessment(inp: LiveInput) -> Optional[str]:
    """When this read stops being current — the RETURN TRIGGER.

    The next boundary at which the coordinator would reach a different
    conclusion for reasons of time alone, so the client knows when to come back
    rather than polling.
    """
    boundaries = [11, 16, 19, 22]
    for h in boundaries:
        if inp.hour < h:
            return _clock(inp, h, 0)
    nxt = (inp.now + timedelta(days=1)).replace(
        hour=DAY_ROLLOVER_HOUR, minute=0, second=0, microsecond=0)
    return nxt.isoformat(timespec="minutes")


# ─────────────────────────────────────────────────────────────────────────────
# Wire shape
# ─────────────────────────────────────────────────────────────────────────────

def to_wire(state: LiveState, generated_at: datetime) -> dict:
    """The `/api/v1/coach/live` body. One contract; every section reads from it."""
    def dom(d: DomainState) -> dict:
        return {
            "state": d.state,
            "current": d.current,
            "target": d.target,
            "expected_finish": d.expected_finish,
            "intervention": d.intervention,
            "detail": d.detail or None,
        }

    return {
        "v": 1,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "freshness": {
            "state": state.freshness,
            "primary_source": state.freshness_source,
            "updated_at": state.freshness_updated_at,
        },
        "overall_state": state.overall_state,
        "limiting_domain": state.limiting_domain,
        "commands": [
            {"slot": c.slot, "type": c.type, "label": c.label, "context": c.context}
            for c in state.commands
        ],
        "focus": (None if not state.focus else {
            "domain": state.focus.domain,
            "action": state.focus.action,
            "reason": state.focus.reason,
            "deadline": state.focus.deadline,
            "minimum": state.focus.minimum,
        }),
        "insight": (None if not state.insight else {
            "kind": state.insight.kind,
            "subject": state.insight.subject,
            "evidence_n": state.insight.evidence_n,
            "evidence_window": state.insight.evidence_window or None,
            "typical_value": state.insight.typical_value,
            "detail": state.insight.detail,
        }),
        "domains": {k: dom(v) for k, v in state.domains.items()},
        "recent_change": (None if not state.recent_change else {
            "type": state.recent_change.type,
            "occurred_at": state.recent_change.occurred_at,
            "before": state.recent_change.before,
            "after": state.recent_change.after,
            "cause": state.recent_change.cause,
            "summary": state.recent_change.summary,
        }),
        "next_reassessment": state.next_reassessment,
    }
