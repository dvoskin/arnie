"""A row is not ground truth just because we wrote it.

`_logged_history_match` returns an OVERRIDE, and `_analyze_food` returns on an
override before the resolver, the plausibility cap, the web lane and the micro
fallback — everything that would otherwise object. So a bad row there is not
wrong once; it is wrong every time that food is logged again, permanently.

Prod 2026-08-03: one cup of white rice committed at 1 cal through a unit slip.
It cleared both filters the matcher already had (`calories > 0` and
`estimated_flag is False`), so it was eligible to come back as the user's own
confirmed history and beat USDA forever.

The gate is the same physics that refuses it on the way in, applied on the way
back out — and NOTHING ELSE about the override changes. It exists because a
generic 290-cal bagel row kept beating the user's own 80-cal Royo, and that is
still exactly what it does.
"""
import pytest

from handlers.tool_executor import _history_row_is_plausible as plausible
from skills.nutrition.normalize import confident_lower_mass


# ── the poison ────────────────────────────────────────────────────────────────

def test_the_one_calorie_cup_of_rice_is_not_served_back():
    assert plausible(1, "1 cup", "White rice, cooked") is False


def test_the_same_food_priced_sanely_still_wins():
    assert plausible(205, "1 cup", "White rice, cooked") is True


# ── what the override exists for, and must keep doing ────────────────────────

def test_the_royo_bagel_still_beats_usda():
    """The incident the override was built for: the user's own 80-cal bagel
    losing to a generic 290. Nothing here may cost them that."""
    assert plausible(80, "1 bagel", "Royo Everything Bagel") is True


def test_a_food_at_the_energy_ceiling_is_not_refused():
    """Only FATAL findings gate the row. Oils sit at the ceiling legitimately
    and produce a SUSPECT note, which is a disclosure and not a refusal."""
    assert plausible(119, "1 tbsp", "Olive oil") is True


def test_a_genuinely_zero_drink_is_not_refused():
    assert plausible(0, "12 oz", "Black coffee") is True


# ── the reason it does not overreach ──────────────────────────────────────────

def test_a_vague_portion_is_never_refused():
    """"some lettuce" normalizes to 80 g with an uncertainty of 85 g — which is
    to say we do not know. A refusal resting on our own guess about how much
    there was would be a bound on the estimate, not on the food."""
    assert confident_lower_mass("some", "Lettuce") is None
    assert plausible(3, "some", "Lettuce") is True


def test_the_lower_bound_is_what_gets_judged():
    """A refusal takes the most generous reading: below `grams -
    uncertainty_g` there is no portion left to argue about."""
    assert confident_lower_mass("1 cup", "White rice, cooked") == pytest.approx(
        134.7, abs=0.5)
    assert confident_lower_mass("158 g", "Rice") == pytest.approx(158.0, abs=0.5)


def test_it_fails_open():
    """A plausibility check that errors must never cost the user their own
    history — the override is the safer default of the two."""
    assert plausible(1, None, None) is True
    assert plausible(None, "1 cup", "Rice") is True
