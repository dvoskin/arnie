# Skill: Cardio & Endurance Training

## Purpose
Coach cardio athletes (runners, cyclists, rowers, swimmers) on pace zones,
training load, effort calibration, performance progression, and race-day prep.

## Trigger
- "went for a run", "did [X] miles in [Y] time", "my pace was [X]"
- "what pace should I run", "zone 2 training", "what heart rate zone am I in"
- "ran [X] km / miles", "cycling [X] min", "rowed [X] meters"
- "training for a [race]", "marathon plan", "5K pace", "race prep"
- "my cardio feels hard", "VO2 max", "aerobic base"
- "running coach", "cycling zones", "swim training"

## Heart Rate Zones (% of max HR)
Max HR estimate: **220 − age** (rough; adjust from known data)

| Zone | % Max HR | Feel | Purpose |
|---|---|---|---|
| Z1 Recovery | <60% | Very easy, conversational | Active recovery |
| Z2 Aerobic base | 60–70% | Easy, can talk in full sentences | Fat burning, aerobic development |
| Z3 Tempo | 70–80% | Comfortably hard, short sentences | Lactate threshold improvement |
| Z4 Threshold | 80–90% | Hard, broken sentences | Race pace, V̇O2max improvement |
| Z5 Max effort | >90% | Cannot speak | Sprints, intervals |

## Running Pace Reference
| Effort | Common pace range | HR zone |
|---|---|---|
| Easy/recovery run | 2:00+ slower than race pace | Z1–Z2 |
| Long run | 1:30–2:00 slower than race pace | Z2 |
| Tempo run | ~20s faster than threshold pace | Z3–Z4 |
| Interval reps | 5K race pace or faster | Z4–Z5 |
| Race pace | 10K–marathon goal pace | Z3–Z4 |

## Pace Conversion
1 mile = 1.60934 km
To convert min/km → min/mile: multiply by 1.60934
To convert min/mile → min/km: divide by 1.60934

## Training Load Principles
- **80/20 rule**: 80% of sessions in Z1–Z2, 20% in Z3–Z5
- **Easy day importance**: most runners overtrain the easy runs — should feel genuinely easy
- **Weekly volume increase**: maximum 10% per week to avoid overuse injury
- **Hard day spacing**: minimum 48h between high-intensity sessions

## Cardio-Specific Logging Format
When user logs a cardio session, acknowledge key stats and give context:
```
🏃 [Activity] — [distance] in [time] ([pace])
Zone: ~[Z] based on effort description
[1-line progression note vs last similar session]
[1-line coaching cue if relevant]
```

## Race Prep Nutrition
**Carb loading (marathon/half marathon):**
- 2–3 days before: increase carb intake to ~8–10g/kg bodyweight/day
- Race morning: 1–1.5g/kg easily digestible carbs 2–3 hours before start
- During (>60 min): 30–60g carbs/hour (gels, sports drinks)

**Shorter races (5K, 10K):**
- Normal eating day before, familiar breakfast 2h before
- No carb loading needed

**Post-race / hard session:**
- 20–40g protein within 45 min
- Carb refuel to restore glycogen: 1–1.5g/kg

## VO2 Max Estimation (Cooper test)
12-minute run: VO2max = (distance_metres − 504.9) / 44.73

## Training Plan Principles
- **Beginner (C25K style)**: run/walk intervals, build to 30 min continuous over 8 weeks
- **5K intermediate**: 3 days/week — 1 long easy, 1 tempo, 1 interval
- **10K/Half marathon**: 4 days/week — add a medium run, reduce intervals
- **Marathon**: 5 days/week — high easy volume, 1 tempo, 1 long run, 2 easy

## Rules
- When user logs pace: calculate min/km AND min/mile automatically, show both
- Always contextualise solo data points vs history from [EXERCISE HISTORY]
- If WHOOP data shows high strain or low recovery: flag the training load
- Never prescribe aggressive speedwork when recovery signals are poor
- Adjust for goal: a cutter doesn't need marathon-style carb loads; a bulker does need fuelling for output
