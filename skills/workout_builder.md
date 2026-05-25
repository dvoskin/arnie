# Skill: Workout Builder

## Purpose
Generate a practical, goal-aligned workout when the user asks for one.

## Trigger
- User asks: "give me a workout", "what should I do today",
  "build me a push day", "I don't know what to train"

## Logic
1. Check user profile: goal, training experience, injuries
2. Check today's log: is a workout already done? What was yesterday?
3. Select appropriate split and muscle groups
4. Match volume/intensity to experience level
5. Provide exercise list with sets × reps and RPE or RIR guidance

## Response Format
```
[Day/Focus] — [goal context]

[Exercise 1]: [sets]×[reps]  @[load guidance]  RIR [X]
[Exercise 2]: ...
...

Notes: [1–2 practical coaching notes]
```

## Volume Guidelines
| Experience | Sets per muscle | Frequency |
|---|---|---|
| Beginner | 3–4 | 2–3x/week |
| Intermediate | 4–6 | 3–4x/week |
| Advanced | 5–8 | 4–5x/week |

## Rules
- Respect injury limitations — always route around them
- Don't prescribe exact weights — give RPE/RIR instead
- Keep workouts under 60 min for most users
- On cut phases: reduce volume 10–20%, keep intensity

## Example Output (Intermediate, Cut, Push Day)
```
Push Day — moderate volume, deficit week

Bench Press: 4×6  @~75% 1RM  RIR 2
Incline DB Press: 3×10  RIR 2
Shoulder Press: 3×10  RIR 2
Lateral Raises: 3×15  RIR 1
Tricep Pushdowns: 3×12  RIR 1

Keep rest 90–120s. Log weights — we're tracking progress.
Low energy on a cut is normal. Don't reduce load, reduce volume if needed.
```
