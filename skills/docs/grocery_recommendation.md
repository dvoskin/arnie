# Skill: Grocery Recommendation

## Purpose
Build a practical grocery list aligned with the user's macro targets,
dietary preferences, and eating patterns.

## Trigger
- User says: "what should I buy", "grocery list", "meal prep ideas",
  "what should I stock up on"

## Logic
1. Pull user profile: calorie/protein targets, dietary preferences, allergies
2. Identify gaps from recent food logs (recurring low-protein days, etc.)
3. Prioritise high-protein, whole-food staples
4. Add flexible fillers (carbs and fats vary more day-to-day)
5. Keep it short and practical — a real shopping list, not a nutrition textbook

## Response Format
```
Grocery list — [weekly target context]

Proteins (hit [target]g/day):
• [item 1]
• [item 2]
...

Carbs / Staples:
• [items]

Vegetables / Volume:
• [items]

Optional:
• [items for variety/preference]
```

## Rules
- Match dietary preferences (no suggestions that violate restrictions)
- Favour foods user already eats (check food_entries history)
- Include at least 3 high-protein options that require minimal prep
- Keep list to 15–20 items max — practical, not exhaustive

## Example Output (2500 cal, 190g protein, no restrictions)
```
Grocery list — 190g protein/day target

Proteins:
• Chicken breast (1.5kg)
• Ground beef 93% lean (1kg)
• Eggs (24-pack)
• Greek yoghurt 0% (4×200g)
• Cottage cheese (500g)
• Protein powder (if low)

Carbs / Staples:
• White rice (2kg)
• Oats
• Wholegrain bread
• Sweet potatoes

Vegetables / Volume:
• Broccoli, spinach, peppers (frozen bags work fine)
• Bananas + apples

Optional:
• Almonds (snacks — watch portions)
• Low-cal hot sauce / seasonings
```
