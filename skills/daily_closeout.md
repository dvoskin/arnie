# Skill: Daily Closeout

## Purpose
Generate an end-of-day coaching summary when the user closes their log.

## Trigger
- User says: "close the day", "that's it for today", "day done", "wrap up"
- `/closeday` command

## Logic
1. Pull today's totals from DB
2. Compare against calorie / protein targets (if set)
3. Note workout / cardio completion
4. Identify the single most important coaching observation
5. State one concrete action for tomorrow

## Response Format
```
Day closed — [date]
Calories: [actual] / [target]   Protein: [actual]g / [target]g
Carbs: [actual]g   Fats: [actual]g
Workout: [✓/✗]   Cardio: [✓/✗]

[1–2 sentence coaching observation — honest, direct]
Tomorrow: [one concrete recommendation]
```

## Rules
- Max 8 lines
- No tables, no bullet lists
- Tone matches user's coaching_style preference
- Reference memory patterns when relevant (e.g. "protein was low again — this is a recurring pattern")

## Example Output
```
Day closed — 2026-05-25
Calories: 2,320 / 2,500   Protein: 162g / 190g
Carbs: 218g   Fats: 76g
Workout: ✓   Cardio: ✗

Solid lift day. Protein came up short again — third time this week.
Tomorrow: add a shake after training. That gap is becoming a habit.
```
