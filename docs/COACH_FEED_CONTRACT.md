# The Coach feed contract

One interpretation of the day, computed server-side, read by every section.

`core/coach_live.py` decides. `api/coach_live.py` assembles and serialises.
The briefing layer may **phrase** what the coordinator decides; it may not
decide it. Nothing else interprets the day.

The governing rule, applied per section: **orient, create an action, reinforce an
action, or prepare the next return.** A section that does none of those is not
built, whatever data an endpoint happens to expose.

---

## Status of each section

| # | Section | Status |
|---|---------|--------|
| 1 | Header / live status | **Locked** — contract shipped |
| 2 | Contextual commands | **Locked** — contract shipped |
| 3 | Daily Verdict | **Locked** — contract shipped |
| 4 | Today / live execution | **Locked** — contract shipped |
| 5 | Today's Focus | **Locked** — contract shipped (reads the coordinator, does not re-query) |
| 6 | Coach Insight | **Locked** — basis shipped; phrasing layer open |
| 7 | Nutrition trajectory | **Locked** — categorical, no probability |
| 8 | Training and activity | Partial — training locked, activity blocked on a step goal |
| 9 | Recovery / body state | Partial — reads `core.coaching_state`; modification vocabulary locked |
| 10 | Recent meaningful change | **Locked** — derived by replay |
| 11 | End-of-day closure | Not started |

---

## 1. Header — presence, freshness, continuity

**Product job.** Establish that Arnie is current and connected. *Not* where the
day is judged.

**Backend inputs.** `WearableDevice.last_sync_at` (max across the user's
devices), `WearableDevice.device_type`.

**Derived state.** `freshness.state` ∈
`live` (≤30m) · `recently_updated` (≤4h) · `partially_current` (≤24h) ·
`waiting_for_sync` · `no_wearable`

**User action.** Only when needed: reconnect, refresh. Otherwise none.

**Completion response.** Freshness updates. No celebration — a successful sync
is not an achievement.

**Return trigger.** Quietly signals there may be something new.

> **Gap closed.** Whoop and Oura wrote `last_sync_at`; HealthKit never did, so an
> Apple-Health-only user had no readable sync time anywhere in the system. The
> column already existed. `api/health_sync.py` now stamps it.

---

## 2. Contextual commands — fastest useful paths

**Product job.** Cut the distance between opening Arnie and doing the thing the
user already intends. Not chat prompts.

**Derived state.** Three slots, each carrying enough context to invoke a focused
operation:

- `primary` — the current highest-leverage action, mirroring the focus.
- `explanation` — only when there is a live interpretation worth interrogating.
  Absent on a calm day; "why is everything fine?" is not a question anyone asks.
- `planning` — the *next* decision, not the current one.

**Completion response.** The command disappears or becomes the next appropriate
command, because it is derived from state rather than stored.

---

## 3. Daily Verdict — the current thesis

**Product job.** One interpretation of the day. Not a score, not a morning report.

**Server-owned state.** `overall_state` ∈
`calibrating` · `building` · `on_track` · `at_risk` · `recovering` · `secured` ·
`complete`

Selected by the deterministic coordinator. The LLM never picks it.

| State | Condition |
|---|---|
| `calibrating` | No evidence yet, or nutrition still unreadable |
| `building` | Started; real commitments still open |
| `on_track` | Domains within realistic pace, nothing open |
| `at_risk` | A nutrition domain is drifting, or a planned session was missed |
| `recovering` | The previous read was `at_risk` and an action moved it |
| `secured` | Minimum meaningful requirements met |
| `complete` | Reviewed, or past the 04:00 rollover |

**Minimums for `secured`.** Nutrition landed **and** training done / declared off
/ never asked for. Deliberately *not* every box — requiring a weigh-in and a step
goal is how a genuinely good day gets reported as incomplete.

**Action.** Leads into the current focus. Never an unrelated CTA.

---

## 4. Today — the live execution ledger

**Product job.** What happened, what is open, what is moving.

