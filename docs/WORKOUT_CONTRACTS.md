# Workout logging contracts — defined now, implemented in Phase D

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
| one clock | `core/clock` | one-clock suites |

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

None of these renames may happen speculatively — each is earned by the workout
implementation actually arriving (rule of two), and each is mechanical because
the SHAPES are already right. That is this document's entire job.
