# Skill: Strength Programming

## Purpose
Help strength athletes track progress, estimate 1RMs, plan progressions,
detect stalls, and build or adjust their training program.

## Trigger
- "what's my 1RM on [lift]", "estimate my max", "what can I bench/squat/deadlift"
- "write me a program", "give me a training plan", "how should I structure my week"
- "I'm stalling on [lift]", "I can't progress my [lift]", "stuck on bench/squat"
- "should I run 5/3/1", "what's a good split", "push pull legs", "upper lower"
- "[N]×[reps] @ [weight] — is that good for my 1RM"
- "deload week", "my lifts are going down", "overreaching"
- "what are my PRs", "show my best lifts"

## Data Available
- `[ESTIMATED 1RMs]` section in context: Epley-estimated 1RMs from best recent sets
- `[EXERCISE HISTORY]` section: last 6 sessions with exact weights and reps
- User profile: experience level (beginner/intermediate/advanced), goal, bodyweight

## 1RM Estimation
**Epley formula:** `1RM = weight × (1 + reps / 30)`
**Brzycki formula:** `1RM = weight / (1.0278 - 0.0278 × reps)` (more accurate 1–10 rep range)
Use Epley as default; note estimates are reliable at 3–8 reps, less accurate at 1–2 or 12+.

## Training Percentage Reference
| % of 1RM | Typical reps | Use case |
|---|---|---|
| 90–100% | 1–3 | Maximal strength / testing |
| 80–90% | 3–5 | Strength development |
| 70–80% | 6–8 | Hypertrophy + strength |
| 60–70% | 10–12 | Hypertrophy |
| 50–60% | 15+ | Muscular endurance / deload |

## Program Templates

### Linear Progression (beginner — add weight every session)
Add 5lb to upper-body lifts, 10lb to lower-body, every session.
Stop when 3 consecutive fails at same weight → deload 10%, rebuild.

### 5/3/1 (intermediate — Wendler)
4-week cycle. Training Max (TM) = 90% of actual 1RM.
- Week 1: 3×5 @ 65/75/85% TM (last set AMRAP)
- Week 2: 3×3 @ 70/80/90% TM (last set AMRAP)
- Week 3: 3×5/3/1 @ 75/85/95% TM (last set AMRAP)
- Week 4: Deload — 3×5 @ 40/50/60% TM
Increase TM by 5lb (upper) / 10lb (lower) each cycle.

### PPL (Push/Pull/Legs — 6-day hypertrophy)
Push: bench, OHP, incline, lateral raises, triceps
Pull: deadlift, rows, pull-ups/pulldowns, biceps, face pulls
Legs: squat, Romanian deadlift, leg press, lunges, leg curls

### Upper/Lower (4-day strength + hypertrophy)
Upper A (strength): bench 4×4, rows 4×4, OHP 3×5, pull-ups 3×6
Lower A (strength): squat 4×4, RDL 3×5, leg press 3×8
Upper B (hypertrophy): incline 4×8, DB rows 4×10, lateral raises 3×15
Lower B (hypertrophy): front squat / leg press 4×10, curls 3×12, lunges 3×10

## Stall Detection
A stall = same weight and reps for 3 or more sessions in a row.
Solutions by cause:
- **Volume stall** → add 1 working set, keep intensity
- **Recovery issue** → check sleep, calories, stress; reduce frequency first
- **Technique plateau** → deload 10–15%, focus on form for 2 weeks
- **Long stall (6+ weeks)** → change rep range, swap variation (close-grip bench, pause squat)

## Deload Protocol
Frequency: every 4–6 weeks (beginner), 6–8 weeks (intermediate), as needed (advanced).
Method: reduce volume by 40–50%, keep same weight/intensity. NOT a rest week.
Indicators to deload now: persistent soreness, sleep disruption, performance declining, WHOOP red 3+ days.

## Response Format
```
[Lift] — estimated 1RM: [X] lb / [X] kg
(based on best recent set: [W]lb × [R] reps)

Training percentages:
  Heavy (85%):  [X] lb × 3–5 reps
  Main (75%):   [X] lb × 6–8 reps
  Volume (65%): [X] lb × 10–12 reps

[1-sentence coaching note on progression or stall]
```

## Rules
- Always use data from [ESTIMATED 1RMs] context when available — don't estimate from scratch
- Clearly state estimates are estimates — not tested maxes
- Never prescribe an exact 1RM attempt unless user specifically asks
- Adjust all percentages to nearest 5lb (or 2.5kg) for practicality
- Experience-aware: beginners → linear progression; intermediate → 5/3/1 or PPL; advanced → periodised
