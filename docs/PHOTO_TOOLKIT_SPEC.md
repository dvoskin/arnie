# Photo Intelligence Toolkit — Unified Spec

**Goal:** A single cohesive photo toolkit that handles ANY photo or screenshot the user sends, fluidly, with no interference to existing behaviors.

---

## TL;DR — Tool Surface

Despite supporting 10 distinct photo types, the actual new tool surface is **minimal**:

| Bucket | Photo Types | New Tools |
|--------|-------------|-----------|
| **LOG** (OCR extraction → write) | food, food_diary, packaged, workout_log, blood_test, wearable, receipt | **0** — reuses existing log_food, log_exercise, track_metric, log_body_weight, update_profile |
| **DECIDE** (coaching response) | menu, fridge, grocery, delivery_app, body_progress | **1** — `coach_on_photo` |
| **ASK** (clarify) | unknown, ambiguous prepared meal | **0** — plain text question |
| **TOTAL** | 10 types | **1 new tool** |

The "10 types" describes how the **preprocessor** extracts differently for each (different vision prompts per type). From the tool layer, it's just `coach_on_photo` + reuse of every tool you already have.

**OCR/extraction is bundled in the preprocessor** (one vision call API, one tagged-block contract). NOT in tool-per-type proliferation.

---

## 1. What Users Experience

Users send a photo. Arnie does the right thing — *automatically*. No mode selectors, no "choose your action" UI. Just send → Arnie responds with the appropriate behavior.

### The 10 Photo Types

| Type | Example | Arnie's Behavior |
|------|---------|------------------|
| 1. **Prepared meal** | Plated lunch | LOG or DECIDE based on intent ("I ate" → log, "should I?" → decide) |
| 2. **Restaurant menu** | Photo of menu | DECIDE — recommend dish + mods |
| 3. **Fridge / pantry** | Open fridge | SUGGEST meal from ingredients |
| 4. **Grocery cart / receipt** | Cart or receipt | SUGGEST swap or upcoming meals |
| 5. **Delivery app** | Sweetgreen / UberEats screen | DECIDE — order + mods |
| 6. **Workout log** | Apple Notes, handwritten, gym app screen | EXTRACT exercises → auto-log |
| 7. **Blood test / lab** | Lab report screenshot | EXTRACT metrics → store in profile |
| 8. **Wearable screen** | Whoop, Oura, Apple Watch | EXTRACT metrics → store |
| 9. **Food diary screenshot** | MyFitnessPal, Cronometer | EXTRACT food entries → log_food per item |
| 10. **Body progress** | Mirror photo | OBSERVE → encouraging coach response |

**Plus a fallback:** unclear photo → Arnie asks "what am I looking at?" (graceful, never silent).

---

## 2. Architecture (Three Components)

```
┌─────────────────────────────────────────────────────────────┐
│  USER SENDS PHOTO (Telegram)                                │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  [1] SMART PREPROCESSOR — multimodal/image_handler.py       │
│                                                             │
│  • Classifies photo type (1 of 10 + unknown)               │
│  • Runs type-specific extraction prompt                    │
│  • Emits TAGGED structured text:                           │
│      [FOOD_LOG] ...                                        │
│      [MENU_DECISION] ...                                   │
│      [WORKOUT_LOG] ...                                     │
│      [METRICS] ...                                         │
│      etc.                                                  │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  [2] LLM SEES TAGGED TEXT + CALLS TOOLS                     │
│                                                             │
│  • [FOOD_LOG]    → log_food (existing tool)                │
│  • [WORKOUT_LOG] → log_exercise per item (existing)        │
│  • [METRICS]     → track_metric / log_body_weight (existing)│
│  • [FOOD_DIARY]  → log_food per item (existing)            │
│  • [MENU_DECISION], [FRIDGE], [GROCERY], [DELIVERY],       │
│    [PREPARED_MEAL_DECISION], [BODY_PROGRESS]               │
│              → coach_on_photo (NEW tool, returns rich      │
│                structured decision)                        │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  [3] RESULT RENDERS IN TELEGRAM                             │
│                                                             │
│  Log tools → existing confirmation flow                     │
│  coach_on_photo → rich decision card with macros + reasoning│
└─────────────────────────────────────────────────────────────┘
```

