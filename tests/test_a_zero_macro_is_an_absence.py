"""A macro of zero is questioned the way a calorie count of zero is.

Audit T-4. `reconcile_macros` rebalances multiplicatively, so `fat * scale`
keeps a zero at zero for every scale and the entire shortfall is pushed into
whichever macro happened to be non-zero.

From production: a chocolate sweet roll submitted at 210 cal / 20 P / 24 C /
0 F came back `(210, 20, 32.5, 0.0)`. Twenty grams of protein and twenty-four
of carbohydrate account for 176 calories; the other 34 — about 3.8 g of fat —
were turned into carbohydrate, and the item shipped fat-free on a product that
cannot be.

This is the butter-at-zero-calories shape (`aad3416`) one level down. That fix
taught the system to doubt a zero CALORIE count. A zero MACRO had the identical
hole, and `sanity.check_values` bounds energy density from ABOVE only — so a
too-low macro passes every check in the lane.
"""
import pytest

from core.food_intelligence import (reconcile_macros,
                                    reconcile_macros_traced)


def _macro_cal(protein, carbs, fat):
    return protein * 4 + carbs * 4 + fat * 9


# ── the defect ────────────────────────────────────────────────────────────────

def test_the_sweet_roll_gets_its_fat_back():
    """The interpreter never supplied fat — `_log_call` omits an absent macro —
    so it arrives as None, and that is the case where placing is honest."""
    cal, protein, carbs, fat = reconcile_macros(210, 20, 24, None)
    assert fat > 0, "34 unexplained calories on a chocolate roll are not carbs"
    assert fat == pytest.approx(3.8, abs=0.2)
    # And the carbohydrate was left alone rather than inflated to cover it.
    assert carbs == 24
    assert _macro_cal(protein, carbs, fat) == pytest.approx(cal, abs=2)


def test_it_works_the_other_way_round():
    """Nothing about this is fat-specific — a missing carb count has the same
    shape, and a rule that only knew about fat would be a coincidence."""
    cal, protein, carbs, fat = reconcile_macros(210, 20, None, 10)
    assert carbs > 0
    assert fat == 10, "the macro we DO have is not the one to adjust"
    assert _macro_cal(protein, carbs, fat) == pytest.approx(cal, abs=2)


# ── and what must not change ──────────────────────────────────────────────────

def test_a_genuinely_fat_free_food_is_left_alone():
    """Egg whites really are fat-free. The 15% consistency band is what
    protects them, and this branch is only reachable once the macros are
    already inconsistent — so the guard must not reach past it."""
    assert reconcile_macros(100, 21, 2, 0) == (100, 21, 2, 0)


def test_a_shortfall_too_small_to_be_a_gram_still_scales():
    """Placing 0.2 g of fat is false precision. Below a whole gram the old
    proportional rebalance is the honest answer."""
    _, _, _, fat = reconcile_macros(200, 20, 29, None)
    assert fat == 0


def test_both_macros_missing_still_falls_to_carbs():
    """The pre-existing residual path, unchanged — with nothing to compare
    against there is no reason to prefer fat."""
    cal, protein, carbs, fat = reconcile_macros(200, 10, 0, 0)
    assert fat == 0 and carbs > 0
    assert _macro_cal(protein, carbs, fat) == pytest.approx(cal, abs=2)


def test_protein_over_budget_still_scales_everything():
    cal, protein, carbs, fat = reconcile_macros(100, 40, 10, 5)
    assert protein < 40
    assert _macro_cal(protein, carbs, fat) == pytest.approx(cal, abs=2)


@pytest.mark.parametrize("args", [
    (0, 0, 0, 0), (210, 0, 0, 0), (-5, 1, 1, 1),
])
def test_degenerate_input_is_returned_untouched(args):
    assert reconcile_macros(*args) == args


# ── absent is not zero (audit T-4, item 9) ────────────────────────────────────

def test_a_stated_zero_is_not_overwritten():
    """A source that says "fat: 0" has made a claim.

    Replacing it with 3.8 g invents a fact against evidence — the same error as
    trusting the zero, aimed the other way. `float(x or 0)` in `analyze` used to
    collapse absent into zero one line before the only code that could tell them
    apart, which is what made "fat = 0" unfalsifiable.
    """
    _, _, carbs, fat = reconcile_macros(210, 20, 24, 0)
    assert fat == 0, "a stated zero survives"
    assert carbs > 24, "the residual goes where it always did"


def test_analyze_no_longer_collapses_absent_into_zero():
    from core.food_intelligence import analyze
    kw = dict(usda_candidate=None, memory_match=None, web_candidate=None)
    absent = analyze("roll", "1 roll", 210, 20, 24, None, **kw)
    stated = analyze("roll", "1 roll", 210, 20, 24, 0, **kw)
    assert (absent.calories, absent.fat) != (stated.calories, stated.fat)


# ── it reports what it moved (audit T-4, item 10) ─────────────────────────────

def test_a_material_move_is_reported():
    """`sanity`'s Atwater check fires at 30% drift and this fires at 15%, so the
    whole 15-30% band is resolved here and nowhere else hears about it. The
    transcript's roll sits at 16.2%."""
    *_, note = reconcile_macros_traced(210, 20, 24, None)
    assert "fat" in note and "34 cal" in note


def test_an_unclosable_gap_is_reported_too():
    """Scaling cannot move a stated zero, so the gap stays open — and this is
    the one place that knows it did."""
    *_, note = reconcile_macros_traced(210, 20, 24, 0)
    assert "unaccounted" in note and "stated as zero" in note


def test_consistent_macros_say_nothing():
    assert reconcile_macros_traced(100, 21, 2, 0)[-1] == ""
