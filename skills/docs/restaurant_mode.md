# Skill: Restaurant Mode

## Purpose
Help the user make smart macro-aligned choices at a specific restaurant or
cuisine type, based on their goal and remaining macros for the day.

## Trigger
- "I'm at [restaurant]", "eating at [restaurant]", "at [restaurant] right now"
- "what should I order at [restaurant]", "what's good at [restaurant]"
- "[restaurant] options for my macros", "ordering from [restaurant]"
- User names a restaurant or food chain + asks what to eat/order

## Logic
1. Identify the restaurant (chain or cuisine type)
2. Pull remaining calories and protein from [TODAY] context
3. List 3–5 options that best fit the remaining macro budget
4. Rank by goal alignment (protein density for cut, overall fit for bulk/maintain)
5. Optional: 1 line on what to avoid or a useful ordering tip

## Response Format
```
[Restaurant] — [X] cal · [Y]g P remaining

• [Item/order] (~[cal] cal, [P]g P, [C]g C, [F]g F)
• [Item/order] (~[cal] cal, [P]g P, [C]g C, [F]g F)
• [Item/order] (~[cal] cal, [P]g P, [C]g C, [F]g F)

[1 line: avoid or tip]
```

## Ordering Strategies by Goal
| Goal | Priority | Avoid |
|---|---|---|
| Cut | Lean protein first, minimal sauces/extras | Liquid calories, extra fats (cheese, sauces) |
| Bulk | Higher cal dense options, no need to restrict | Nothing specific, keep protein anchored |
| Maintain | Balance — protein-dense options, moderate portions | Unknowingly doubling up on fats/carbs |

## Common Chains — Key Items
**McDonald's:** McDouble (no bun: 250cal/22P), Grilled McChicken (350cal/30P), Egg McMuffin (300cal/17P)
**Chipotle:** Chicken bowl no sour cream (550cal/48P), Chicken salad bowl (380cal/45P)
**Subway:** 6" Chicken breast sub no sauce (310cal/27P), Double chicken salad (330cal/48P)
**Starbucks:** Egg white bites (170cal/12P), Protein box chicken (480cal/34P)
**Chick-fil-A:** Grilled chicken sandwich (380cal/40P), Grilled nuggets 8pc (200cal/25P)

## Rules
- All macros are approximations — always use ~
- Reference remaining macro budget from [TODAY] context
- For unknown restaurants: use cuisine type as proxy (e.g. "sushi place" = Japanese cuisine defaults)
- Max 8 lines
- Never shame any choice — just rank by fit
- If user says "I already ordered X" → pivot to logging it, no commentary on the choice

## Example Output
```
Chipotle — 740 cal · 58g P remaining

• Chicken bowl (no cheese/sour cream, light rice): ~520 cal, 48g P, 50g C, 11g F
• Chicken salad bowl (lettuce base): ~380 cal, 45g P, 20g C, 12g F
• Steak + double protein bowl: ~650 cal, 65g P, 45g C, 18g F

Bowl over burrito — saves ~300 cal from the tortilla alone.
```