**Key insight:** The LLM remains the orchestrator. The preprocessor gives it richer context. Existing tools get reused for logging paths. Only ONE new tool (`coach_on_photo`) for decision paths.

---

## 3. Component 1: Smart Preprocessor

### Current State

`multimodal/image_handler.py` has `process_food_image()` — runs vision with `_FOOD_PROMPT` and returns structured food text (PACKAGED lines, item lines, TOTAL).

### New State

Rewrite to `process_photo()` — runs a **two-step vision call**:

**Step A: Classify** (fast, low-token)
```python
classification_prompt = """
Look at this image. What is it? Reply with ONE label from this list:
- PREPARED_MEAL (a plated meal, cooked food, food on a plate)
- MENU (restaurant menu, paper or digital)
- FRIDGE (inside of fridge or pantry)
- GROCERY (grocery cart, receipt, grocery items)
- DELIVERY_APP (Sweetgreen, UberEats, DoorDash order screen)
- WORKOUT_LOG (Apple Notes, gym app, handwritten workout)
- BLOOD_TEST (lab report, blood panel screenshot)
- WEARABLE (Whoop, Oura, Apple Watch screen)
- FOOD_DIARY (MyFitnessPal, Cronometer, food log screenshot)
- BODY_PROGRESS (mirror photo, body shot)
- PACKAGED_PRODUCT (a packaged item with visible label)
- UNKNOWN

Reply with ONLY the label, nothing else.
"""
```

**Step B: Extract** (type-specific, richer prompt)

Each type has its own extraction prompt that emits a tagged block.

#### Tagged Block Formats

```
[FOOD_LOG]
Items extracted from food photo for logging.
• grilled chicken breast, ~6oz, 280 cal, 35g P, 0g C, 6g F
• white rice, ~1 cup, 200 cal, 4g P, 45g C, 0g F
TOTAL: 480 cal, 39g P
INTENT: log_now
[/FOOD_LOG]

[MENU_DECISION]
Restaurant menu items visible:
• Grilled salmon — $24, ~450 cal, 35g P
• Cesar salad — $14, ~600 cal (heavy dressing), 12g P
• Pasta carbonara — $22, ~900 cal, 25g P
• Chicken sandwich — $16, ~700 cal, 30g P
CONTEXT: User has 800 cal remaining, target 150g protein, currently at 100g.
[/MENU_DECISION]

[WORKOUT_LOG]
Exercises extracted from workout notes:
• bench press, 3 sets × 8,8,7 reps, 185 lbs
• incline DB press, 3 sets × 10,10,8 reps, 70 lbs
• cable fly, 3 sets × 12 reps, 35 lbs
• tricep pushdown, 4 sets × 12 reps, 50 lbs
DATE: today (no date visible on notes)
[/WORKOUT_LOG]

[METRICS]
Health metrics extracted:
• total_cholesterol: 185 mg/dL
• HDL: 55 mg/dL
• LDL: 110 mg/dL
• triglycerides: 100 mg/dL
• glucose_fasting: 92 mg/dL
SOURCE: lab report dated 2026-05-15
[/METRICS]

[WEARABLE]
Wearable metrics extracted:
• device: Whoop
• recovery: 45%
• sleep: 6h 12m
• strain: 12.3
DATE: today
[/WEARABLE]

[FOOD_DIARY]
Food entries from app screenshot (MyFitnessPal):
• breakfast: oatmeal w/ berries, 320 cal, 8g P, 60g C, 6g F
• lunch: chicken caesar salad, 450 cal, 35g P, 15g C, 22g F
• snack: protein bar, 200 cal, 20g P, 22g C, 7g F
DATE: 2026-06-12
[/FOOD_DIARY]

[FRIDGE]
Visible ingredients:
• eggs (carton, ~half full)
• spinach
• cheddar cheese
• ground turkey (1 lb pack)
• broccoli
• greek yogurt
[/FRIDGE]

[GROCERY]
Items in cart/receipt:
• ground beef (2 lbs)
• white rice (5 lb bag)
• granola (large bag)
• whole milk (gallon)
• bananas (bunch)
• broccoli
TOTAL: $47.32 (if receipt)
[/GROCERY]

[DELIVERY_APP]
Order screen (Sweetgreen) — items shown:
• Harvest Bowl — 705 cal, 24g P, 90g C, 28g F
• Chicken Pesto Parm — 800 cal, 51g P, 64g C, 31g F
• Kale Caesar — 470 cal, 19g P, 25g C, 32g F
[/DELIVERY_APP]

[BODY_PROGRESS]
Body progress photo:
• mirror selfie, front view, gym lighting
• visible changes: tighter midsection vs typical progress photos
NOTE: cannot accurately estimate body fat % from photo alone.
[/BODY_PROGRESS]

[UNKNOWN]
Photo content unclear. Ask user what they're sharing.
[/UNKNOWN]
```

