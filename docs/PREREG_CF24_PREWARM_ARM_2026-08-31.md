# PREREGISTRATION — CF24 arm B: prehydrated candidate state

**Committed before the arm runs.** Amendments only, dated. Follows
`docs/PREREG_CF24_CONSUMER_REPLAY_2026-08-31.md`, whose arm A returned a valid
**NULL** and positively excluded `legacy.fetch_candidates` under cold state.

## The question — the incident's shape, not a favourite commit

> Can row 936's nutrition exist downstream in a **prehydrated / in-memory
> candidate** before `memory_nutrition_evidence` is invoked, such that later
> code consumes the payload without another guarded DB read?

⛔ **This arm does NOT test CF25.** Two hypotheses of equal standing came out of
arm A — **(a) missing state** and **(b) incidental removal between `a7549d7`
and `63d926a`**. Opening with (b) would anchor the experiment on the most
attractive commit rather than on the incident. **(a) is tested first.** The
commit bisect is authorised ONLY if arm B reproduces, or at least causally
separates from arm A.

## Why the shape is plausible — structural, read from the tree

`core/food_intelligence.py::analyze` seats a candidate and then reads:

```python
per100 = src.get("per100g") or {"calories": src.get("cal_100"),
                                "protein": src.get("protein_100"), ...}
```

Raw `user_food_matches` column names. So **any** candidate carrying those
attributes is converted to a priced profile **with no guard of its own** — the
trust check runs at the *reader*, and a copy made elsewhere never meets it.

On the deployed build that copy cannot arrive by the ordinary route:
`fetch_candidates` sets `m = None` when the door refuses, so
`FoodCandidates.memory` → `analyze(memory_match=…)` is already guarded. That is
consistent with arm A committing 137.

**Therefore the bypass, if it exists, needs a candidate assembled somewhere the
door does not run** — a warmed cache, a speculative/prefetch path, or a
`FoodCandidates` built before the guard. That is what this arm forces.

⚠ Recorded as CONTEXT, not as a finding: the CF25 record already ruled out
`pricing.enrichment_hit` on the grounds that its inflight cache holds
`(usda, off)` only and "touches NO DB". That ruling was made by reading, not by
executing, and this arm re-tests it rather than inheriting it.

## Arms

| arm | state | status |
|---|---|---|
| **A** | cold / `hydration=direct_read` | ✅ RUN — `telegram:9495`, NULL. Door ran, `trusted=False`, usage unmoved, 137 kcal |
| **B** | prewarmed / prehydrated candidate carrying row-936 nutrition | ⏭ this document |

Same fixture throughout: row 936, `user_id=26`, `Shrimp, grilled` 120 g.

## ⛔ REFUSAL CONDITIONS — the arm is VOID, not "no bypass found"

1. ⭐ **PREHYDRATION UNPROVEN.** If it cannot be positively demonstrated that a
   candidate carrying **row-936-derived nutrition** existed in memory *before*
   the food turn began, the arm is VOID. Not "the bypass did not fire" — the
   state under test never existed. *This is the condition this whole arm turns
   on: it is exactly the mistake of calling something a prewarm experiment when
   nothing was warm.* Proof must be an assertion on the candidate's contents
   (`cal_100 == 437.5` or `per100g.calories == 437.5`), captured before the
   turn, not inferred from timing or from a cache-hit log line.
2. Row 936 no longer exists, or is no longer poisoned/untrusted.
3. The tree under test does not contain `7fd15d9` (no instrument, no reading).
4. **Stale conversational state** — any unanswered `pending_questions` row for
   the identity at probe time. *(Added from arm A's amendment: this gap was
   found the hard way. Condition 6 of arm A covered config and missed state a
   turn both reads and mutates.)*
5. Config drift outside the declared arm.

## What is captured

`hydration` (⭐ must read `prehydrated`, not `direct_read`) · `consumer` ·
`row_id` · `trusted` · `candidate_kind` · `turn` · `operation` · `stage`;
plus **whether any consumer sees `per100g` / `cal_100` with NO corresponding
`memory_nutrition_use` event**, `times_used` before/after, and the committed
payload in full.

## BENEFIT / NULL / HARM

```text
BENEFIT   poisoned nutrition reaches settlement, OR a consumer is observed
          reading row-936 per-100g values with no corresponding trust event
          -> the bypass is reproduced and attributed. Fix at the SHARED
             BOUNDARY, never at the caller. Then, and only then, the commit
             bisect over a7549d7 -> 26af6b2 -> 7fd15d9 -> 6de3c5d -> 63d926a,
             same fixture, same prewarm, ONE tree changed at a time

NULL      prehydration is proven to have occurred and the door still refuses,
          with clean nutrition committed
          -> hypothesis (a) is WEAKENED, not disproven, and only for the
             warming path actually exercised. Do NOT tune the warm-up and
             retry as the same arm. Escalate to hypothesis (b) — the commit
             bisect — as a SEPARATE registered arm

HARM      the arm writes poisoned nutrition to a real user's log
          -> ⛔ STOP. Correct on the entry-3050 protocol: restore the ENTIRE
             evidence-owned payload, never selected fields; recompute
             `daily_logs` FROM THE ENTRIES, never by delta; ledger event
             naming this document. Characterise before designing any fix
```

## Environment

Arm B runs **locally first**, against a cloned fixture of row 936 — because
condition 1 requires *proving* prehydration, and that proof needs assertions on
in-process candidate state that production cannot give. A production replay is
authorised only if the local arm reproduces and a production confirmation is
then needed.

## What this does NOT decide

- Whether CF25 (`26af6b2`) closed the bypass. Separate arm, gated on this one.
- The **producer** defect (whatever wrote 437.5 on Aug 2) — separate, live
  fixture entry 3053 / row 1031.
- Anything about the `27983be` deploy hold.
