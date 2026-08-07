# Workout logging contracts — defined now, implemented in Phase D


> **Current as of 2026-08-07.** Phase E/F has not started, and the food work has
> deliberately built toward it. **The honesty test for the shared layer: if
> workouts adopt it, core must not change.**
>
> Already generic and reusable: `core/semantic_fields.py` (registry, with
> `_DOMAIN_REGISTRARS` as the only place core names a domain), `ResolvedFields`
> as the sole settlement boundary, `PendingOperation` + `ClarificationInteraction`
> (domain-neutral by construction — `domain`, `subject_entity_id`,
> `candidate_kind`), and the coming semantic evidence layer (§B-1.5E), which is
> explicitly split so nutrition owns `FoodIntent` and its vocabulary while
> workouts add `ExerciseIntent` and theirs.
>
> Phase-O attributes (`SET_COUNT`, `REP_COUNT`, `EXTERNAL_LOAD`, `EQUIPMENT`…)
> already exist in `ClarificationAttribute` and are CONSTRUCTIBLE without a food
> edit — a gate protects that seam. They are not registered, so they cannot yet
> be presented, which is the correct state.
**This document is a contract, not a build plan.** It exists so that no
decision made while food proves the spine forecloses workout adoption — and so
"workout-ready" is checkable against something written down rather than
asserted. The executable half of that claim is
`tests/test_the_spine_has_no_food_assumptions.py`, which runs a non-food
payload through the real coordinator.

Rule of two (§24): nothing here is implemented until food's production
implementation and this contract demonstrate the same invariant.

## What workouts will reuse, unchanged

| shared | where it lives today | proven by |
|---|---|---|
| operation identity `lane:user:turn` | `core/canonical_writer.operation_id_for` | collision test |
| `DirectOperation` (payload-is-the-operation) | `core/canonical_writer` | quick_log promotion |
| commit coordinator: claim → write → record → finalise | `core/commit_coordinator` | PG concurrency suite + fake-domain test |
| `UNIQUE (operation_id, operation_revision)` | `meal_commits` | `test_two_connections_one_commit` |
| duplicate → identical persisted result, disclosures included | `core/meal_commit` | C6 |
| pending lifecycle (RESOLVING … FAILED) | `core/semantics.PendingOperation` | transition tests |
| `CanonicalEvent` / `CanonicalQuantity` / `Dimension` | `core/semantics` | dimensional-consistency tests |
| provenance enum (USER_STATED / USER_SELECTED / …) | `core/semantics.Provenance` | — add `DEVICE` at Phase D for HealthKit/Whoop imports |
| candidate source enum | `core/semantics.CandidateSource` | `DEVICE` landed at B-0c (device data is the PRIMARY candidate source for DURATION/DISTANCE, and the enum is closed and coercing — its absence made a device-sourced candidate unconstructable). B-1's food candidate rules exclude it, so no selector policy is owed yet |
| entity-selection patch | `core/semantics.SelectEntity` | domain-neutral by name as of B-0c: it writes `CanonicalEvent.entity_id`, which every domain has, so `EXERCISE_IDENTITY` needs no second patch class. Renamed from `SelectFoodEntity` while zero producers existed — after B-1 stores patches, `patch_type` is wire data |
| uncertainty evidence | `core/semantics.UncertaintyEvidence` | `impact_spread` is a `CanonicalQuantity`, not a calorie number — a 60-100 kg squat's consequence is training load. Fake-domain round trip |
| durable outbox events | `core/meal_commit.OutboxEvent` | fake-domain test enqueues one `training_analysis` job with zero food rows |
| one clock | `core/clock` | one-clock suites |

**Still owed for workouts, named rather than implied:** load-basis semantics
(per-dumbbell vs total) — `SetExternalLoad` alone cannot express "50s" meaning
two 50 kg dumbbells. Tracked for F-2; food does not need it, so the rule of
two has not been met.

## Target domain model (Phase D, verbatim from the directive)

```python
@dataclass(frozen=True)
class ResolvedWorkout:
    operation_id: str
    revision: int
    user_id: str
    logging_day: date
    user_timezone: str           # same refusal rules as ResolvedMeal
    started_at: datetime | None
    ended_at: datetime | None
    workout_type_id: str | None
    exercises: tuple[ResolvedExercise, ...]
    unresolved_fields: tuple[ClarificationField, ...]
    assumptions: tuple = ()
    warnings: tuple = ()
    source_turn_id: str = ""

@dataclass(frozen=True)
class ResolvedExercise:
    event_id: str
    entity_id: str | None        # exercise.barbell_bench_press — ID, not tokens
    surface_text: str
    sets: tuple[ResolvedSet, ...]
    equipment_id: str | None
    resolution_status: ResolutionStatus
    confidence: Confidence
    provenance: Provenance

@dataclass(frozen=True)
class ResolvedSet:
    set_id: str
    reps: CanonicalQuantity | None       # COUNT
    load: CanonicalQuantity | None       # MASS, used as external load
    duration: CanonicalQuantity | None   # DURATION
    distance: CanonicalQuantity | None   # DISTANCE
    effort: CanonicalQuantity | None     # DIMENSIONLESS (RPE)
    set_type: str = "working"
    provenance: Provenance = Provenance.UNKNOWN
```

Mirrors `ResolvedMeal`'s discipline: understood ≠ recorded-in-full, required
`logging_day` + validated timezone, disclosure travels with the payload, and
construction-time refusal of the unpriceable (a set with neither reps nor
duration nor distance is the workout analogue of an unpriced food).

## Capability metadata prevents impossible questions

`EntityCapabilities(allowed_dimensions, required_attributes,
optional_attributes, clarification_order, default_display_units)` — supplied by
the domain registry, consumed by the shared clarification planner. "How many
reps did you run?" must be unconstructable, the same way a MASS quantity
resolved only to millilitres already is.

## Storage (Phase D migrations, additive)

Shared tables stay shared: `pending_operations`, `meal_commits` (renamed or
wrapped per §5 when the second domain lands), `ledger_events`.
Domain tables stay domain: `workout_sessions` / `workout_exercises` /
`workout_sets` — workouts do not go into food tables or a universal JSON blob.
The existing `exercise_entries` table is the legacy analogue of `food_entries`
and migrates on the same shadow → parity → promote → delete path.

## Known renames owed at Phase C (deliberate, tracked, not yet earned)

* `MealCommitResult` → carried inside `OperationResult` with
  `DomainCommitResult = MealCommitResult | WorkoutCommitResult`. Generic in
  shape today; food-named. The fake-domain test uses it as the protocol it is.
* `meal_commits` table name — same story; the constraint and mechanics are
  already domain-neutral.
* `write_canonical_meal`'s `resolved_meal` kwarg → `payload` when the writer
  protocol (§13) is extracted.
* `OutboxEvent` — the NAME is domain-neutral; what is owed is RELOCATION out
  of `core.meal_commit`, alongside the `MealCommitResult` → `OperationResult`
  extraction. The coordinator hard-requires it for every domain's durable
  post-commit work (`core/commit_coordinator.py:65`), so a workout writer
  imports a meal module to enqueue a training analysis.

None of these renames may happen speculatively — each is earned by the workout
implementation actually arriving (rule of two), and each is mechanical because
the SHAPES are already right. That is this document's entire job.
