# Skill: Aggressive Cut Day

## Purpose
Help a user maximise fat loss on a hard deficit day while protecting muscle.

## Trigger
- User says: "aggressive cut today", "hard deficit today", "cut day protocol"
- User's goal is "cut" AND they ask for a plan
- Calories are running very low and user asks what to eat

## Logic
1. Calculate remaining calories and protein from today's log
2. Prioritise protein to hit target (minimum 0.8g × body weight lbs)
3. Fill remaining calories with volume foods (vegetables, lean protein)
4. Minimise fats and liquid calories
5. Flag if deficit is dangerously aggressive (>1000 cal below TDEE)

## Response Format
```
Cut day — [remaining cal] left, [remaining protein]g protein to hit.

Recommended remainder:
• [meal 1] — [approx macros]
• [meal 2] — [approx macros]

Notes: [1–2 coaching notes about training, hunger management, hydration]
```

## Rules
- Keep responses to 6–8 lines
- Prioritise protein above all else on cut days
- Warn if deficit will impair training performance
- Recommend high-volume, high-satiety foods

## Example Output
```
Cut day — 680 cal left, 74g protein to hit.

Recommended:
• 200g chicken breast + vegetables — ~250 cal, 44g P
• 2 eggs + cottage cheese — ~200 cal, 28g P
• Save ~230 cal buffer for anything else

Train hard, keep water high. If hungry tonight — more protein, not fat or carbs.
```
