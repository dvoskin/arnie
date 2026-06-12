"""
Smart photo preprocessor.

Two-step vision pipeline:
  1. classify_image() — one cheap vision call (max_tokens=20) returns a label.
  2. extract_*() — type-specific vision call emits a TAGGED structured block
     the main LLM reads to decide which existing tool(s) to call (log_food,
     log_exercise, track_metric, log_body_weight, coach_on_photo, ...).

The LLM never sees raw photos directly — it sees the tagged extraction blocks
plus the user's caption. This preserves Arnie's existing photo flow (vision
preprocessor → LLM with tools) while extending it to handle workouts, blood
tests, wearables, food diaries, menus, fridges, grocery, delivery apps,
body progress, and packaged products.

Legacy wrappers (process_food_image, process_general_image) are kept so the
bot handler and any other callers continue to work unchanged during rollout.
"""
import logging
from core.llm import analyze_image

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: CLASSIFICATION PROMPT
# Tiny output (one label). Use max_tokens=20.
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFY_PROMPT = """Classify this image into ONE of these categories. Reply with ONLY the label, nothing else:

PREPARED_MEAL — a plated/cooked meal, food on a plate, restaurant dish, homemade dish
PACKAGED_PRODUCT — a packaged item with a visible brand/label (bottle, bar, carton, can, box, pouch)
MENU — a restaurant menu (paper or digital, listing dishes)
FRIDGE — inside view of a fridge, freezer, or pantry showing ingredients
GROCERY — grocery cart, grocery items laid out, OR a grocery receipt
DELIVERY_APP — screenshot of a food delivery app (Sweetgreen, UberEats, DoorDash, etc.)
WORKOUT_LOG — a workout note (Apple Notes, gym app, handwritten paper, whiteboard) showing exercises
BLOOD_TEST — a lab report screenshot or photo (cholesterol panel, blood panel, glucose, etc.)
WEARABLE — screenshot of a wearable app/device (Whoop, Oura, Apple Watch, Garmin, Fitbit)
FOOD_DIARY — screenshot of another food-logging app (MyFitnessPal, Cronometer, Lose It!) showing logged meals
BODY_PROGRESS — a body/mirror photo, progress shot
UNKNOWN — anything else, or unclear

Reply with ONLY one label from above."""


VALID_LABELS = {
    "PREPARED_MEAL", "PACKAGED_PRODUCT", "MENU", "FRIDGE", "GROCERY",
    "DELIVERY_APP", "WORKOUT_LOG", "BLOOD_TEST", "WEARABLE", "FOOD_DIARY",
    "BODY_PROGRESS", "UNKNOWN",
}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: TYPE-SPECIFIC EXTRACTOR PROMPTS
# Each emits a TAGGED block the LLM routes on.
# ─────────────────────────────────────────────────────────────────────────────

# Shared estimation rules used across food-related extractors.
_FOOD_ESTIMATION_RULES = """Estimation rules:
- State prep method when visible (grilled, fried, steamed, raw).
- Restaurant or packaged meals: estimate 30-50% larger than typical home portions.
- Account for hidden calories: pan-cooked items assume oil/butter (~100-150 cal); sauces and dressings add 100-300 cal.
- Use realistic portion sizes — a restaurant chicken breast is typically 7-8oz, not 4oz.
- When prep is not clearly visible, note it: "chicken (prep unclear)".
- For bowls, salads, wraps: always list the BASE as its own line.
- BIAS HIGH on calories and macros — Arnie systematically undercounts; better to overestimate slightly than under.
"""


