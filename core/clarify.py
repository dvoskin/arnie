"""Mode-gradient clarify-on-swing — a CODE layer over the frozen July-7 prompt.

Pass-1 logs every item (reliably, prompt unchanged). AFTER the write, this runs a
tiny focused model read over the COMMITTED items and, if an item has an unstated
detail that would swing calories past the user's MODE threshold, produces ONE
bundled clarifying question ("how much butter on the toast, and was the chicken
grilled or fried?"). The caller appends it and records a pending-clarification so
the user's next answer updates those entries via update_food_entry.

Why a separate pass (not the prompt): every prompt addition regressed multi-item
completeness (see feedback_arnie_food_prompt_frozen). This never touches arnie.py
and runs CONCURRENTLY with voice_log, so it costs ~no extra wall-clock. It also
never withholds a log — the items are already on the board; the question only
sharpens them.

Mode gradient (calorie-swing threshold to ask):
  quick    → only BIG swings (>250 cal)   — speed first, still catches grilled-vs-fried
  moderate → medium+ (>120 cal)
  strict   → small+ (>60 cal)              — nails the details quick lets ride

Switch: CLARIFY_SWINGS=false disables. Never raises; any miss -> None (no question).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from core.llm import chat

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-5"

_THRESH = {"quick": 250, "moderate": 120, "strict": 60}


def clarify_swings_enabled() -> bool:
    return os.getenv("CLARIFY_SWINGS", "true").lower() in ("true", "1", "yes")


def _model() -> str:
    return os.getenv("CLARIFY_SWINGS_MODEL", _MODEL) or _MODEL


def _mode(user) -> str:
    prefs = getattr(user, "preferences", None)
    m = (getattr(prefs, "food_logging_mode", None) or "moderate").lower()
    return m if m in _THRESH else "moderate"


_SYSTEM = (
    "You are the accuracy check for a nutrition logger. Items were JUST logged with "
    "estimated macros; they are already saved. Find items whose UNSTATED detail would "
    "swing calories by MORE than {thresh} kcal, and ask ONE bundled question to pin them.\n"
    "Swing sources: cooking fat (grilled vs fried, dry vs buttered/oiled), sauce/dressing "
    "amount, vague quantity ('some', a partial), or a branded VARIANT with different macros "
    "(e.g. Core Power vs Core Power Elite). NOT a swing: diet soda, black coffee, water, "
    "plain fruit/veg, an exact branded item, anything the user already specified.\n"
    "OUTPUT: if nothing clears {thresh} kcal, output exactly NONE. Otherwise ONE short "
    "question, coach voice, sentence case, no preamble, bundling the items: "
    "\"quick one so these are right, how much butter on the toast and was the chicken "
    "grilled or fried?\" Never restate macros. Never use ~ or an em dash. Max ~30 words."
)


def _clean(text: str) -> str:
    text = (text or "").strip().replace("~", "")
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    return re.sub(r"\s+", " ", text).strip()


def _items_block(tool_calls, tool_results) -> list[str]:
    """Names + macros of just-logged foods, so the check can judge each one."""
    out = []
    for tc in (tool_calls or []):
        if tc.get("name") != "log_food":
            continue
        inp = tc.get("input") or {}
        name = (inp.get("food_name") or "").strip()
        if not name:
            continue
        qty = inp.get("quantity") or ""
        cal = inp.get("calories")
        out.append(f"- {name} ({qty}) ~{cal} cal" if cal is not None else f"- {name} ({qty})")
    return out


async def clarify_swings(tool_calls, tool_results, user) -> Optional[str]:
    """Return ONE bundled clarify question for mode-exceeding swings, or None.
    Safe to run concurrently with voice_log; never raises."""
    if not clarify_swings_enabled():
        return None
    items = _items_block(tool_calls, tool_results)
    if not items:
        return None
    mode = _mode(user)
    thresh = _THRESH[mode]
    sys = _SYSTEM.format(thresh=thresh)
    facts = f"Accuracy mode: {mode} (ask if swing > {thresh} kcal)\nItems:\n" + "\n".join(items)
    try:
        res = await asyncio.wait_for(
            chat([{"role": "user", "content": facts}], sys,
                 tools=False, max_tokens=80, model=_model()),
            timeout=8.0,
        )
    except Exception as e:
        logger.warning("clarify_swings failed (mode=%s): %s: %s", mode, type(e).__name__, e)
        return None
    out = _clean(res.get("text") or "")
    if not out or out.upper().strip(".!") == "NONE" or len(out) < 8:
        return None
    return out
