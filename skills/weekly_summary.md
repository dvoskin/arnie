# Skill: Weekly Summary

## Purpose
Give the user a clear, data-backed snapshot of their last 7 days: calorie
adherence, protein averages, workout frequency, and one honest coaching read.

## Trigger
- "how was my week", "weekly summary", "week recap", "week review"
- "how did I do this week", "last 7 days", "weekly stats", `/week`
- "summarise my week", "week in review"

## Data Sources
- Last 7 closed daily logs (calories, protein, carbs, fats, workout/cardio flags)
- Calorie and protein targets from user profile
- Weight trend if available

## Logic
1. Pull last 7 days from [RECENT HISTORY] / [WEEKLY BREAKDOWN] in context
2. Calculate averages (not totals)
3. Calculate adherence: days within ±10% of calorie target / days logged
4. Identify the biggest gap — usually protein
5. State one concrete action for next week based on the gap

## Response Format
```
Week — [Mon DD] – [Sun DD]

Calories   avg [X] / [target]    ([N]/[logged] days on target)
Protein    avg [X]g / [target]g  ([%] of target)
Workouts   [X] / 7 days
[Optional: Weight trend if weigh-ins available]

[1 sentence honest coaching read — real numbers, no filler]
[1 sentence focus for next week]
```

## Rules
- Always show averages, not totals
- Adherence = days within ±10% of calorie target / days with closed log
- Flag if sample is small (< 3 closed days): note limited data
- Max 10 lines total
- No preamble ("Here's your weekly summary...")
- Tone matches coaching_style preference
- Bold key numbers with <b>tags</b>

## Common Patterns to Address
| Pattern | Coaching note |
|---|---|
| Protein consistently short | "You're Xg short every day — that's X×7=Yg/week of missed protein" |
| Calories over on weekends | "Weekdays solid, weekends pushing you over target" |
| No workouts logged | "0 workout days logged — rest week or just not logging?" |
| On-target week | "On point this week. Keep the same rhythm." |

## Example Output
```
Week — May 19 – May 25

Calories   avg <b>2,140</b> / 2,200    (5/6 days on target ✓)
Protein    avg <b>148g</b> / 190g      (78% — consistently short)
Workouts   <b>4</b> / 7 days

Solid calorie control. Protein is the only gap — 42g short every day.
Next week: 50g of protein before noon, every day. That closes it.
```