The LLM sees these tagged blocks alongside the user's caption (if any) and decides what to do.

### Preprocessor File Changes

```python
# multimodal/image_handler.py — REWRITE

import logging
from core.llm import analyze_image

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """Classify this image with ONE label:
PREPARED_MEAL, MENU, FRIDGE, GROCERY, DELIVERY_APP, WORKOUT_LOG,
BLOOD_TEST, WEARABLE, FOOD_DIARY, BODY_PROGRESS, PACKAGED_PRODUCT, UNKNOWN
Reply with ONLY the label."""

# Type-specific extraction prompts (see Section 3 above for all 10)
_EXTRACTORS = {
    "PREPARED_MEAL": _PREPARED_MEAL_PROMPT,
    "MENU": _MENU_PROMPT,
    "FRIDGE": _FRIDGE_PROMPT,
    "GROCERY": _GROCERY_PROMPT,
    "DELIVERY_APP": _DELIVERY_PROMPT,
    "WORKOUT_LOG": _WORKOUT_PROMPT,
    "BLOOD_TEST": _BLOOD_TEST_PROMPT,
    "WEARABLE": _WEARABLE_PROMPT,
    "FOOD_DIARY": _FOOD_DIARY_PROMPT,
    "BODY_PROGRESS": _BODY_PROMPT,
    "PACKAGED_PRODUCT": _FOOD_PROMPT,  # use existing
}


async def process_photo(image_data: bytes, caption: str = "") -> str:
    """
    Smart photo processor. Returns tagged structured text for the LLM.
    
    Two-step vision: classify first (fast), then extract with type-specific prompt.
    """
    # Step A: classify
    try:
        label = (await analyze_image(image_data, _CLASSIFY_PROMPT)).strip().upper()
    except Exception as e:
        logger.error(f"Photo classification failed: {e}")
        return ""
    
    # Validate label
    if label not in _EXTRACTORS:
        # Try to find a match or fall back
        for key in _EXTRACTORS:
            if key in label:
                label = key
                break
        else:
            label = "UNKNOWN"
    
    # Step B: extract with type-specific prompt
    if label == "UNKNOWN":
        return "[UNKNOWN]\nPhoto content unclear. Ask user what they're sharing.\n[/UNKNOWN]"
    
    extractor = _EXTRACTORS[label]
    try:
        prompt = extractor.format(caption=caption or "none")
        return await analyze_image(image_data, prompt)
    except Exception as e:
        logger.error(f"Photo extraction ({label}) failed: {e}")
        return f"[UNKNOWN]\nClassified as {label} but extraction failed.\n[/UNKNOWN]"


# Keep backward-compat wrappers (legacy callers)
async def process_food_image(image_data: bytes) -> str:
    """Legacy wrapper — delegates to process_photo."""
    return await process_photo(image_data, "")


async def process_general_image(image_data: bytes, caption: str = "") -> str:
    """Legacy wrapper — delegates to process_photo."""
    return await process_photo(image_data, caption)
```

