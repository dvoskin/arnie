# Arnie Brain Taxonomy — the contract

One reconciled profile, rendered uniformly across chat `[AI PROFILE]`, the dashboard,
and the bio. Every write path (`store_attribute` tool, `profile_updater` synthesis)
and every cleanup path (`profile_consolidator`, `prune_attributes`) enforces this.

**The rule that prevents all known drift: each fact lives in exactly ONE lane.
Snapshots, targets, and weight NEVER become attributes.**

## The three lanes

### Lane 1 — STRUCTURED (typed columns / `UserPreferences`)
Source of truth for anything with a column or its own UI. **Never** mirror these
into `UserAttribute` — a mirrored copy only drifts and conflicts.

- Demographics: name, age, sex, height, units
- Body: `current_weight_kg`, `goal_weight_kg` (history in `BodyMetric`)
- Targets: calorie / protein / carb / fat (`UserPreferences`)
- Schedule: wake_time, sleep_time
- Goals/level: primary_goal, training_experience
- Coaching config: coaching_style, accountability_level, food_logging_mode, reminder_frequency

### Lane 2 — DURABLE TRAITS (`UserAttribute` — what the brain is FOR)
Stable facts that change only when the user's life changes. One row per concept,
deduped, reconciled. This is the only lane that becomes an attribute.

- nutrition: diet_style, protein_habits, meal_timing, staple_foods, foods_avoided,
  food_preferences, restaurant_preferences, beverage habits, snack patterns, carb cycling
- fitness: training_split, training_time, training_frequency, cardio_habits,
  preferred_exercises, progression_system, rir prefs, dislikes
- health: injuries, physical_limitations, real supplements, **lab biomarkers (dated)**
- lifestyle: occupation, work_schedule, family_status, wake_sleep_schedule
- behavior / mental: motivation, coaching prefs, failure_points, stress_patterns

### Lane 3 — LIVE / TRANSIENT (computed fresh every turn — NEVER an attribute)
Has a live source table or is recomputed per turn. Storing it freezes a stale copy
that then contradicts the live section.

- Wearable daily metrics: HRV, RHR, recovery, strain, **last-night sleep**
  → owned by `HealthSnapshot` → `[WEARABLE]` / `[COACHING STATE]`
- Today's session focus / today's macros / remaining → `today_log`, `[SESSION STATE]`, `[PACING]`
- Momentum, streaks, projections → computed (`momentum`, `insights_engine`)
- One-off events ("stomach upset today") → conversation history, not a standing trait

## Category dictionary (resolve misclassification at the source)

| Thing | Category / key | NOT |
|---|---|---|
| Protein bar (Barebells, David, Happy Wolf) | `nutrition_protein_bar_preference` / `nutrition_staple_foods` | ❌ `health_supplement_*` |
| Protein shake, RTD (Oikos, Muscle Milk, Shamrock, Elmhurst) | `nutrition_staple_foods` / `nutrition_protein_sources` | ❌ `health_supplement_*` |
| Energy drink (C4, Bloom) | `nutrition_beverage_*` | ❌ `health_supplement_*` |
| Real supplement (fish oil, vit D, magnesium, zinc, creatine, protein **powder**) | `health_supplement_<name>` | — |
| Lab value (a1c, glucose, tsh, lh, testosterone, vit-D level, eGFR, ferritin, liver) | `health_biomarker_<name>` (+ unit, draw date) | ❌ `health_supplement_*` |
| Wearable daily metric (HRV, recovery, RHR, sleep) | *(not stored — Lane 3)* | ❌ any attribute |

**Foods are food.** A product you eat/drink for macros is nutrition, even if it's
"protein-fortified." `health_supplement_*` is reserved for things taken FOR health
(vitamins, minerals, oils, creatine), not for meals/snacks/drinks.

## Confidence (so the signal stays usable)
- `confirmed` — user stated it in plain words, OR it's Lane-1 structured truth.
- `inferred` — deduced from 3+ recurrences. **Most learned traits are inferred.**
- `needs_verification` — single offhand mention.

Cleanup ranks on **recency + source**, not self-reported confidence (which inflates).

## Lab panels — capture completely
When a user shares a lab panel, store the **full** set of values as dated
`health_biomarker_<name>` rows (value + unit + draw date), not a cherry-picked few.
