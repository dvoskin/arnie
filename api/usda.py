"""
USDA FoodData Central API client.

Provides accurate nutrition data (calories, macros, fiber, sugar, sodium, key
micros) for foods, used to ground Arnie's logging in real numbers instead of
pure LLM estimates. Falls back gracefully when the API key is missing or a
food isn't found — Arnie's estimate is always the safety net.

API: https://fdc.nal.usda.gov/api-guide.html
Key: USDA_API_KEY env var.
"""
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.nal.usda.gov/fdc/v1"

# FDC nutrient numbers → our keys. Macros (the first seven) land in dedicated
# food_entries columns; everything below is a MICRONUTRIENT and is stored in
# micronutrients_json (see _MICRO_KEYS / _MICRO_UNITS).
_NUTRIENT_MAP = {
    "208": "calories",   # Energy (kcal)
    "203": "protein",
    "204": "fat",
    "205": "carbs",
    "291": "fiber",
    "269": "sugar",
    "307": "sodium",     # mg
    # ── minerals ──
    "301": "calcium",    # mg
    "303": "iron",       # mg
    "306": "potassium",  # mg
    "304": "magnesium",  # mg
    "305": "phosphorus", # mg
    "309": "zinc",       # mg
    # ── vitamins ──
    "401": "vitamin_c",  # mg
    "320": "vitamin_a",  # µg RAE
    "328": "vitamin_d",  # µg
    "323": "vitamin_e",  # mg
    "430": "vitamin_k",  # µg
    "404": "thiamin",    # mg (B1)
    "405": "riboflavin", # mg (B2)
    "406": "niacin",     # mg (B3)
    "415": "vitamin_b6", # mg
    "417": "folate",     # µg
    "418": "vitamin_b12",# µg
    # ── lipids + sterols (fat breakdown) ──
    "601": "cholesterol",          # mg
    "606": "saturated_fat",        # g
    "605": "trans_fat",            # g
    "645": "monounsaturated_fat",  # g
    "646": "polyunsaturated_fat",  # g
}

# The micronutrient subset (everything that isn't a column macro) + display units
# and a friendly label, consumed by the Daily Log nutrition reveal.
_MICRO_UNITS = {
    "calcium": "mg", "iron": "mg", "potassium": "mg", "magnesium": "mg",
    "phosphorus": "mg", "zinc": "mg", "vitamin_c": "mg", "vitamin_a": "µg",
    "vitamin_d": "µg", "vitamin_e": "mg", "vitamin_k": "µg", "thiamin": "mg",
    "riboflavin": "mg", "niacin": "mg", "vitamin_b6": "mg", "folate": "µg",
    "vitamin_b12": "µg", "cholesterol": "mg", "saturated_fat": "g",
    "trans_fat": "g", "monounsaturated_fat": "g", "polyunsaturated_fat": "g",
}
MICRO_KEYS = tuple(_MICRO_UNITS.keys())


def micro_units(key: str) -> str:
    return _MICRO_UNITS.get(key, "")

_http: Optional[httpx.AsyncClient] = None


def _key() -> str:
    return os.getenv("USDA_API_KEY", "")


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=8.0)
    return _http


async def food_portions(fdc_id) -> list[dict]:
    """USDA's OWN measures for one record: "1 large" = 50 g, "1 cup" = 244 g.

    ⛔⛔ THIS IS THE HALF `/foods/search` DOES NOT RETURN, and its absence is why
    a generic count was unpriceable. The search response carries a BRANDED
    serving panel (`servingSize` + `householdServingFullText`) and nothing at
    all for Foundation / SR Legacy rows — which is where eggs, bananas and
    potatoes live, and where 142 of 207 declining items were. `foodPortions` is
    on the DETAIL endpoint only.

    ⭐ BUILD TIME ONLY. This is called by the artifact enrichment script, never
    by a settle. `assemble()` stays LOAD-NEVER-BUILD and Gate B is untouched:
    the measure has to be committed evidence before pricing can see it.

    ⚠ AND THE MODIFIER IS THE UNIT, NOT PROSE. USDA states portions as
    `amount` + `measureUnit.name` + `modifier` — "1", "undetermined", "large" —
    so a portion is only usable when SOMETHING names the unit. A row that says
    only "1 undetermined = 50 g" names nothing a user could have counted, and is
    dropped rather than matched against everything.
    """
    if not _key():
        return []
    try:
        # ⛔⛔ `format=full`, AND THE ABRIDGED FORM IS WHY THIS FIRST READ ZERO.
        # `abridged` returns 6 keys and NO `foodPortions` at all; `full` returns
        # 15 keys and the portions. The enrichment reported "0 of 124 candidates
        # gained a measure" — a silence that looked exactly like "USDA has no
        # portion data for generic foods", which would have been a wrong and
        # very expensive conclusion about the whole tranche.
        resp = await _client().get(
            f"{_BASE}/food/{fdc_id}",
            params={"api_key": _key(), "format": "full"})
        resp.raise_for_status()
        out = []
        for portion in (resp.json().get("foodPortions") or []):
            grams = portion.get("gramWeight")
            if not isinstance(grams, (int, float)) or grams <= 0:
                continue
            amount = portion.get("amount")
            amount = float(amount) if isinstance(amount, (int, float)) and \
                amount else 1.0
            unit = str((portion.get("measureUnit") or {}).get("name")
                       or "").strip()
            if unit.lower() in ("undetermined", "", "none"):
                unit = ""
            modifier = str(portion.get("modifier") or "").strip()
            description = str(portion.get("portionDescription") or "").strip()
            # The unit words, best available: an explicit measure unit, else the
            # modifier ("large", "medium"), else the portion description.
            unit_text = " ".join(w for w in (modifier, unit) if w).strip() \
                or description
            if not unit_text:
                continue
            out.append({"unit_text": unit_text.lower(),
                        "amount": amount,
                        "grams": float(grams)})
        return out
    except Exception as e:
        logger.warning(f"USDA foodPortions failed for {fdc_id}: {e}")
        return []


