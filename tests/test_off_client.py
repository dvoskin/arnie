"""Open Food Facts backend client — parsing, matching, and noise rejection.
These are the accuracy-critical bits: a wrong map or a loose match ships bad macros."""
import pytest

from skills.nutrition import off


def test_per100g_maps_and_converts_sodium():
    n = {"energy-kcal_100g": 380, "proteins_100g": 30, "carbohydrates_100g": 40,
         "fat_100g": 9, "fiber_100g": 5, "sugars_100g": 2, "sodium_100g": 0.4}
    p = off._per100g(n)
    assert p["calories"] == 380 and p["protein"] == 30 and p["carbs"] == 40 and p["fat"] == 9
    assert p["fiber"] == 5 and p["sugar"] == 2
    assert p["sodium"] == 400          # 0.4 g -> 400 mg


def test_per100g_sodium_from_salt_when_no_sodium():
    n = {"energy-kcal_100g": 200, "proteins_100g": 8, "carbohydrates_100g": 20,
         "fat_100g": 10, "salt_100g": 1.0}
    p = off._per100g(n)
    assert p["sodium"] == 400          # 1.0 g salt / 2.5 * 1000 = 400 mg


def test_per100g_kj_fallback_when_no_kcal():
    n = {"energy_100g": 1590, "proteins_100g": 8, "carbohydrates_100g": 20, "fat_100g": 10}
    p = off._per100g(n)
    assert p["calories"] == pytest.approx(380, abs=1)   # 1590 kJ / 4.184


@pytest.mark.parametrize("n", [
    {},                                                       # empty
    {"energy-kcal_100g": 380},                                # missing macros
    {"energy-kcal_100g": 9999, "proteins_100g": 1, "carbohydrates_100g": 1, "fat_100g": 1},  # sentinel
    {"energy-kcal_100g": 0, "proteins_100g": 0, "carbohydrates_100g": 0, "fat_100g": 0},      # zero/implausible
])
def test_per100g_rejects_noise(n):
    assert off._per100g(n) is None


def test_overlap_is_query_anchored():
    # every query token present in the product -> 1.0, even with a long title
    assert off._overlap("barebells salty peanut", "Barebells Protein Bar Salty Peanut 55g", "Barebells") == 1.0
    # partial: 3 of 4 query tokens present (no "vanilla" in the product)
    assert off._overlap("fairlife core power vanilla", "Core Power Elite", "fairlife") == 0.75
    # unrelated -> low
    assert off._overlap("greek yogurt", "Coca-Cola Classic", "Coca-Cola") == 0.0


async def test_search_returns_strong_match(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"products": [
                {"product_name": "Salty Peanut Protein Bar", "brands": "Barebells",
                 "nutriments": {"energy-kcal_100g": 364, "proteins_100g": 36,
                                "carbohydrates_100g": 27, "fat_100g": 15, "sodium_100g": 0.5}},
                {"product_name": "Random Cookie", "brands": "Other", "nutriments": {}},
            ]}
    class _C:
        async def get(self, *a, **k): return _Resp()
    monkeypatch.setattr(off, "_client", lambda: _C())
    res = await off.search("barebells salty peanut")
    assert res is not None
    assert res["source"] == "off" and res["_match"] == "exact"
    assert res["per100g"]["calories"] == 364 and res["per100g"]["sodium"] == 500


async def test_search_weak_match_returns_none(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"products": [
                {"product_name": "Sparkling Water Lime", "brands": "Generic",
                 "nutriments": {"energy-kcal_100g": 0, "proteins_100g": 0,
                                "carbohydrates_100g": 0, "fat_100g": 0}}]}
    class _C:
        async def get(self, *a, **k): return _Resp()
    monkeypatch.setattr(off, "_client", lambda: _C())
    # unrelated query + noise macros -> None (LLM estimate should win)
    assert await off.search("grilled chicken breast") is None
