import logging
from core.llm import analyze_image

logger = logging.getLogger(__name__)

_FOOD_PROMPT = """You are analyzing a food image for a fitness tracking app. Reply in plain text only — no markdown, no headers, no bullet symbols, no asterisks.

If it's a meal: list each food item on its own line with estimated quantity and macros (cal, protein, carbs, fat).
If it's a nutrition label: state the key numbers — serving size, calories, protein, carbs, fat, fiber.
If it's a receipt or packaging: extract item names and any nutritional info shown.

Keep it concise and factual. Use realistic estimates."""

_SCALE_PROMPT = "Read the weight shown on this scale. Reply with just the number and unit, nothing else."

_WORKOUT_PROMPT = """You are analyzing a workout image for a fitness tracking app. Reply in plain text only — no markdown, no headers.
List each exercise with sets, reps, and weight on its own line."""

_GENERAL_PROMPT = """You are analyzing an image for a fitness/nutrition coaching app. Reply in plain text only — no markdown, no headers, no asterisks, no bullet symbols.

Identify what's shown, then extract all relevant fitness or nutrition information.
Be concise. User caption: {caption}"""


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
