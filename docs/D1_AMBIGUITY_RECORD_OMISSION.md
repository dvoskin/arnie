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

---

# ⭐⭐⭐ CAUSAL ROUND 1 — **SEPARATION ACHIEVED**

`code=0a4099d` · gate=true · resolver=live · model=claude-sonnet-4-6 ·
24 turns · 0 errors. Predictions frozen at `63952e2` **before any turn**.
Raw: `data/corpus/d1_causal_round1_result_2026-08-27.jsonl`.

```
BASELINE  "Five Guys Little Cheeseburger and a small fries"  zero-record 6/7  n_amb [0,0,1,0,0,0,0,0]
TEST      "Five Guys Little Cheeseburger and fries"          zero-record 0/8  n_amb [1,1,1,1,1,1,1,1]
CONTROL   "8 oz sirloin, a loaded baked potato, Caesar"      zero-record 0/8  n_amb [3,3,3,3,3,3,3,3]
```

**The baseline reproduced its defect** (6/7, consistent with the 5/8 base rate
from `469f7e4`). **The test arm eliminated it** — a structured record on every
one of eight asks. **The control was untouched.** One variable: two words.

## The verdict, and only the verdict

> **The SECONDARY component's vague stated size word is causally implicated in
> D1 omission.**

Mechanism this supports: *"a small fries"* reads to the interpreter as a size
already STATED, so it records no quantity ambiguity — while still asking about
it in prose, because it knows the size is not really pinned. That produces
exactly D1's signature: a question in `points`, nothing in `ambiguities`.
Remove the word and the size is genuinely open, so the record appears.

## ⛔ WHAT DOES **NOT** FOLLOW

- **No brand or SKU conclusion.** Brand was held fixed by design and remains
  confounded in all prior data.
- **No policy, DEFAULTABILITY or prompt conclusion.**
- **c3 was not in this round.** Whether Panda's *"Bigger Plate"* omission has
  the same cause is untested.
- **Only the SECONDARY component was manipulated.** Whether a vague size word
  on the PRIMARY behaves the same way is untested.
- **One utterance family, one chain.** Generality is unmeasured.

## Why this result is interpretable when four earlier rounds were not

```
pinned config      gate/resolver/model resolved and recorded in the output
clean code SHA     0a4099d, no dirty marker, compared not asserted
eligible probes    all three qualified on THAT code state before turn 1
same-run control   clean 0/8 — proves the harness could see healthy behaviour
one variable       "and a small fries" -> "and fries"
frozen prediction  committed before any turn, threshold mechanical
```

⭐ **Every one of those five was violated at least once earlier today, and each
violation produced either a void arm or a reversed conclusion.**

**Per the contract: STOP ON FIRST SEPARATION.** Do not layer further variables
into this round. The next experiment discriminates between the remaining
explanations — starting with whether c3 shares the mechanism.

---

# CAUSAL ROUND 2 — **c3 IS A DIFFERENT SUBTYPE**

Same `code=0a4099d`, same config, same control as round 1 — so the two rounds
are directly comparable. 24 turns, 0 errors. Predictions frozen at `c3f8e21`
before any turn.
Raw: `data/corpus/d1_causal_round2_result_2026-08-27.jsonl`.

```
BASELINE  "Panda Express Bigger Plate: A, B, C, D"                 zero-record 3/8
TEST      "Panda Express Bigger Plate, the 3-entree meal: A,B,C,D" zero-record 4/7
CONTROL   "8 oz sirloin, a loaded baked potato, Caesar"            zero-record 0/8  ✅
```

**The baseline reproduced omission** (3/8, meets the ≥3 threshold) and **adding
a precise structural fact did not reduce it** — 4/7, if anything higher.

## Verdict

> **The size-like lexical mechanism does NOT extend to c3. c3 is a DIFFERENT
> D1 SUBTYPE and splits from the Five Guys repair.**

Side by side, same code state, same control:

| | baseline | test | separation |
|---|---|---|---|
| **round 1** — remove vague size on a SECONDARY COMPONENT | 6/7 | **0/8** | ⭐ dramatic |
| **round 2** — add precision beside a size-like SKU | 3/8 | 4/7 | none |

## ⭐⭐⭐ THE VALUE OF THIS RESULT IS THAT IT PREVENTS A MERGE

Both utterances present identically at the surface: a branded chain, a
size-like word, an omitted ambiguity record. **A repair built from round 1 and
applied to both would have silently failed on c3**, and the failure would have
looked like an incomplete fix rather than a wrong theory.

⛔ The two mechanisms stay separate, per the frozen instruction. Round 1
established SECONDARY-COMPONENT vague size causally. Round 2 was the test of
whether that generalises to a size-like term on the CONTAINER. **It does not.**

## What still does not follow

No brand, SKU, prompt or DEFAULTABILITY conclusion. c3's actual cause remains
**unknown** — this round rules one explanation out, it does not supply another.

## D1 as now understood

```
D1a  secondary-component vague size    CAUSE ESTABLISHED (round 1)
D1b  c3 / Bigger Plate                 CAUSE UNKNOWN — not the size-like term
```

Next work: a fresh discriminating variable for D1b. Round 1's repair may
proceed independently for D1a; it must not be presented as fixing D1.

---

# ⛔⛔⛔ CORRECTION — D1'S SIGNATURE IS NOT WHAT THIS DOCUMENT SAID

**From data already on disk. Zero model turns.**

Pooled across both families, six runs, three code states:

```
omitting asks:  35
   ...with points > 0 :   0
   ...with points = 0 :  35     ← unanimous, no exceptions
```

Per family: c2-family **18/18**, c3-family **17/17**.

## What I asserted, repeatedly, and what is true

