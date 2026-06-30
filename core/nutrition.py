"""Micronutrient presentation — turn a stored {key: amount} micro blob into a
ranked, labelled, %-daily-value panel for the iOS Daily Log nutrition reveal.

The amounts are per-portion (food_intelligence scales them); here we attach the
human label, unit, and % of the FDA Daily Value, then rank by relevance so the
client can show the top few and tuck the rest behind "see all". Kept separate
from api/usda.py (fetching) — this is the presentation layer.
"""
from __future__ import annotations

from api.usda import micro_units

# FDA Reference Daily Values (adult), used for the % DV framing. Only the
# vitamins + minerals get a DV here — the fat-breakdown keys (saturated/…
# /cholesterol) are "limit" nutrients with a different meaning, so they're
# intentionally excluded from the vitamins-and-minerals panel.
_DAILY_VALUES = {
    "calcium": 1300, "iron": 18, "potassium": 4700, "magnesium": 420,
    "phosphorus": 1250, "zinc": 11,
    "vitamin_c": 90, "vitamin_a": 900, "vitamin_d": 20, "vitamin_e": 15,
    "vitamin_k": 120, "thiamin": 1.2, "riboflavin": 1.3, "niacin": 16,
    "vitamin_b6": 1.7, "folate": 400, "vitamin_b12": 2.4,
}

_MICRO_LABELS = {
    "calcium": "Calcium", "iron": "Iron", "potassium": "Potassium",
    "magnesium": "Magnesium", "phosphorus": "Phosphorus", "zinc": "Zinc",
    "vitamin_c": "Vitamin C", "vitamin_a": "Vitamin A", "vitamin_d": "Vitamin D",
    "vitamin_e": "Vitamin E", "vitamin_k": "Vitamin K", "thiamin": "Thiamin",
    "riboflavin": "Riboflavin", "niacin": "Niacin", "vitamin_b6": "Vitamin B6",
    "folate": "Folate", "vitamin_b12": "Vitamin B12",
}


def _round_amount(v: float) -> float:
    """Display rounding: whole numbers for big mg/µg, 1-2 places for tiny ones."""
    if v >= 100:
        return round(v)
    if v >= 10:
        return round(v, 1)
    return round(v, 2)


def build_micro_panel(micros: dict | None) -> list[dict]:
    """[{key, label, amount, unit, pct_dv}] for the vitamins+minerals present,
    ranked by % daily value (most notable first). Empty list when there's
    nothing with a DV to show."""
    if not micros:
        return []
    panel = []
    for key, dv in _DAILY_VALUES.items():
        amt = micros.get(key)
        if amt is None or amt <= 0:
            continue
        panel.append({
            "key": key,
            "label": _MICRO_LABELS.get(key, key.replace("_", " ").title()),
            "amount": _round_amount(amt),
            "unit": micro_units(key),
            "pct_dv": round(amt / dv * 100) if dv else None,
        })
    panel.sort(key=lambda m: (m["pct_dv"] or 0), reverse=True)
    return panel
