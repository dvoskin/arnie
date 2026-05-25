# Skill: Weigh-In Analysis

## Purpose
Provide context-aware analysis when a user logs their weight,
preventing over-reaction to single data points.

## Trigger
- User logs body weight (text, scale photo, or voice)
- User asks "what does my weight mean?" or "why did I go up?"

## Logic
1. Retrieve last 7–14 days of weight entries
2. Calculate rolling 7-day average
3. Compare to previous 7-day average (trend)
4. Contextualise against yesterday's food/water/training
5. Give interpretation and recommendation

## Response Format
```
[Current weight] logged.
7-day avg: [X]kg  →  Previous avg: [Y]kg  ([+/-Z] trend)

[1-sentence interpretation]
[1-sentence recommendation or reassurance]
```

## Rules
- Single weigh-in ≠ fat gain/loss — always contextualise
- Flag water retention if: high sodium yesterday, heavy training, low sleep
- Flag measurement conditions (morning vs evening, post-meal vs fasted)
- Keep to 4 lines max — no essays about weight fluctuation

## Common Patterns to Explain
| Situation | Likely cause | Message |
|---|---|---|
| +1–2 kg overnight | Water retention | Normal. High carbs/sodium/stress. |
| Weight up after hard training | Inflammation/glycogen | Expected. Trend matters, not today. |
| Weight stuck for 10+ days | Adaptive response | Consider diet break or refeed. |
| Consistent drop over 2 weeks | Real fat loss | This is the trend. Keep going. |

## Example Output
```
191.4 lbs logged.
7-day avg: 192.1 lbs → Last week: 193.8 lbs (−1.7 lbs trend ✓)

Down on the trend — that's what matters. Today's reading is solid.
Keep food consistent this week and weigh at the same time each morning.
```