> ❌ *"the interpreter produced `action:ask` with `points` and no
> `ambiguities`"* — written in the attribution section above, in the tranche
> doc, and in commit messages.
>
> ❌ *"a question exists in `points` with no `ambiguities` entry... the prompt's
> own ONE UNKNOWN, ONE ENTRY rule is being violated"*

**Both are FALSE.** On an omitting turn **`points` is empty too.** The
ONE-UNKNOWN-ONE-ENTRY rule is not being violated in that way — there is no
question in `points` left dangling without a record. **There is no structured
content at all.**

## The real signature

> **On an omitting turn the interpreter returns an ask carrying NO structured
> output — neither `points` nor `ambiguities` — and the question the user sees
> is produced DOWNSTREAM, in prose.**

```
[prod_char c2 rep1] points=0 ambiguities=0, yet the reply asks:
   "Five Guys, nothing's on the board yet — need one thing first.|||The little
    cheeseburger and fries, did you finish both, or leave some?"
```

⭐ This also explains the `unclassified` typing directly: `_ask_types_from`
receives empty `ambiguities`, so it correctly returns `(UNCLASSIFIED,)`. The
typing was never wrong; its input was empty.

⚠ The coupling is not strict in the other direction either — emitting turns
carry points only 9/13 (c2) and 4/12 (c3) of the time. `points` and
`ambiguities` are not a matched pair in practice.

## What survives, and what is retracted

**SURVIVES — the facts, all measured under pinned conditions:**
- D1 exists and reproduces; base rates measured (c2 5/8, c3 3/5).
- **Round 1**: removing *"a small"* eliminated the omission, 6/7 → 0/8, control clean.
- **Round 2**: adding precision beside the Panda SKU did not, 3/8 → 4/7.
- The **D1a / D1b split**.

**RETRACTED — the mechanism story built on the wrong signature:**
- *"the model treats the size as already STATED, so it records no quantity
  ambiguity while still asking in prose"* — this presumed a question in
  `points`. There is none.
- Any claim that the prompt's ONE-UNKNOWN-ONE-ENTRY instruction is being
  violated, and the inference that "adding a rule is unlikely to help because
  the rule is already there and ignored."

⭐⭐⭐ **The round-1 RESULT stands; my EXPLANATION of it does not.** Removing
"a small" causes the interpreter to produce a structured ask instead of a bare
one. *Why* that word suppresses the entire structured output is now unknown.

## What this reframes the question into

Not *"why does the interpreter forget the ambiguity record?"* but:

> **Why does the interpreter return an ask with NO structured content, and what
> produces the question text when it does?**

That is a far more code-shaped question — a downstream composer or fallback
renderer is generating a question the structured lane never described.
**Not investigated here.**

---

# ⭐⭐⭐ CODE-PATH ATTRIBUTION — **TWO ASK STORES, ONE INSTRUMENT**

Zero model turns. Static trace from one omitting turn's signature.

## The seam, exactly

`core/food_turn.py:6304`:

```python
if _decision is not None and _decision.asks:          # <- STAGED PIPELINE
    _q = _decision.question
    _text = await _render(_ctx(clarify_plan(_decision, _q, ...)))
    ...
    return {"action": "ask", "text": _text,
            "ask_types": _ask_types_from(data),        # <- INTERPRETER's object
```

**The staged pipeline raises the ask from its OWN `_decision.asks`, entirely
independent of the interpreter's `points` and `ambiguities`.** The question text
is rendered from `_decision`. But `ask_types` is computed from `data` — a
different object, empty on these turns — so the ask types as `unclassified`.

## The structure was never missing. It is in the OTHER STORE.

```
skills/nutrition/clarify_policy.py
  ClarificationDecision.questions      <- the asks
  build_questions_for_item(item, ...)  <- built from StagedFoodItem.ambiguities
  _question_id(staged_item_id, fields) <- the questions carry FIELDS
```

A staged-pipeline ask is **fully structured** — with per-item ambiguities and
field names. It simply is not in `data["ambiguities"]`, which is the only place
the ask-type instrumentation reads.

## ⛔⛔ THIS RETRACTS THE CORRECTION I COMMITTED ONE STEP AGO

> ❌ *"On an omitting turn the interpreter returns an ask carrying NO
> structured output... the question is produced DOWNSTREAM, in prose."*

Wrong again, in the opposite direction. `points=0, ambiguities=0` means **the
INTERPRETER raised nothing** — it does NOT mean the ask is unstructured. The
staged pipeline very likely raised it, with structure of its own.

**Two retractions on the same defect in one session**, both from reading one
store and generalising to "no structure."

## What D1 probably is

> **NOT "ambiguity record omission." Rather: the system has TWO ask-raising
> stores — the interpreter's `data.ambiguities` and the staged pipeline's
> `ClarificationDecision.questions` — and the canonical ask-type instrumentation
> reads only the first.**

If so:
- the `unclassified` rate ≈ **the rate of pipeline-raised asks**, not a defect rate;
- **my instrumentation types the wrong object at 1 of its 4 data-driven sites**;
- round 1's result restates as: removing *"a small"* moved the ask from the
  pipeline store to the interpreter store — which is a real behavioural effect,
  but not "restoring a missing record".

## ⚠ WHAT IS ESTABLISHED vs INFERRED

**Established, from code:** site 6304/6391 exists, returns an ask from
`_decision.asks`, and types it from `data`. `ClarificationDecision.questions`
carry fields.

**INFERRED, not yet verified:** that the observed omitting turns actually took
that branch. The captures never recorded `question_id` / `staged_item_id`,
which that site returns and `conversation.py` persists — **so one confirmation
is needed**, and it is cheap: read those fields off a durable row.

**Do not act on the two-store diagnosis until that check passes.**