# 1) PREPARED MEAL — intent-aware. Caption decides LOG vs DECIDE vs ASK.
_PREPARED_MEAL_PROMPT = """You are analyzing a meal photo for a fitness tracking app. Reply in plain text only — no markdown.

User caption: {caption}

FIRST decide intent from the caption:
- INTENT=LOG if caption uses past/present tense ("had", "ate", "having", "just finished", "for lunch", "for breakfast", logging language, OR if no caption is given AND the meal looks already partially consumed)
- INTENT=DECIDE if caption asks a question ("should I eat this?", "is this okay?", "what do you think?", "good?", "?")
- INTENT=ASK if caption is empty AND meal is untouched (cannot tell if they're about to eat or asking)

Then emit ONE of these tagged blocks based on intent:

IF INTENT=LOG — emit a FOOD_LOG block for downstream log_food calls:
[FOOD_LOG]
INTENT: log
• [item name], [quantity], [cal] cal, [protein]g P, [carbs]g C, [fat]g F
• [item name], [quantity], [cal] cal, [protein]g P, [carbs]g C, [fat]g F
TOTAL: [sum cal] cal, [sum protein]g P
CONFIDENCE: 0.0-1.0
[/FOOD_LOG]

IF INTENT=DECIDE — emit a PREPARED_MEAL_DECISION block for coach_on_photo:
[PREPARED_MEAL_DECISION]
Items visible:
• [item name], ~[cal] cal, ~[protein]g P
ESTIMATED_TOTAL: [cal] cal, [protein]g P, [carbs]g C, [fat]g F
CONFIDENCE: 0.0-1.0
[/PREPARED_MEAL_DECISION]

IF INTENT=ASK — emit:
[PREPARED_MEAL_AMBIGUOUS]
Visible: [brief description]
Likely items: [item], [item]
ESTIMATED_TOTAL: ~[cal] cal
ASK_USER: "you eating this, or asking?"
[/PREPARED_MEAL_AMBIGUOUS]

""" + _FOOD_ESTIMATION_RULES


# 2) PACKAGED PRODUCT — branded item with visible label.
_PACKAGED_PRODUCT_PROMPT = """You are analyzing a packaged food product photo. Reply in plain text — no markdown.

User caption: {caption}

Emit a FOOD_LOG block with the PACKAGED line format:
[FOOD_LOG]
INTENT: log
PACKAGED: [brand] [product name + flavor], [serving size from label, e.g. "11 fl oz (1 carton)"], [cal] cal, [protein]g P, [carbs]g C, [fat]g F
CONFIDENCE: 0.0-1.0
[/FOOD_LOG]

Pull brand and flavor VERBATIM from the package — do not paraphrase ("a pistachio shake").
If a macro is not visible, write "?" but ALWAYS fill brand, product name/flavor, serving size — downstream enrichment uses these.
Set CONFIDENCE >= 0.9 if label is fully legible; lower if blurry/partial.
"""


# 3) MENU — restaurant menu, paper or digital.
_MENU_PROMPT = """You are analyzing a restaurant menu photo. Reply in plain text — no markdown.

User caption: {caption}

FIRST, check if this is an ACTUAL menu the user is choosing from, or a stock/template/sample image.
Signs of a TEMPLATE (not a real menu):
- Generic placeholder dish names ("Best Burger", "Delicious Meat", "Best Taste", "Special Dish")
- Obvious typos that real restaurants wouldn't ship ("Browne", "Apple Pe", "Tonc", "Cock Tail")
- Unrealistic uniform pricing ($14 water, all prices in $10-$14 range)
- Watermarks/source URLs ("graphicsfamily.com", "freepik", "shutterstock", "canva")
- "RESTAURANT NAME" / "Your Street 123" / "Add Road Name" placeholder text
- Stock-photo styling (bright red/black flyer aesthetic, generic "FOOD MENU" header)

IF TEMPLATE — emit:
[MENU_DECISION]
NOTABLE: TEMPLATE_OR_STOCK — this looks like a stock menu template or sample graphic, not a real menu the user is choosing from.
CONFIDENCE: 0.25
[/MENU_DECISION]
Stop. Do not list dishes.

IF REAL MENU — identify dishes visible. For each, estimate macros.

OUTPUT VOLUME RULE:
- If the menu has ≤ 15 distinct dishes → list all dishes in "Dishes visible:".
- If the menu has > 15 dishes (dense menus like Cheesecake Factory, big
  steakhouses, multi-section diners) → DO NOT list every dish. Instead, bucket
  into LEAN / MID / HEAVY groups and surface 5-8 representative items per bucket
  that span the menu's categories. The downstream decision only needs candidates
  worth picking + heavy items worth avoiding, not a complete inventory.

Emit (sparse menu, ≤ 15 dishes):
[MENU_DECISION]
Dishes visible:
• [dish name], [price if visible], ~[cal] cal, ~[protein]g P — [brief note]
• [dish name], ~[cal] cal, ~[protein]g P
RESTAURANT_TYPE: [italian, sushi, american diner, fast casual, steakhouse, etc.]
NOTABLE: [dietary callouts visible — vegan, GF, keto — or empty]
CONFIDENCE: 0.0-1.0
[/MENU_DECISION]

Emit (dense menu, > 15 dishes):
[MENU_DECISION]
MENU_SIZE: dense (N+ dishes — surfacing decision-relevant items only)
LEAN (< 700 cal, 35g+ protein):
• [dish name], $price, ~cal, ~protein
• ... (5-8 items max)
MID (700-950 cal):
• [dish name], $price, ~cal, ~protein
• ... (5-8 items max)
HEAVY (1000+ cal, eat-only-if-budgeted):
• [dish name], $price, ~cal, ~protein
• ... (5-8 items max)
RESTAURANT_TYPE: [type]
NOTABLE: [shared side combos, dietary flags, side-swap leverage, etc.]
CONFIDENCE: 0.0-1.0
[/MENU_DECISION]

""" + _FOOD_ESTIMATION_RULES


