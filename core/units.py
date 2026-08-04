"""One place that knows what a pound is.

Measured on 2026-08-04 (`scripts/food_identity_inventory.py --conversions`):
`2.20462` appeared at 69 sites across 16 modules, `0.45359` at 5 more, and
there was no units module anywhere. The literal was written out at each call
site in `api/app.py` (15), `handlers/tool_executor.py` (10),
`api/native_data.py` (7), `api/exercise_edit.py` (6), `core/targets.py` (5),
`core/context_builder.py` (5), plus `strength_prs`, `session_state` and
`memory_moments` — spanning weight, height, strength and nutrition.

That is the single largest measured duplication in the codebase, and it is the
one the cross-domain audit found genuinely shared: seven of the eight non-food
domains had no language-layer anti-patterns at all, but every one of them
converts units.

WHY THE VALUES HERE ARE THE OLD ONES, TO THE DIGIT. The international
avoirdupois pound is exactly 0.45359237 kg, so the honest constant for kg->lb
is 2.204622621…, not 2.20462. Using it would be more correct and would change
numbers on a migration whose entire purpose is to change none — every
subsequent test failure would then need triaging as "real bug or sixth-decimal
drift?" So this module reproduces what the call sites did, exactly, and
promoting the constants to their defined values is a separate, deliberate
change with its own commit and its own review of what it moves.

`_EXACT` records the true values so that change is a diff and not a research
task.
"""
from __future__ import annotations

# ── mass ─────────────────────────────────────────────────────────────────────
#: kg -> lb. What 69 call sites wrote inline.
LB_PER_KG = 2.20462
#: lb -> kg. NOT 1/LB_PER_KG — that is 0.4535918…, while the call sites wrote
#: 0.453592, which is both what they do and the closer of the two to the
#: defined 0.45359237. Kept apart so the migration stays numerically identical;
#: they reconcile in `_EXACT`.
#:
#: This constant was 0.45359 for one commit, because the audit regex that found
#: these sites was `0\.45359\b` and `\b` cannot match between "9" and "2" — so
#: every `0.453592` site was invisible to it AND the shorter value looked like
#: the one in use. Adopting it would have shifted four user WEIGHT-WRITE paths
#: in api/app.py by 4.4e-6 relative. Small, real, and on exactly the kind of
#: path where a silent change is least acceptable.
KG_PER_LB = 0.453592
#: g -> oz, and the one place two spellings were in use (28.3495 at 7 sites,
#: 28.35 at 4). The longer one wins because it is the closer of the two.
G_PER_OZ = 28.3495

# ── length ───────────────────────────────────────────────────────────────────
CM_PER_IN = 2.54

# ── volume ───────────────────────────────────────────────────────────────────
ML_PER_FLOZ = 29.5735

#: The defined values, for the follow-up change that adopts them. Kept here so
#: "what should these be?" is already answered and the only open question is
#: what adopting them moves.
_EXACT = {
    "KG_PER_LB": 0.45359237,      # exact by definition (1959 agreement)
    "LB_PER_KG": 1.0 / 0.45359237,
    "G_PER_OZ": 28.349523125,
    "CM_PER_IN": 2.54,            # exact already
    "ML_PER_FLOZ": 29.5735295625,
}


def kg_to_lb(kg: float) -> float:
    """Kilograms to pounds. Unrounded — rounding is a presentation decision and
    belongs to whoever is doing the presenting."""
    return kg * LB_PER_KG


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB


def g_to_oz(g: float) -> float:
    return g / G_PER_OZ


def oz_to_g(oz: float) -> float:
    return oz * G_PER_OZ


def cm_to_in(cm: float) -> float:
    return cm / CM_PER_IN


def in_to_cm(inches: float) -> float:
    return inches * CM_PER_IN


def ml_to_floz(ml: float) -> float:
    return ml / ML_PER_FLOZ


def floz_to_ml(floz: float) -> float:
    return floz * ML_PER_FLOZ
