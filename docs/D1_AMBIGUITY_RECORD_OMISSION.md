# D1 — AMBIGUITY RECORD OMISSION

**Opened 2026-08-27. SEPARATE from D2 by explicit instruction — and the
separation is the point.**

> **Exit: every ask-producing path emits at least one structured ambiguity when
> an unresolved semantic subject exists.**

## The defect

**5 of 18 asks carried ZERO ambiguity records** (`producer_characterisation_
2026-08-27.jsonl`). Every one was case 2 or case 3:

```
c2  "The little cheeseburger and fries, did you finish both, or leave some?"   n_amb=0
c3  "For the Orange Chicken, was that one scoop or two?"                       n_amb=0
c3  "regular entree scoop or did you double it?"                              n_amb=0
```

The question is asked with **nothing structured behind it**. The prompt's own
rule — *"ONE UNKNOWN, ONE ENTRY... nothing may appear in one and not the
other"* — is being violated: a question exists in `points` with no
`ambiguities` entry.

## ⛔⛔⛔ WHY THIS MUST NOT BE FOLDED INTO D2

**A path that emits nothing still bypasses the entire contract, however rich
the vocabulary becomes.** Extending the field vocabulary (D2) cannot repair an
absent record, and — the real hazard — **fixing D2 must not be allowed to make
D1 look solved.** If the vocabulary work lifts overall coverage, a residual
zero-record path is easy to mistake for noise.

Confirmed empirically: after the D2 prompt exception, c2 rep1 still emits
`n_amb=0`. The vocabulary changed; the omission did not.

## Not started

No repair proposed. The first question is whether the omission is a distinct
ask-return path (several of the 7 sites build a question without an
interpreter ambiguity) or an interpreter behaviour on these utterances.

---

# ATTRIBUTION — from data already on disk, zero model turns

