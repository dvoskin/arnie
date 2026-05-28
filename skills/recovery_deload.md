# Skill: Recovery & Deload

## Purpose
Detect overtraining and recovery debt, recommend deload protocols, guide
active recovery sessions, and optimise sleep + nutrition for faster adaptation.

## Trigger
- "should I deload", "I think I'm overtrained", "my lifts are dropping"
- "feeling beat up", "everything feels heavy", "no motivation to train"
- "sore for days", "can't recover", "sleep is bad"
- "WHOOP is red", "recovery score is low", "HRV dropped"
- "rest day", "active recovery", "what should I do on rest days"
- "how long to recover", "train through soreness", "deload week"
- "I'm burnt out from training"

## Recovery Signals — Read from Context

### Wearable data (if available in [WEARABLE] context)
| Signal | Green | Yellow | Red |
|---|---|---|---|
| Whoop recovery | 67–100% | 34–66% | 0–33% |
| HRV (relative to personal baseline) | ≥ baseline | 5–10% below | >10% below |
| Resting HR | At baseline | 2–5 bpm elevated | >5 bpm elevated |
| Sleep hours | ≥7h | 6–7h | <6h |

### Training pattern signals (read from [EXERCISE HISTORY])
- 5+ training days in a row without a rest day → recovery needed
- Same lift declining for 2+ consecutive sessions → likely fatigue, not technique
- Workouts getting progressively shorter (less volume completed) → early overreaching
- User describing low energy, heavy legs, poor sleep = subjective overtraining markers

## Deload Decision Framework
**Deload now if 3+ of these are true:**
1. Performance declining on main lifts
2. Persistent soreness lasting >72 hours
3. Sleep quality deteriorating
4. Motivation to train is unusually low
5. Wearable recovery score averaging red/yellow for 5+ days
6. 5+ consecutive training days
7. Approaching week 4–6 of a hard training block

**Don't deload if:**
- Poor performance from 1 bad night's sleep (improve sleep first)
- Just had a genuinely easy training week
- Poor performance because of diet deficit (check calories first)

## Deload Protocol Options

### Method 1: Volume Deload (recommended for most)
Keep same weights and intensity. Reduce sets by 40–50%.
Example: normally 4×8 bench → deload week: 2×8 same weight
Duration: 1 week. Return to normal next week.

### Method 2: Intensity Deload
Keep same volume (sets/reps). Reduce weight to 50–60% of working weight.
Good for: skill work, technique refinement, active recovery
Duration: 1 week.

### Method 3: Full Rest Week
Complete rest or only light walking/stretching.
Use only when: burnout is severe, illness recovery, travel/life disruption
Not ideal as standard deload — detraining risk after 1+ week complete rest.

## Active Recovery Protocols

### Light active recovery (ideal for rest days)
- 20–30 min walk (Zone 1 — very easy)
- Swimming (easy laps, non-competitive)
- Casual cycling
- Yin/restorative yoga
Goals: blood flow, reduced soreness, nervous system parasympathetic state

### Mobility work (30–45 min)
- Hip flexor stretch: 2 min/side (key for lifters and runners)
- Thoracic spine: foam roller + cat-cow 2 min
- Hamstrings: seated forward fold, leg swings 2 min
- Shoulders: banded distraction, 90/90 stretch
- Hip 90/90 rotations
Good for: any athlete, especially the day after heavy leg or back work

### Contrast therapy (if available)
Cold: 10–15 min ice bath (10–15°C) or cold shower (2–3 min)
Heat: sauna 15–20 min
Protocol: heat → cold → heat → cold (2 cycles)

## Nutrition for Recovery
- **Protein**: maintain or slightly increase on deload/rest days — muscle repair continues
- **Carbs**: reduce slightly on true rest days (lower glycogen demand), but don't crash them
- **Fats**: omega-3s support inflammation reduction — fatty fish, walnuts, fish oil
- **Sleep nutrients**: magnesium glycinate (400mg before bed), tart cherry juice (melatonin), chamomile
- **Hydration**: water + electrolytes, especially if sweating heavily

## Sleep Optimisation (biggest recovery lever)
- 7–9 hours is the target for training athletes
- Consistent sleep/wake time matters more than duration
- Avoid screens 60 min before bed, keep room cool (16–19°C)
- If WHOOP sleep score <70%: check light exposure, room temp, alcohol (even 1–2 drinks suppresses REM)

## Response Format — Deload Recommendation
```
Recovery check — [date]

Signals: [list 2-3 relevant indicators from context]
Verdict: [Deload recommended / Monitor / Training fine]

Protocol: [Method 1/2/3 — brief description]
[1 specific thing to do today]
[1 nutrition note for this week]
```

## Rules
- Always check [WEARABLE] data before making recovery recommendations
- Check [EXERCISE HISTORY] for consecutive training days and performance trends
- Frame deloads as part of the plan, not failure: "This is where the gains actually happen"
- Never tell a user to just "rest" without specifying what that means — give active recovery options
- Distinguish between feeling tired (normal) and systemic recovery debt (needs action)
