"""A portion with real mass and no energy was never priced.

Every bound in `skills/nutrition/sanity.py` was one-sided until 2026-08-03, and
the gap shipped: one cup of cooked white rice — 158 g by the ontology —
committed at 1 CALORIE while the interpreter had said 205. Nothing objected.
The only density rule was a ceiling, and the Atwater check is gated at
`MACRO_CHECK_MIN_KCAL = 40`, so the entire failing range was exempt by
construction.

Two halves, and the second is the one that matters:

  * a FLOOR, at 0.05 kcal/g;
  * measured against the STATED portion. `analyze` was passing
    `_implied_grams`, which on the estimate path is `cal / cal100 * 100` — so
    `calories / _implied_grams` is identically `cal100/100`, a constant. The
    density check was live, and mathematically incapable of detecting a portion
    error in either direction.

The floor is 0.05 and not the 0.2 that looks defensible, because lettuce
(~0.15), celery (~0.16) and cucumber (~0.15) are real foods that really are
that thin. A bound that only holds when you pick the examples is not a bound.
"""
import pytest

from skills.nutrition import sanity


def _codes(findings):
    return {f.code for f in findings}


def _fatal(findings):
    return [f for f in findings if f.is_fatal]


# ── the defect ────────────────────────────────────────────────────────────────

def test_a_cup_of_rice_at_one_calorie_is_refused():
    """The production row, exactly: 1 cal against the 158 g a cup of cooked
    rice actually weighs."""
    out = sanity.check_values(calories=1, grams=158.5, name="White rice, cooked")
    assert "energy_density_negligible" in _codes(out)
    assert _fatal(out), "it must REFUSE, not merely note — the row commits otherwise"


def test_the_same_row_priced_correctly_passes():
    assert not _fatal(sanity.check_values(
        calories=205, grams=158.5, name="White rice, cooked"))


# ── what it must not break ────────────────────────────────────────────────────

@pytest.mark.parametrize("name,cal,grams", [
    ("Lettuce", 15, 100),            # ~0.15 kcal/g
    ("Celery sticks", 16, 100),      # ~0.16
    ("Cucumber", 15, 100),           # ~0.15
    ("Jalapenos", 5, 35),            # ~0.14 — the one that failed a 0.2 floor
    ("Spinach", 23, 100),            # ~0.23
])
def test_genuinely_thin_vegetables_survive(name, cal, grams):
    """These are the reason the floor is 0.05. A 0.2 floor fails every one."""
    assert not _fatal(sanity.check_values(calories=cal, grams=grams, name=name)), \
        f"{name} at {cal} cal / {grams} g was refused"


@pytest.mark.parametrize("name", [
    "Water", "Black coffee", "Green tea", "Diet coke", "Chicken broth",
    "Sparkling water", "Espresso",
])
def test_the_genuinely_zero_foods_are_exempt(name):
    """`food_intelligence` says the same thing where it refuses to attribute a
    zero: water and black coffee are real foods that really are zero."""
    assert not _fatal(sanity.check_values(calories=0, grams=350, name=name)), \
        f"{name} was refused for being zero, which it is"


def test_a_sweet_drink_is_not_exempt():
    """The exemption is calorie-free drinks, not drinks. A 350 g cola at 0 cal
    is a pricing failure wearing a drink's name."""
    assert _fatal(sanity.check_values(calories=0, grams=350, name="Coca-Cola"))


def test_a_small_portion_is_not_judged():
    """Below 20 g the arithmetic is noise — a garnish at 0 cal is a garnish."""
    assert not _fatal(sanity.check_values(calories=0, grams=5, name="Parsley"))


def test_no_mass_means_no_verdict():
    """The check needs a portion to measure against. Without one it says
    nothing rather than guessing."""
    assert not _fatal(sanity.check_values(calories=1, grams=None, name="Rice"))


# ── the ceiling still works ───────────────────────────────────────────────────

def test_the_ceiling_is_untouched():
    out = sanity.check_values(calories=588, grams=16, name="Peanut butter")
    assert "energy_density_impossible" in _codes(out)


def test_olive_oil_still_passes_at_the_ceiling():
    assert not _fatal(sanity.check_values(
        calories=119, grams=13.5, name="Olive oil"))
