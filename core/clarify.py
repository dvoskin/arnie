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
    """Log-FIRST clarify-on-swing (append a question AFTER logging). Default OFF
    (2026-07-22): the July-7 direction is ask-BEFORE-log (ASK_FIRST_HOLD), not a
    trailing question — and this path leaked the model's ask-or-not reasoning to
    users. CLARIFY_SWINGS=true restores the append-after behavior."""
    return os.getenv("CLARIFY_SWINGS", "false").lower() in ("true", "1", "yes")


def ask_first_hold_enabled() -> bool:
    """Kill switch for the ASK-FIRST hold. **Default ON** (2026-07-23, Danny: "ask
    and clarify vague things like some strawberries BEFORE, then log cleanly"). In
    strict mode a food-log turn with a VAGUE QUANTITY or an unstated high-swing detail
    HOLDS the write and asks BEFORE logging (July-7 behavior) instead of estimate-and-
    flagging. Held items are STASHED on the pending (payload_json); the answer turn
    logs them with the confirmed amount — model-refined when it cooperates, replayed
    deterministically from the stash when it loops. The no-tool-phantom blocker is
    resolved: H (the marker made mode-aware, 2026-07-23) routes a strict-mode phantom
    to the HOLD/ask instead of a force-log. ASK_FIRST_HOLD=false → log-first with the
    estimate flag. Applies to STRICT mode only (is_ask_first_mode)."""
    return os.getenv("ASK_FIRST_HOLD", "true").lower() in ("true", "1", "yes")


def is_ask_first_mode(user) -> bool:
    """Ask-before-log applies to ALL users (Danny 2026-07-23): a vague quantity like
    'some strawberries' warrants a 'how much?' for everyone — you can't log it cleanly
    otherwise. The clarification DEPTH scales with mode (see clarify_swings): non-strict
    asks only the vague quantity; STRICT also asks cooking method, added fat, and sauce.
    The caller already gates on not-in-onboarding + a real food log."""
    return True


def _model() -> str:
    return os.getenv("CLARIFY_SWINGS_MODEL", _MODEL) or _MODEL


def _mode(user) -> str:
    prefs = getattr(user, "preferences", None)
    m = (getattr(prefs, "food_logging_mode", None) or "moderate").lower()
    return m if m in _THRESH else "moderate"


# Mode-gradient clarification (Danny 2026-07-23). ALL users get asked on a vague
# QUANTITY; STRICT users ALSO get asked cooking method, added fat, and sauce.
_BASE = (
    "You are the accuracy check for a nutrition logger. You get the USER'S EXACT MESSAGE "
    "and the items the model is about to log. The quantities in the proposal may be the "
    "model's GUESS — your job is to catch when the USER was vague so we confirm instead "
    "of guessing.\n"
    "ALWAYS ask when the USER'S OWN WORDS gave a vague or unspecified QUANTITY, for ANY "
    "food, even plain fruit or veg or a low-calorie item: 'some', 'a bit', 'a little', "
    "'a handful', 'a few', 'a couple', 'a piece', a partial, or no amount at all. A "
    "proposed quantity carrying a '~', 'about', or 'approx' is a guess from a vague "
    "input, so ask to confirm the real amount.\n"
)
_STRICT_EXTRA = (
    "This user wants STRICT accuracy. ALSO, for any COOKED or COMPOSITE food, ask the "
    "cooking method (grilled, fried, baked), any added fat (butter, oil), and any sauce "
    "or dressing, even if the calorie impact is small, plus a branded VARIANT with "
    "different macros. Bundle every open detail into the single question.\n"
)
_NONSTRICT_EXTRA = (
    "Ask ONLY about a vague quantity. Do NOT ask this user about cooking method, added "
    "fat, or sauce.\n"
)
_OUT = (
    "Never ask about a clearly stated amount, a single countable unit (an apple, a "
    "banana, a coffee, 2 eggs, 200g chicken), diet soda, black coffee, or water.\n"
    "OUTPUT: if there is nothing to pin down, output exactly NONE. Otherwise ONE short "
    "question, coach voice, sentence case, no preamble, bundling everything: \"quick one "
    "so it's clean, how much chicken, how was it cooked, and any oil or sauce?\" Never "
    "restate macros. Never use ~ or an em dash. Max ~35 words."
)


def _system_for(mode: str) -> str:
    return _BASE + (_STRICT_EXTRA if mode == "strict" else _NONSTRICT_EXTRA) + _OUT


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


async def clarify_swings(tool_calls, tool_results, user, user_message="") -> Optional[str]:
    """Return ONE bundled clarify question for a vague quantity (or, for strict users,
    an unstated prep detail), or None. Judges the USER'S OWN WORDS (user_message) — the
    model estimates 'some' -> '~1 cup' into the proposal, so checking only the proposal
    misses the vagueness. Safe to run concurrently; never raises. Callers gate."""
    items = _items_block(tool_calls, tool_results)
    if not items:
        return None
    mode = _mode(user)
    sys = _system_for(mode)   # non-strict: vague quantity only; strict: + cooking/fat/sauce
    facts = (f"User's exact message: \"{(user_message or '').strip()}\"\n"
             f"User accuracy mode: {mode}\nItems the model proposes to log:\n"
             + "\n".join(items))
    try:
        res = await asyncio.wait_for(
            chat([{"role": "user", "content": facts}], sys,
                 tools=False, max_tokens=100, model=_model()),
            timeout=8.0,
        )
    except Exception as e:
        logger.warning("clarify_swings failed (mode=%s): %s: %s", mode, type(e).__name__, e)
        return None
    out = _clean(res.get("text") or "")
    # OUTPUT GUARD (Danny 2026-07-22): the model sometimes NARRATES its no-ask
    # reasoning instead of emitting a bare "NONE" ("Fritos are a fixed portion...
    # would swing more than 60 kcal. NONE" / "...no real ambiguity to ask about.
    # Both items are exact branded products with...") and that leaked to the user.
    # A real clarify question is ALWAYS a short question, so require a "?", reject
    # any output carrying the NONE sentinel, and cap the length — the reasoning
    # leak has no "?" and is long, so all three catch it.
    if (not out or len(out) < 8 or len(out) > 280   # strict bundles quantity+cooking+fat+sauce
            or "?" not in out
            or "NONE" in out.upper()):
        return None
    return out
