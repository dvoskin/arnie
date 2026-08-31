"""⛔⛔⛔ CONFIRMED DEFECT: the priceability gate infers DATA COMPLETENESS from
CALORIE MAGNITUDE.

```python
if not (10 <= cal <= 900):
    return None        # "Reject sentinels (0, 9999)"
```

The premise — *100g of real food is ~10-900 kcal* — is true of FOOD and false of
DRINKS. Measured 2026-08-31 against live OFF:

```
Coca-Cola Zero              0.2 kcal/100g   all four macros present   REJECTED
Coca-Cola Zero Caffeine     0.3                    "                  REJECTED
Gatorade Zero Glacier       0.0                    "                  REJECTED
Zero Sugar Thirst Quencher  0.0                    "                  REJECTED
```

⭐ A GENUINE ZERO AND A MISSING ZERO ARE INDISTINGUISHABLE BY SIZE. The gate was
written to reject sentinels, and OFF already separates the two — every macro
field is populated on these records. Affected class: diet soda, zero-sugar
sports drinks, seltzer/flavoured water, black coffee.

⭐ REPAIRED 2026-08-31. `absent is not zero`, at all THREE sites that made the
same mistake — `_per100g`, `_per_serving` (floor of 1), and
`correction_application.rescale`, where `not per_100_cal` treated 0 and None
identically because Python says so. Fixing only the first would have moved the
failure downstream and looked like a repair.

The old expectations are restated below as WAS -> IS, so the direction of the
change is on the record rather than silently overwritten.
"""
from __future__ import annotations

import logging

import pytest

from skills.nutrition.off import _per100g

#: A complete panel that is legitimately zero — the class being discarded.
COKE_ZERO = {"energy-kcal_100g": 0.2, "proteins_100g": 0,
             "carbohydrates_100g": 0, "fat_100g": 0}
#: calories=0 with NOTHING else. A completely different evidence state, and the
#: one the sentinel guard was actually written for.
EMPTY = {"energy-kcal_100g": 0}
REAL_FOOD = {"energy-kcal_100g": 250, "proteins_100g": 10,
             "carbohydrates_100g": 30, "fat_100g": 8}
ABSURD = {"energy-kcal_100g": 9999, "proteins_100g": 0,
          "carbohydrates_100g": 0, "fat_100g": 0}


def _reasons(caplog):
    return [r.getMessage() for r in caplog.records
            if "priceability_rejected" in r.getMessage()]


#: 0 kcal beside 20 g of protein. A COMPLETE panel that is nonetheless broken —
#: the case a pure presence test would wrongly admit.
INCOHERENT = {"energy-kcal_100g": 0, "proteins_100g": 20,
              "carbohydrates_100g": 0, "fat_100g": 0}


def test_the_repaired_verdicts(caplog):
    """WAS -> IS, so the change is legible rather than silently overwritten."""
    assert _per100g(REAL_FOOD) is not None          # accept -> accept
    assert _per100g(COKE_ZERO) is not None          # ⭐ REJECT -> ACCEPT
    assert _per100g(EMPTY) is None                  # reject -> reject (absent)
    assert _per100g(ABSURD) is None                 # reject -> reject (>900)
    assert _per100g(INCOHERENT) is None             # ⭐ NEW: complete but broken
    assert _per100g({}) is None
    assert _per100g("not a dict") is None


def test_a_zero_calorie_drink_now_PRICES(caplog):
    """⭐ THE POINT OF THE TRANCHE. Diet soda, zero-sugar sports drinks,
    seltzer and black coffee were structurally unpriceable by this lane."""
    out = _per100g(COKE_ZERO)
    assert out is not None and out["calories"] == 0.2
    assert out["protein"] == 0 and out["carbs"] == 0 and out["fat"] == 0
    gat = _per100g({"energy-kcal_100g": 0.0, "proteins_100g": 0,
                    "carbohydrates_100g": 0.28, "fat_100g": 0})
    assert gat is not None and gat["calories"] == 0.0


def test_rescale_no_longer_treats_zero_as_absent():
    """⛔ THE THIRD SITE, and the one that would have stayed broken. A
    correction on a zero-calorie product could not rescale at all, so
    "actually that was 500 ml" failed on every diet soda — invisibly, long
    after retrieval and pricing were fixed."""
    from skills.nutrition.correction_application import rescale
    assert rescale({"calories": 0.0, "protein": 0, "carbs": 0, "fat": 0}, 500) is not None
    assert rescale({"calories": None}, 500) is None      # absent stays absent
    assert rescale({}, 500) is None
    assert rescale({"calories": 50}, 0) is None          # zero grams still refused


def test_a_zero_calorie_SERVING_panel_prices():
    """The second site. A published 0-calorie serving panel was rejected by a
    floor of 1, so fixing `_per100g` alone would have moved the failure."""
    from skills.nutrition.off import _per_serving
    out = _per_serving({"energy-kcal_serving": 0, "proteins_serving": 0,
                        "carbohydrates_serving": 0, "fat_serving": 0})
    assert out is not None and out["calories"] == 0


def test_the_broken_panel_is_named_INCOHERENT_not_missing(caplog):
    """⭐ THE DISTINCTION THE CENSUS EXISTS TO EXPOSE, now on the two records
    that are STILL refused: one is complete-but-broken, the other is empty, and
    they must not share a recorded reason."""
    with caplog.at_level(logging.INFO, logger="skills.nutrition.off"):
        _per100g(INCOHERENT)
        broken = _reasons(caplog)
    assert any("PRICEABILITY_INCOHERENT" in m for m in broken), broken
    assert any("n_present=4" in m for m in broken), (
        "a complete panel must be recorded as complete — that is the whole "
        "evidence distinction")

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="skills.nutrition.off"):
        _per100g(EMPTY)
        empty = _reasons(caplog)
    assert any("PRICEABILITY_MISSING_FIELDS" in m for m in empty), empty
    assert any("n_present=1" in m for m in empty)


def test_the_high_end_is_named_separately(caplog):
    with caplog.at_level(logging.INFO, logger="skills.nutrition.off"):
        _per100g(ABSURD)
    assert any("PRICEABILITY_HIGH_CALORIE" in m for m in _reasons(caplog))


def test_an_ACCEPTED_record_logs_no_rejection(caplog):
    """A census that fires on success would drown the signal it exists for."""
    with caplog.at_level(logging.INFO, logger="skills.nutrition.off"):
        assert _per100g(REAL_FOOD) is not None
    assert _reasons(caplog) == []


def test_the_boundaries_after_the_repair():
    """⭐ THE FLOOR IS GONE; THE CEILING REMAINS. `9.99` was rejected before and
    prices now — that IS the repair. 900 stays inclusive because a sentinel
    9999 arrives with all four fields populated, so completeness cannot replace
    the upper bound."""
    assert _per100g({**REAL_FOOD, "energy-kcal_100g": 900}) is not None
    assert _per100g({**REAL_FOOD, "energy-kcal_100g": 900.01}) is None
    # was None, now prices — a low value with a coherent complete panel
    assert _per100g({"energy-kcal_100g": 9.99, "proteins_100g": 0,
                     "carbohydrates_100g": 2.4, "fat_100g": 0}) is not None
