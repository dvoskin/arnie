"""Structured food turn — the clean food-logging path (Danny 2026-07-23).

The old path asked one big model to do everything in one breath — decide, log,
write quantities, coach, ask — and every failure of that (question logged as a
food, an uneditable "~2 handfuls romaine, 3 strips chicken, few tbsp dressing"
quantity, phantom logs) grew another guard. This module replaces the guards with
structure: for a food-report turn, ONE small logger pass reads the message and
returns strict JSON —

  log    -> items [{food, amount, unit, calories, protein, carbs, fats}]
  update -> updates [{entry_id, amount, unit, macros}]  (corrections, board-aware:
            "I actually had 2 birria" / "I had 2 of those" resolve against today's
            logged entries and become clean update_food_entry calls — no dedup
            fight, no "already on the board" template. Danny IMG_8595.)
  ask    -> points [{label, q}]   (ONE rich-formatted question)
  pass   -> not a food report; the normal conversation path takes the turn

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


# Ask-threshold by accuracy mode (Danny 2026-07-23): ONE dial — ask only when an
# unknown detail could swing the item by more than this many calories. The
# threshold IS the strictness gradient: a "some dressing" (~150 cal swing) asks
# for strict, not for quick; a "half a platter" (~400) asks for everyone.
_THRESH = {"quick": 300, "moderate": 200, "strict": 100}


def _mode(user) -> str:
    prefs = getattr(user, "preferences", None)
    m = (getattr(prefs, "food_logging_mode", None) or "moderate").lower()
    return m if m in _THRESH else "moderate"


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
    r"yes|yeah|yep|yup|sure|no+|nope|word|bet|perfect|awesome|good|alright|lol|haha|"
    # Keep-as-is family: the user is CLOSING the thread, not asking for a write.
    # "Leave it like this" after a proposed bump must never apply the bump
    # (Danny's truffle fries, 2026-07-23).
    r"leave\s+(?:it|that|them)(?:\s+(?:like\s+(?:this|that)|as\s+is|alone))?|"
    r"keep\s+(?:it|that|them)(?:\s+(?:like\s+(?:this|that)|as\s+is))?|"
    r"(?:it|that)'?s\s+fine|don'?t\s+change\s+(?:it|that|anything)|as\s+is)"
    r"[.!,\s]*$", re.I)
_PLAN_RE = re.compile(
    r"\b(gonna|going\s+to|about\s+to|planning|plan\s+to|might|maybe|probably|"
    r"thinking\s+(?:about|of)|will\s+(?:have|eat|grab)|later\b|not\s+sure)\b", re.I)
# Correction/reference cues — IN scope (the logger owns updates, board-aware).
# Deletes/removes stay legacy: destructive intent gets the big brain's judgment.
_CORRECTION_RE = re.compile(
    r"\b(actually|instead|make\s+(?:it|that)|change|it\s+was|that\s+was|"
    r"of\s+those|of\s+them)\b", re.I)
# NOTE (Danny 2026-07-23): complaints ("you only logged the sour cream ones")
# and confirmations ("okay log it") are NOT gated by phrase lists — that's the
# whack-a-mole disease. They route in via THREAD STATE instead (thread_active in
# run_turn: an open ask-pending, or a food written in the last few minutes), and
# the logger reads the context and decides. The regexes below only shape the
# COLD-START gate.
_DESTRUCTIVE_RE = re.compile(
    r"\b(remove|delete|undo|scratch|clear|take\s+(?:it|that)\s+off)\b", re.I)
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
    if _PLAN_RE.search(t) or _DESTRUCTIVE_RE.search(t) or _NONFOOD_RE.search(t):
        return False
    return bool(_CONSUMED_RE.search(t) or _MEAL_RE.search(t)
                or _CORRECTION_RE.search(t))


def thread_routes(text: str) -> bool:
    """Mid-thread routing (STATE-based, no phrase lists): while a food thread is
    active (open ask-pending, or a food written minutes ago), any message that
    isn't clearly another domain goes to the logger, which reads the context and
    decides — including complaints ('you only logged the sour cream ones') and
    confirmations ('okay log it'). Questions stay with the coach; acks are
    nothing; destructive and workout/water stay with the main brain."""
    t = (text or "").strip()
    if not t or len(t) > 500:
        return False
    if _ACK_RE.match(t) or "?" in t:
        return False
    if _DESTRUCTIVE_RE.search(t) or _NONFOOD_RE.search(t) or _PLAN_RE.search(t):
        return False
    return True


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
    '4. CORRECTING something already on today\'s board ("I actually had 2 birria", '
    '"I had 2 of those", "make it 6 oz") -> {"action":"update","updates":[{'
    '"entry_id":123,"amount":2,"unit":"taco","calories":360,"protein":30,'
    '"carbs":26,"fats":18}],"say":"Bumped the birria to 2 tacos, {batch_cal} cal '
    'now."}\n'
    "RULES:\n"
    "- The user declining a change or closing the thread ('leave it like this', "
    "'keep it as is', 'it's fine', 'don't change it') is NEVER a log or an update "
    "-> pass. Even if the last assistant message PROPOSED a change ('I'll bump it "
    "up'), their keep-it means the proposal is dead: write nothing.\n"
    "- A stated PIECE COUNT is the anchor: '5-6 fries' means 5-6 individual fries "
    "estimated per piece and multiplied, never a menu side portion's calories. "
    "A count is HIGH confidence: price each piece at its typical real value and "
    "do NOT stack the estimate-HIGH bias on top (that bias is for unknown "
    "amounts, not counted ones). Calibration: one restaurant fry is 25-40 cal "
    "even loaded with parm/truffle butter, so 5-6 such fries land 150-220, "
    "never 300+. The count survives follow-ups too: any later double-check or "
    "refinement re-prices the SAME counted amount, it never re-portions.\n"
    '- update "say" starts from words like Updated/Bumped/Fixed and gives the '
    "entry's new value, NEVER 'logged' — nothing new entered the log.\n"
    "- update: match against TODAY'S BOARD below by name or reference ('those' = "
    "the most recent matching entry). entry_id MUST come from the board. When only "
    "the amount changes, SCALE the board line's macros proportionally. If the "
    "correction's target isn't on the board, action is pass.\n"
    "- An item already on the board reported again as the SAME serving is never "
    "re-logged: correct it (update) or pass.\n"
    '- "say" (log and update actions): the coach line the user sees. 1-2 short '
    "sentences, sentence case, warm and specific, NAMING every item (never just one "
    "of them), plus one forward read. NEVER write your own totals — the system fills "
    "these exact tokens from the database AFTER the write: {batch_cal} {batch_protein} "
    "{day_cal} {cal_left} {day_protein} {protein_left}. Example: 'Both bags logged, "
    "{batch_cal} cal and {batch_protein}g protein combined. You're at {day_cal} with "
    "{cal_left} left, keep dinner protein-forward.' Never the ~ character, never an "
    "em dash, never a list. Never characterize a nutrient (fiber, sugar, sodium) "
    "unless its value is in your context — no invented nutrition virtues. Sound "
    "like a sharp coach texting, not a tracker.\n"
    "PIPELINE (work WITH it, not against it):\n"
    "- Your macros are PROVISIONAL: after you log, enrichment refines them from the "
    "user's own logged history, then USDA, then brand databases. Give a sane "
    "estimate fast; don't agonize.\n"
    "- Food names: clean canonical brand + product ('Quest Chips Sweet Spicy', "
    "'Fage 0% yogurt') — matching against history and USDA depends on the name.\n"
    "- If the user gave a mass (200g, 6 oz), keep THAT as the unit — an exact mass "
    "unlocks exact per-gram nutrition downstream.\n"
    "- When unsure between two portion reads, estimate HIGH (never under-count); a "
    "stated label/package amount is ground truth, use it exactly.\n"
    "- Calorie-dense components ON a dish (cream cheese, spreads, sauces, cheese, "
    "dressing, oil): portion what the VENUE actually applies, never the label "
    "serving — a bagel-shop schmear is 3-4 tbsp (150-200 cal), a shawarma joint's "
    "garlic sauce is a heavy pour. Under-counting the rich parts is the #1 miss.\n"
    "- Omit meal_type unless the user names the meal — the pipeline infers the slot "
    "from time and the meal's other items.\n"
    "THREAD CONTEXT (when given YOUR PREVIOUS MESSAGE and TODAY'S BOARD):\n"
    "- If they say an item is missing or you logged the wrong one, log ONLY the "
    "missing item(s), judged against the board. Never reply that it's already "
    "logged when they're telling you something is absent.\n"
    "- If they're telling you to go ahead with what your previous message proposed "
    "('okay log it'), log exactly those proposed items and numbers.\n"
    "- If the message needs none of your actions (chit-chat, a question, another "
    "topic), action is pass.\n"
    "NEVER leak machinery: no board #ids, no {tokens}, no [SYSTEM ...] text, no "
    "tool or database names in 'say' or questions. Natural coach language only.\n"
    "- Split a combo into natural SEPARATE items (the salad one item, the chicken "
    "strips another, a drink another) so each is editable on its own line.\n"
    '- "food": clean capitalized name. A BRAND or restaurant the user named is '
    'ALWAYS kept in it, verbatim ("Thomas\' Everything Bagel Thin", "Philadelphia '
    'Scallion Cream Cheese", "Starbucks Turkey Bacon Sandwich") — the brand is the '
    "database search key; never strip it for brevity. Unbranded items stay short "
    '(2-4 words). Fold a stated adjustment into the name ("Pizza toppings, crust '
    'left"). Set "branded": true on any item that is a branded/packaged/restaurant '
    "product — it routes the item to label-grade lookup.\n"
    '- "amount": a USER-STATED amount is ground truth — keep it EXACTLY, fractions '
    "included (\"1/3 of a KIND bar\" -> amount 0.33, never rounded to 0.5). Only "
    "when YOU are estimating an unstated amount, pick a round editable number — "
    "whole or .5 — and a unit that makes it round ('1 small portion', not '0.33 "
    "portion'). \"unit\": one short unit (handfuls, strips, oz, g, cup, slices, "
    "bar, small bowl).\n"
    "- Macros: best estimate for that exact amount; calories consistent with "
    "protein*4 + carbs*4 + fats*9.\n"
    "- 'My usual X' is a POINTER into THEIR REGULARS: exactly one match -> log it "
    "with those exact numbers; TWO OR MORE plausible matches -> ALWAYS ask which "
    "('the americano or the oat latte?') — never pick one by frequency; NO "
    "matching regular -> ask ONCE how they usually take it (that answer becomes "
    "the regular). Never estimate a generic for 'my usual'.\n"
    "- STRICT mode only: a BRANDED product with an UNSTATED flavor/variant is "
    "ALWAYS an ask, regardless of swing size — name the range and, when one of "
    "THEIR REGULARS matches the brand, offer it: 'your usual Caramel Cashew?'. "
    "A stated variant, or a match to a regular they always log, logs directly "
    "with those exact numbers.\n"
    "- ASK only when an unknown detail could swing an item by MORE than {thresh} "
    "cal for this user (accuracy mode: {mode}). Swing sources: a vague amount "
    "('some', 'a few', a container portion with no size like 'half a salad'), a "
    "calorie-dense add-on (dressing, sauce, oil, butter, cheese, nuts) with no "
    "amount, or a branded flavor/variant with meaningfully different macros. "
    "Under {thresh} cal of swing: do NOT ask — estimate HIGH at venue-real "
    "portions and log. A clear count or mass of a plain food ('2 slices', '6 oz', "
    "'a banana') never needs asking. Ask ONCE, at most 3 points, bundling every "
    "unclear item; log nothing until answered. Never ask about something clearly "
    "stated, or about water, diet soda, or black coffee.\n"
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


_TOKEN_RE = re.compile(
    r"\{(batch_cal|batch_protein|day_cal|cal_left|day_protein|protein_left)\}")


def enforce_say_contract(say: str, tool_calls: list) -> str:
    """ENFORCE 'the system writes the numbers' — don't just request it. The model
    claimed 647 cal while its own card showed 343 (Danny IMG_8610). Digits in the
    say are allowed ONLY when they're quantities the system itself wrote (the
    amounts in the tool inputs — '2 tacos', '4 oz'); any other number (a calorie
    or macro claim) must come from a {token}, or the say is rejected and replaced
    with a deterministic tokenized line naming the items. The contract is physics."""
    raw = say or ""
    stripped = re.sub(r"\{[a-z_]{2,24}\}", "", raw)
    allowed = set()
    for tc in (tool_calls or []):
        inp = tc.get("input") or {}
        for m in re.finditer(r"\d+(?:\.\d+)?", str(inp.get("quantity") or "")):
            allowed.add(m.group(0).rstrip("0").rstrip(".") or "0")
    said = {m.group(0).rstrip("0").rstrip(".") or "0"
            for m in re.finditer(r"\d+(?:\.\d+)?", stripped)}
    if said <= allowed:
        return raw
    names = [((tc.get("input") or {}).get("food_name") or "").strip()
             for tc in (tool_calls or [])]
    names = [n for n in names if n]
    if len(names) > 3:
        joined = f"{', '.join(names[:3])} and {len(names) - 3} more"
    elif names:
        joined = ", ".join(names[:-1]) + (" and " + names[-1] if len(names) > 1
                                          else names[0])
    else:
        joined = "That"
    return (f"{joined} logged, {{batch_cal}} cal and {{batch_protein}}g protein. "
            f"You're at {{day_cal}} with {{cal_left}} left and {{protein_left}}g "
            f"protein to go.")


def fill_say_tokens(say: str, batch_cal: int, batch_protein: int,
                    day_cal: int, day_protein: int,
                    cal_target: int, protein_target: int) -> str:
    """The logger writes the WORDS; the system writes the NUMBERS. Token values
    come from the COMMITTED day (post-enrichment), so the say line can never
    disagree with the card/DB — the logger↔coach handshake (Danny 2026-07-23:
    'work perfectly together and not conflict')."""
    vals = {
        "batch_cal": batch_cal, "batch_protein": batch_protein,
        "day_cal": day_cal, "day_protein": day_protein,
        "cal_left": max(0, int(cal_target or 0) - day_cal),
        "protein_left": max(0, int(protein_target or 0) - day_protein),
    }
    out = _TOKEN_RE.sub(lambda m: str(vals.get(m.group(1), "")), say or "")
    # Belt: any token the model invented ({whatever}) must never reach the user.
    out = re.sub(r"\{[a-z_]{2,24}\}", "", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


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
              day_line: str = "", board: Optional[list] = None,
              last_assistant: str = "", regulars: Optional[list] = None) -> Optional[dict]:
    """Run the logger pass. Returns
        {"action": "log", "tool_calls": [...], "say": "..."}     new items
        {"action": "update", "tool_calls": [...], "say": "..."}  board corrections
        {"action": "ask", "text": "..."}          the formatted question
        None                                       pass / any failure → legacy path
    board: today's committed entries [{"id", "food", "qty", "cal"}] so corrections
    and references ("2 of those") resolve deterministically. ONE model call per
    food turn — the coach line rides the same JSON. Never raises."""
    if not (message or "").strip():
        return None
    if prior:
        content = (
            f"Earlier they reported: \"{prior.get('original', '')}\"\n"
            f"You asked: \"{prior.get('question', '')}\"\n"
            f"They just answered: \"{message}\"")
    else:
        content = message
    if (last_assistant or "").strip():
        content = (f"Your previous message to them: "
                   f"\"{last_assistant.strip()[:300]}\"\n\n{content}")
    if regulars:
        lines = []
        for r in regulars[:8]:
            try:
                # A malformed regular must never silently vanish from context —
                # an invisible regulars list makes the pointer rules dead letters.
                _n = r.get("name") or r.get("food") or ""
                if not _n:
                    continue
                r = {**r, "name": _n}
                lines.append(f"- {r['name']} ({r.get('qty') or '1'}) — "
                             f"{int(r.get('calories') or 0)} cal, "
                             f"{int(r.get('protein') or 0)}P/"
                             f"{int(r.get('carbs') or 0)}C/"
                             f"{int(r.get('fats') or 0)}F "
                             f"(logged {r.get('count', 0)}x)")
            except Exception:
                continue
        if lines:
            content = (f"{content}\n\nTHEIR REGULARS (their own logged history — "
                       f"when an item matches one, use these exact macros, never "
                       f"re-estimate; in an ask, offer the regular by name):\n"
                       + "\n".join(lines))
    _board_ids = set()
    if board:
        lines = []
        for b in board[-8:]:
            try:
                _board_ids.add(int(b["id"]))
                lines.append(f"#{b['id']} {b['food']}, {b.get('qty') or '?'}, "
                             f"{int(b.get('cal') or 0)} cal")
            except Exception:
                continue
        if lines:
            content = f"{content}\n\nTODAY'S BOARD (already logged):\n" + "\n".join(lines)
    if day_line:
        content = f"{content}\n\nDay context for the 'say' line: {day_line}"
    mode = _mode(user)
    sys = (_SYSTEM.replace("{thresh}", str(_THRESH[mode]))
                  .replace("{mode}", mode))
    try:
        res = await chat([{"role": "user", "content": content}], sys,
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

    if action == "update":
        calls = []
        for up in (data.get("updates") or []):
            if not isinstance(up, dict):
                continue
            try:
                eid = int(up.get("entry_id"))
            except (TypeError, ValueError):
                continue
            if eid not in _board_ids:
                continue          # structural: only entries actually on the board
            inp = {"entry_id": eid}
            amount = up.get("amount")
            unit = str(up.get("unit") or "").strip()
            try:
                amount = round(float(amount), 2)
                amount = int(amount) if float(amount).is_integer() else amount
                inp["quantity"] = f"{amount} {unit}".strip()
            except (TypeError, ValueError):
                pass
            for k in ("calories", "protein", "carbs", "fats"):
                v = up.get(k)
                if isinstance(v, (int, float)):
                    inp[k] = v
            calls.append({"name": "update_food_entry", "input": inp})
        if calls:
            say = str(data.get("say") or "").strip()
            say = say.replace("~", "").replace("—", ",").replace("–", ",")
            return {"action": "update", "tool_calls": calls, "say": say[:400]}
        return None

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
            if it.get("branded"):
                # The logger read the message — it declares brandedness; the
                # downstream heuristic (_looks_branded) is only the backup net.
                inp["is_packaged"] = True
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