# 4) FRIDGE — fridge/pantry contents.
_FRIDGE_PROMPT = """You are analyzing a fridge or pantry photo for meal suggestions. Reply in plain text — no markdown.

User caption: {caption}

List visible ingredients. Be concrete — name the actual items, not categories.

Decide if this fridge is SPARSE (few items, mostly empty shelves, hard to make a
real meal from what's visible) or STOCKED. A SPARSE flag changes downstream
coaching — instead of "make X", the response becomes "you might want to shop
or check freezer/pantry."

SPARSE heuristics:
- Fewer than 5-6 distinct food items visible
- Mostly condiments, drinks, or non-meal items (no real proteins/veg/carbs)
- Empty shelves or drawers dominate the frame
- Items are scattered, no clear meal base

Emit a FRIDGE block:
[FRIDGE]
SPARSE: [yes | no]
Proteins: [list with rough quantities — e.g. "eggs (~6 left)", "ground turkey (1 lb)"]
Carbs/grains: [list — e.g. "white rice", "sourdough bread", "oats"]
Vegetables: [list]
Fruit: [list, if visible]
Dairy: [list]
Other: [condiments, snacks, drinks, anything notable]
NOTES: [if STOCKED → 1-2 concrete meal suggestions from visible ingredients.
        if SPARSE → flag what's missing for a full meal; suggest asking about
        freezer/pantry/grocery run]
CONFIDENCE: 0.0-1.0
[/FRIDGE]
"""


# 5) GROCERY — cart or receipt.
_GROCERY_PROMPT = """You are analyzing a grocery cart or receipt photo. Reply in plain text — no markdown.

User caption: {caption}

Extract items. If it's a receipt, also extract total and store if visible.

Emit a GROCERY block:
[GROCERY]
SOURCE: [cart | receipt]
STORE: [if visible on receipt]
Items:
• [item name], [quantity if visible], [$price if receipt]
• [item name], [quantity], [$price]
HIGH_QUALITY: [items aligned with healthy eating — lean proteins, veg, complex carbs]
LOW_QUALITY: [items that work against goals — ultra-processed, high-sugar, hidden cals]
TOTAL_SPEND: [if receipt]
CONFIDENCE: 0.0-1.0
[/GROCERY]
"""


# 6) DELIVERY APP — food delivery app screen.
_DELIVERY_APP_PROMPT = """You are analyzing a screenshot from a food delivery app. Reply in plain text — no markdown.

User caption: {caption}

The app likely shows menu items with macros and/or calories pre-listed.

Emit a DELIVERY_APP block:
[DELIVERY_APP]
APP: [Sweetgreen | UberEats | DoorDash | Caviar | other — best guess]
RESTAURANT: [if visible]
Items visible (with macros if shown by app — these are usually accurate):
• [item name], [cal] cal, [protein]g P, [carbs]g C, [fat]g F
• [item name], [cal] cal, [protein]g P
CART_TOTAL: [if a cart screen]
CONFIDENCE: 0.0-1.0
[/DELIVERY_APP]
"""