def _extract_nutrients(food: dict) -> dict:
    """Pull our nutrient set out of an FDC food record (per 100g)."""
    out = {}
    for n in food.get("foodNutrients", []):
        # search results use nutrientNumber; detail uses nested nutrient.number
        num = str(n.get("nutrientNumber") or n.get("nutrient", {}).get("number") or "")
        val = n.get("value")
        if val is None:
            val = n.get("amount")
        if num in _NUTRIENT_MAP and val is not None:
            out[_NUTRIENT_MAP[num]] = val
    return out


#: Serving-size units that state a VOLUME. A set rather than a prefix test:
#: "milligram" also starts with "m", and "mg" is not "ml".
_ML_UNITS = frozenset({"ml", "mls", "milliliter", "millilitre",
                       "milliliters", "millilitres"})

#: What every row this client returns describes: 100 GRAMS of the food.
#:
#: True by construction for the curated types this client prefers — Foundation
#: and SR Legacy ARE measured composition on a mass basis, so no row in either
#: is anything else whatever unit its serving panel quotes — and it is what
#: every consumer has always assumed of the Branded rows too.
#:
#: The value is that it is now SAID, once, by the code holding the record.
#: Before this it was said nowhere: `candidates.usda_candidates` hardcoded
#: `Per100g()` two layers down, so the basis could not be corrected without
#: editing the layer whose job is ranking, and the gold set drifted to a
#: different answer entirely because nothing connected the two.
USDA_BASIS = "per_100g"


async def _search(query: str, data_types: list[str], page_size: int) -> list[dict]:
    """One USDA search request restricted to the given data types."""
    try:
        resp = await _client().post(
            f"{_BASE}/foods/search",
            params={"api_key": _key()},
            json={"query": query.strip(), "pageSize": page_size, "dataType": data_types},
        )
        if resp.status_code != 200:
            logger.warning(f"USDA search {resp.status_code}: {resp.text[:120]}")
            return []
        out = []
        for f in resp.json().get("foods", []):
            per100 = _extract_nutrients(f)
            if not per100.get("calories"):
                continue
            # Serving panel, carried so a COUNT portion ("15 pieces") can be
            # given a mass from the record that is answering. USDA's Branded
            # rows state both halves: servingSize/servingSizeUnit is the mass,
            # householdServingFullText is what the packet calls it.
            #
            # A serving stated in ml used to go on the FLOOR: the ternary below
            # returned None for any unit that was not grams, and nothing else
            # read the field. `PerServing` has carried a `serving_ml` the whole
            # time and `scaling._factor` already divides ml by it, so a drink
            # whose panel said "240 ml" was left unscalable by this line alone.
            _unit = str(f.get("servingSizeUnit") or "").strip().lower()
            _size = f.get("servingSize")
            _size = float(_size) if isinstance(_size, (int, float)) else None
            out.append({
                "fdc_id": f.get("fdcId"),
                "description": f.get("description", ""),
                "brand": f.get("brandName") or f.get("brandOwner") or "",
                "data_type": f.get("dataType", ""),
                "per100g": per100,
                # What these numbers describe, declared by the adapter holding
                # the record rather than assumed by whoever consumes it. The
                # gold set had drifted to `per_100ml` on six USDA cases — a
                # basis the live adapter could not produce, on rows that are
                # per 100 g — and the mislabel priced a tablespoon of olive oil
                # at 131 calories against USDA's own 13.5 g/tbsp, which is 119.
                "basis": USDA_BASIS,
                "serving_text": str(
                    f.get("householdServingFullText") or "").strip(),
                "serving_mass_g": (_size if _unit in ("g", "gram", "grams")
                                   else None),
                "serving_ml": (_size if _unit in _ML_UNITS else None),
            })
        return out
    except Exception as e:
        logger.warning(f"USDA search failed: {e}")
        return []


def _looks_branded(query: str) -> bool:
    """Query names a specific product/brand (capitalized token or long phrase)."""
    toks = query.split()
    return len(toks) >= 4 or any(t[:1].isupper() for t in toks)


async def search_food(query: str, page_size: int = 5) -> list[dict]:
    """
    Search USDA for a food. Two-pass: USDA's CURATED data (Foundation, SR Legacy)
    is clean and trustworthy, so it's preferred for generic foods. Branded is
    crowdsourced/noisy, used only as a fallback — or first when the query clearly
    names a brand. Nutrients are per 100g. Empty list on miss/no-key/error.
    """
    if not _key() or not query.strip():
        return []

    curated = ["Foundation", "SR Legacy"]
    branded = ["Branded"]

    if _looks_branded(query):
        order = [branded, curated]
    else:
        order = [curated, branded]

    for data_types in order:
        res = await _search(query, data_types, page_size)
        if res:
            return res
    return []