This preserves the existing API (`process_food_image`, `process_general_image` still work) while adding the smart classification on top. Zero breakage to bot/telegram_handler.py.

---

## 4. Component 2: New Tool `coach_on_photo`

### Why a new tool?

For DECISION photos (menu, fridge, grocery, delivery_app, prepared_meal-with-question, body_progress), the LLM needs to return a *structured* coaching response with:
- The decision (short, actionable)
- Reasoning (1-2 sentences)
- Estimated macros (where applicable)
- Confidence level

We could let the LLM emit this as plain text, but a tool gives us:
- Structured output → rich Telegram rendering (cards, callouts)
- Telemetry (track usage, response time, satisfaction)
- Future: one-tap "log this" buttons attached to decisions

### Tool Schema

```python
{
    "name": "coach_on_photo",
    "description": (
        "Return a structured coaching decision for a photo that's been classified as a "
        "decision-mode photo (menu, fridge, grocery, delivery app, prepared meal needing "
        "verdict, body progress). "
        ""
        "Call this AFTER the preprocessor has extracted items from the photo (visible in "
        "the [MENU_DECISION], [FRIDGE], [GROCERY], [DELIVERY_APP], or similar tagged block). "
        ""
        "Do NOT call this for: "
        "  • [FOOD_LOG] → use log_food directly "
        "  • [WORKOUT_LOG] → use log_exercise per item "
        "  • [METRICS] → use track_metric or log_body_weight per value "
        "  • [FOOD_DIARY] → use log_food per item with date= "
        ""
        "The decision should be CRISP and SPECIFIC. Not 'salmon is healthy' but 'get the "
        "salmon, sub broccoli for rice, one drink not two.' Reasoning should reference the "
        "user's daily targets concretely."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "photo_type": {
                "type": "string",
                "enum": ["menu", "fridge", "grocery", "delivery_app", "prepared_meal", "body_progress"],
                "description": "What kind of photo this is (from the tagged block label)."
            },
            "decision": {
                "type": "string",
                "description": (
                    "The recommendation — short, specific, actionable. "
                    "Examples: 'Get the salmon, sub broccoli for rice, one drink not two.' "
                    "'Make scrambled eggs with spinach and toast — you have everything.' "
                    "'Swap the granola for greek yogurt, that's the one fix worth making.' "
                    "'Eat it, but skip the bread.' For body photos: encouraging observation."
                )
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "1-2 sentence WHY. Reference user's daily targets concretely. "
                    "'You're at 1200/2000 cals with 50g protein left to hit. Salmon nails it.' "
                    "Coach voice, not chart voice."
                )
            },
            "items_identified": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short list of items Arnie noticed in the photo (for transparency)."
            },
            "macros_estimate": {
                "type": "object",
                "properties": {
                    "calories": {"type": "number"},
                    "protein": {"type": "number"},
                    "carbs": {"type": "number"},
                    "fats": {"type": "number"}
                },
                "description": "Estimated macros for the recommended option, where applicable. Omit for fridge/grocery/body photos."
            },
            "confidence": {
                "type": "number",
                "description": "0.0-1.0. Cap at 0.85 for photos (inherently estimates). Lower for blurry/ambiguous photos."
            }
        },
        "required": ["photo_type", "decision", "reasoning", "confidence"]
    }
}
```

### Backend Handler

```python
# In handlers/tool_executor.py, _dispatch function, after log_food branch:

elif name == "coach_on_photo":
    photo_type = inp.get("photo_type", "")
    decision = inp.get("decision", "")
    reasoning = inp.get("reasoning", "")
    items = inp.get("items_identified", [])
    macros = inp.get("macros_estimate", {})
    confidence = float(inp.get("confidence", 0.7))
    confidence = max(0.0, min(0.85, confidence))  # cap at 0.85 for photos
    
    # Telemetry
    logger.info(
        f"event=coach_on_photo user={user.id} type={photo_type} "
        f"confidence={confidence:.2f}"
    )
    
    # Return as multimodal result — bot renders as a rich card
    return {
        "_type": "photo_coaching",
        "photo_type": photo_type,
        "decision": decision,
        "reasoning": reasoning,
        "items_identified": items,
        "macros_estimate": macros,
        "confidence": confidence,
        "caption": f"{decision}",  # short version for notification text
    }
```