# 7) WORKOUT LOG — Apple Notes, gym app, handwritten, whiteboard.
_WORKOUT_LOG_PROMPT = """You are analyzing a workout log photo. Reply in plain text — no markdown.

User caption: {caption}

CRITICAL — what to LOG vs what to put in NOTES:
- Exercises with sets×reps×weight that the user actually DID → log them.
- "Next time bump bench to 85kg" / "should add another set next time" / "going to try
  a drop set on Friday" / anything in FUTURE tense → these are PLANS, not logs. Put
  them in NOTES, NEVER in the Exercises list. The main LLM is told not to log NOTES
  content as exercises.
- A "Workout Plan" table separate from the actual session log → if it's a future
  plan (showing what the user intends to do), do NOT extract those rows as
  exercises. If it's the session they did today, extract them normally. When
  ambiguous, prefer the bulleted session list over the plan table and note the
  ambiguity in NOTES.

Match the log_exercise tool's expected shape:
- SETS WITH SAME LOAD: one line per exercise with sets=N, reps="8,8,7", weight=X
- SETS WITH DIFFERENT LOADS: one line PER load (e.g. "bench 135x10, 145x8, 155x6"
  becomes 3 separate lines)

WEIGHT FIELD:
- If a number is given (in lbs or kg) → convert to lbs (kg × 2.20462) and write
  "weight=W lbs (orig: Xkg)".
- BODYWEIGHT exercises (dips, pull-ups, push-ups with no added weight) →
  write "weight=bodyweight" (literal string). The main LLM will omit the weight
  field on log_exercise so the entry records as a bodyweight movement.
- Unknown / not shown → "weight=?".

REPS FIELD:
- Standard numeric: reps="8,8,7"
- AMRAP / "to failure" / "fail" → reps="fail,fail,fail" (preserve the user's text).
  The LLM treats these as max-effort sets without a numeric target.
- RIR / RPE annotated (e.g. "8 @ RPE 8") → reps="8 @ RPE 8" — capture both.

DATE FIELD:
- If a full date is shown (e.g. "May 18, 2026" or "2026-05-18") → DATE: 2026-05-18.
- If a partial date is shown WITHOUT YEAR (e.g. "MAY 18", "Mon 3/4") → write
  DATE_RAW: "MAY 18" (preserve as-shown). The main LLM will resolve to the most
  recent past occurrence using today's date — do NOT guess a year here.
- If no date is shown at all → DATE: today.

Emit a WORKOUT_LOG block:
[WORKOUT_LOG]
DATE: [today | YYYY-MM-DD if year visible]
DATE_RAW: [as-shown text, only if year missing — else omit this line]
WORKOUT_NAME: [if labeled — "Push Day", "Mon Leg", etc.]
Exercises:
• [exercise name], sets=N, reps="R1,R2,R3", weight=W lbs (orig: Xkg)
• [exercise name], sets=N, reps="fail,fail,fail", weight=bodyweight
• [exercise name], sets=N, reps="R1,R2", weight=?
Cardio (if present):
• [type], duration=M min, [optional: distance, pace, heart rate]
CONFIDENCE: 0.0-1.0
NOTES: [anything noteworthy from the user's notes — RPE marks, "felt strong",
        PRs, injuries, AND any FUTURE plans like "bump bench to 85kg next time".
        Future plans go here as context — they are NEVER logged as exercises.]
[/WORKOUT_LOG]
"""


# 8) BLOOD TEST — lab report.
_BLOOD_TEST_PROMPT = """You are analyzing a blood test or lab report photo. Reply in plain text — no markdown.

User caption: {caption}

FIRST, check if this is the user's actual recent lab report or a SAMPLE/DEMO image.
Signs of a SAMPLE/DEMO report (not real user data):
- Report date is very old (more than 3 years before today)
- Patient name looks generic ("Ana Betz", "John Doe", "Jane Smith", "Patient Name",
  "Sample Patient", "Test Patient")
- Watermark text like "DEMO", "SAMPLE", "EXAMPLE", "TEST REPORT", "FOR DEMONSTRATION"
- Lab/system markers known for demos: "GNU Solidario", "OpenEMR sample",
  "FHIR demo", placeholder hospitals ("Hospital Name", "General Hospital 12345")
- Lorem ipsum or placeholder fields anywhere on the page

IF SAMPLE — emit:
[METRICS]
SOURCE: blood_test
DATE: [date as shown]
LAB: [lab name as shown]
NOTABLE: SAMPLE_OR_DEMO — this looks like a sample/demo lab report (very old date,
generic patient name, demo system markers), NOT the user's real recent results.
CONFIDENCE: 0.30
[/METRICS]
Still list the metrics below the NOTABLE line for visibility, but the low
confidence + SAMPLE_OR_DEMO flag will trip the ASK-FIRST gate downstream.

IF REAL — extract EVERY numeric metric visible with value, unit, reference range,
and status. Flag values outside range.
Emit:
[METRICS]
SOURCE: blood_test
DATE: [report date if visible, else "today"]
LAB: [lab name if visible]
Metrics:
• [metric name], value=X, unit="mg/dL", range="Y-Z", status=[normal|high|low|flagged]
• [metric name], value=X, unit="mg/dL", range="Y-Z", status=normal
CONFIDENCE: 0.0-1.0
NOTABLE: [panel-level callouts — "cholesterol panel mostly normal", "fasting
glucose mildly elevated" — or empty if everything is normal]
[/METRICS]

Common panels: lipid panel (total cholesterol, HDL, LDL, triglycerides),
comprehensive metabolic panel, CBC, A1C, glucose, vitamin D, testosterone,
thyroid (TSH, T3, T4).
Use coach-friendly snake_case metric names: "total_cholesterol", "HDL", "LDL",
"triglycerides", "glucose_fasting", "A1C", "vitamin_D", "testosterone_total",
"TSH", "hemoglobin", "RBC", "HCT", "WBC", "platelets", etc.
"""


