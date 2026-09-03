"""⛔ THE GATE MUST RANK WITH THE QUERY PRODUCTION ISSUES. `verify_artifact_v2.winner`
ranked every entry by its entity alone ("beef" for `beef|grilled`) while the turn ranks
with `core.canonical_pricing._ranker_query(entity, preparation)`. On the v1 baseline six
prep entries rank differently between the two (2026-09-03): with V2 off, "beef" reaches
nothing in `beef|grilled` but production's query reaches the ribeye row, and "mackerel"
reaches a `mackerel|roasted` row production cannot. A gate measuring the wrong quantity
blocks correct work and waves through a real reprice. Fixtures are the v1 rows verbatim."""
from __future__ import annotations

import os

import pytest

BEEF_GRILLED_V1 = [
    {
        "evidence_id": "usda:174702",
        "description": "Beef, ribeye filet, boneless, separable lean only, trimmed to 0\" fat, choice, cooked, grilled",
        "per100g": {
            "calories": 208,
            "protein": 28.4,
            "carbs": 0.51,
            "fat": 10.3
        }
    },
    {
        "evidence_id": "usda:174703",
        "description": "Beef, ribeye filet, boneless, separable lean only, trimmed to 0\" fat, select, cooked, grilled",
        "per100g": {
            "calories": 186,
            "protein": 29.4,
            "carbs": 0.0,
            "fat": 7.61
        }
    },
    {
        "evidence_id": "usda:171785",
        "description": "Beef, shoulder steak, boneless, separable lean and fat, trimmed to 0\" fat, choice, cooked, grilled",
        "per100g": {
            "calories": 186,
            "protein": 28.2,
            "carbs": 0.0,
            "fat": 7.25
        }
    },
    {
        "evidence_id": "usda:171786",
        "description": "Beef, shoulder steak, boneless, separable lean and fat, trimmed to 0\" fat, select, cooked, grilled",
        "per100g": {
            "calories": 177,
            "protein": 28.4,
            "carbs": 0.0,
            "fat": 6.14
        }
    },
    {
        "evidence_id": "usda:168731",
        "description": "Beef, shoulder steak, boneless, separable lean only, trimmed to 0\" fat, choice, cooked, grilled",
        "per100g": {
            "calories": 178,
            "protein": 28.5,
            "carbs": 0.0,
            "fat": 6.25
        }
    }
]

MACKEREL_ROASTED_V1 = [
    {
        "evidence_id": "usda:175120",
        "description": "Fish, mackerel, Atlantic, cooked, dry heat",
        "per100g": {
            "calories": 262,
            "protein": 23.8,
            "carbs": 0.0,
            "fat": 17.8
        }
    },
    {
        "evidence_id": "usda:174236",
        "description": "Fish, mackerel, king, cooked, dry heat",
        "per100g": {
            "calories": 134,
            "protein": 26.0,
            "carbs": 0.0,
            "fat": 2.56
        }
    },
    {
        "evidence_id": "usda:173674",
        "description": "Fish, mackerel, spanish, cooked, dry heat",
        "per100g": {
            "calories": 158,
            "protein": 23.6,
            "carbs": 0.0,
            "fat": 6.32
        }
    },
    {
        "evidence_id": "usda:171994",
        "description": "Fish, mackerel, Pacific and jack, mixed species, cooked, dry heat",
        "per100g": {
            "calories": 201,
            "protein": 25.7,
            "carbs": 0.0,
            "fat": 10.1
        }
    }
]


@pytest.fixture
def v2_off(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "")
    from core.food_intelligence import _nutrition_accuracy_v2
    assert _nutrition_accuracy_v2() is False, "flag did not take effect"


def test_a_prep_entry_production_can_price_is_not_reported_unreachable(v2_off):
    from scripts.verify_artifact_v2 import winner
    evidence_id, kcal = winner({"candidates": BEEF_GRILLED_V1}, "beef|grilled")
    assert evidence_id == "usda:174702", (evidence_id, kcal)


def test_a_prep_entry_production_cannot_price_is_not_reported_priced(v2_off):
    """The mirror: "mackerel" alone seats a row; the turn's query does not. The
    gate must say None, as production would."""
    from scripts.verify_artifact_v2 import winner
    assert winner({"candidates": MACKEREL_ROASTED_V1}, "mackerel|roasted") == (None, None)


def test_a_bare_entity_is_ranked_by_the_entity():
    from scripts.verify_artifact_v2 import winner
    evidence_id, _ = winner({"candidates": MACKEREL_ROASTED_V1}, "mackerel|")
    assert evidence_id is not None
