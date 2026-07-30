# Phase 6 baseline — the writers that create no turn (I1, I11, I16)

**Measured 2026-07-30 20:00 UTC, 7-day window, production, read-only.**
Build live: `d43fd83cc821` (`/health`).

These are the starting numbers for the next phase. They are not from the 18-hour
master-audit window — several differ from it materially, and where they do, the
7-day number is the one to plan against.

---

## I16 · The join Phase 1 built, verified on traffic

```
461 / 495 operations resolve to a turn   (93%)
```

The master audit §9 said flatly: *"There is no reliable join between a turn and
its operations."* There is now, and this is its coverage. **Phase 1 is
`DEPLOYED` and confirmed by production**, not by a migration count.

The remaining 7% (34 operations) is the Phase 6 target, and §I1 below is why.

## I1 · Turns that carry no reasoning at all

| source_type | turns | no `reasoning_json` |
|---|---:|---:|
| ios | 595 | 0 |
| **proactive** | **79** | **79 (100%)** |
| **dashboard_edit** | **35** | **35 (100%)** |
| **text** | **16** | **16 (100%)** |
| photo | 18 | 0 |
| voice | 10 | 1 |

**130 turns in 7 days are invisible to every audit query in this repository** —
they carry no route, no owner, no build stamp, no flags. Three whole surfaces,
not a sampling gap.

Two corrections to the master audit:

- It found **8** such turns and named `dashboard_edit` and `proactive`. At 7-day
  scale it is **130**, and there is a **third surface it did not name: `text`**
  (16 turns, 100% unreasoned).
- Its §1 framing — "writes that never create a canonical turn" — is now
  measurable as its own quantity rather than inferred from a missing column.

## I11 · The legacy escape is worse than the audit's number

```
198 / 504 ledger events legacy-sourced   (39%)
```

The master audit measured **25%** on its 18-hour window and the 07-29 audit
measured **37.8%**. The 7-day figure is 39%. **The 25% was a favourable window,
not an improvement** — the same class of error as the "62 duplicate pendings"
claim that this project already had to correct once. Plan against 39%, and
treat any single-window improvement as unproven until a 7-day number agrees.

By source:

| source | events | no `turn_id` |
|---|---:|---:|
| `structured_food:food_interpreter_v2` | 263 | 4 |
| `legacy:ios` | 132 | 5 |
| `legacy` | 66 | 0 |
| `ios_edit` | 28 | 0 |
| `structured_food:confirm_replay` | 12 | 0 |
| `ledger_undo:v1` | 3 | 0 |
| **total** | **504** | **9 (2%)** |

Only 9 events carry no `turn_id` whatsoever, which is the good news inside the
bad: the write path is nearly fully identified. The gap is not that operations
are anonymous — it is that **130 turns were never created for them to point
at**, and that 39% of writes still arrive through a legacy source label rather
than a typed adapter.

## What this makes the next phase

The three violations are one cause with one fix: a write boundary that creates
the canonical turn. Ordering follows the size of the hole —

1. `proactive` (79 turns) — biggest, and entirely un-audited today.
2. `dashboard_edit` (35) — also the I9 second-reconciler surface.
3. `text` (16) — not previously named; establish what it even is first.
4. `api/quick_log.py` — no turn identity references at all in the file; the
   double-writer, now masked by `ledgerdedup001`'s unique index.

Re-run this exact file's queries after each surface lands. The success
condition is `no_reasoning = 0` per surface and the I16 join climbing from 93%,
**not** a green suite.

## Method note

`GET https://arnie.onrender.com/health` reports the live commit, branch and
effective flags with no token and no traffic. It closes the master audit's
Unknown #1 outright. Use it first in every future audit; marker inference is
only for what it does not carry.
