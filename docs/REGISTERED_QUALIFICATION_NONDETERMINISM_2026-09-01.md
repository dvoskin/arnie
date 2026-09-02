# REGISTERED — qualification nondeterminism across repetitions

**Observed 2026-09-01, during the Phase 2A 25-identity preload probe.**
Registered as its own finding so it cannot disappear into an aggregate rate.

## THE OBSERVATION

`american cheese` **refused** `ACQUIRE_IDENTITY_UNQUALIFIED` inside the batch,
then **succeeded** on an immediate standalone retry: `raw=9, kept=2`.

Same identity. Same producer. Same code. Different outcome.

    same query + same candidate population -> qualification changed across
    repetitions

## WHY IT IS REGISTERED SEPARATELY

It is **not** the FNDDS coverage gap. `apple juice` failed for a nameable,
reproducible reason — the authoritative record lived in a dataset the source
filter excluded. This one has no such explanation, and lumping the two together
would let a reproducibility defect vanish inside "the preload rate improved".

⛔ **Authority is not at risk here; REPRODUCIBILITY is.** Both outcomes are safe:
a refusal loads nothing, and an acceptance loads qualified evidence. What is
unsafe is a bulk preload whose output depends on when a row happened to be
processed — the same 328 identities could produce materially different coverage
on two consecutive runs, and no diff would explain why.

## CANDIDATE CAUSES — NOT YET DISTINGUISHED

- resolver model nondeterminism on a borderline identity
- a truncated reply caught by `_QUALIFY_ATTEMPTS` retry on one run and not the
  other (`build_one` treats truncation as a property of the reply, not the food)
- transient provider behaviour changing the candidate set between runs, so the
  question genuinely differed
- ⭐ concurrency: chunks now qualify in parallel, so a batch's chunk boundaries
  can differ from a standalone call's — a DIFFERENT PARTITION of the same rows
  is a different set of questions

The last is specific to the change shipped in `f623fb0` and is the one worth
eliminating first, because it is mechanical rather than statistical.

## MEASUREMENT OWED

Run one identity population **twice** under identical config and diff:
acquired set, refusal reasons, raw and qualified candidate counts. Report the
disagreement rate. A nonzero rate is a reproducibility bound on every preload
number, and must be stated alongside them.

## NOT BLOCKING

Phase 2A proceeds. This is registered, not deferred silently — the preload's
reported coverage carries an unmeasured reproducibility error bar until the
above is run.

---

## CONFIRMED 2026-09-01 — genuine resolver nondeterminism

The batch-vs-standalone comparison could not have proved this: those may be
different questions. So the test was the same question, repeated.

```
FIXED POPULATION 'american cheese': 9 rows, all reaching the resolver
fresh EvidenceContext per run

run 1  qualified=[]          run 3  qualified=['747429']
run 2  qualified=[]          run 4  qualified=[]
        -> 2 distinct outcomes across 4 repetitions
```

⛔ **Same identity, same rows, same order, same code, same config.** The
variance is in the resolver itself — not partitioning, not context reuse, not
provider row drift. The concurrency suspect from `f623fb0` is ELIMINATED.

⭐ **AUTHORITY IS SAFE; REPRODUCIBILITY IS NOT.** Both outcomes are defensible —
qualifying a valid row, or qualifying nothing — so no wrong nutrition can enter
this way. But the same identity population can yield materially different
coverage on consecutive runs, and no diff explains why.

**CONSEQUENCE FOR PHASE 2A — STATED PRECISELY.** The correct claim is:

    Resolver nondeterminism is CONFIRMED on at least one borderline identity.
    Prevalence and probability remain UNMEASURED.

⛔ NOT "a ~1-in-4 error rate". One alternate result across four repetitions on
ONE identity is evidence of EXISTENCE, not a population rate — the sample is a
single hand-picked borderline case, chosen precisely because it had already
behaved oddly, and four draws bound nothing. Carrying "1 in 4" into the
ownership result would overstate what this experiment established, which is the
same class of error as every instrument defect this project has found: a number
right about its arithmetic and wrong about its subject.

So a re-run of the same 328 must not be read as regression or improvement
without a MEASURED bound — and that measurement (one population, twice,
diffed) has not been run.

**NOT BLOCKING.** The 328 preload proceeds. Fixing this means making a
borderline qualification decision stable, which is a producer-design question,
not a bug with a patch.
