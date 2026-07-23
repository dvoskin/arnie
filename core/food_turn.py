"""Structured food turn — the clean food-logging path (Danny 2026-07-23).

The old path asked one big model to do everything in one breath — decide, log,
write quantities, coach, ask — and every failure of that (question logged as a
food, an uneditable "~2 handfuls romaine, 3 strips chicken, few tbsp dressing"
quantity, phantom logs) grew another guard. This module replaces the guards with
structure: for a food-report turn, ONE small logger pass reads the message and
returns strict JSON —

  log  -> items [{food, amount, unit, calories, protein, carbs, fats}]
  ask  -> points [{label, q}]   (ONE rich-formatted question)
  pass -> not a food report; the normal conversation path takes the turn

A question structurally CANNOT become a food entry (asks and items are different
actions), and quantities are always a clean "amount unit" so every entry is
editable. Composites split into natural separate items (Caesar salad one item,
grilled chicken strips another — Danny). The items are executed through the
EXISTING tool executor (enrichment, dedup, meal-slot inheritance, cards intact)
by impersonating pass-1's tool calls, and the coach (voice_log) talks over the
committed result. Non-food, photos, corrections, mixed food+workout messages, and
non-English reports fall through to the legacy path untouched.

Kill switch: STRUCTURED_FOOD=false.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from core.llm import chat

logger = logging.getLogger(__name__)

ASK_KIND = "food_structured_ask"


def structured_food_enabled() -> bool:
    return os.getenv("STRUCTURED_FOOD", "true").lower() in ("true", "1", "yes")


def _logger_model() -> str:
    # Sonnet by default: the logger also estimates macros, which Haiku fumbles.
    # Tiny prompt, so it's still fast. Env-tunable.
    return os.getenv("FOOD_LOGGER_MODEL", "claude-sonnet-5") or "claude-sonnet-5"


# ── pre-gate: is this plausibly a food report? ────────────────────────────────
# Cheap and conservative. Anything missed just takes the legacy path — the gate
# exists to avoid an extra model call on obvious non-food turns, not to be right.
_CONSUMED_RE = re.compile(
    r"\b(had|ate|eaten|having|grabbed|finished|snacked|downed|drank|"
    r"just\s+(?:had|ate|grabbed|finished|got|made)|"
    r"for\s+(?:breakfast|lunch|dinner|a\s+snack|dessert))\b", re.I)
_MEAL_RE = re.compile(r"\b(breakfast|lunch|dinner|snack|dessert)\b", re.I)
_ACK_RE = re.compile(
    r"^(ok(ay)?|k+|thx|thanks|thank\s+you|ty|cool|nice|great|sweet|got\s+it|gotcha|"
    r"yes|yeah|yep|yup|sure|no+|nope|word|bet|perfect|awesome|good|alright|lol|haha)"
    r"[.!,\s]*$", re.I)
_PLAN_RE = re.compile(
    r"\b(gonna|going\s+to|about\s+to|planning|plan\s+to|might|maybe|probably|"
    r"thinking\s+(?:about|of)|will\s+(?:have|eat|grab)|later\b|not\s+sure)\b", re.I)
_CORRECTION_RE = re.compile(
    r"\b(actually|instead|change|fix|wrong|remove|delete|undo|scratch|"
    r"not\s+the|was\s+supposed)\b", re.I)
# Non-food logging domains → legacy path (log_water / log_exercise / weight).
_NONFOOD_RE = re.compile(
    r"\b(water|weighed|weigh[- ]?in|workout|gym|bench|squat|deadlift|press|"
    r"curls?|reps?|sets?|ran|running|walk\w*|bike|biked|swam|swim|cardio|"
    r"treadmill|jump\s*rope|min(?:ute)?s?\s+of)\b", re.I)


def applies(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 500:
        return False
    if _ACK_RE.match(t) or "?" in t:
        return False
    if _PLAN_RE.search(t) or _CORRECTION_RE.search(t) or _NONFOOD_RE.search(t):
        return False
    return bool(_CONSUMED_RE.search(t) or _MEAL_RE.search(t))


# ── the logger pass ───────────────────────────────────────────────────────────
_SYSTEM = (
    "You are the food LOGGER for a nutrition coach. Read the user's message and "
    "output ONLY minified JSON. No prose, no code fences.\n"
    "Pick exactly one action:\n"
    '1. Not a report of food/drink they consumed -> {"action":"pass"}\n'
    '2. Consumed food, but a quantity or calorie-critical prep detail is genuinely '
    'unclear -> {"action":"ask","points":[{"label":"Chicken","q":"how much, and '
    'grilled or fried?"}]}\n'
    '3. Consumed food with enough detail -> {"action":"log","items":[{"food":'
    '"Caesar salad","amount":2,"unit":"handfuls","calories":180,"protein":4,'
    '"carbs":8,"fats":15}],"say":"Pizza and the Caesar logged, 560 cal and 22g '
    'protein for the pair. Dinner protein-forward and the day lands clean."}\n'
    "RULES:\n"
    '- "say" (log action only): the coach line the user sees. 1-2 short sentences, '
    "sentence case, warm and specific, NAMING every item logged (never just one of "
    "them) with the combined calories and protein for this batch, plus one forward "
    "read using the day context if given. Never the ~ character, never an em dash, "
    "never a list. Sound like a sharp coach texting, not a tracker.\n"
    "- Split a combo into natural SEPARATE items (the salad one item, the chicken "
    "strips another, a drink another) so each is editable on its own line.\n"
    '- "food": short clean name, 2-4 words, capitalized. Fold a stated adjustment '
    'into the name ("Pizza toppings, crust left").\n'
    '- "amount": a number. "unit": one short unit (handfuls, strips, oz, g, cup, '
    "slices, bar, small bowl). The cleanest reading of what they said.\n"
    "- Macros: best estimate for that exact amount; calories consistent with "
    "protein*4 + carbs*4 + fats*9.\n"
    "- ASK whenever any item's amount is vague — 'some', 'a few', 'a bit', 'a "
    "splash', a container portion with no size ('half a salad', 'a bowl') — or a "
    "calorie-dense add-on (dressing, sauce, oil, butter, cheese, nuts) has no "
    "amount. A clear count or mass ('2 slices', '6 oz', 'a banana') never needs "
    "asking. Ask ONCE, at most 3 points, bundling every unclear item; log nothing "
    "until answered. Never ask about something clearly stated, or about water, "
    "diet soda, or black coffee.\n"
    "- When PRIOR CONTEXT shows you already asked and they answered: log EVERYTHING "
    "from the whole exchange with their answers applied. Do NOT ask again — fill "
    "any still-missing detail with your best estimate.\n"
    "- Consumed food only: a plan they haven't eaten or a question is pass."
)


def _format_question(points: list) -> str:
    """One rich-formatted clarify bubble: numbered list, bolded labels."""
    pts = [(str(p.get("label") or "").strip(", ").strip(),
            str(p.get("q") or "").strip())
           for p in points if isinstance(p, dict) and (p.get("q") or "").strip()]
    pts = [(l, q) for l, q in pts if q][:3]
    if not pts:
        return ""
    if len(pts) == 1:
        l, q = pts[0]
        return f"Quick one so it's clean, **{l.lower()}**: {q}" if l else \
               f"Quick one so it's clean: {q}"
    lines = ["Quick one so it's clean:"]
    for i, (l, q) in enumerate(pts, 1):
        lines.append(f"{i}. **{l}**: {q}" if l else f"{i}. {q}")
    return "\n".join(lines)


def _parse(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    start = t.find("{")
    if start < 0:
        return None
    try:
        return json.loads(t[start:t.rfind("}") + 1])
    except Exception:
        return None


async def run(message: str, user, prior: Optional[dict] = None,
              day_line: str = "") -> Optional[dict]:
    """Run the logger pass. Returns
        {"action": "log", "tool_calls": [...], "say": "..."}  ready-to-execute
        {"action": "ask", "text": "..."}          the formatted question
        None                                       pass / any failure → legacy path
    ONE model call per food turn — the coach line rides the same JSON (July-7
    shape: one pass, tools, done). Never raises."""
    if not (message or "").strip():
        return None
    if prior:
        content = (
            f"Earlier they reported: \"{prior.get('original', '')}\"\n"
            f"You asked: \"{prior.get('question', '')}\"\n"
            f"They just answered: \"{message}\"")
    else:
        content = message
    if day_line:
        content = f"{content}\n\nDay context for the 'say' line: {day_line}"
    try:
        res = await chat([{"role": "user", "content": content}], _SYSTEM,
                         tools=False, max_tokens=700, model=_logger_model())
    except Exception as e:
        logger.warning(f"food_turn logger pass failed: {e}")
        return None
    data = _parse(res.get("text") or "")
    if not isinstance(data, dict):
        return None
    action = data.get("action")

    if action == "ask" and not prior:
        text = _format_question(data.get("points") or [])
        return {"action": "ask", "text": text} if text else None

    if action == "log" or (action == "ask" and prior):
        # An ask on the answer turn means the model ignored the do-not-ask rule;
        # never chain questions — fall through to legacy rather than loop.
        if action == "ask":
            return None
        calls = []
        for it in (data.get("items") or []):
            if not isinstance(it, dict):
                continue
            food = str(it.get("food") or "").strip()
            # Structural sanity, not a guard pile: an item is a NAMED FOOD.
            if not food or "?" in food or len(food) > 60:
                continue
            amount = it.get("amount")
            unit = str(it.get("unit") or "").strip()
            try:
                amount = round(float(amount), 2)
                amount = int(amount) if float(amount).is_integer() else amount
            except (TypeError, ValueError):
                amount = None
            qty = f"{amount} {unit}".strip() if amount is not None else unit
            inp = {"food_name": food, "quantity": qty,
                   "estimated": True, "confidence": 0.65}
            for src, dst in (("calories", "calories"), ("protein", "protein"),
                             ("carbs", "carbs"), ("fats", "fats")):
                v = it.get(src)
                if isinstance(v, (int, float)):
                    inp[dst] = v
            mt = str(it.get("meal_type") or "").strip().lower()
            if mt in ("breakfast", "lunch", "dinner", "snack"):
                inp["meal_type"] = mt
            calls.append({"name": "log_food", "input": inp})
        if calls:
            say = str(data.get("say") or "").strip()
            say = say.replace("~", "").replace("—", ",").replace("–", ",")
            return {"action": "log", "tool_calls": calls, "say": say[:400]}
    return None
