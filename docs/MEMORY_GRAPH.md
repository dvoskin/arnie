# Arnie Memory Graph

How Arnie holds the arc of a person's life — remembers commitments, reasons
about them, follows through, and closes the loop — so he functions like a coach
who knows you, not a chat box that answers the last message.

This is the durable architecture. Build against it; don't improvise parallel
memory stores next to it.

---

## The core idea: one typed memory graph, three slices

Everything Arnie holds about a user is a **node** with a common envelope:

    content · provenance · confidence/source · status · optional time · salience · links

Three slices of the same graph, by two axes (durability, and whether it has a
future beat that needs follow-through):

| Slice | What it is | Backing (today) | Has follow-through? |
|---|---|---|---|
| **Open loops (threads)** | Time-bound commitments to track + close | `user_threads` (this doc) | yes |
| **Knowing you** | Durable, timeless traits/facts | `user_attributes` | no |
| **How we're doing** | The relationship's own state (trust, rapport) | *(future)* | meta |

"A trip" is one row in the open-loops slice. So is "starting a cut Monday,"
"resting a shoulder," "I promised to check tonight."

---

## Open-loops taxonomy (the `kind` field)

Stored as a string, not an enum — a new coaching situation never needs a
migration.

- **event** — a dated thing happening (trip, appointment, race, deadline)
- **intention** — a stated plan ("starting a cut Monday")
- **habit** — a behavior change they're attempting ("fix breakfast")
- **constraint** — a limit with a window (injury rest, travel, illness)
- **promise** — something *Arnie* said he'd do (keeping these = trust)
- **watch_item** — a pattern to keep an eye on ("protein chronically low")
- **decision** — something they're weighing ("cut or maintain?")
- **experiment** — a trial with a review ("creatine for a month")
- **milestone** — a target in flight ("180 by fall")
- **state** — an emotional/motivation state to check back on ("burned out")
- **other** — escape hatch

---

## The lifecycle (the one spine)

    capture → surface → follow through → resolve

1. **Capture** — the model files a node via `remember_thread` when the user
   shares something durable + forward-looking (or when Arnie makes a promise).
   Rides the turn the model is already taking — no extra hot-path LLM call.
2. **Surface** — `[OPEN THREADS]` context block, every turn, top-N by
   salience × proximity (`get_open_threads`). This is where situational
   awareness comes from: the model sees the whole arc and reasons across it.
3. **Follow through** — *(Stage 2)* the proactive scheduler scans
   `(status, next_touch_at)` and nudges (day-before a trip, etc.) on the
   existing push path.
4. **Resolve** — `update_thread [#id] status=done` on report-back, or expiry.
   **Closing loops matters as much as opening them.**

---

## What keeps it scalable, stable, and truthful

These are load-bearing. Skipping them is how memory systems become noise.

**Truthful**
- **Provenance** on every node (`source`, `provenance_log_id`) — grounded in
  what the user actually said. Never confabulate a memory.
- **Stated vs inferred** (`source`) — inferred loops are surfaced as questions,
  not asserted as fact.
- **Correctable** — `update_thread` edits/closes; a wrong memory held
  confidently is the "you liar" failure at scale.

**Stable**
- **Bounded, ranked working set** — context only ever pulls top-N
  (`get_open_threads`, default 6). Unbounded memory is the #1 killer.
- **Dedup / merge on write** — `upsert_thread` merges a restated commitment
  (overlap-coefficient similarity over content words) instead of duplicating.
  This is the exact "planned the Hamptons trip twice" bug.
- **Ruthless GC** — resolve on mention, expiry (`expires_at`), staleness drop
  (`_STALE_DAYS`). A loop that never closes is clutter.

**Scalable**
- **Cheap capture** — a tool call on the existing turn, not a second LLM pass.
- **Indexed reads** — `(user_id, status)` for the per-turn read;
  `(status, next_touch_at)` for the future proactive scan.

**Relationship (not surveillance)**
- **Reference, don't perform** — "how'd the shoulder hold up?", never "per my
  records on the 8th." Enforced in the prompt + the tool result instruction.
- **Care about the arc** — `state` and `promise` kinds are what make it a
  relationship, not a task list.
- **Restraint** — *(Stage 2)* one proactive touch per loop, quiet-hours +
  frequency prefs + a global daily cap.

---

## Extend, don't duplicate (the boundary that keeps this an evolution)

`user_threads` runs **alongside** `pending_questions` and `schedule_check_in`
for now. It does **not** fork them. The direction is to fold both into this
node model over later stages (backward-compatible), so we end with ONE memory
system, not three that disagree. Any new "Arnie remembers X" work goes through
this graph — never a fourth parallel table.

---

## Staging

- **Stage 1 (this)** — spine: `user_threads` table + `upsert_thread`/queries +
  `remember_thread`/`update_thread` tools + `[OPEN THREADS]` context block +
  `MEMORY_RULES` prompt + tests. In-conversation awareness only; no proactive.
- **Stage 2** — thread-driven proactive follow-through on the existing push
  path, with the discipline guards.
- **Stage 3** — fold `pending_questions` + `schedule_check_in` in; the
  "knowing you" pillar (people, why, sensitivities) and the "how we're doing"
  pillar (trust ledger, rapport); node links; salience learning.