---

## 5. Component 3: Wiring & System Prompt

### 5a. Existing Tools Stay Untouched

For the EXTRACTION paths, the LLM uses tools it already has:

- **[FOOD_LOG]** → `log_food` per item (with `from_photo=true` flag, existing flow)
- **[FOOD_DIARY]** → `log_food` per item (with `from_photo=true` AND `date=` extracted from the diary)
- **[WORKOUT_LOG]** → `log_exercise` per item (existing tool, just used with photo-extracted data)
- **[METRICS]** → `track_metric` per metric (existing tool) OR `log_body_weight` if scale weight
- **[BLOOD_TEST]** → `track_metric` per value, possibly `update_profile` for relevant attributes
- **[WEARABLE]** → `track_metric` per metric
- **[GROCERY]** → coaching response via `coach_on_photo`, no logging (until receipt-OCR-to-log is built later)
- **[BODY_PROGRESS]** → `coach_on_photo` for response, optionally `log_body_weight` if visible

### 5b. System Prompt Additions

Add a new section to the system prompt teaching the LLM how to handle tagged photo blocks:

```
WHEN A PHOTO ARRIVES:

The bot preprocesses every photo and gives you a TAGGED BLOCK of extracted info.
Your job: read the tag, then call the right tool(s).

TAGGED BLOCK ROUTING:

[FOOD_LOG] / [PACKAGED_PRODUCT] / [PREPARED_MEAL] (when user says "I ate")
  → call log_food per item (set from_photo=true)
  → confirm in coach voice

[FOOD_DIARY] (screenshot of another food app)
  → call log_food per item (set from_photo=true, date= from the diary)
  → confirm: "Pulled in X items from your other log, looks like Y cal total"

[WORKOUT_LOG]
  → call log_exercise per exercise (split sets-with-different-loads into multiple calls)
  → confirm: "Logged your [muscle group] day — N exercises"

[METRICS] / [BLOOD_TEST] / [WEARABLE]
  → call track_metric per numeric value (or log_body_weight for scale weight)
  → for blood tests: store as profile attributes too if user wants
  → confirm: brief, supportive ("recovery's low today — taking it lighter?")

[MENU_DECISION] / [FRIDGE] / [GROCERY] / [DELIVERY_APP] / [BODY_PROGRESS]
  → call coach_on_photo with structured decision
  → tone: crisp, specific, coach voice (NOT generic "this is healthy")
  → reference user's daily targets concretely
  → for fridge/body: no macros_estimate needed

[PREPARED_MEAL] (ambiguous — user didn't say "ate" or "should I?")
  → If you can infer intent from caption, route accordingly
  → If unclear: ASK first — "you eating this, or thinking about it?"
  → Do NOT log silently when intent is ambiguous

[UNKNOWN]
  → Ask what they're sharing ("can't quite make this out — what am I looking at?")

CRITICAL: Photos can have multiple tagged blocks. Handle each one.
CRITICAL: NEVER call coach_on_photo for [FOOD_LOG] / [WORKOUT_LOG] / [METRICS] blocks — those have dedicated tools.
CRITICAL: ALWAYS confirm in coach voice after tool calls. Never leave the user staring at silence.
```

### 5c. Bot Handler Update

`bot/telegram_handler.py` line 537-544: replace `process_food_image` call with `process_photo`:

```python
# Before:
from multimodal.image_handler import process_food_image
analysis = await process_food_image(photo_data)
if analysis:
    caption_part = f" {caption}" if caption else ""
    combined = (
        f"[Food photo]{caption_part}\n"
        f"Photo analysis:\n{analysis}"
    )

# After:
from multimodal.image_handler import process_photo
analysis = await process_photo(photo_data, caption)
if analysis:
    caption_part = f" Caption: {caption}" if caption else ""
    combined = f"[Photo received]{caption_part}\n\n{analysis}"
```