**No equal-metric trap.** `domains` are ranked, not listed. `limiting_domain`
names the binding constraint — and is `null` when nothing limits the day
(nothing started, or already closed).

Every domain reports `state` · `current` · `target` · `expected_finish` ·
`intervention`.

---

## 5. Today's Focus — one commitment

Reads the coordinator; does not independently query and re-interpret endpoints.

`{domain, action, reason, deadline, minimum}`

`minimum` is the fallback that preserves momentum — a 20-minute session still
counts. A missed workout must not collapse the day.

**One divisor.** The per-meal ask divides the remaining gap by
`meals_remaining`, the same divisor iOS `DayTargets.proteinBand` uses. Two
divisors is how one screen printed "land 110g" beside "168g left".

---

## 6. Coach Insight — causal explanation

**Rule: never restate the focus.** Structured, not prose, so the coordinator
establishes what is true and the briefing layer writes the sentence — which is
what stops the model inventing a pattern the data does not support.

`{kind: pattern|constraint|tradeoff|cause, subject, evidence_n,
evidence_window, typical_value, detail}`

- `pattern` needs ≥4 finished days. Below that it degrades to `constraint`
  rather than inventing an average.
- On an unstarted day it is a `tradeoff` about starting early — **not** a gap
  analysis. Running the shortfall copy at 8am produced *"carrying 162g into
  tonight makes the target unreliable"* to someone who simply had not eaten yet.

---

## 7. Nutrition trajectory — will it land

`state` ∈ `not_calibrated` · `ahead` · `on_pace` · `reachable` · `at_risk` ·
`secured`

**Categorical by instruction. No probability is published.** The engine computes
a pace ratio to rank domains; it does not print one, because nothing has been
validated against real outcomes yet and a number is far harder to walk back than
a word.

**Two rules that took a bug each to find:**

1. **Protein is a floor; calories are a band.** Undereating misses as surely as
   overeating.
2. **Nutrition extrapolates against the eating day (06:00–21:00), not the waking
   day.** Against a midnight denominator, 2,000 calories at 8pm projects to 2,535
   and gets flagged at-risk — because the model assumes four more hours of eating
   that never happen.

**`reachable` vs `at_risk`** is the distinction the whole intervention layer
rests on: a gap that fits in the meals the clock still allows is a plan; the same
gap with nowhere to put it is a fact.

---

## 10. Recent meaningful change — the reinforcement layer

`{type, occurred_at, before, after, cause, summary}`

**Derived by replay, not stored.** Because `compute` is a pure function of the
facts, "what did the day look like before lunch landed" is answered by removing
lunch and running it again. No event table, no writer, no migration — and no
possibility of stored history disagreeing with the live read, because there is no
stored history.

The clock rolls back with the facts. Replaying at the *current* hour would
compare a 2pm state against an 8pm one and blame the whole difference on the meal.

**An event that changed nothing produces no entry.** A row saying "you logged a
snack and nothing happened" is noise; this layer earns its place only by
reporting consequences.

---

## What is deliberately not built

- **Activity pace** — no step goal exists as a user setting anywhere, so the
  domain reports `unknown` rather than inventing a 10,000 nobody chose.
- **Planned workouts** — `planned_workout: null` means *unknown*, never "no
  workout today". Silence is the correct response to a session Arnie cannot see.
- **End-of-day closure (§11)** — not started.
- **The client** — Pass 2. Every section above is contract-only until iOS reads
  it.

---

## Consequence for the iOS engines

`DayProjector` and `CoachSalience` (added 2026-08-02, `Features/CoachIntelligence/`)
interpret the day **on the client**. Under this architecture that is the wrong
place: they become a second opinion the moment the server disagrees.

They should be reduced to *renderers* of `overall_state` / `domains` / `focus`,
keeping the salience → material mapping (which is a presentation concern and
belongs on the client) and dropping the projection maths (which is now the
coordinator's). The pass mark is already duplicated in both — `DayQualification`
in Swift and `qualifying_range` here — and that duplication is exactly the drift
this endpoint exists to end.