53 asks pooled across the three characterisation runs; **19 zero-record.**
Discriminator: was `_ask_types_from` **called with an empty list** (an
interpreter-backed site ran and got nothing) or **never called** (a hardcoded
site, or a producer outside `food_turn`'s seven ask sites)?

| population | n | cases | signature |
|---|---:|---|---|
| **A — CALLED, `n_amb=0`** | **14** | **2, 3 only** | interpreter returned an ask with ZERO ambiguities |
| B — NEVER called | 5 | 1, 9 only | `ask_types=[]` |

## ⛔ POPULATION B IS AN INSTRUMENT ARTIFACT, NOT A DEFECT

Pending-question `kind` settles it:

```
food_structured_ask   ask_types present  24/24   <- the structured lane is 100% TYPED
conversation_hook     ask_types present   0/2    <- NOT a food clarification at all
food_clarification    ask_types present   0/1    <- the TOOL path
```

`c1 rep2` is a **`conversation_hook`** — a general conversational follow-up the
harness counted as a food ask. The one `food_clarification` is the
`note_food_clarification` tool path, which records no `ask_types` **by my own
choice**: that payload write was reverted to avoid raising the
pending-mutation ratchet. A known, documented coverage hole — not an omission
defect.

⭐ **D1's real size is 14 of 19, cases 2 and 3 only.** The instrument inflated
it by counting non-food asks.

## The answer to the diagnostic question

> *If cases 2 and 3 concentrate on the acquisition/split-refusal sites, D1 is
> probably a plain code-path omission and the model may not need to change.*

**They do not.** Neither hardcoded site fired — `6533` writes
`['consumption_complete']` and `6497` writes `['unclassified']`; we observed
`[]`. Every case-2/3 zero-record ask **called the helper and received an empty
list**, so an interpreter-backed site ran and the interpreter produced
`action:ask` with `points` and no `ambiguities`.

> ⛔ **D1 DOES NOT COLLAPSE INTO A DETERMINISTIC CODE FIX. It is
> interpreter-output.**

## ⭐ AN ATTRACTIVE HYPOTHESIS, ALREADY FALSIFIED

*"The interpreter omitted the record because it had no valid field name for
consumption or multiplier."* Tempting — cases 2 and 3 are exactly the two
subjects the vocabulary lacked, which would have made D1 and D2 one defect.

**The post-exception runs refute it.** Both field values were added and **c2
still emitted zero records on 5/5 of its asks.** The omission is independent of
vocabulary availability. D1 and D2 remain genuinely separate.

## What D1 actually is

A **compliance failure against a rule the prompt already states**:

> *"ONE UNKNOWN, ONE ENTRY. Every question you put in `points` must have its own
> entry in `ambiguities` naming the same field, and nothing may appear in one
> and not the other."*

The instruction exists and is explicit. The model ignores it on two specific
utterance shapes — Five Guys (consumption) and Panda Bigger Plate (multiplier) —
**c2 7/8 and c3 7/9 of their asks.** So *adding a rule* is unlikely to be the
repair: the rule is there and is being violated deterministically by case.

⚠ **Not yet investigated:** whether these two utterances share a structural
property that routes them past the rule, or whether the model treats a
consumption/multiplier question as not-an-ambiguity by nature. That is D1's
first real question, and it is NOT answerable from data on disk.

---

# MINIMAL-PAIR DISCRIMINATION — round 1: FORM implicated, SEMANTICS untested

8 cases × 3 reps = 24 turns.
Raw: `data/corpus/d1_minimal_pairs_result_2026-08-27.jsonl`.

**Controls healthy** — c207 `[3,3,3]`, c208 `[2,1,3]`, both 3/3 emitting.

## FORM AXIS — a real effect

```
c3  ORIGINAL   "Bigger Plate: X, Y, and Z"         zero-record 7/9
c204 staccato  "Panda Express, bigger plate.       zero-record 0/3   n_amb [2,2,2]
                Orange chicken. Teriyaki..."

c2  ORIGINAL   "Five Guys Little Cheeseburger      zero-record 7/8
                and a small fries"
c201 past prose                                     zero-record 1/3   n_amb [1,1,0]
c202 bare list                                      zero-record 2/3   n_amb [1,0,0]
```

Same meaning, different shape, and **c3's omission disappears entirely.** Form
is implicated. It does NOT fully explain c2 — reshaping improves 7/8 to 1/3 and
2/3 without eliminating it. And it is not "lists are bad": c202 is a list and
mostly omits; c204 is staccato and never omits.

## ⛔ THE SEMANTIC AXIS WAS NOT TESTED — DESIGN FAILURE

**Both held-out semantic probes never asked.** c203 logged 0/3, c206 logged
0/3. **A turn that logs produces no evidence about ambiguity omission**, so six
turns returned nothing.

⭐ **I selected those utterances for their SEMANTICS without verifying they
reliably ELICIT AN ASK** — the one property the experiment required. A probe
that cannot reach the behaviour under test is an instrument that cannot fail,
the same class as a guard whose protected input never occurs.

c205 is the single semantic datapoint: it emitted records (0/2 zero-record) but
its fields were `prep` + `quantity`, **not `multiplier`** — consistent with c20
for `consumed`. Records exist; the subject still is not selected.

## Verdict

Closest to *"neither axis separates cleanly"*, with form carrying a real signal
and semantics **unmeasured rather than excluded**. Whether c2's residual
omission is semantic or another structural property is still open.

---

# ROUND 2 (semantic arm) — **THE BASELINE DID NOT REPRODUCE**

Raw: `data/corpus/d1_semantic_arm_result_2026-08-27.jsonl`.

```
c303  c2 VERBATIM   asked 1/3   zero-record 0/1   n_amb [1,0,0]   history 7/8
c304  c3 VERBATIM   asked 2/3   zero-record 0/2   n_amb [0,2,2]   history 7/9
c305  CONTROL c16   asked 3/3   zero-record 0/3   n_amb [3,3,3]   ✅
```

**The originals emitted ambiguities every time they asked.** With no signal on
the "originals omit" side, nothing can be attributed to form or semantics —
c302 emitting 3/3 means nothing when c304 emits too. c301 never asked (0/3):
**probe selection failed a second time.**

## ⛔⛔⛔ I RAN THREE DISCRIMINATION ROUNDS AGAINST A DEFECT WHOSE BASE RATE WAS NEVER ESTABLISHED

D1's 14/19 came from three runs. A fourth shows 0/3. Three asks cannot declare
the defect gone — but they are enough to say **the base rate was never
measured**, and every minimal-pair comparison presumed it.

## ⛔⛔ AND THE HARNESS HAD NO CONFIG PINNING

`sweep_case_stability.py` refuses to run under an unpinned configuration and
records the resolved config in its output. **`characterise_ask_producer.py` was
written from scratch WITHOUT that guard, and four experiments ran through it.**

So the baseline's failure to reproduce **cannot be attributed to variance
rather than configuration** — no run recorded its own config.

⭐ Having spent the same day proving that unpinned configuration silently
reverses conclusions, I built a second harness without the protection. **The
guard now lives in ONE place — `scripts/config_pin.py` — that every harness
imports**, because a rule enforced in one harness is a rule the next harness
will be written without.

## Corrected sequence

```
1. ✅ ONE shared config guard; both harnesses pinned, config in the output
2.    D1 BASE RATE — c2 / c3 verbatim + control, n=8, pinned
3.    resume discrimination ONLY if the defect reproduces
```

---

# BASE RATE — **D1 SURVIVES**

First run under a fully pinned harness. `tree=469f7e4` (clean), `gate=true`,
`resolver=live`, `model=claude-sonnet-4-6`, config and SHA in the output header.
Raw: `data/corpus/d1_base_rate_result_2026-08-27.jsonl`.

```
CONTROL c16      asked 8/8   zero-record 0/8   n_amb [3,3,3,3,3,3,3,3]   ✅
c2 Five Guys     asked 8/8   zero-record 5/8   -> REPRODUCES
c3 Panda Plate   asked 5/8   zero-record 3/5   -> REPRODUCES
```

## The rule was mechanical, not a judgement call

Derived from the CONTROL, not the subjects: the control had emitted on 12/12
asks historically, and by the **rule of three** the 95 % upper bound on a rate
observed as 0/12 is 25 %. Over 8 asks that is 2. Hence **≥3 reproduces, ≤2 does
not, <4 asks is under-powered**, plus a void condition if the control itself
ever shows a zero-record ask.

⚠ **Honest limit on the preregistration.** The 24 turns had finished before the
numeric threshold was written to disk. The counts were not read — only the
progress line — but that cannot be proved. The mitigating fact is that the
threshold is anchored to the control's HISTORICAL 0/12 from earlier runs, not
to anything in this run.

## Round 2's non-reproduction is explained by sample size

At a true rate near 60 %, three consecutive non-omissions has probability
≈ 6 %. Uncommon, not extraordinary. **A three-ask sample was over-read as a
failure to reproduce** — the same small-n error as the rest of the day, in the
opposite direction. No configuration difference need be invoked.

## Measured prevalence

**c2 ≈ 5/8, c3 ≈ 3/5**, against a control of **0/8**. Lower than the pooled
historical ~78 %, and unambiguously above zero.

## ⛔ NOTHING FURTHER IS CLAIMED

Per the frozen rule, the only legitimate output here is the verdict. **No
cause. No policy. No minimal-pair interpretation.** Rounds 1–2 remain VOID —
their in-run baseline failed and they were not config-pinned, so their form,
semantic and chain comparisons are not weak evidence, they are no evidence.

**D1 survives. The right to ask WHY is now earned, and discrimination may
resume — from a measured base rate, on a pinned harness.**