The tagged blocks now ARE the analysis. The LLM reads them directly.

---

## 6. Conversation Flow Examples

### Example 1: User sends a menu photo

```
USER: [photo of menu] "thinking about lunch"

PREPROCESSOR runs:
  - classify → MENU
  - extract → [MENU_DECISION] block with dishes and prices

LLM SEES:
  "[Photo received] Caption: thinking about lunch
  
  [MENU_DECISION]
  Restaurant menu items visible:
  • Grilled salmon — $24, ~450 cal, 35g P
  • Cesar salad — $14, ~600 cal (heavy dressing), 12g P
  • Pasta carbonara — $22, ~900 cal, 25g P
  • Chicken sandwich — $16, ~700 cal, 30g P
  CONTEXT: User has 800 cal remaining, target 150g protein, at 100g.
  [/MENU_DECISION]"

LLM CALLS:
  coach_on_photo(
    photo_type="menu",
    decision="Get the salmon. Skip the bread basket. One drink, not two.",
    reasoning="You've got 800 cal left and 50g protein to hit. Salmon's the only thing here that nails both without blowing your day.",
    items_identified=["salmon", "caesar salad", "pasta carbonara", "chicken sandwich"],
    macros_estimate={"calories": 450, "protein": 35, "carbs": 20, "fats": 18},
    confidence=0.85
  )

USER SEES:
  ┌─────────────────────────────────────┐
  │ 🍽️ Menu Read                        │
  │                                     │
  │ Get the salmon. Skip the bread      │
  │ basket. One drink, not two.         │
  │                                     │
  │ You've got 800 cal left and 50g     │
  │ protein to hit. Salmon's the only   │
  │ thing here that nails both without  │
  │ blowing your day.                   │
  │                                     │
  │ Estimated: 450 cal, 35g P, 20g C    │
  └─────────────────────────────────────┘
```

### Example 2: User sends workout from Apple Notes

```
USER: [screenshot of Apple Notes]
  "Mon Push Day
   Bench: 185 x 8, 8, 7
   Incline DB: 70 x 10, 10, 8
   Cable fly: 35 x 12, 12, 12
   Tricep pushdown: 50 x 12, 12, 12, 12"

PREPROCESSOR runs:
  - classify → WORKOUT_LOG
  - extract → [WORKOUT_LOG] block with 4 exercises

LLM SEES tagged block, CALLS:
  log_exercise(exercise_name="bench press", sets=3, reps="8,8,7", weight=185)
  log_exercise(exercise_name="incline DB press", sets=3, reps="10,10,8", weight=70)
  log_exercise(exercise_name="cable fly", sets=3, reps="12,12,12", weight=35)
  log_exercise(exercise_name="tricep pushdown", sets=4, reps="12,12,12,12", weight=50)

USER SEES:
  "Logged your push day — 4 exercises, bench was your money set.
  Volume: 16 sets total. Tight workout."
```

### Example 3: User sends blood test

```
USER: [screenshot of lab results]

PREPROCESSOR runs:
  - classify → BLOOD_TEST
  - extract → [METRICS] block with cholesterol, HDL, LDL, etc.

LLM SEES tagged block, CALLS:
  track_metric(name="total_cholesterol", value=185, unit="mg/dL", date="2026-05-15")
  track_metric(name="HDL", value=55, unit="mg/dL", date="2026-05-15")
  track_metric(name="LDL", value=110, unit="mg/dL", date="2026-05-15")
  track_metric(name="triglycerides", value=100, unit="mg/dL", date="2026-05-15")
  track_metric(name="glucose_fasting", value=92, unit="mg/dL", date="2026-05-15")

USER SEES:
  "Saved your panel. Numbers look solid — cholesterol's in range, glucose is healthy.
  HDL could come up a bit, but nothing flagging here. Want to talk strategy or 
  just store it?"
```

### Example 4: User sends food photo with "should I eat this?"

