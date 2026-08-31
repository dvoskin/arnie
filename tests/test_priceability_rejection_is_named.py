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

This file pins the CENSUS, not a repair. The repair is unauthorized until
production says what the defect costs, so the gate's DECISIONS are asserted
unchanged and only the naming is new.
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


def test_the_decision_is_UNCHANGED_by_the_census(caplog):
    """⛔ OBSERVABILITY ONLY. Every verdict below is what the gate returned
    before the naming was added. If any of these flip, the census has become a
    repair and this commit's contract is broken."""
    assert _per100g(REAL_FOOD) is not None
    assert _per100g(COKE_ZERO) is None      # ← the defect, still live on purpose
    assert _per100g(EMPTY) is None
    assert _per100g(ABSURD) is None
    assert _per100g({}) is None
    assert _per100g("not a dict") is None


def test_a_legitimate_zero_is_named_LOW_CALORIE_not_missing(caplog):
    """⭐ THE DISTINCTION THE CENSUS EXISTS TO EXPOSE. Both records are refused
    today; they must not be refused for the SAME RECORDED REASON, because one
    is a complete panel and the other is an empty one."""
    with caplog.at_level(logging.INFO, logger="skills.nutrition.off"):
        _per100g(COKE_ZERO)
        zero = _reasons(caplog)
    assert any("PRICEABILITY_LOW_CALORIE" in m for m in zero), zero
    assert any("n_present=4" in m for m in zero), (
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


def test_the_boundary_values_are_pinned():
    """10 and 900 inclusive, exactly as before — so a later repair has to move
    them deliberately rather than by drift."""
    assert _per100g({**REAL_FOOD, "energy-kcal_100g": 10}) is not None
    assert _per100g({**REAL_FOOD, "energy-kcal_100g": 900}) is not None
    assert _per100g({**REAL_FOOD, "energy-kcal_100g": 9.99}) is None
    assert _per100g({**REAL_FOOD, "energy-kcal_100g": 900.01}) is None
