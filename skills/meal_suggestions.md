# Skill: Meal Suggestions

## Purpose
Suggest 2–3 specific, realistic meals based on remaining macros for the day
and the user's dietary preferences, goal, and eating context.

## Trigger
- "what should I eat", "what can I have for [meal]", "suggest a meal"
- "I have [X] cal left, what should I eat", "what fits my macros"
- "meal ideas", "what to eat", "I'm hungry, what should I have"
- "what's a good dinner / lunch / snack", "give me a meal idea"

## Logic
1. Pull remaining calories and protein from [TODAY] context
2. Note dietary preferences / restrictions from profile
3. Prioritise protein when behind target (>20g short vs day-fraction pacing)
4. Suggest 2–3 concrete options ranked by goal alignment
5. Keep suggestions realistic — meals people actually make or order

## Response Format
```
[X] cal · [Y]g protein left

• [Meal 1] (~[cal] cal, [P]g P) — [1-word benefit]
• [Meal 2] (~[cal] cal, [P]g P) — [1-word benefit]
• [Meal 3] (~[cal] cal, [P]g P) — [optional]

[Optional: 1 prep or context note if useful]
```

## Rules
- Suggest real meals, not abstract "balanced plates"
- Match dietary preferences: no suggestions that violate restrictions
- If protein is more than 25g behind target → lead exclusively with high-protein options
- If calories remaining < 300 → lean/volume foods, flag that it's tight
- If calories remaining > 700 → variety is fine, still anchor on protein
- No clarifying questions unless dietary restriction genuinely unclear
- If user is travelling: skew toward hotel-room, delivery, or convenience options
- Max 6 lines

## Macro Density Reference (for accurate suggestions)
| Food | Portion | Cal | Protein |
|---|---|---|---|
| Chicken breast grilled | 6oz | 280 | 53g |
| Ground beef 93% lean | 4oz cooked | 195 | 26g |
| Eggs | 3 large | 210 | 18g |
| Greek yogurt 0% | 200g | 120 | 20g |
| Cottage cheese | 200g | 160 | 28g |
| Canned tuna | 1 can (140g) | 130 | 30g |
| Salmon fillet | 5oz | 270 | 37g |
| Protein shake | 1 scoop + water | 120 | 25g |
| White rice cooked | 200g | 260 | 5g |
| Sweet potato | 200g | 180 | 4g |

## Example Output
```
620 cal · 74g protein left

• Ground beef bowl + rice (~520 cal, 45g P) — most protein per effort
• 3 eggs + cottage cheese 200g (~390 cal, 46g P) — fast, zero prep
• Canned tuna + sweet potato (~320 cal, 35g P) — light if not very hungry

Any of these close the protein gap cleanly.
```