```
USER: [photo of donut] "should I have this?"

PREPROCESSOR runs:
  - classify → PREPARED_MEAL (or PACKAGED_PRODUCT)
  - extract → both [FOOD_LOG] (in case they decide yes) AND [PREPARED_MEAL_DECISION]
  
  (Or: classifier emits PREPARED_MEAL but extraction prompt notices "should I?" caption
   → tags as [PREPARED_MEAL_DECISION] instead of [FOOD_LOG])

LLM SEES decision-tagged block, CALLS:
  coach_on_photo(
    photo_type="prepared_meal",
    decision="One's fine if you stay under target the rest of the day.",
    reasoning="That's ~280 cal and 30g sugar. You're already at 1400/2000 — eat it, then keep dinner protein-heavy and skip the rice.",
    items_identified=["glazed donut"],
    macros_estimate={"calories": 280, "protein": 4, "carbs": 38, "fats": 12},
    confidence=0.80
  )

USER SEES:
  ┌─────────────────────────────────────┐
  │ 🍩 Verdict                          │
  │ One's fine if you stay under target │
  │ the rest of the day.                │
  │ That's ~280 cal and 30g sugar...    │
  │ Estimated: 280 cal, 4g P, 38g C     │
  └─────────────────────────────────────┘
```

### Example 5: User sends food photo and says "had this"

```
USER: [photo of meal] "had this for lunch"

PREPROCESSOR runs:
  - classify → PREPARED_MEAL
  - caption says "had this" → extractor emits [FOOD_LOG]

LLM SEES [FOOD_LOG] block, CALLS:
  log_food(food_name="grilled chicken breast", quantity="6oz", calories=280, ..., from_photo=true)
  log_food(food_name="white rice", quantity="1 cup", calories=200, ..., from_photo=true)
  log_food(food_name="broccoli", quantity="1 cup", calories=55, ..., from_photo=true)

USER SEES:
  (existing log_food confirmation flow — unchanged)
```

This is the KEY integration point: **existing logging behavior is untouched** when the user is clearly logging. The new tooling only activates for decisions and non-food extractions.

---

## 7. Files Changed

| File | Change | Lines | Risk |
|------|--------|-------|------|
| `multimodal/image_handler.py` | Rewrite to smart preprocessor (keeps legacy wrappers) | ~300 (replaces ~50) | Low — preserves API |
| `core/tools.py` | Add `coach_on_photo` tool def to `_NUTRITION_TOOLS` | ~50 | Zero — additive |
| `handlers/tool_executor.py` | Add `elif name == "coach_on_photo":` branch in `_dispatch` | ~25 | Low — additive |
| `core/system_prompt.py` (or wherever) | Add "WHEN A PHOTO ARRIVES" section | ~50 | Low — additive guidance |
| `bot/telegram_handler.py` | Change `process_food_image` → `process_photo`, pass caption | ~5 | Low — same return contract |

**Total new code: ~430 lines (mostly prompts and routing logic)**  
**Total deletions: ~0 (legacy wrappers preserved)**  
**Breaking changes: 0**

---

## 8. Rollout Plan

### Phase 0: Validate Spec (this conversation)
- [x] Spec written
- [ ] User reviews + confirms scope
- [ ] User confirms 10 photo types are right (cut/add any?)

### Phase 1: Build Preprocessor (3-4 hours)
- [ ] Rewrite `multimodal/image_handler.py`
- [ ] Write 11 type-specific extraction prompts (10 types + UNKNOWN)
- [ ] Test classification on 5-10 sample photos
- [ ] Verify tagged output is parseable

### Phase 2: Add coach_on_photo Tool (1 hour)
- [ ] Add tool def to `core/tools.py`
- [ ] Add dispatcher branch in `handlers/tool_executor.py`
- [ ] Test result dict renders correctly

### Phase 3: Update System Prompt (1 hour)
- [ ] Add "WHEN A PHOTO ARRIVES" guidance
- [ ] Run simulated conversation tests
- [ ] Verify LLM routes correctly for each tag

