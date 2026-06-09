import logging
from core.llm import analyze_image

logger = logging.getLogger(__name__)

_FOOD_PROMPT = """You are analyzing a food image for a fitness tracking app. Reply in plain text only — no markdown, no headers, no bullet symbols, no asterisks.

PACKAGED PRODUCT WITH VISIBLE LABEL — TOP PRIORITY:
If the image shows a packaged item (bottle, carton, can, bar, box, pouch, etc.) where the BRAND, FLAVOR/VARIANT, and macro callouts on the front are LEGIBLE, READ THEM and put the label data on ONE line in this exact format:
  PACKAGED: [brand] [product name + flavor], [serving size from label, e.g. "11 fl oz (1 carton)"], [cal] cal, [protein]g P, [carbs]g C, [fat]g F
Example: PACKAGED: Elmhurst Clean Protein Pistachio Crème, 11 fl oz (1 carton), 190 cal, 27g P, 4g C, 7g F
Pull the brand and flavor verbatim from the package — do not paraphrase ("a pistachio shake"). If carbs/fat aren't shown on the front but cal and protein are, fill the visible numbers and write "?" for the unseen macros. Never ask the user for info that's on the label in the photo.

If it's a meal (cooked / plated / unpackaged): list each distinct food item on its own line in this format:
  [item name], [quantity], [cal] cal, [protein]g P, [carbs]g C, [fat]g F
Example: grilled chicken breast, ~6oz, 280 cal, 35g P, 0g C, 6g F

Estimation rules:
- State prep method when visible (grilled, fried, steamed, raw).
- Restaurant or packaged meals: estimate 30-50% larger than typical home portions — restaurants use more oil, butter, and larger serves.
- Account for hidden calories: pan-cooked items assume oil/butter (~100-150 cal); sauces and dressings add 100-300 cal even when not dominant.
- Use realistic portion sizes — a restaurant chicken breast is typically 7-8oz, not 4oz.
- When prep is not clearly visible, note it: "chicken (prep unclear)".
- When sauce, dressing, or oil presence is uncertain, add a range note on that line: "sauce (est. +100-200 cal)".
- For bowls, salads, wraps, and burritos: always list the BASE as its own line (e.g. "white rice, ~1.5 cups, 300 cal" or "romaine lettuce, 2 cups, 20 cal"). If the base type is unclear from the photo, write: "base (unclear — rice ~300cal vs lettuce ~20cal, needs clarification)".

If there are multiple items, add a TOTAL line at the end:
  TOTAL: [sum cal] cal, [sum protein]g P

If it's a nutrition-facts label (the back-panel table): state serving size, calories, protein, carbs, fat, fiber on one line.
If it's a receipt: extract item names and any nutritional info shown.

Be concise. One line per item."""

_GENERAL_PROMPT = """You are analyzing an image for a fitness/nutrition coaching app. Reply in plain text only — no markdown, no headers, no asterisks, no bullet symbols.

Identify what's shown, then extract all relevant fitness or nutrition information.
Be concise. User caption: {caption}"""


async def process_food_image(image_data: bytes) -> str:
    return await analyze_image(image_data, _FOOD_PROMPT)


async def process_general_image(image_data: bytes, caption: str = "") -> str:
    prompt = _GENERAL_PROMPT.format(caption=caption or "none")
    try:
        return await analyze_image(image_data, prompt)
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        return ""
