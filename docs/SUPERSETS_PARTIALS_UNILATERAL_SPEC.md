# Supersets · Partial Reps · Unilateral (Isolateral) — Design Consideration

Status: **SPEC ONLY — not implemented.** Phase 1 (logging-accuracy + pacing,
prompt/logic only) ships first and is verified before any schema migration runs
against the live prod DB. This doc is the design for the *next* pass.

Motivated by Danny's real 2026-06-14 shoulder session, which exercised all three
cases and exposed where the flat model breaks:
- **Supersets**: "face pull superset with upright rows", "Super set 2/3" — pairing lost.
- **Unilateral**: "16x20 **each side**" on cable laterals — per-side volume dropped (logged 16 reps, actually 32 across both sides).
- **Partials**: not in that session, but advanced lifters append them constantly ("8 + 4 partials") and the flat `reps` string has nowhere to put them.

---

## 0. Current model (what we're extending)

- **Storage** — `db/models.py:171` `ExerciseEntry`: `exercise_name`, `sets` (int),
  `reps` (comma-string, per-set e.g. `'12,12,10'`), `weight` (kg), `rir`,
  `duration_minutes`, `cardio_type`, `notes` (Text, **currently unused in UI**),
  `source_type`. No superset link, no partial field, no per-side concept.
- **Logging** — `core/tools.py:216` `log_exercise`; executor at
  `handlers/tool_executor.py:1113`. Canonicalize → dedup guard → `add_exercise_entry`.
- **Catalog** — `skills/fitness/exercise_catalog.py`: `name/aliases/primary/equipment/rest_seconds`. **No `unilateral` flag.**
- **UI** — `api/templates.py:5708` `renderGroupedExercises` groups by lowercased
  name → `N × reps @ wt`, expandable to per-set chips; `:5759` `renderExerciseRow`;
  `api/insights.py:62` `f"{sets}×{reps}"`. Manual entry form posts
  `{name,sets,reps,weight_lbs,duration_minutes,is_cardio}` (`:3905`, `:6247`).
- **Pacing** — `core/session_state.py` uses catalog `rest_seconds`/`primary`/`equipment`.

### Guiding principles (inherited from the live-workout architecture)
1. **Additive, nullable columns only** — never repurpose existing fields; older
   entries (and the manual UI form) keep working with the new fields NULL.
2. **Forward-only** — no backfill of historical rows; new semantics apply to new logs.
3. **Dedup-safe** — any new field that participates in identity must be folded into
   `exercise_dedup.is_duplicate_of_recent`'s match key, or dedup silently breaks.
4. **Low-friction logging** — the user types "16x20 each side"; the *model* fills the
   structure. Never add a UI step or a required tool arg that makes logging feel like a form.
5. **Voice/perf untouched** — display + parsing changes only; no new LLM behavior beyond
   recognizing the three patterns.

---

## 1. Unilateral / Isolateral (single-arm / single-leg)

**What** — movements loaded/performed per side: single-arm DB row, cable lateral
"each side", Bulgarian split squat, single-leg press, unilateral pulldown. Weight
is per-hand; reps are per-side; **true working volume = 2× the logged set**.

**Why it matters** — volume/tonnage math, PR tracking, and pacing all under-count
2× today. Danny's "16x20 each side" stored as one 16-rep set; the dashboard shows
half the work he did.

**Current gap** — no flag anywhere. The catalog already *contains* unilateral
movements (single-arm DB row, Bulgarian split squat, lunges at
`exercise_catalog.py:102,125,288`) but doesn't mark them as such.

**Data model (recommended, minimal):**
- Catalog: add `unilateral: bool` (default False) to entries that are inherently
  per-side. Source of truth for "this movement is two-sided."
- `ExerciseEntry`: add `per_side: Boolean (nullable)` — set True when the logged
  reps/weight are per-side. Defaults to catalog's `unilateral` flag at log time,
  overridable by explicit user phrasing ("each side", "per arm", "/side").
- Volume helpers multiply by 2 when `per_side` is True. (Optionally a
  `side` enum `left|right|both` later, only if users start logging asymmetric
  L/R sets — defer until asked; most log symmetric per-side.)

**Logging/parsing** — `log_exercise` gains optional `per_side: bool`. Prompt rule:
"each side / per arm / per leg / /side → `per_side=true`." Executor falls back to
the catalog `unilateral` flag when the model omits it, so "16x20" on a
known-unilateral movement still flags correctly.

**Dedup/pacing** — add `per_side` to the dedup match key (a per-side 16 and a
both-sides 16 are different sets). `session_state` muscle-coverage doubles
per-side set contribution; rest windows unaffected.

**UI display (the emphasis):**
- Grouped/row summary: append a compact `/side` marker — `16 × 20lb /side` and a
  small "×2" or "per side" pill, so the number the user reads matches what they did.
- Set chips (`renderExerciseRow:5765`): `S1: 16/side`.
- Volume/tonnage readouts and `/today` (`api/insights.py:62`) multiply per-side sets.
- Manual entry form: a small "per side" checkbox next to weight (`templates.py:3905` body
  gains `per_side`). Pre-checked when the typed name resolves to a unilateral catalog entry.

---

## 2. Partial Reps