### Phase 4: Update Bot Handler (15 min)
- [ ] Swap `process_food_image` → `process_photo` in telegram_handler.py
- [ ] Pass caption through to preprocessor

### Phase 5: Sample Photo Testing (2-3 hours)
- [ ] Test photos for each of 10 types
- [ ] Iterate on prompts where extraction fails
- [ ] Confirm conversation flow feels natural

### Phase 6: Beta Test (1-2 days)
- [ ] Deploy to staging
- [ ] Danny + 2-3 testers send real photos for a week
- [ ] Collect feedback, iterate

### Phase 7: Launch (1 day)
- [ ] Merge to main
- [ ] Deploy production
- [ ] Announcement message to user base

**Total effort: 8-12 hours of focused work, spread across 1-2 weeks with beta testing.**

---

## 9. Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Classification wrong (e.g., menu read as fridge) | Med | Med | Caption hints, fallback to UNKNOWN block, user can correct |
| Extraction fails on blurry photo | Med | Low | UNKNOWN tag triggers "what am I looking at?" |
| LLM ignores tag, calls wrong tool | Low | Med | Clear system prompt rules + few-shot examples in prompt |
| Workout extraction misses sets w/ different loads | Med | Low | Existing `log_exercise` already handles per-load splits; prompt teaches preprocessor to split too |
| Blood test numeric extraction inaccurate | Med | Med | Cap confidence, show extracted values to user before storing, allow correction |
| Photos that mix types (workout note w/ food list) | Low | Low | Emit MULTIPLE tagged blocks, LLM handles each |
| Existing food logging breaks | Low | High | Legacy wrappers preserved, behavior tested explicitly |
| Telegram rich rendering breaks | Low | Low | Fall back to plain text if rendering fails |

---

## 10. Open Questions for Validation

Before we code, confirm:

1. **Photo type taxonomy** — are the 10 types right? Should we cut any (e.g., body_progress is harder to do well) or add any (e.g., supplement labels, exercise machine readout)?

2. **Decision vs. extract for prepared meals** — currently the preprocessor decides based on caption ("ate" vs "should I?"). Is this enough or should we always extract BOTH and let the LLM choose?

3. **Auto-log threshold for extractions** — for workout/blood test/food diary extractions: do we auto-log when confidence is high, or always preview first?

4. **Blood test scope** — track all metrics or only the ones we know how to coach on (cholesterol, glucose, A1C, lipid panel)?

5. **Body progress photos** — store the photo? Just respond with text? This is sensitive territory; want to be thoughtful.

6. **Wearable scope** — which devices to support? (Whoop, Oura, Apple Watch, Garmin, Fitbit — different screen formats)

7. **Receipt OCR** — for grocery receipts, do we OCR each item and build a meal plan, or keep it as a coaching prompt for now?

8. **Cost ceiling** — two-step vision (classify + extract) doubles vision API cost per photo. Acceptable, or should we use one-shot with a smarter prompt?

---

## 11. Decision Points for Phase 0

Once you've read this, the decisions I need from you:

**Scope:**
- [ ] All 10 photo types at launch? Or start with subset (which 4-5)?
- [ ] Body_progress in or out of v1?
- [ ] Receipt OCR — v1 or later?

**Behavior:**
- [ ] Auto-log extractions on high confidence? Or always preview?
- [ ] Two-step vision OK on cost? Or optimize to one-step?

**Existing behavior:**
- [ ] Keep current `log_food + from_photo=true` flow as-is for "I ate X" cases? (Recommended yes)
- [ ] Any concerns about the system prompt additions affecting non-photo conversations?

**Timing:**
- [ ] Build all phases sequentially over 1-2 weeks?
- [ ] Or ship subset (e.g., menu + workout + blood test) first to test the pattern?

My recommendation: **Launch with 5 types — menu, fridge, prepared_meal (decision mode), workout_log, food_diary**. These are the highest-value, lowest-risk. Add blood_test, wearable, body_progress in v1.5 once the pattern is proven.

Ready to lock the spec and start Phase 1?
