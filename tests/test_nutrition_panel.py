"""The Daily Log nutrition reveal's micro panel: ranked, labelled, %-DV
vitamins+minerals built from a stored {key: amount} blob."""
from core.nutrition import build_micro_panel


def test_panel_ranks_by_pct_dv_and_labels():
    micros = {"potassium": 422, "vitamin_b6": 0.41, "vitamin_c": 10.3,
              "magnesium": 32, "iron": 0.31}
    panel = build_micro_panel(micros)
    # ranked most-notable-first
    assert [m["key"] for m in panel] == [
        "vitamin_b6", "vitamin_c", "potassium", "magnesium", "iron"]
    top = panel[0]
    assert top["label"] == "Vitamin B6"
    assert top["unit"] == "mg"
    assert top["pct_dv"] == 24          # 0.41 / 1.7 DV
    assert top["amount"] == 0.41


def test_panel_excludes_fat_breakdown_and_is_none_safe():
    # saturated/mono/poly fat + cholesterol are limit nutrients, not V&M
    panel = build_micro_panel({"saturated_fat": 3, "cholesterol": 30, "iron": 2})
    assert [m["key"] for m in panel] == ["iron"]
    assert build_micro_panel(None) == []
    assert build_micro_panel({}) == []
    assert build_micro_panel({"calcium": 0}) == []   # zero/empty dropped
