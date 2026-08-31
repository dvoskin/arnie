# PREREGISTRATION — CF24 consumer replay (row 936)

**Written and committed BEFORE the probe runs.** Prediction and readings are
frozen here; nothing below may be edited after the turn executes. Amendments
only, dated.

## The question

> Which named consumer receives or attempts to convert **row 936**'s nutrition
> into pricing evidence?

Not "does it log 119 instead of 525". The calorie number is **secondary
evidence**. The deliverable is the `consumer=` field.

## Target — resolved from production, not improvised

```
user_food_matches.id = 936        user_id = 26        name_norm 'grilled shrimp'
cal_100 437.5   P8.8  C63.8  F16.2  sugar 3.8  sodium 1562
origin_tier 'branded_exact'   confidence 'exact'   user_confirmed False
settled_by_operation_id NULL · settled_basis NULL · settled_evidence_id NULL
      -> UNTRUSTED (trust is a resolved link to meal_commits; NULL cannot resolve)
times_used 2      last_used 2026-08-25 18:28:06.902789
```

`last_used` is stamped to **the exact instant entry 3050 committed 525 kcal**
— the 1.2x image of 437.5.

**Identity**: row 936 is `user_id=26`, the same identity that produced entry
3050. No synthetic user. **Channel**: entry 3050's turn was `telegram:9406`,
`channel='telegram'` — so the replay goes through **Telegram**, not iOS.
(The Aug-2 *producer* entry 2687 was iOS; producer and consumer used different
entrypoints, which is itself why channel is pinned here.)

**Probe utterance**, matching the original meal shape: `Shrimp, grilled` at
**120 g**.

## ⭐ Instrument liveness — already established, not assumed

Three `memory_nutrition_use` events exist in production (08-20 → 09-01), and
one of them is **row 936 itself**:

```
08-26 00:25  row_id=886  'cucumber'        trusted=False  consumer=legacy.fetch_candidates
08-26 00:50  row_id=936  'grilled shrimp'  trusted=False  consumer=legacy.fetch_candidates
08-26 01:06  row_id=292  'banana'          trusted=False  consumer=legacy.fetch_candidates
                          candidate_kind=legacy_memory_candidate  hydration=direct_read
```

So a future "no event" means **the consumer did not execute**, not that the
instrument failed to observe. That leg is closed before the run.

## ⛔ Why the historical absence proves nothing

There is **no** `memory_nutrition_use` event at 18:28:06 on 08-25. That is
NOT evidence of an uninstrumented path: `7fd15d9` (the instrumentation) was
committed 08-25 **15:25**, and the build running at 18:28 was `a7549d72fbfb`,
merged **13:57**. **The instrument was not deployed during the incident.**
Recorded so nobody later reads that silence as a finding.

## ⭐ The second observable — the usage counter

The 08-26 00:50 read through `legacy.fetch_candidates` did **not** move
`times_used` or `last_used`. Something at 18:28:06 **did**.

So the incident path **updates usage counters** and `legacy.fetch_candidates`
**does not** — evidence they are different paths. `times_used` is therefore
captured before and after, and crossed with the log reading:

| usage moves? | event fires? | reading |
|---|---|---|
| no | no | ⛔ **VOID** — the probe never reached the row |
| no | yes | the door ran; the incident path did not |
| **yes** | no | ⭐ the incident path ran and is **still uninstrumented** |
| yes | yes | the door ran on the incident path — read `consumer=` |

## The four prescribed readings (from `docs/CF25_...`, verbatim)

- event fires, `trusted=False`, and **525 commits** → the check runs and is
  **ignored after conversion**
- event fires with `trusted=True` → the defect is in **trust derivation or
  stale hydration**
- **no event** and 525 commits → an **uninstrumented conversion path** remains
- ~110–120 commits → depends on speculative/prewarm state or a one-turn race;
  the canary must be repeated under that state

## Captured, minimum

`row_id` · `trusted` · `consumer` · `candidate_kind` · `hydration` · `turn` ·
`operation` · `stage`; plus `times_used`/`last_used` before and after, the
committed entry (calories and full macro payload), `pricing_rung`,
`nutrition_evidence_id`, and the turn's `build_sha`.