# 9) WEARABLE — Whoop, Oura, Apple Watch, Garmin, Fitbit screens.
_WEARABLE_PROMPT = """You are analyzing a screenshot from a wearable device or fitness app. Reply in plain text — no markdown.

User caption: {caption}

Identify the device/app first. Then determine CONTEXT (what kind of screen this is) — this matters because different screens show different KINDS of data.

CONTEXT options:
- current_reading — Health Monitor / instantaneous vitals (HR right now, current
  SpO2, current respiratory rate). NOT a daily summary — these are spot values.
- daily_summary — strain, calories burned, steps, exercise minutes for a day
- recovery_score — Whoop recovery %, Oura readiness, Garmin body battery snapshot
- sleep — Whoop/Oura/Fitbit sleep score + hours + stages for last night
- workout_summary — single workout recap with HR zones, duration, calories
- weekly_trend / monthly_trend — graph view across multiple days

The downstream LLM treats these differently — current_reading at 5:24 AM is a
sleep spot value (don't compare to "daytime average"), while a daily_summary
heart rate is meaningful as a tracked metric.

Emit a METRICS block:
[METRICS]
SOURCE: wearable
DEVICE: [Whoop | Oura | Apple Watch | Garmin | Fitbit | other]
CONTEXT: [current_reading | daily_summary | recovery_score | sleep | workout_summary | weekly_trend | monthly_trend]
DATE: [today, or date shown]
TIME_OF_DAY: [if visible on the screen, e.g. "5:24 AM" — useful for current_reading context]
Metrics:
• [metric name], value=X, unit="[%|hours|bpm|steps|kcal|etc.]", personal_threshold="[user's personal range if shown, e.g. 'low < 37']"
• [metric name], value=X, unit="..."
CONFIDENCE: 0.0-1.0
NOTABLE: [device-specific callouts — "recovery low, deload day?", "sleep score
solid", "this is a Health Monitor snapshot during sleep — readings reflect rest
state not daily averages"]
[/METRICS]

Device-specific metrics to look for:
- Whoop: recovery_score (%), strain_score (0-21), sleep_hours, hrv_ms, rhr_bpm,
  spo2 (%), respiratory_rate (rpm), skin_temp_delta_c, heart_rate (bpm — current)
- Oura: readiness_score, sleep_score, activity_score, hrv_ms, body_temp_delta_c
- Apple Watch: move_kcal, exercise_min, stand_hours, heart_rate (bpm), workout details
- Garmin: body_battery (%), training_status, sleep_score, stress_score, vo2_max
- Fitbit: sleep_hours, sleep_score, steps, active_minutes, rhr_bpm

Use snake_case metric names. Preserve any "personal_threshold" the screen shows
(e.g. Whoop's "low < 37" or "elevated > 203") — this is the user's own baseline
range and matters for personalized coaching.
"""


