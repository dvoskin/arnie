"""Phase 3 plausibility backstop — as an INVARIANT, not an example.

Prod fe#2705 (2026-08-03, build d117581): "1 cup rice" — the interpreter said 205
cal; the resolver's EXACT-grade lookup priced ~1 gram and committed **1 cal**.
P1's identity gate let it through because identity says WHICH food, not whether
the VALUE is sane. Phase 2 measured the line: past ~5x an override is always a
unit slip or mis-bind (interp won 8/8), while the useful 2-5x corrections (Royo
bagel 290→80, multi-can drinks) sit below it.

The invariant these tests pin: **no lookup may move committed calories by >= the
cap (default 5x) — for ANY food, ANY direction, ANY verified grade — unless the
source is the user's own data.** Not one test per incident food; a sweep over the
ratio space, so the next 1-cal cup is caught by construction.
"""
from types import SimpleNamespace

import pytest

import skills.nutrition.promotion as P


class _Nutrients:
    def __init__(self, **kw):
        self._d = kw

    def amount(self, key):
        return self._d.get(key)

    def unknown(self):
        return []


def _resolution(source="usda", cal=100, grade="exact"):
    return SimpleNamespace(
        source=source, match_grade=grade,
        nutrients=_Nutrients(calories=cal, protein=1, carbs=1, fat=1),
        tier=None, confidence=0.9, is_estimate=False, source_id=None)


def _legacy(cal, source="estimate"):
    return SimpleNamespace(
        source=source, enrichment_source=source, calories=cal,
        provenance=None, micros=None, micros_estimated=False,
        fiber=None, sugar=None, sodium=None)


@pytest.fixture(autouse=True)
def _owns(monkeypatch):
    monkeypatch.setattr(P, "owns_committed_values", lambda uid=None: True)
    # The promoted analysis carries the RESOLUTION's calories, so the ratio the
    # backstop sees is the real move it would commit.
    def _fake_to_analysis(resolution, *, food_name, quantity, legacy):
        return SimpleNamespace(calories=resolution.nutrients.amount("calories"),
                               source=resolution.source)
    monkeypatch.setattr(P, "to_food_analysis", _fake_to_analysis)


def _promote(res, leg):
    return P.promote(res, food_name="any food", quantity="1 serving",
                     legacy=leg, user_id=26)


# ── the invariant, swept ─────────────────────────────────────────────────────
@pytest.mark.parametrize("legacy_cal,lookup_cal", [
    (205, 1),        # the 1-cal cup of rice (205x down) — the prod incident
    (205, 41),       # 5x down, boundary
    (150, 2450),     # the shrimp class (16x up)
    (33, 1650),      # the eggplant class (50x up)
    (90, 1),         # Sun Chips class (90x down)
    (100, 500),      # exactly 5x up
    (100, 2000),     # 20x up
])
def test_no_verified_lookup_may_move_calories_past_the_cap(legacy_cal, lookup_cal):
    """EXACT identity, absurd value → the interpreter's baseline stands."""
    leg = _legacy(legacy_cal)
    out = _promote(_resolution(cal=lookup_cal, grade="exact"), leg)
    assert out is leg, (legacy_cal, lookup_cal)


@pytest.mark.parametrize("legacy_cal,lookup_cal", [
    (290, 80),       # Royo bagel — the correction the resolver exists for (3.6x)
    (100, 420),      # multi-can drink class (4.2x)
    (150, 210),      # ordinary refinement (1.4x)
    (205, 205),      # agreement
    (100, 60),       # modest down-correction
])
def test_useful_corrections_below_the_cap_still_promote(legacy_cal, lookup_cal):
    out = _promote(_resolution(cal=lookup_cal, grade="exact"), _legacy(legacy_cal))
    assert out is not None and out.calories == lookup_cal


def test_users_own_data_is_exempt_at_any_ratio():
    """A value the user confirmed wins even 20x out — their word beats our math."""
    out = _promote(_resolution(source="memory", cal=5, grade="category"),
                   _legacy(100))
    assert out.calories == 5


def test_cap_is_tunable_and_zero_disables(monkeypatch):
    monkeypatch.setenv("FOOD_PLAUSIBILITY_CAP", "3")
    leg = _legacy(290)
    assert _promote(_resolution(cal=80, grade="exact"), leg) is leg  # 3.6x > 3
    monkeypatch.setenv("FOOD_PLAUSIBILITY_CAP", "0")
    assert _promote(_resolution(cal=1, grade="exact"), _legacy(205)).calories == 1
    monkeypatch.setenv("FOOD_PLAUSIBILITY_CAP", "garbage")
    assert P.plausibility_cap() == pytest.approx(5.0)


def test_no_baseline_means_no_ratio_and_no_block():
    """Legacy 0/None calories → nothing to protect; the lookup may stand."""
    out = _promote(_resolution(cal=205, grade="exact"), _legacy(0))
    assert out.calories == 205


def test_the_decline_keeps_identity_gate_semantics():
    """CATEGORY grade still declines on identity (P1) before value is even
    considered — the backstop tightens, never loosens."""
    leg = _legacy(150)
    out = _promote(_resolution(cal=160, grade="category"), leg)
    assert out is leg