## ⛔ Refusal conditions — VOID, not "the consumer didn't fire"

1. row 936 no longer exists, or its payload is no longer the poisoned one
2. `settled_by_operation_id` is non-NULL (the row became trusted)
3. the deployed build does not contain `7fd15d9`
4. `memory_nutrition_use` is not demonstrably live before the run
5. identity or channel differ from entry 3050's (`user 26`, `telegram`)
6. any unrelated config change is introduced in the same window
7. `times_used` does not move AND no event fires — the probe did not reach

A proof afterwards that the run was *probably* fine does not rescue it.

## BENEFIT / NULL / HARM

```text
BENEFIT   a named consumer is attributed to row 936's conversion
          -> proceed to the SHARED-BOUNDARY fix. ⛔ Never a caller patch:
             `if consumer == X: reject` is forbidden by the frozen closure

NULL      the row is not reached, or is reached and correctly refused with
          nothing anomalous committed
          -> NO conclusion about the bypass. Do not tune, do not re-word the
             probe and retry as if it were the same experiment. Re-run only
             under the speculative/prewarm state the fourth reading names,
             and register that as a separate arm

HARM      the probe REPRODUCES a poisoned commit (~525 kcal, or any per-100g
          reconstruction of 437.5) on a real user's log
          -> ⛔ STOP. Correct immediately per the entry-3050 protocol:
             restore the ENTIRE evidence-owned nutrition payload, never
             selected fields (the first 3050 repair fixed calories and left
             sugar and sodium carrying the other food's profile, and a later
             edit dutifully scaled them). Recompute `daily_logs` FROM THE
             ENTRIES, never by applying a delta. Write a ledger event naming
             this preregistration. Then characterise before designing a fix.
```

## What this does NOT decide

- The **producer** defect (whatever wrote 437.5 on Aug 2) — separate, live
  fixture entry 3053 / row 1031, explicitly not conflated with CF24.
- Whether row 936 should be cleaned up. It stays. The standing CF23
  instruction is not to modify rows, and it is inert while untrusted.
- Anything about the deploy hold on `27983be`. The eventual hotfix is cut from
  the **deployed lineage** (`63d926a`), not from development HEAD.

---

## AMENDMENT 1 — 2026-08-31, two runs: one VOID, one valid NULL

**The prediction and readings above are unchanged.** Nothing here edits them.

### Run A — `telegram:9491`, 16:15:53 — ⛔ VOID

```
route=structured_ask   disposition=ask   stopped_at=clarify   mode=strict
row 936   times_used 2 -> 2   last_used UNCHANGED
memory_nutrition_use   0 events
committed              nothing
```

**Refusal condition 7 fired**: usage did not move AND no event fired → the
probe never reached the row. Pricing never ran; the turn stopped at
clarification. Arnie asked *"was it just grilled plain, or was there oil or
butter in the pan?"* — an OILS question, and its own estimate was **137**, a
clean plain-shrimp figure, not 525.

⚠ **A GAP IN MY OWN REFUSAL CONDITIONS.** Pending question **2213**
(*"Got chicken breast so far. Grilled, baked, or fried?"*, created 08-26 17:21)
was still OPEN when the probe arrived, and was stamped
`answered_at = 16:15:47.401` — three milliseconds before the new question was
created at `16:15:47.404`. The reply was correctly about shrimp, so the probe
does not appear to have been mis-consumed as the chicken answer, but *"does not
appear to"* is not a control.

Condition 6 covered **config**. It did not cover **stale conversational
state**, which is prior state the turn reads and mutates. Any future arm must
require: no unanswered `pending_questions` row for the identity at probe time.

### Run B — `telegram:9495`, 16:17:58 — VALID, outcome **NULL**

```
16:17:58  event=memory_nutrition_use row_id=936 key='grilled shrimp' trusted=False
          consumer=legacy.fetch_candidates candidate_kind=legacy_memory_candidate
          hydration=direct_read turn=telegram:9495
16:17:58  event=legacy_memory_untrusted key='grilled shrimp' reason=no_provenance

entry 3067  'Shrimp, grilled plain'  137 kcal  P29 C1 F2
row 936     times_used 2 -> 2   last_used UNCHANGED   cal_100 still 437.5
```

