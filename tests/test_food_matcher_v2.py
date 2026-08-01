"""Part 1 of the accuracy redesign: the identity matcher (NUTRITION_ACCURACY_V2).

The legacy `best_candidate` rejects USDA's own verbose whole-food rows via a
length penalty — "skirt steak" scores 1.05 < 1.2 despite a perfect token match,
so it seats nothing and the LLM's low guess stands. V2 gates on IDENTITY (query
coverage), accepting a descriptive row for the SAME food while still rejecting
composites and wrong cousins. Default off; these pin both states so the flag is
a safe, reversible switch.
"""
import os

import pytest

from core.food_intelligence import best_candidate

SKIRT = [{"description": 'Beef, plate steak, boneless, inside skirt, separable '
          'lean and fat, trimmed to 0" fat, choice, raw', "fdc_id": 1,
          "per100g": {"calories": 195}}]
COMPOSITE = [{"description": "Turkey breast and gravy, frozen meal", "fdc_id": 2,
              "per100g": {"calories": 90}}]
COUSIN = [{"description": "Chicken, broilers or fryers, breast, meat only, "
           "cooked, roasted", "fdc_id": 3, "per100g": {"calories": 165}}]


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "true")


@pytest.fixture
def v1(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "false")


def test_v1_rejects_the_verbose_whole_food_row(v1):
    # The bug: a perfect token match thrown out for description length.
    assert best_candidate("skirt steak", SKIRT)[0] is None


def test_v2_seats_the_verbose_whole_food_row(v2):
    cand, conf = best_candidate("skirt steak", SKIRT)
    assert cand is not None and cand["fdc_id"] == 1


def test_v2_still_rejects_composite_dishes(v2):
    # _FORM_PENALTY (gravy/frozen/meal) must still drag a composite under the floor.
    assert best_candidate("turkey breast", COMPOSITE)[0] is None


def test_v2_still_rejects_wrong_cousins(v2):
    # "shawarma" absent from the description → query not covered → different food.
    assert best_candidate("chicken shawarma", COUSIN)[0] is None


def test_v2_covers_query_regardless_of_description_length(v2):
    # Two extra descriptive words vs a dozen must not change the verdict — the
    # gate is coverage, not brevity.
    short = [{"description": "skirt steak", "fdc_id": 9, "per100g": {"calories": 255}}]
    assert best_candidate("skirt steak", short)[0]["fdc_id"] == 9
    assert best_candidate("skirt steak", SKIRT)[0]["fdc_id"] == 1


def test_default_is_v1(monkeypatch):
    # Flag unset → legacy behavior, so the change ships dark until the eval passes.
    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    assert best_candidate("skirt steak", SKIRT)[0] is None
