# Skill: Progress Timeline

## Purpose
Show the user a clear, honest view of their overall progress: weight trend,
nutrition adherence, and workout consistency over the last 4–8 weeks.

## Trigger
- "show my progress", "how much have I lost", "how much have I gained"
- "am I making progress", "progress update", "progress timeline"
- "weight trend", "how's my progress going", `/progress`
- "where am I at", "show me my stats over time"

## Data Sources
- Body weight history from [WEIGHT TREND] in context (extended — up to 8 weeks)
- Per-week calorie/protein averages from [WEEKLY BREAKDOWN] in context
- Workout frequency from daily logs
- Goal weight from user profile

## Logic
1. Pull weight start and current from extended weight history
2. Calculate total delta and rate per week (kg/week or lb/week)
3. Pull per-week calorie and protein averages from [WEEKLY BREAKDOWN]
4. Calculate workout days per week average over last 4 weeks
5. Compare rate of change against goal: is it on track, too fast, too slow?
6. Give a direct 2-sentence coaching read

## Response Format
```
Progress — [start date] – today

Weight    [start] → [current] kg  ([+/−X]kg · [N] weeks · [rate]/wk)
Goal      [goal weight] kg  ([X]kg to go)
Avg cal   [X] / [target] cal/day
Avg pro   [X]g / [target]g/day
Workouts  [X] sessions / week (last 4 weeks)

[Sentence 1: is the trend on track? reference the rate vs goal]
[Sentence 2: biggest lever to improve — what to focus on]
```

## Rate Benchmarks
| Goal | Healthy rate | Flag if |
|---|---|---|
| Cut | 0.5–1.0 kg/week | >1.2 kg/week (too fast) or <0.2 kg/week (stalled) |
| Bulk | 0.2–0.4 kg/week | >0.6 kg/week (gaining fat) or <0.1 kg/week (undereating) |
| Maintain | <0.3 kg variation | >0.5 kg consistent drift |

## Rules
- NEVER fabricate or extrapolate weight data — use only what exists in [WEIGHT TREND]
- If < 2 weight entries: say so clearly: "Not enough weigh-ins to show a trend — aim for 3× per week, same time, same conditions"
- If weight going wrong direction vs goal: say it directly, don't soften
- Max 10 lines
- Always state if data covers less than 2 weeks: small sample caveat
- No preamble

## Example Output — Cut
```
Progress — Apr 7 – May 25

Weight    94.2kg → 91.8kg  (−2.4kg · 7 weeks · −0.34kg/wk)
Goal      88.0kg  (3.8kg to go)
Avg cal   2,080 / 2,200 cal/day
Avg pro   172g / 190g/day
Workouts  3.2 / week (last 4 weeks)

On track — 0.34kg/week is clean, sustainable fat loss. No muscle alarm signs.
Protein at 90% is solid; keep it there and the last 4kg will follow.
```

## Example Output — Insufficient Data
```
Progress — not enough data yet

Only 1 weigh-in on record — can't show a real trend yet.
Aim for 3 weigh-ins per week, same time each day (morning, fasted).
After 2 weeks I'll be able to give you a proper read.
```
