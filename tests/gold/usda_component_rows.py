"""USDA search payloads for the composite component queries, offline.

Same purpose as the rest of this package: what is under test is the resolution
logic, not whether USDA is up. Descriptions and per-100g figures are USDA
curated (Foundation / SR Legacy) records, in the shape `api.usda.search_food`
returns them.

Every list carries the DISTRACTORS the real index returns alongside the right
row, because the matcher's job is PICKING, not accepting — and two of these
distractors are here because they actually beat the right answer during
development. "Snacks, tortilla chips, plain, white corn" answers every word of
"Tortillas, corn" and outscored the tortilla; "Rice flour, white, unenriched"
covers two thirds of "Rice, white, cooked". A fixture with only the right rows
in it would have passed against both bugs.
"""

ROWS = {
    "Tortillas, corn": [
        {"fdc_id": 172810, "description": "Tortillas, ready-to-bake or -fry, corn",
         "per100g": {"calories": 218, "protein": 5.7, "carbs": 44.6, "fat": 2.85, "fiber": 6.3}},
        {"fdc_id": 172811, "description": "Tortillas, ready-to-bake or -fry, flour, shelf stable",
         "per100g": {"calories": 304, "protein": 8.2, "carbs": 51.0, "fat": 7.1, "fiber": 3.0}},
        {"fdc_id": 168920, "description": "Snacks, tortilla chips, plain, white corn",
         "per100g": {"calories": 508, "protein": 7.0, "carbs": 64.0, "fat": 25.0, "fiber": 5.0}},
    ],
    "Tortillas, flour": [
        {"fdc_id": 172811, "description": "Tortillas, ready-to-bake or -fry, flour, shelf stable",
         "per100g": {"calories": 304, "protein": 8.2, "carbs": 51.0, "fat": 7.1, "fiber": 3.0}},
        {"fdc_id": 172810, "description": "Tortillas, ready-to-bake or -fry, corn",
         "per100g": {"calories": 218, "protein": 5.7, "carbs": 44.6, "fat": 2.85, "fiber": 6.3}},
    ],
    "Rice, white, cooked": [
        {"fdc_id": 169704, "description": "Rice, white, long-grain, regular, enriched, cooked",
         "per100g": {"calories": 130, "protein": 2.69, "carbs": 28.2, "fat": 0.28, "fiber": 0.4}},
        {"fdc_id": 169756, "description": "Rice, white, long-grain, regular, raw, enriched",
         "per100g": {"calories": 365, "protein": 7.13, "carbs": 80.0, "fat": 0.66, "fiber": 1.3}},
        {"fdc_id": 168878, "description": "Rice flour, white, unenriched",
         "per100g": {"calories": 366, "protein": 5.95, "carbs": 80.1, "fat": 1.42, "fiber": 2.4}},
    ],
    "Beans, black, cooked": [
        {"fdc_id": 173735, "description": "Beans, black, mature seeds, cooked, boiled, without salt",
         "per100g": {"calories": 132, "protein": 8.86, "carbs": 23.7, "fat": 0.54, "fiber": 8.7}},
        {"fdc_id": 175189, "description": "Beans, black, mature seeds, canned, low sodium",
         "per100g": {"calories": 91, "protein": 6.03, "carbs": 16.6, "fat": 0.36, "fiber": 6.3}},
    ],
    "Cheese, cheddar": [
        {"fdc_id": 328637, "description": "Cheese, cheddar",
         "per100g": {"calories": 403, "protein": 22.9, "carbs": 3.09, "fat": 33.3, "fiber": 0.0}},
        {"fdc_id": 170899, "description": "Cheese, pasteurized process, American",
         "per100g": {"calories": 375, "protein": 18.0, "carbs": 9.0, "fat": 31.0, "fiber": 0.0}},
    ],
    "Cheese, pasteurized process, American": [
        {"fdc_id": 170899, "description": "Cheese, pasteurized process, American, fortified with vitamin D",
         "per100g": {"calories": 375, "protein": 18.0, "carbs": 9.0, "fat": 31.0, "fiber": 0.0}},
        {"fdc_id": 328637, "description": "Cheese, cheddar",
         "per100g": {"calories": 403, "protein": 22.9, "carbs": 3.09, "fat": 33.3, "fiber": 0.0}},
    ],
    "Cheese, queso fresco": [
        {"fdc_id": 171256, "description": "Cheese, Mexican, queso fresco",
         "per100g": {"calories": 310, "protein": 18.0, "carbs": 3.9, "fat": 24.0, "fiber": 0.0}},
    ],
    "Salsa": [
        {"fdc_id": 171195, "description": "Sauce, salsa, ready-to-serve",
         "per100g": {"calories": 29, "protein": 1.5, "carbs": 6.6, "fat": 0.2, "fiber": 1.6}},
        {"fdc_id": 168564, "description": "Snacks, tortilla chips, nacho cheese",
         "per100g": {"calories": 498, "protein": 7.8, "carbs": 62.0, "fat": 24.0, "fiber": 4.6}},
    ],
    "Cream, sour, cultured": [
        {"fdc_id": 171256, "description": "Cream, sour, cultured",
         "per100g": {"calories": 198, "protein": 2.44, "carbs": 4.63, "fat": 19.4, "fiber": 0.0}},
    ],
    "Avocados, raw": [
        {"fdc_id": 171705, "description": "Avocados, raw, all commercial varieties",
         "per100g": {"calories": 160, "protein": 2.0, "carbs": 8.53, "fat": 14.7, "fiber": 6.7}},
    ],
    "Mayonnaise": [
        {"fdc_id": 169075, "description": "Salad dressing, mayonnaise, regular",
         "per100g": {"calories": 680, "protein": 0.96, "carbs": 0.57, "fat": 74.9, "fiber": 0.0}},
        {"fdc_id": 171009, "description": "Salad dressing, mayonnaise, light",
         "per100g": {"calories": 324, "protein": 0.9, "carbs": 12.0, "fat": 31.0, "fiber": 0.0}},
    ],
    "Butter, salted": [
        {"fdc_id": 173410, "description": "Butter, salted",
         "per100g": {"calories": 717, "protein": 0.85, "carbs": 0.06, "fat": 81.1, "fiber": 0.0}},
    ],
    "Rolls, hamburger": [
        {"fdc_id": 174987, "description": "Rolls, hamburger or hotdog, plain",
         "per100g": {"calories": 283, "protein": 9.6, "carbs": 50.4, "fat": 4.2, "fiber": 2.2}},
        {"fdc_id": 174988, "description": "Rolls, dinner, plain",
         "per100g": {"calories": 310, "protein": 8.6, "carbs": 52.0, "fat": 6.9, "fiber": 2.4}},
    ],
    "Bread, white, commercially prepared": [
        {"fdc_id": 174899, "description": "Bread, white, commercially prepared",
         "per100g": {"calories": 270, "protein": 9.0, "carbs": 49.2, "fat": 3.6, "fiber": 2.3}},
        {"fdc_id": 172686, "description": "Bread, wheat",
         "per100g": {"calories": 254, "protein": 10.7, "carbs": 43.1, "fat": 3.5, "fiber": 3.8}},
    ],
    "Egg, whole, raw, fresh": [
        {"fdc_id": 748967, "description": "Egg, whole, raw, fresh",
         "per100g": {"calories": 143, "protein": 12.6, "carbs": 0.72, "fat": 9.51, "fiber": 0.0}},
        {"fdc_id": 172184, "description": "Egg, whole, dried",
         "per100g": {"calories": 594, "protein": 47.4, "carbs": 4.95, "fat": 41.2, "fiber": 0.0}},
    ],
    "Beef, ground, cooked": [
        {"fdc_id": 174032, "description": "Beef, ground, 85% lean meat / 15% fat, patty, cooked, broiled",
         "per100g": {"calories": 250, "protein": 25.8, "carbs": 0.0, "fat": 15.4, "fiber": 0.0}},
        {"fdc_id": 174036, "description": "Beef, ground, 85% lean meat / 15% fat, raw",
         "per100g": {"calories": 215, "protein": 18.6, "carbs": 0.0, "fat": 15.0, "fiber": 0.0}},
    ],
    "Pork, shoulder, cooked": [
        {"fdc_id": 167903, "description": "Pork, fresh, shoulder, whole, separable lean and fat, cooked, roasted",
         "per100g": {"calories": 269, "protein": 23.6, "carbs": 0.0, "fat": 18.7, "fiber": 0.0}},
        {"fdc_id": 167902, "description": "Pork, fresh, shoulder, whole, separable lean and fat, raw",
         "per100g": {"calories": 220, "protein": 17.0, "carbs": 0.0, "fat": 16.5, "fiber": 0.0}},
    ],
    "Chicken, breast, meat only, cooked, roasted": [
        {"fdc_id": 171077, "description": "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
         "per100g": {"calories": 165, "protein": 31.0, "carbs": 0.0, "fat": 3.57, "fiber": 0.0}},
        {"fdc_id": 171075, "description": "Chicken, broilers or fryers, breast, meat and skin, cooked, fried, batter",
         "per100g": {"calories": 260, "protein": 22.0, "carbs": 8.99, "fat": 13.6, "fiber": 0.3}},
    ],
    "Turkey, breast, meat only, cooked, roasted": [
        {"fdc_id": 171496, "description": "Turkey, whole, breast, meat only, cooked, roasted",
         "per100g": {"calories": 135, "protein": 30.1, "carbs": 0.0, "fat": 0.74, "fiber": 0.0}},
    ],
    "Fish, tuna, yellowfin, raw": [
        {"fdc_id": 175159, "description": "Fish, tuna, yellowfin, fresh, raw",
         "per100g": {"calories": 109, "protein": 24.4, "carbs": 0.0, "fat": 0.49, "fiber": 0.0}},
        {"fdc_id": 175158, "description": "Fish, tuna, light, canned in water, drained solids",
         "per100g": {"calories": 116, "protein": 25.5, "carbs": 0.0, "fat": 0.82, "fiber": 0.0}},
    ],
}


async def search(query, page_size=8):
    return ROWS.get(query, [])
