"""LLM fallback: estimate a food's micronutrient panel when no database (USDA)
match exists — the gap foods (restaurant / branded / composite meals USDA has no
entry for). This is explicitly an ESTIMATE from the model's knowledge of typical
composition; callers flag it (micros_estimated) so the UI renders it softer than
measured values and never claims a confident "good source".

Cheap + low-latency: one Haiku call, per-portion amounts in our units, parsed into
the same {key: amount} shape USDA produces so the rest of the pipeline is unchanged.
"""
from __future__ import annotations

import json
import logging

from api.usda import micro_units
from core.nutrition import _DAILY_VALUES

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_KEYS = list(_DAILY_VALUES.keys())   # the vitamins + minerals we estimate

# Macro-adjacent nutrients the health score needs but gap foods never get from
# a database match (they live in dedicated food_entries columns, not the micro
# panel). Estimated in the SAME Haiku call; caller pops them out of the result.
# Caps are per-single-food plausibility guards, mirroring the sodium clamp in
# food_intelligence (5000 mg) — implausible values are dropped, not stored.
_EXTRA_KEYS = {"fiber": ("g", 60.0), "sugar": ("g", 250.0), "sodium": ("mg", 5000.0)}

_SYSTEM = (
    "You are a precise nutrition database. From your knowledge of a food's typical "
    "composition (ingredients, fortification), estimate its vitamin and mineral "
    "content. Output ONLY a JSON object — no prose, no code fences."
)


def _key_list() -> str:
    micros = ", ".join(f"{k} ({micro_units(k)})" for k in _KEYS)
    extras = ", ".join(f"{k} ({unit})" for k, (unit, _cap) in _EXTRA_KEYS.items())
    return f"{extras}, {micros}"


def _parse_estimate(text: str) -> dict | None:
    """Parse the model's JSON reply into a clean {key: amount} micro dict: only our
    keys, positive values, and drop hallucinated absurdities (>300% DV for one food)."""
    text = (text or "").strip()
    if text.startswith("```"):                     # tolerate accidental code fences
        text = text.strip("`")
        text = text[4:].strip() if text[:4].lower() == "json" else text
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    out: dict = {}
    for k in _KEYS:
        v = data.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            continue
        if v > 3 * _DAILY_VALUES[k]:                # implausible for a single food
            continue
        out[k] = round(float(v), 2)
    for k, (_unit, cap) in _EXTRA_KEYS.items():
        v = data.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            continue
        if v > cap:                                 # implausible for a single food
            continue
        out[k] = round(float(v), 2)
    return out or None


async def estimate_micros(food_name: str, quantity: str | None,
                          calories: float, protein: float,
                          carbs: float, fat: float) -> dict | None:
    """Best-effort per-PORTION nutrient estimates ({key: amount} in our units)
    for a food with no database match. Includes the vitamin/mineral panel PLUS
    fiber/sugar/sodium (callers pop those into the dedicated entry columns).
    None on any failure (caller just shows no panel)."""
    from core.llm import _get_anthropic

    portion = (quantity or "").strip() or f"a ~{calories:.0f} kcal serving"
    prompt = (
        f"Food: {food_name}\n"
        f"Portion: {portion}\n"
        f"Macros for this portion: {calories:.0f} kcal, {protein:.0f} g protein, "
        f"{carbs:.0f} g carbs, {fat:.0f} g fat.\n\n"
        f"Estimate the amount of each micronutrient IN THIS WHOLE PORTION, in the "
        f"unit shown:\n{_key_list()}\n\n"
        "Rules:\n"
        "- Ground it in the food's real composition and any fortification.\n"
        "- Include ONLY nutrients present in a meaningful amount; omit trace/zero.\n"
        "- Values are plain numbers (no units). Be realistic, not generous.\n"
        'Return JSON only, e.g. {"potassium": 420, "vitamin_c": 9, "vitamin_b6": 0.4}.'
    )
    try:
        client = _get_anthropic()
        resp = await client.messages.create(
            model=_MODEL, max_tokens=400, system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in (getattr(resp, "content", []) or [])
            if getattr(b, "type", None) == "text"
        )
    except Exception as e:
        logger.warning(f"micro estimate failed for {food_name!r}: {e}")
        return None
    return _parse_estimate(text)