**What** — reps through a partial ROM, usually appended after full reps to failure:
"8 + 4 partials", "10 full then 5 halves", "8+4p". They count toward intensity/volume
but are **not** full reps — conflating them corrupts rep PRs and e1RM estimates.

**Current gap** — `reps` is a flat per-set string. A "8+4p" set has nowhere to
live; the model either drops the partials or stores "12" (a fake full-rep PR).

**Data model (recommended, minimal):**
- `ExerciseEntry`: add `partial_reps: String (nullable)` — per-set partial counts,
  same comma shape as `reps` (e.g. full `reps='8,8,6'`, `partial_reps='0,2,4'`).
  Parallel array keeps it dead simple and backward-compatible (NULL = no partials).
- PR/e1RM logic counts only `reps` (full); partials surface as a separate
  intensity signal, never inflate a rep PR.

**Logging/parsing** — `log_exercise` gains optional `partial_reps: str`. Prompt
rule: "N full + M partials / N+Mp / M halves → `reps=N, partial_reps=M`. Partials
NEVER go in `reps`." Notation convention documented once in `EXERCISE_LOGGING`.

**Dedup** — fold `partial_reps` into the match key (8+4p ≠ 8+0p).

**UI display:**
- Chip: `8 + 4p` with the partial portion muted/smaller so it reads as supplementary,
  never as 12 full reps. Summary: `3 × 8 (+4p last set) @ 185lb`.
- PR badges ignore partials (no false "rep PR" from a partial-padded set).
- Manual form: optional "+ partials" mini-input beside reps.

---

## 3. Supersets / Paired Movements

**What** — 2+ movements performed back-to-back as one unit (A1/A2), rest taken
after the *pair*, not between. Danny: "face pull superset with upright rows",
"Super set 2/3", "front raise superset with shrugs".

**Why it matters** — (a) pacing: rest applies after the whole superset, so the
catalog single-movement `rest_seconds` is wrong mid-superset; (b) display: the user
thinks in pairs/rounds, the flat list scatters them; (c) it's the #1 source of the
over/under-log confusion Phase 1 just patched — structure would make it robust.

**Current gap** — no grouping concept; each movement is an independent entry.

**Data model (recommended, minimal):**
- `ExerciseEntry`: add `superset_group: String (nullable)` — a short per-session
  label shared by entries in the same superset (e.g. `"A"`, `"B"`, or a uuid4 hex
  slice). NULL = standalone (the default; 99% of entries). Optionally
  `superset_order: Int (nullable)` for A1/A2 ordering within the group.
- A group is scoped to one `daily_log` (one session). No new table needed — a
  nullable label on the existing row is enough to render brackets and compute
  paired rest.

**Logging/parsing** — when the user declares a superset, the model assigns the
next group label and tags each round's entries with it. Prompt already (Phase 1)
logs each round's sets as performed; this just adds the shared label. No new tool
arg strictly required if the executor derives the group from "superset" phrasing,
but an explicit optional `superset_group` arg on `log_exercise` is cleaner.

**Dedup/pacing** — `superset_group` does NOT join the dedup key (same set is a dup
regardless of grouping). `session_state` rest logic: when the last entry has a
`superset_group`, suppress the single-movement rest cue *between* the paired
movements and apply rest only after the round completes — the pacing fix that
tonight's session wanted.

**UI display (the emphasis):**
- Grouped view: render superset members under one bracketed card — a left rule/
  brace connecting `A1 Face Pull` and `A2 Upright Row`, with a "superset" pill and
  per-round columns (`R1 / R2 / R3`). `renderGroupedExercises` gains a pre-pass that
  buckets by `superset_group` before the by-name grouping.
- Collapsed summary: `Superset · Face Pull 3×12 @70 + Upright Row 3×12 @110`.
- Manual form: a "+ add to superset" affordance that tags the next entry with the
  same group; low priority (most superset logging is conversational).

---

## 4. Migration & rollout plan (when Phase 2 is greenlit)

1. One Alembic revision adds all nullable columns at once: `per_side`,
   `partial_reps`, `superset_group`, (`superset_order`). All NULL-default → zero
   impact on existing rows, the manual UI form, and current queries.
   `alembic check` + verify the generated Postgres SQL compiles (per project rule).
2. Catalog `unilateral` flags added in the same PR (static Python, no migration).
3. Wire dedup key (`per_side`, `partial_reps`) — **ship with unit tests first**, or
   dedup regresses silently.
4. Prompt: one consolidated `EXERCISE_LOGGING` addition documenting the three
   notations (each-side, +partials, superset). Keep it tight — the section is
   already long; lead with examples.
5. UI render last, behind the data: summary markers → chips → manual-form inputs.
6. Run `simulate_live_workout.py` (extend it with each-side / +partials / superset
   assertions) against the live LLM before and after.

**Do NOT** run the migration until Phase 1 is verified in prod and the dedup-key
tests are green. Real users are active (Gi 303 convs, Steve 134, Michelle 70…).

---

## 5. Scope discipline / what to defer
- Asymmetric L/R per-side logging (`side` enum) — defer until a user actually logs
  uneven sides; per-side symmetric covers the real cases now.
- Drop sets, rest-pause, cluster sets, tempo notation — out of scope; the
  `partial_reps` parallel-array pattern generalizes to them later if needed.
- A dedicated `supersets` table / many-to-many — unnecessary; the nullable label
  on `ExerciseEntry` renders and paces correctly without it.
