# CF24 — the consumer, attributed

**Reproduced 2026-08-31** on tree `a7549d7` (the incident build), production-
equivalent runtime, subject literally 26, fresh fixture per repetition.

```
predicate  {'seq': 1, 'is_row936': True, 'trusted': False}   ← the guard RAN
seq 2-7    authority.select[branded_exact]   seated_is_row936=True
committed  525.0 kcal · P10.6 C76.6 F19.4 · sugar 4.6 · sodium 1874.4
```

Every macro is row 936's per-100g × 1.2 — `8.8→10.56`, `63.8→76.56`,
`16.2→19.44`, `1562→1874.4`. Entry 3050 committed **exactly 525** in production
on 2026-08-25.

## The attribution

> The consumer is **not** an unknown memory reader. It is the path that lets an
> untrusted memory-derived candidate enter the **authority candidate map**
> despite the shared trust decision.
>
> **The trust decision existed, returned `False`, and was not authoritative
> downstream.**

`authority.candidate_map` seated the row at `branded_exact` — its own
`origin_tier` — after `memory_nutrition_is_trusted` had already said no.

⚠ This is **not** the shape the CF25 record nominated. Its prime suspect was
`food_intelligence.analyze` reading `cal_100` off a prehydrated dict. What
actually happens is the ordinary ladder, with nothing enforcing the answer the
guard had just given.

Reproduction rate is **intermittent** — 5/6 in one session, 1/3 in another,
6/9 pooled. High enough to attribute the mechanism; too unstable to bisect
commits at three reps.

## The repair — at the boundary, not the caller

```
If memory nutrition is untrusted, no representation derived from that
nutrition may appear in an authoritative pricing candidate map.
```

`candidate_map` refuses any `memory_match` without `_trusted_memory`, whose
sole producer sits immediately after `memory_nutrition_evidence` returns
non-None. A reader that forgets the door gets its candidate **dropped**, not
silently trusted.

⛔ Deliberately not `if branded_exact`, not a food name, not "CF25's
qualification happens to reject this". Guarding `fetch_candidates` would
protect one route — and CF24's entire cost was not knowing which route was
used.

Regression: `tests/test_a_failed_trust_decision_cannot_become_pricing_authority.py`
— all four food classes, both directions, mutation-proven (restoring the old
behaviour turns 4 tests red).

## ⛔ Commit attribution ABANDONED, deliberately

Which commit incidentally closed this first is **not established and will not
be pursued**. The table is consistent with `26af6b2` and that is as far as it
can be honestly taken at this power.

```
commit    poisoned  seated  gate0fail
a7549d7     1/3      1/3     0/3      (5/6 in a prior session)
26af6b2     0/3      0/3     3/3      ← VOID under the old gate; SAFE_DECLINE now
7fd15d9     0/3      0/3     0/3
6de3c5d     0/3      0/3     0/3
4fcb31d     0/3      0/3     1/3
63d926a     0/3      0/3     1/3
```

The directive's purpose was never to name the lucky commit. It was: identify
the bypass → enforce the shared boundary → exact regression → clean production
replay. Three are done; the fourth remains.

## Gate 0, three states

`any(rungs_offered)` conflated *the ladder was never reached* (VOID) with *the
ladder was reached and seated nothing* (a RESULT — possibly the protection
working). At `26af6b2` that scored 3/3 failures while `row 936 reached` and
`trust predicate answered` both passed: **a run declared void for doing exactly
what a fix is supposed to do.**

```
HARNESS_VOID     the ladder was never reached      -> gate 0 fails
SAFE_DECLINE     reached, nothing eligible seated  -> readable
PRICING_REACHED  a candidate reached authority     -> readable
```

## Still open before closure

1. **Production replay** of the exact 3050 shape against the new invariant —
   row addressed, trust false, poisoned candidate not seated, no 525, clean
   durable outcome.
2. **`times_used` semantics.** No longer used causally. Identify which writer
   increments it and document what it measures. Production arm A: door fired,
   counter unmoved. Local: door fired, counter moved. Instrumentation
   clarification, not a tranche.

---

## `times_used` — traced, and a retraction

**One writer, and it is not a reader.**

```
db/queries.py:3891   upsert_user_food_match()          times_used = (times_used or 1) + 1
db/queries.py:3892                                     last_used  = utcnow()
db/queries.py:3765   remember_canonical_settlement()   last_used only
```

No reader increments it — not `memory_nutrition_evidence`, not the legacy
memory rung in `fetch_candidates`, not `canonical_pricing_inputs._memory`.

### What the counter actually measures

**Cache-write activity on a surface key: how many times a row was upserted.**
Not memory consumption. A row can be read and priced from repeatedly without
moving, and can move without its nutrition ever being used — the upsert fires
after any successful lookup.

That accounts for all three observations without appeal to a hidden path:

