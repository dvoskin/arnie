"""Every nutrient figure in a food reply is one the row can back.

Audit I-5. `enforce_say_contract` is absolute about digits — "the contract is
physics" — but its output becomes `plan.model_say`, a HINT. With
FOOD_COMPOSER=true the text the user reads is `compose_async()`'s own, and
`validate()` had no rule comparing it to `plan.committed_snapshot`: its numeric
regexes only test card-duplication and dashboard syntax.

So the commit path had a contract that was bypassed and the ask path had a
guard that was unfed, which together meant **no stage checked a number in a
food reply against what committed**. T-2 closed the no-snapshot half; this is
the commit half.
"""
import pytest

from core.food_ledger import TransactionSnapshot
from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, Reason, apply_policy, validate)

SNAP = TransactionSnapshot(batch_cal=340, batch_protein=28, day_cal=1200,
                           day_protein=95, cal_target=2200, protein_target=180)


def _committed(**kw):
    kw.setdefault("card_will_render", False)
    return apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="chicken bowl", portion="1 bowl"),),
        committed_snapshot=SNAP, **kw))


# ── the defect ────────────────────────────────────────────────────────────────

def test_a_figure_the_row_cannot_back_is_refused():
    result = validate("That is 420 cal in.", _committed())
    assert result.ok is False
    assert result.reason == Reason.NUMBER_NOT_COMMITTED


def test_the_failure_names_the_figure():
    """So the next reader is looking at the number, not at the rule."""
    assert "420" in validate("That is 420 cal in.", _committed()).detail


# ── and every legal number stays legal ────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "That is 340 cal in, 28g protein.",          # the batch
    "Nice — that lands you at 1200 for the day.",  # the day
    "You have 1000 cal left to play with.",      # derived: target - day
    "That is 341 cal.",                          # rounding, ±1
    "Solid choice — that will keep you full.",   # no figures at all
])
def test_a_backed_figure_ships(text):
    assert validate(text, _committed()).ok is True


def test_an_item_may_be_priced_by_its_own_calories():
    """Naming what one item cost is not a claim about the day."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="bar", portion="1 bar",
                                         calories=210),),
        committed_snapshot=SNAP, card_will_render=False))
    assert validate("The bar was 210.", plan).ok is True


def test_a_small_count_is_not_a_nutrient_figure():
    """"one of your two bars" is a count. A guard that reads it as calories
    would reject ordinary sentences, and the cost of a false positive here is
    the composer's reply being discarded for the deterministic fallback."""
    assert validate("That is 2 bars down, 340 cal in.", _committed()).ok is True


def test_a_turn_with_no_snapshot_is_not_judged_on_numbers():
    """The check needs an authority to check against. Without one, T-2's rule
    is what applies — not a guess about which digits are allowed."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="bar", portion="1 bar"),),
        card_will_render=False))
    assert validate("That is 999 cal in.", plan).ok is True
