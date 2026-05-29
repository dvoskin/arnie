# Skill: HIIT & Circuit Training

## Purpose
Generate, coach, and log HIIT (High Intensity Interval Training) and circuit
workouts for users who prefer time-efficient, high-output sessions.

## Trigger
- "HIIT workout", "give me a HIIT session", "interval training"
- "circuit workout", "give me a circuit", "full body circuit"
- "Tabata", "EMOM", "AMRAP", "interval session"
- "no equipment workout", "bodyweight only", "home workout"
- "20 min workout", "quick workout", "15 min / 30 min session"
- "cardio circuit", "CrossFit-style", "conditioning work"
- Logged a HIIT session and asking for analysis or what to do next

## Protocol Library

### Tabata (4 minutes per exercise)
20 seconds on / 10 seconds off × 8 rounds per exercise.
Traditionally: 1 exercise × 4 min. Common: 4–8 exercises back-to-back.
Effort: Z4–Z5. Very demanding — suitable for intermediate+.

### EMOM (Every Minute On the Minute)
Set number of reps to complete each minute. Rest = remaining time.
If reps take 40s → 20s rest. If reps creep to 55s+ → reduce reps.
Duration: typically 10–20 minutes.

### AMRAP (As Many Rounds As Possible)
List of exercises. Complete as many full rounds as possible in set time.
Note rounds + any partial rounds completed.

### Ladder
Ascending, descending, or pyramid rep scheme.
Example: 1–2–3–4–5–4–3–2–1 reps of burpee + pullup.

### Standard Interval
Work : Rest ratio. Common ratios:
- 1:1 (30s on / 30s off) — moderate intensity, sustainable
- 2:1 (40s on / 20s off) — higher intensity
- 3:1 (45s on / 15s off) — very high intensity, short duration only

## Exercise Library by Category

**Lower body**: squat jump, lunge jump, lateral lunge, Bulgarian split squat, step-up, wall sit
**Upper body**: push-up (standard/wide/diamond/archer), pike push-up, dips (chair), inverted row
**Core**: plank, side plank, mountain climber, V-up, hollow hold, L-sit
**Full body / cardio**: burpee, squat thrust, sprawl, bear crawl, inchworm, star jump
**Equipment options**: kettlebell swing, goblet squat, box jump, medicine ball slam, battle ropes

## Workout Generation by Time Available

### 15-minute bodyweight HIIT (beginner)
3 rounds × 5 exercises, 40s on / 20s off, 60s rest between rounds:
squat jump, push-up, mountain climber, lunge, plank

### 20-minute HIIT (intermediate)
4 rounds × 5 exercises, 40s on / 20s off, 45s rest between rounds:
burpee, squat jump, push-up to downward dog, speed skater, V-up

### 30-minute circuit (intermediate, with equipment)
5 rounds × 6 stations, 45s work / 15s transition:
KB swing, box jump, push-up, goblet squat, plank, battle rope (or mountain climber)

### 45-minute AMRAP / EMOM combination (advanced)
Warm-up 5 min → 20 min EMOM → 15 min AMRAP → 5 min cool-down

## Effort Scaling
- **Beginner**: reduce reps 30–40%, add 10–15s rest, substitute high-impact with low-impact (step-out instead of squat jump)
- **Intermediate**: as written
- **Advanced**: add weight (vest, KB), reduce rest, increase reps

## Calorie Burn Estimates (rough; highly individual)
| Session type | Cal / 20 min | Cal / 45 min |
|---|---|---|
| Low-impact circuit | 150–200 | 300–400 |
| Standard HIIT | 200–300 | 400–500 |
| High-intensity Tabata/AMRAP | 250–350 | 500–700 |

## Logging HIIT Sessions
HIIT sessions are logged as cardio (`cardio_type="hiit"` or "circuit").
Log as duration-only. If RPE or rounds noted by user, capture in exercise_name detail.
Example: "HIIT — 25 min, 5 rounds" → exercise_name="HIIT Circuit (5 rounds)", duration=25.

## Post-HIIT Nutrition
- HIIT depletes glycogen + creates protein breakdown — recovery nutrition matters
- Within 45 min: 25–40g protein + 30–60g fast carbs
- For cut goals: protein shake + banana; adequate even on deficit days
- Hydration: replace fluid + electrolytes, especially in hot conditions

## Response Format — Generated Workout
```
[X]-min [Protocol] — [Level]

[Exercise 1]: [reps or duration]
[Exercise 2]: ...
[Exercise N]: ...

Work: [Xs] | Rest: [Xs] | Rounds: [N]
[1-line tip on scaling or what to track]
```

## Rules
- Always ask or infer equipment availability before generating a workout
- Adapt to experience level and goal (cut → more cardio-biased; bulk → shorter, heavier circuits)
- HIIT is high-impact — flag it for recovery: don't generate hard HIIT on back-to-back days
- If WHOOP data shows red recovery: suggest lower-intensity circuit or full rest
- Log HIIT sessions immediately after generation if user confirms they did it
