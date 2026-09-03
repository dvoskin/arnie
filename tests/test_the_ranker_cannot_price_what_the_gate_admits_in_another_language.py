"""⛔ REGISTERED DEFECT, PINNED SO IT CANNOT BE FORGOTTEN.

The v2 qualification gate reads an intent in ANY language and admits the right
rows. `best_candidate` — the ranker that must then pick among them — scores
LEXICAL token overlap against an English description, so a Cyrillic query
prices nothing even when the only candidate is exactly the right food.

Measured 2026-09-03 with no provider involved:

    candidate  Blueberries, raw
    'черника'      -> None          'blueberries' -> PRICES, conf=exact

The rung yields None and a lower rung answers, silently. 16 of the 20
identities query expansion recovered are non-Latin, and none of them price
under their own query. See docs/REGISTERED_LEXICAL_RANKER_LANGUAGE_GAP.md.

⭐ `xfail(strict=True)`, the house pattern from the reachability gates: it
encodes the defect without reddening the board, and it will FAIL the moment the
ranker is fixed — which is the signal to delete the marker and the registration
together. It is NOT a license: the passing test below is the guard that the
ENGLISH path keeps working while the gap stands.
"""
from __future__ import annotations

import pytest

BLUEBERRIES = [{"fdc_id": "171711", "evidence_id": "usda:171711",
                "description": "Blueberries, raw",
                "per100g": {"calories": 57, "protein": 0.7, "carbs": 14.5, "fat": 0.3}}]


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "1")


def test_the_english_query_prices_the_right_candidate(v2):
    """The control. If THIS fails, the ranker broke, not the language gap."""
    from core.food_intelligence import best_candidate
    winner, conf = best_candidate("blueberries", list(BLUEBERRIES))
    assert winner is not None and winner["evidence_id"] == "usda:171711"
    assert conf == "exact"


@pytest.mark.xfail(strict=True, reason=(
    "REGISTERED: best_candidate is lexical and cannot match a Cyrillic query to "
    "an English description — docs/REGISTERED_LEXICAL_RANKER_LANGUAGE_GAP.md. "
    "When this XPASSes, the ranker was fixed: delete this marker and close the "
    "registration."))
def test_the_same_candidate_under_the_cyrillic_query(v2):
    from core.food_intelligence import best_candidate
    winner, _ = best_candidate("черника", list(BLUEBERRIES))
    assert winner is not None, "the gate admitted this row; the ranker refused it"
