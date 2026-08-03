"""DIMENSION INVARIANT (root fix 0803, prod fe#2705): a NormalizedQuantity's
`(amount, unit)` pair must denominate one measurement — so ANY surface that
re-serializes it (describe() fallback, _log_call/_update_call, a model echo) and
re-normalizes lands on the SAME grams. The old constructor returned amount=<count
of cups> beside unit="ml"; "1 cup" recombined as "1 ml" and priced a cup of rice
at ~0.7 g -> 1 cal, which an EXACT-grade promotion then committed over the
interpreter's correct 205.

Property test, not an example: swept across every volume unit, vessel and a food
spread. The rice case is pinned only as the incident's regression anchor.
"""
import pytest

from skills.nutrition.normalize import normalize_quantity

VOLUMES = ["1 cup", "2 cups", "0.5 cup", "1 tbsp", "2 tsp", "250 ml", "1 l",
           "8 floz", "1 glass", "1 mug", "1 shot"]
FOODS = ["White rice, cooked", "oatmeal", "milk", "olive oil", "chicken soup",
         "orange juice", "greek yogurt"]


def _recombined(q):
    # The exact shape every recombination surface produces from the pair.
    amt = f"{q.amount:g}" if q.amount is not None else "1"
    return f"{amt} {q.unit}"


@pytest.mark.parametrize("raw", VOLUMES)
@pytest.mark.parametrize("food", FOODS)
def test_volume_quantities_survive_recombination(raw, food):
    q = normalize_quantity(raw, food)
    if q is None:
        pytest.skip(f"{raw} did not normalize for {food}")
    r = normalize_quantity(_recombined(q), food)
    assert r is not None, (raw, food, _recombined(q))
    assert r.grams == q.grams, (
        f"{raw!r} {food}: {q.grams}g became {r.grams}g via {_recombined(q)!r}")
    assert r.milliliters == q.milliliters


def test_the_unit_is_a_word_someone_said():
    """amount=<count> beside unit="ml" is the broken pair itself — the unit must
    be the surface token whenever amount counts vessels, not milliliters."""
    q = normalize_quantity("1 cup", "White rice, cooked")
    assert q.unit != "ml" and q.amount == 1.0


def test_the_incident_regression_anchor():
    """fe#2705: a cup of cooked rice is ~150-210 g / never prices per-gram."""
    q = normalize_quantity("1 cup", "White rice, cooked")
    assert q.grams is not None and 140 <= q.grams <= 210
    # And a LITERAL "1 ml" stays 1 ml — honesty is symmetric.
    lit = normalize_quantity("1 ml", "White rice, cooked")
    assert lit.grams is not None and lit.grams < 2