# 10) FOOD DIARY — screenshot of MyFitnessPal/Cronometer/etc.
_FOOD_DIARY_PROMPT = """You are analyzing a screenshot from a food-logging app (MyFitnessPal, Cronometer, Lose It!, etc.). Reply in plain text — no markdown.

User caption: {caption}

Extract every food entry visible with whatever macro info the app shows.

Emit a FOOD_DIARY block:
[FOOD_DIARY]
APP: [MyFitnessPal | Cronometer | Lose It! | other]
DATE: [date shown in screenshot — if visible. Otherwise: "today"]
MEALS:
breakfast:
  • [food name], [quantity], [cal] cal, [protein]g P, [carbs]g C, [fat]g F
  • [food name], [quantity], [cal] cal, [protein]g P
lunch:
  • [food name], [quantity], [cal] cal
dinner:
  • [food name], [quantity], [cal] cal
snacks:
  • [food name], [quantity], [cal] cal
DAILY_TOTAL: [cal] cal, [protein]g P, [carbs]g C, [fat]g F
CONFIDENCE: 0.0-1.0
INTENT: log_existing
[/FOOD_DIARY]

If the app shows macro totals at the top/bottom, use those — they're more accurate than re-summing per-item.
"""


# 11) BODY PROGRESS — body/mirror photo.
_BODY_PROGRESS_PROMPT = """You are analyzing a body progress photo. Be encouraging, observational, and accurate-but-humble. Reply in plain text — no markdown.

User caption: {caption}

DISCLAIMER UP FRONT: body fat estimation from photos is inherently imprecise. Always give a RANGE (e.g. "14-17%"), never a single number. Single readings are not the point — TRENDS over time are. Flag this in the output.

Emit a BODY_PROGRESS block:
[BODY_PROGRESS]
VIEW: [front | side | back | flexed | unflexed]
LIGHTING: [good | dim | harsh shadows | overhead | natural]
QUALITY: [clear | partially obscured | low-res | filtered]
VISIBLE_REGIONS: [e.g. midsection, shoulders, arms, legs — what's actually shown]
COMPOSITION_NOTES:
- midsection: [observations — e.g. "visible upper abs", "softness at lower abs", "obliques showing"]
- shoulders/arms: [if visible — "delt cap visible", "biceps lean"]
- back: [if visible]
- legs: [if visible]
ESTIMATED_BF_RANGE: [low%]-[high%]
ESTIMATE_CAVEAT: "Photo-based BF estimates are noisy — range only. Use trend over multiple photos as the signal."
CONFIDENCE: 0.0-1.0 (CAP AT 0.75 for any BF estimate)
TONE_GUIDANCE: encouraging, specific (call out actual visible progress areas), never judgmental.
[/BODY_PROGRESS]

Body fat estimation rough guide (males, for reference — adjust for stated sex if known):
- 8-11%: clear ab definition, visible vascularity, separation between muscle groups
- 12-15%: ab outline visible, some vascularity, lean overall
- 16-19%: midsection softer, abs not visible, athletic but not lean
- 20-24%: noticeable softness throughout
- 25%+: significant softness, no muscle definition visible

For females, add ~8-10% to each range.

If you're not at least 0.5 confident, EXPAND the range (e.g. "14-19%") rather than guessing tighter.
"""


# 12) UNKNOWN — fallback.
_UNKNOWN_PROMPT = """This image was classified as UNKNOWN. Reply in plain text — no markdown.

User caption: {caption}

Briefly describe what's visible (1 sentence) so the user can be asked a clarifying question.

Emit:
[UNKNOWN]
VISIBLE: [1-sentence description]
ASK_USER: "couldn't quite tell what this is — what am I looking at?"
[/UNKNOWN]
"""


_EXTRACTORS = {
    "PREPARED_MEAL": _PREPARED_MEAL_PROMPT,
    "PACKAGED_PRODUCT": _PACKAGED_PRODUCT_PROMPT,
    "MENU": _MENU_PROMPT,
    "FRIDGE": _FRIDGE_PROMPT,
    "GROCERY": _GROCERY_PROMPT,
    "DELIVERY_APP": _DELIVERY_APP_PROMPT,
    "WORKOUT_LOG": _WORKOUT_LOG_PROMPT,
    "BLOOD_TEST": _BLOOD_TEST_PROMPT,
    "WEARABLE": _WEARABLE_PROMPT,
    "FOOD_DIARY": _FOOD_DIARY_PROMPT,
    "BODY_PROGRESS": _BODY_PROGRESS_PROMPT,
    "UNKNOWN": _UNKNOWN_PROMPT,
}

