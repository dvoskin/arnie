"""
CoachingState — computes a structured training readiness assessment
from all available wearable and health data.

Injected into every conversation context as [COACHING STATE].
Every skill and the system prompt reads this to adjust recommendations.

Readiness levels:
    optimal   → 80+ recovery, HRV at/above baseline, good sleep
    good      → 60-79 recovery, minor fatigue ok
    moderate  → 40-59 recovery, reduce volume/intensity ~20%
    reduced   → 20-39 recovery, light session only
    recovery  → <20 recovery or >10% HRV drop, rest day recommended
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


@dataclass
class CoachingState:
    readiness: str = "unknown"          # optimal | good | moderate | reduced | recovery | unknown
    readiness_score: int = 0            # 0-100 composite
    training_rec: str = "normal"        # full | moderate | light | rest | normal
    calorie_adjustment: int = 0         # +/- kcal from daily target
    hrv_trend: str = "unknown"          # improving | stable | declining | unknown
    key_signals: list[str] = field(default_factory=list)
    data_freshness: str = "stale"       # live | today | yesterday | stale
    sources: list[str] = field(default_factory=list)

    def to_context_string(self) -> str:
        """Render as [COACHING STATE] block for injection into system prompt."""
        if self.readiness == "unknown" or not self.sources:
            return ""

        lines = ["[COACHING STATE]"]
        lines.append(f"  Readiness: {self.readiness.upper()} ({self.readiness_score}/100)")
        lines.append(f"  Training: {self.training_rec.upper()}")

        if self.calorie_adjustment != 0:
            sign = "+" if self.calorie_adjustment > 0 else ""
            lines.append(f"  Calorie adjustment: {sign}{self.calorie_adjustment} kcal from target")

        if self.hrv_trend != "unknown":
            lines.append(f"  HRV trend: {self.hrv_trend}")

        if self.key_signals:
            lines.append(f"  Signals: {' | '.join(self.key_signals)}")

        lines.append(f"  Data: {self.data_freshness} ({', '.join(self.sources)})")
        return "\n".join(lines)


def compute_coaching_state(
    health_snapshots: list,
    recent_logs: list,
    user,
) -> CoachingState:
    """
    Compute CoachingState from available health data.

    health_snapshots: recent HealthSnapshot rows (newest first)
    recent_logs:      recent DailyLog rows
    user:             User model instance
    """
    state = CoachingState()

    if not health_snapshots:
        return state

    latest = health_snapshots[0]
    today = date.today()

    # ── Data freshness ────────────────────────────────────────────────────────
    if latest.date == today:
        state.data_freshness = "today"
    elif latest.date == today - timedelta(days=1):
        state.data_freshness = "yesterday"
    else:
        state.data_freshness = "stale"

    # ── Sources ───────────────────────────────────────────────────────────────
    if latest.source:
        state.sources.append(latest.source.replace("_", " ").title())

    # ── Primary readiness signal (Whoop recovery score is most reliable) ──────
    recovery = latest.recovery_score
    signals = []
    score = 50  # default neutral

    if recovery is not None:
        score = recovery
        if recovery >= 80:
            state.readiness = "optimal"
            state.training_rec = "full"
        elif recovery >= 60:
            state.readiness = "good"
            state.training_rec = "full"
        elif recovery >= 40:
            state.readiness = "moderate"
            state.training_rec = "moderate"
            signals.append(f"recovery {recovery}%")
        elif recovery >= 20:
            state.readiness = "reduced"
            state.training_rec = "light"
            signals.append(f"recovery {recovery}% (reduced)")
        else:
            state.readiness = "recovery"
            state.training_rec = "rest"
            signals.append(f"recovery {recovery}% (rest day)")

    # ── HRV signal ────────────────────────────────────────────────────────────
    if latest.hrv is not None:
        # Compute personal HRV baseline from last 7 days
        hrv_values = [
            s.hrv for s in health_snapshots[:7]
            if s.hrv is not None
        ]
        if len(hrv_values) >= 3:
            baseline = sum(hrv_values[1:]) / len(hrv_values[1:])  # exclude today
            today_hrv = latest.hrv
            pct_diff = (today_hrv - baseline) / baseline * 100 if baseline > 0 else 0

            if pct_diff >= 5:
                state.hrv_trend = "improving"
            elif pct_diff <= -10:
                state.hrv_trend = "declining"
                signals.append(f"HRV {abs(pct_diff):.0f}% below baseline")
                # Downgrade readiness one level if HRV is significantly depressed
                if state.readiness in ("optimal", "good") and pct_diff <= -15:
                    state.readiness = "moderate"
                    state.training_rec = "moderate"
            else:
                state.hrv_trend = "stable"

    # ── Sleep signal ──────────────────────────────────────────────────────────
    if latest.sleep_hours is not None:
        if latest.sleep_hours < 6.0:
            signals.append(f"sleep {latest.sleep_hours:.1f}h (low)")
            # Poor sleep downgrades readiness
            if state.readiness == "optimal":
                state.readiness = "good"
            elif state.readiness == "good":
                state.readiness = "moderate"
                state.training_rec = "moderate"
        elif latest.sleep_hours >= 8.0:
            signals.append(f"sleep {latest.sleep_hours:.1f}h (strong)")

    # ── Strain/load signal (Whoop) ────────────────────────────────────────────
    if latest.strain is not None:
        if latest.strain >= 18:
            signals.append(f"yesterday strain {latest.strain:.1f}/21 (high)")
            # High strain yesterday means more recovery needed today
            if state.readiness in ("optimal", "good"):
                state.readiness = "moderate" if state.readiness == "optimal" else "moderate"
                state.training_rec = "moderate"

    # ── Calorie adjustment based on activity and recovery ────────────────────
    if state.training_rec == "full" and latest.strain and latest.strain >= 15:
        state.calorie_adjustment = +150  # high activity — eat more
    elif state.training_rec == "rest":
        state.calorie_adjustment = -100  # rest day — slightly less
    elif state.training_rec == "light":
        state.calorie_adjustment = -50

    # ── Consecutive training days check ──────────────────────────────────────
    if recent_logs:
        consecutive = 0
        check_date = today - timedelta(days=1)
        log_dates = {l.date for l in recent_logs if l.workout_completed}
        while check_date in log_dates:
            consecutive += 1
            check_date -= timedelta(days=1)
        if consecutive >= 5:
            signals.append(f"{consecutive} consecutive training days")
            if state.readiness not in ("reduced", "recovery"):
                state.readiness = "moderate"
                state.training_rec = "moderate"

    state.readiness_score = score
    state.key_signals = signals[:4]  # cap at 4 most important signals

    return state
