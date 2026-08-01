"""Serving units that priced to NOTHING in prod (2026-08-01 audit).

"1 ear" of corn, "1 clove" of garlic, "1 bun" all returned no grams, so a seated
density was discarded and the model's low/zero guess stood (corn card showed 0).
These pin that the units now resolve to a plausible mass, so a density is usable.
"""
from skills.nutrition.normalize import normalize_quantity as nq


def _g(q, food):
    return getattr(nq(q, food), "grams", None)


def test_ear_of_corn_has_mass():
    assert _g("1 ear", "corn") == 90.0
    assert _g("2 ears", "corn") == 180.0


def test_clove_of_garlic_has_mass():
    assert _g("1 clove", "garlic") == 3.0
    assert _g("3 cloves", "garlic") == 9.0


def test_bun_has_mass():
    assert _g("1 bun", "burger bun") == 50.0


def test_existing_units_unchanged():
    # Guard against regressing the units that already worked.
    assert _g("3 slices", "turkey") == 54.0
    assert _g("200 g", "turkey") == 200.0
    assert round(_g("2 oz", "parmesan"), 1) == 56.7
