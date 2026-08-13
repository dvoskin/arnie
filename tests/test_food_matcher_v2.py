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


@pytest.fixture
def as_eaten(monkeypatch):
    """⭐ THE PREFERENCE IS NO LONGER PART OF V2, so a test of the preference
    must ask for it by name. Split on 2026-08-13: `as_eaten_over_trimmed` is a
    ±0.4 tie-break, and a tie-break only decides NEAR-TIES — so on real USDA
    data it was selecting rows that differ from the runner-up in CUT and in
    COATING, dimensions it never evaluates (knuckle -> striploin, +123 kcal;
    meat-only -> BATTERED, +7.7 g carbs). V2's structural half is what the
    Phase 0 baseline freezes against; this rides its own flag until cut and
    coating are separately modelled."""
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "true")
    monkeypatch.setenv("NUTRITION_AS_EATEN_PREFERENCE", "true")


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


# ── cut/species identity (the ribeye residual) ───────────────────────────────
#
# USDA returns, for "ribeye steak": a BISON ribeye (wrong animal), five ribeye
# CAP rows (a different sub-cut, leaner), and the real beef ribeye — whose
# description reads "ribeye steak/roast", so the "/" hid the token "steak" and
# dropped it below the identity gate. Three fixes, one row: split separators,
# reject the wrong animal, deprioritise the wrong cut.
RIBEYE = [
    {"description": 'Game meat, bison, ribeye, separable lean only, 1" steak, '
     'cooked, broiled', "fdc_id": 20, "per100g": {"calories": 177}},
    {"description": 'Beef, ribeye cap steak, boneless, separable lean only, '
     'choice, cooked, grilled', "fdc_id": 21, "per100g": {"calories": 259}},
    {"description": 'Beef, Australian, grass-fed, rib, ribeye steak/roast lip-on, '
     'separable lean and fat, raw', "fdc_id": 22, "per100g": {"calories": 217}},
]


def test_v2_seats_the_real_cut_over_wrong_species_and_sub_cut(v2):
    # Not the bison (20), not the ribeye cap (21) — the actual beef ribeye (22).
    cand, conf = best_candidate("ribeye steak", RIBEYE)
    assert cand is not None and cand["fdc_id"] == 22


def test_v2_separator_splits_recover_the_hidden_token(v2):
    # "ribeye steak/roast" must cover the query token "steak"; without the split
    # it reads as "steakroast" and the row fails the 0.75 identity gate.
    only_real = [RIBEYE[2]]
    assert best_candidate("ribeye steak", only_real)[0]["fdc_id"] == 22


def test_v2_rejects_a_lone_wrong_species_row(v2):
    # If bison is all USDA offers for a beef cut, log an estimate — never a bison
    # density for beef. (A cap, same animal, may still seat: next test.)
    assert best_candidate("ribeye steak", [RIBEYE[0]])[0] is None


def test_v2_seats_a_sub_cut_only_when_it_is_the_only_option(v2):
    # A ribeye cap is leaner but still beef ribeye — better than an estimate when
    # nothing else is on the shelf.
    assert best_candidate("ribeye steak", [RIBEYE[1]])[0]["fdc_id"] == 21


def test_v2_keeps_the_species_when_the_query_asks_for_it(v2):
    # "bison ribeye" NAMES bison, so its bison row is the right food, not penalised.
    cand, _ = best_candidate("bison ribeye", [RIBEYE[0]])
    assert cand is not None and cand["fdc_id"] == 20


def test_v1_unaffected_by_species_and_cut_rules(v1):
    # The penalties and separator split are v2-only; v1 seats by the old logic
    # (its glued tokenisation makes the "/" row miss, so it takes the bison).
    cand, _ = best_candidate("ribeye steak", RIBEYE)
    assert cand is None or cand["fdc_id"] != 22


# ── as-eaten over trimmed, and a COMPLETE cooked-marker list (thigh) ──────────
#
# USDA offers the thigh both "meat only" (the lab sample) and "meat and skin"
# (the meal). A person eats the skin unless they say otherwise, so the second is
# the right basis. And "rotisserie"/"BBQ" are cooked — omitting them from the
# marker list made a cooked row read as raw and take the raw->cooked yield twice.
from core.food_intelligence import _COOKED_MARKERS  # noqa: E402

THIGH = [
    {"description": "Chicken, broiler, rotisserie, BBQ, thigh, meat only",
     "fdc_id": 30, "per100g": {"calories": 193}},
    {"description": "Chicken, broiler, rotisserie, BBQ, thigh, meat and skin",
     "fdc_id": 31, "per100g": {"calories": 226}},
]


def test_the_as_eaten_preference_prefers_meat_and_skin(as_eaten):
    """The behaviour still works when it is asked for — the flag parks it for
    a canary, it does not retire it."""
    assert best_candidate("chicken thigh", THIGH)[0]["fdc_id"] == 31


def test_v2_alone_keeps_the_trimmed_row(v2):
    """⭐ THE SPLIT, PINNED WHERE IT MATTERS. Structural V2 must NOT drag the
    preference in — this is the same assertion as the v1 case below, and that
    it now holds for v2 too is exactly what makes the canonical-safe regime
    freezable."""
    assert best_candidate("chicken thigh", THIGH)[0]["fdc_id"] == 30


def test_v1_keeps_the_trimmed_row(v1):
    # v1's length tie-break takes the shorter "meat only".
    assert best_candidate("chicken thigh", THIGH)[0]["fdc_id"] == 30


def test_rotisserie_and_bbq_are_recognised_as_cooked():
    # Pins the fix: the marker list must be complete, or cooked rows get yielded.
    assert {"rotisserie", "bbq", "smoked", "seared"} <= _COOKED_MARKERS
