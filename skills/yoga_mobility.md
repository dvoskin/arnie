# Skill: Yoga & Mind-Body Training

## Purpose
Support users who practise yoga, pilates, tai chi, or other mind-body modalities.
Log sessions meaningfully, track flexibility/balance milestones, and integrate
their practice with nutrition and recovery goals.

## Trigger
- "did yoga", "yoga session", "vinyasa", "yin yoga", "power yoga", "hot yoga"
- "pilates class", "mat pilates", "reformer pilates"
- "tai chi", "qigong"
- "stretching session", "stretch class"
- "I held a [pose]", "can't do [pose] yet", "working toward [pose]"
- "need a yoga routine", "give me a stretch routine"

## Session Types & Typical Character

| Style | Intensity | Duration | Primary benefit |
|---|---|---|---|
| Vinyasa / Flow | Moderate–high | 45–75 min | Strength, flexibility, coordination |
| Power yoga | High | 60–90 min | Strength, endurance |
| Hot yoga (Bikram) | Moderate (heat-amplified) | 90 min | Flexibility, detox feeling |
| Yin yoga | Very low | 45–75 min | Deep connective tissue, fascia |
| Restorative yoga | Minimal | 45–60 min | Nervous system recovery |
| Hatha yoga | Low–moderate | 60–75 min | Balance, alignment, breath |
| Pilates (mat) | Moderate | 45–60 min | Core strength, posture |
| Pilates (reformer) | Moderate–high | 45–60 min | Full-body strength, alignment |
| Tai chi / Qigong | Very low | 20–45 min | Balance, flow, stress reduction |

## Calorie Estimates by Style (rough; highly variable by practitioner)
| Style | Cal/hour estimate |
|---|---|
| Yin / Restorative | 100–150 |
| Hatha | 150–200 |
| Vinyasa | 250–350 |
| Power yoga / Hot yoga | 300–450 |
| Pilates mat | 200–280 |
| Pilates reformer | 250–350 |

## Flexibility & Balance Milestones to Track
- Forward fold: fingers to floor / palms flat
- Seated forward fold: forehead to knees
- Splits: front splits (left/right), middle splits
- Backbend: bridge, wheel (urdhva dhanurasana)
- Balance: tree pose (eyes open/closed), crow pose, handstand against wall
- Hip openers: pigeon pose hold duration, lotus position
- Shoulder: bind in humble warrior, eagle arms behind back

Log milestone progress in memory as first achieved or distance from goal.

## Logging Format for Yoga Sessions
When user logs a yoga session, use this format:
```
🧘 [Style] — [duration] min
[Milestone or note if mentioned]
[1-line recovery / integration note]
```
Yoga sessions count as `cardio_type="yoga"` or left as duration-only exercise entry.
Do NOT count yoga as "workout_completed" unless it is power yoga or pilates (which have strength component).

## Nutrition Integration
- **Before yoga**: light eating; nothing heavy within 2 hours
- **After hot yoga**: electrolyte replenishment important (sodium, potassium, magnesium)
- **Yin/Restorative**: minimal energy demand — normal eating, no special protocol
- **Power yoga / pilates**: treat like a moderate workout — post-session protein matters (20–30g)

## Building a Yoga Practice
For users new to yoga or asking for guidance:
- **Beginner (0–3 months)**: 2–3× /week, hatha or beginner vinyasa, 30–45 min sessions
- **Intermediate (3–12 months)**: 3–5×/week, add yin on rest days for recovery
- **Advanced (1+ year)**: 5–6×/week, varied styles, add advanced poses progressively

## Complementing Other Training
- Yoga + strength training: yoga on off-days (yin) or after (restorative/stretching)
- Yoga + running: yin yoga for hip flexors and hamstrings dramatically reduces injury risk
- Yoga-only athlete: nutrition should still hit protein target for muscle maintenance

## Rules
- Never dismiss yoga/pilates as "just stretching" — it's a complete training system
- Match tone to the practice: yoga users often prefer a calmer, less aggressive coaching voice
- Track milestones with specificity: "working toward front splits — can get to 10cm from floor"
- If user mentions a specific pose by Sanskrit name, recognise it
- Respect recovery purpose: yin/restorative sessions should prompt lower calorie adjustments (less output)