2x2 → **usage did not move + event fired** = *the door ran; the incident path
did not.*

```text
BENEFIT   not observed. A consumer is NAMED, but it is the KNOWN, instrumented,
          correctly-refusing one. `legacy.fetch_candidates` is not what priced
          entry 3050 — and the usage counter proves they are different paths:
          this read left times_used at 2, while something at 18:28:06 moved it.
NULL      ⭐ OBSERVED. Row reached, correctly refused on `no_provenance`,
          nothing anomalous committed.
HARM      not observed. The log is clean; no correction was required.
```

**Action bound by NULL, and taken:** no tuning, no re-wording the probe and
retrying it as the same experiment. CF24 stays **OPEN**.

### Which prescribed reading applies

The fourth: *"~110-120 commits → the incident depends on speculative/prewarm
state or a one-turn race, and the canary must be repeated under that state."*
137 sits in that band. **That is a separate registered arm, not a retry.**

### ⚠ A LEAD, EXPLICITLY NOT A FINDING

Four commits between the incident build `a7549d7` and the deployed `63d926a`
touch memory reads or pricing:

```
26af6b2  CF25: identity before authority in the branded lane
7fd15d9  CF24 instrumentation: one door from a stored row to pricing evidence
6de3c5d  CF26: pre-settlement cache writes may not store nutrition
4fcb31d  CF26 review fix: the public writer may not touch micros either
```

**`26af6b2` is the obvious candidate**: row 936 is `origin_tier='branded_exact'`
and the incident was a branded snack winning a plain-food query — exactly what
"identity before authority in the branded lane" addresses.

If so, CF24's consumer was closed incidentally by a fix made for a different
defect, and nobody knows it. ⛔ **That is a hypothesis and must not be
retrofitted onto this run.** It needs its own arm with its own prediction —
and the honest test is a MUTATION: revert `26af6b2` in a local replay of entry
3050's exact production item and see whether 525 returns. A fix nobody can show
going red is a fix nobody has.

### Instrument note

Liveness was established *before* the run and held *during* it: the door
emitted on row 936 on both 08-26 and today. A future "no event" for this row
means the consumer did not execute.

### ⭐ THE FOUR RECORDED CONCLUSIONS — stated explicitly, per Danny 2026-08-31

*Appended to this amendment before any next arm was opened. Two of these were
implicit in the prose above; implicit is not recorded.*

**1. The probe is VALID / NULL. Not PASS, not FAIL.**
It ran, it reached its target, its instrument observed, and it produced no
conclusion about the thing it was built to find. That is a legitimate third
verdict and must not be softened into either of the other two.

**2. `legacy.fetch_candidates` is POSITIVELY EXCLUDED as the historical bypass
— under this state.**
Not "unlikely", not "probably not". It was observed doing the opposite of what
a bypass does:

```
reached row 936          yes — event names row_id=936, key='grilled shrimp'
instrument observed      yes — liveness held before and during
trusted                  False
shared boundary          REFUSED, reason=no_provenance
usage counter            did NOT move (2 -> 2)
committed nutrition      clean — 137 kcal, not 525
```

The usage counter is the load-bearing part: something at 18:28:06 moved
`times_used`, and this consumer demonstrably does not. **They are different
paths.** The exclusion is scoped to the state actually tested — cold,
direct-read, no prewarm.

**3. The historical incident remains UNEXPLAINED. No consumer attribution claim
may be made from this run.**
Entry 3050's 525 kcal is still unattributed. Nothing in this run names the path
that produced it. Any document, commit message or board line asserting an
attributed consumer for CF24 is wrong until a separate arm earns it.

**4. New hypothesis, registered SEPARATELY and not yet tested.** Either:

- **(a) missing state** — the 3050 failure required conditions absent from a
  controlled replay: prewarm, prehydration, or a one-turn race; **or**
- **(b) incidental removal** — the relevant bypass was removed between
  `a7549d7` and `63d926a` by a change made for a different defect.

⛔ **(a) and (b) are alternatives of equal standing here.** Naming a favourite
commit for (b) before testing (a) would anchor the next experiment on the most
attractive candidate rather than on the incident's own shape.
