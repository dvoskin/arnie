"""
Strength standards — bodyweight-scaled 1RM benchmarks per lift.

Gives an estimated 1RM the context a coach would: is this a novice, intermediate,
or advanced number *for this person's bodyweight and sex*? A 225 lb bench means
something very different at 150 lb vs 250 lb bodyweight.

Standards are expressed as multiples of bodyweight (estimated 1RM ÷ bodyweight),
which is how strength is normalized across people. Values are approximate,
consensus-style thresholds drawn from the common strength-standard tables
(ExRx / StrengthLevel-style). They are benchmarks, not verdicts — framed with the
same calibrated humility as the rest of Arnie (an estimate, not a certified max).

Only the classic barbell lifts have well-established standards; accessory work
does not, so those movements simply carry no `standard` (the PR still shows, just
without a tier). Keyed by the canonical names in
`skills/fitness/exercise_catalog.py`.
"""
from __future__ import annotations

from typing import Optional

# 1RM as a multiple of bodyweight. (novice, intermediate, advanced).
# "beginner" is anything below novice; "elite" territory sits above advanced but
# we cap the ladder at the three tiers the card surfaces.
_STANDARDS: dict[str, dict[str, tuple[float, float, float]]] = {
    # canonical name → sex → (novice, intermediate, advanced)
    "Bench Press":            {"male": (0.75, 1.25, 1.75), "female": (0.40, 0.70, 1.05)},
    "Incline Bench Press":    {"male": (0.60, 1.00, 1.45), "female": (0.32, 0.58, 0.88)},
    "Close-Grip Bench Press": {"male": (0.60, 1.00, 1.45), "female": (0.32, 0.58, 0.88)},
    "Overhead Press":         {"male": (0.55, 0.80, 1.15), "female": (0.30, 0.50, 0.75)},
    "Back Squat":             {"male": (1.25, 1.75, 2.50), "female": (0.90, 1.35, 1.90)},
    "Front Squat":            {"male": (1.00, 1.40, 1.90), "female": (0.70, 1.05, 1.50)},
    "Deadlift":               {"male": (1.50, 2.00, 2.75), "female": (1.10, 1.50, 2.10)},
    "Romanian Deadlift":      {"male": (1.20, 1.70, 2.30), "female": (0.85, 1.25, 1.75)},
    "Barbell Row":            {"male": (0.75, 1.10, 1.50), "female": (0.50, 0.75, 1.05)},
    "Hip Thrust":             {"male": (1.50, 2.25, 3.00), "female": (1.20, 1.80, 2.50)},
    "Leg Press":              {"male": (2.00, 3.00, 4.00), "female": (1.50, 2.30, 3.20)},
}

_KG_TO_LB = 2.20462


def has_standard(canonical: str) -> bool:
    return canonical in _STANDARDS


def classify(
    canonical: str,
    e1rm_kg: float,
    bodyweight_kg: Optional[float],
    sex: Optional[str],
) -> Optional[dict]:
    """Place an estimated 1RM against bodyweight-scaled standards.

    Returns a dict with the three tier thresholds (in lbs), the level this lift
    currently sits at, the next level up, and how much is left to reach it — or
    None when there's no standard for the lift, no bodyweight on file, or the
    numbers don't make sense.
    """
    table = _STANDARDS.get(canonical)
    if not table or not bodyweight_kg or bodyweight_kg <= 0 or e1rm_kg <= 0:
        return None

    # Default to male standards when sex is unknown (the larger table); it's a
    # benchmark, and the user can read the absolute thresholds regardless.
    key = "female" if (sex or "").strip().lower().startswith("f") else "male"
    nov_m, int_m, adv_m = table[key]

    nov_kg = nov_m * bodyweight_kg
    int_kg = int_m * bodyweight_kg
    adv_kg = adv_m * bodyweight_kg

    if e1rm_kg >= adv_kg:
        level, next_level, to_next_kg = "advanced", None, 0.0
    elif e1rm_kg >= int_kg:
        level, next_level, to_next_kg = "intermediate", "advanced", adv_kg - e1rm_kg
    elif e1rm_kg >= nov_kg:
        level, next_level, to_next_kg = "novice", "intermediate", int_kg - e1rm_kg
    else:
        level, next_level, to_next_kg = "beginner", "novice", nov_kg - e1rm_kg

    return {
        "level": level,
        "next_level": next_level,
        "to_next_lbs": round(to_next_kg * _KG_TO_LB, 1),
        "novice_lbs": round(nov_kg * _KG_TO_LB),
        "intermediate_lbs": round(int_kg * _KG_TO_LB),
        "advanced_lbs": round(adv_kg * _KG_TO_LB),
    }
