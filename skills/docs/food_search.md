# Skill: Food Search

## Purpose
Answer "how many calories/macros are in X?" quickly and accurately,
without logging the food. Inform the user; log only when asked.

## Trigger
- "how many calories in [food]", "what are the macros for [food]"
- "is [food] high in protein", "calorie count for [food]"
- "how much protein in [food]", "what's the nutritional info for [food]"
- User asks about a food's nutrition without any intent to log it
- "how fattening is [food]", "is [food] good for [goal]"

## Logic
1. Identify the food item and the most common serving size
2. Return macros for that serving
3. If branded: use actual product macros
4. If preparation matters significantly, note the range
5. Optional: 1-line contextual note if it's clearly relevant (e.g. very high sodium, misleadingly low cal, hidden fat)

## Response Format
```
[Food] ([serving]):
[X] cal  |  [P]g P  |  [C]g C  |  [F]g F

[Optional: 1 brief contextual note]
```

## Rules
- NEVER log the food unless user explicitly says "log that" or "add that"
- Use the most common real-world serving size — not 100g unless the food is typically sold by weight
- For branded items: use known product macros (e.g. Oikos Triple Zero, Quest bar, etc.)
- Stay at 3–5 lines max
- If user asks about multiple foods in one message, answer each in sequence
- If the food is ambiguous by prep (grilled vs fried chicken), give the most common prep AND note the variance

## Serving Size Defaults (when not specified)
| Category | Default serving |
|---|---|
| Meat / poultry / fish | 6oz (170g) cooked |
| Eggs | 2 large |
| Dairy (yogurt, cottage cheese) | 200g / 1 cup |
| Nut butters | 2 tbsp (32g) |
| Nuts | 30g (small handful) |
| Bread / toast | 2 slices |
| Rice / pasta cooked | 200g (1 cup) |
| Oil / butter | 1 tbsp |
| Fruit | 1 medium piece |
| Vegetables | 100g |

## Example Output — Single Food
```
Almond butter (2 tbsp / 32g):
190 cal  |  7g P  |  6g C  |  17g F

Dense in healthy fats — easy to overeat without tracking.
```

## Example Output — Preparation-Dependent Food
```
Chicken breast (grilled, 6oz / 170g):
280 cal  |  53g P  |  0g C  |  6g F

Pan-fried in oil: add ~100 cal and 10g fat. Breaded/fried: +150–200 cal.
```
