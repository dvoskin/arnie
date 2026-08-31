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
