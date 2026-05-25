import logging
from core.llm import analyze_image

logger = logging.getLogger(__name__)

_FOOD_PROMPT = """Analyze this food/nutrition image for a fitness tracking app.

If it's a meal or food item:
  List each visible food, estimate serving size, and give macros (calories, protein, carbs, fats).
  Format: Item | Quantity | Cal | P | C | F

If it's a nutrition label:
  Extract exactly: serving size, calories, protein, carbs, fats, fiber, sugar, sodium.

If it's a receipt, menu, or food packaging:
  Extract the relevant food items and any nutritional info visible.

Use realistic estimates. Be specific with portion sizes."""

_SCALE_PROMPT = "Read the weight shown on this scale. State the number and unit clearly."

_WORKOUT_PROMPT = """Analyze this workout-related image.
Extract: exercise names, sets, reps, weights. Describe what you see concisely."""

_GENERAL_PROMPT = """Analyze this image for a fitness/nutrition coaching app.
Determine its type (food, nutrition label, scale, workout log, body photo, other).
Extract all relevant health/fitness information.
Context from user: {caption}"""


async def process_food_image(image_data: bytes) -> str:
    return await analyze_image(image_data, _FOOD_PROMPT)


async def process_scale_image(image_data: bytes) -> str:
    return await analyze_image(image_data, _SCALE_PROMPT)


async def process_workout_image(image_data: bytes) -> str:
    return await analyze_image(image_data, _WORKOUT_PROMPT)


async def process_general_image(image_data: bytes, caption: str = "") -> str:
    prompt = _GENERAL_PROMPT.format(caption=caption or "none")
    try:
        return await analyze_image(image_data, prompt)
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        return ""