# Per-type max_tokens — long structured outputs (workout logs, blood panels,
# food diaries) need more headroom than a quick verdict (menu, fridge).
_EXTRACTOR_MAX_TOKENS = {
    "PREPARED_MEAL": 768,
    "PACKAGED_PRODUCT": 384,
    "MENU": 1024,           # menus can have many dishes
    "FRIDGE": 512,
    "GROCERY": 1024,        # receipts can be long
    "DELIVERY_APP": 768,
    "WORKOUT_LOG": 1024,    # workout with many exercises × sets
    "BLOOD_TEST": 1024,     # full panel can have 20+ metrics
    "WEARABLE": 512,
    "FOOD_DIARY": 1024,     # full day of meals
    "BODY_PROGRESS": 768,
    "UNKNOWN": 256,
}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

async def classify_image(image_data: bytes) -> str:
    """Return ONE label from VALID_LABELS. Falls back to UNKNOWN on any error
    or unrecognized response."""
    try:
        raw = await analyze_image(
            image_data, _CLASSIFY_PROMPT, max_tokens=20,
        )
    except Exception as e:
        logger.error(f"classify_image: vision call failed: {e}", exc_info=True)
        return "UNKNOWN"

    label = (raw or "").strip().upper()
    # Strip any trailing punctuation, quotes, or extra words.
    for ch in (".", ",", '"', "'", "`"):
        label = label.replace(ch, "")
    # Take the first whitespace-delimited token in case the model added prose.
    label = label.split()[0] if label else "UNKNOWN"

    if label in VALID_LABELS:
        return label

    # Substring match — model occasionally adds context ("PREPARED_MEAL_TYPE").
    for valid in VALID_LABELS:
        if valid in label or label in valid:
            return valid

    logger.warning(f"classify_image: unrecognized label '{label}', falling back to UNKNOWN")
    return "UNKNOWN"


async def process_photo(image_data: bytes, caption: str = "") -> str:
    """
    Smart photo preprocessor. Two-step vision (classify → extract) returns a
    TAGGED block of structured text for the main LLM to route on.

    The block is one of:
      [FOOD_LOG] ...                — for log_food downstream
      [PREPARED_MEAL_DECISION] ...  — for coach_on_photo downstream
      [PREPARED_MEAL_AMBIGUOUS] ... — LLM asks user
      [MENU_DECISION] ...           — for coach_on_photo
      [FRIDGE] ...                  — for coach_on_photo
      [GROCERY] ...                 — for coach_on_photo
      [DELIVERY_APP] ...            — for coach_on_photo
      [WORKOUT_LOG] ...             — for log_exercise per item
      [METRICS] ... SOURCE: blood_test|wearable  — for track_metric / log_body_weight
      [FOOD_DIARY] ...              — for log_food per item with date=
      [BODY_PROGRESS] ...           — for coach_on_photo
      [UNKNOWN] ...                 — LLM asks user

    Returns "" on hard failure (no API key, network out). Returns an UNKNOWN
    block on classification/extraction failure so the LLM can still respond.
    """
    label = await classify_image(image_data)
    extractor_prompt = _EXTRACTORS.get(label, _UNKNOWN_PROMPT)
    max_tokens = _EXTRACTOR_MAX_TOKENS.get(label, 512)
    prompt = extractor_prompt.format(caption=caption or "none")

    try:
        block = await analyze_image(image_data, prompt, max_tokens=max_tokens)
    except Exception as e:
        logger.error(f"process_photo: {label} extraction failed: {e}", exc_info=True)
        return (
            "[UNKNOWN]\n"
            f"VISIBLE: image classified as {label} but extraction failed\n"
            "ASK_USER: \"hit a snag analyzing this — can you describe what you sent?\"\n"
            "[/UNKNOWN]"
        )

    # Telemetry — greppable in production logs.
    logger.info(f"event=photo_preprocessed label={label} chars={len(block or '')}")

    if not block:
        return (
            "[UNKNOWN]\n"
            f"VISIBLE: classified as {label} but extractor returned nothing\n"
            "ASK_USER: \"didn't get anything from that photo — can you resend or describe it?\"\n"
            "[/UNKNOWN]"
        )

    return block


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY WRAPPERS — preserve API for any caller still importing the old names.
# ─────────────────────────────────────────────────────────────────────────────

async def process_food_image(image_data: bytes) -> str:
    """Legacy: delegate to smart preprocessor with empty caption."""
    return await process_photo(image_data, "")


async def process_general_image(image_data: bytes, caption: str = "") -> str:
    """Legacy: delegate to smart preprocessor (now general by default)."""
    return await process_photo(image_data, caption)