| where | door | counter | why |
|---|---|---|---|
| production arm A (`telegram:9495`) | fired | unmoved | the turn committed 137 from the interpreter's estimate (`pricing_rung=None`); no lookup hit, so no upsert. **Reads do not bump.** |
| local gate 0 | fired | 0 → 1 | a lookup DID hit, so `fetch_candidates` wrote the cache |
| the incident (18:28:06.902789) | n/a | `last_used` stamped | an **upsert** ran on that turn — not evidence that a reader touched the row |

### ⛔ THE RETRACTION

`docs/PREREG_CF24_CONSUMER_REPLAY_2026-08-31.md` (amendment 1, and the commit
message of `b7b89af`) states that the unchanged counter proves the incident
path and `legacy.fetch_candidates` are **different paths**, and calls the
counter "the load-bearing part".

**That inference is withdrawn.** The counter never tracked consumption, so an
unchanged counter says nothing about which consumer read a row — only that no
upsert occurred. A distinction was built on a signal that had not been traced,
and then leaned on.

⭐ **CF24's conclusion is unaffected.** The mechanism was attributed by
REPRODUCING it on `a7549d7` — predicate returns `False`, `candidate_map` seats
the row at `branded_exact`, 525 kcal commits with the whole payload scaled
×1.2. That evidence stands on its own and never needed the counter.

⭐ **The general lesson, which is the reason this is written down rather than
quietly fixed:** the counter was used as a discriminator for two days before
anyone asked what it counted. It was plausible, it correlated, and it was
available — and none of those is provenance. *A signal is not evidence until
its writer is known.*

### Standing rule for this counter

Do not cite `times_used` or `last_used` as evidence that memory nutrition was
CONSUMED. They are cache-write bookkeeping. The question "was this row's
nutrition used to price a meal" is answered by `event=memory_nutrition_use`
and by the settled entry's `pricing_rung` / `nutrition_evidence_id` — never by
the counter.

---

# ✅ CF24 — CLOSED, 2026-08-31

Closed on the terms actually available, each stated with the evidence that
supports it and no more.

| | status | evidence |
|---|---|---|
| **Mechanism** | CLOSED | Reproduced on `a7549d7` under production-equivalent runtime, subject 26, fresh fixture: trust returns `False`, `authority.candidate_map` seats the untrusted payload at `branded_exact`, 525 kcal commits with the whole row scaled ×1.2. Entry 3050's exact number. |
| **Primary containment** | CLOSED / production-proven | `fetch_candidates` nulls the memory candidate after trust refusal. TWO controlled Telegram replays on user 26 (`telegram:9495` on `63d926a`, `telegram:9521` on `09b8882`) both committed **137 kcal clean**, `pricing.memory` consulted, row 936 untouched. |
| **Boundary backstop** | CLOSED / mechanically proven | `candidate_map` refuses memory-derived nutrition without proof the trust decision accepted it. Mutation restoring the historical behaviour turns **4 regressions red** across all four food classes. |
| **`times_used`** | CLOSED as an observability correction | One writer, `upsert_user_food_match`. Measures cache upserts, not consumption. The consumer-path inference built on it is **retracted**. |

## ⛔ THE CLOSURE CRITERION THAT WAS IMPOSSIBLE, AND WHY IT WAS DROPPED

I claimed `event=memory_candidate_refused` in production would be the line
distinguishing "the new boundary refused it" from "the old null-out did the
work". **It cannot be**, and I should have traced my own guard's reachability
before saying so:

```
fetch_candidates:   if door(...) is None:  m = None
                    if m is not None:  memory = {...}      ← dict built only here
candidate_map:      if memory_match is not None and not ..._trusted_memory:  refuse
```

On the ordinary path `candidate_map` receives `None`, so the guard is **never
reached**. Its absence from the logs is correct behaviour.

⭐ **The backstop is unreachable in production unless the upstream containment
fails** — so requiring a live backstop hit would be a closure criterion that
can never be met while the system is working. A guard's proof is that it goes
red when the behaviour it forbids is restored, and that proof exists.

## What each layer is actually worth

- **Containment** stops the defect today, and is production-proven.
- **The backstop** stops it returning through a reader nobody has written yet —
  which was CF24's entire cost: three weeks of not knowing *which* reader.
- Neither is a claim about the **producer** defect (whatever wrote 437.5 on
  2026-08-02). That stays separate, with its own live fixture, entry 3053 /
  row 1031.

## ⛔ NO FURTHER MEMORY ARCHAEOLOGY IS AUTHORIZED

Row 936 stays in place at `cal_100=437.5`, untrusted and inert. No cleanup, no
backfill, no heuristic trust restoration. What would justify reopening is a NEW
production incident of this shape — not curiosity about which commit
incidentally closed it first, which is explicitly abandoned.
