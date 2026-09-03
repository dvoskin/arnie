> ⭐ **IR-PUBLISH (2026-09-03): the reviewed-decline contract is BACK IN THE
> TREE** — `scripts/build_pricing_artifact.py`, FAILED-only, bound to
> `(identity, resolver_version, retrieval_fingerprint, candidate_fingerprint)`,
> fail-closed on a missing fingerprint. It was implemented and proven
> 2026-09-01, reverted with the blocked v2 chain, and re-applied narrowly for
> publication. The retry contract's `failure_class` is recorded on every
> `build_one` result; the bounded-retry POLICY is still an operator action.

# REVIEWED SEED DECLINES

A seed identity listed here has been **individually reviewed** and found not
authoritatively buildable under the stated resolver version. The builder may
publish the remaining artifact when every failure is a reviewed decline, and
must still refuse when a seed fails for an unreviewed reason.

⛔⛔ THIS IS NOT A FAILURE QUOTA. `MAX_UNRESOLVED=1` would turn the guard into
an allowance and would eventually admit arbitrary failures — the reviewed
identity would be spent on whichever seed happened to break first. Each entry
here names ONE identity, ONE resolver version, and ONE reason a human checked.
A new failure, or the same identity failing for a different reason, still stops
the build.

⭐ THE SAFETY PROPERTY WE ACTUALLY NEED is *no seed silently becomes
authoritative while unresolved*. That is different from *one unresolved seed
prevents every other valid seed from being published*, which is what the
all-or-nothing rule enforced. The first is the guarantee; the second was an
assumption riding along with it.

---

## `egg|roasted` — resolver `food_evidence_semantics_v2`

**Reason:** `IDENTITY_UNRESOLVED`

**Unresolved row:** `usda:748967` — *"Eggs, Grade A, Large, egg whole"*

**Review:** the record states **no preparation at all**. Against the intent
`egg, roasted` it is genuinely unsettleable, so `INSUFFICIENT_EVIDENCE` is the
correct classification — the gate is right, not broken. No USDA Foundation or
SR Legacy record describes a roasted egg, so no query reaches one.

**Coverage cost: ZERO.** `egg|roasted` is absent from the committed v1 artifact
(27 entries, checked). It has never produced evidence. Under v1 the same
identity returned a clean `no_evidence` and the build proceeded; under v2 the
same row ABSTAINS rather than declining, and the all-or-nothing rule escalates
that into a total refusal.

⚠ **WHY THE BEHAVIOUR MOVED, STATED HONESTLY.** The v2 guidance added "never
treat a language difference as evidence of a different food". That plausibly
shifted the decline/abstain boundary generally — making the classifier more
willing to abstain where it previously declined. That is a real semantic
consequence of the prompt change, not merely a language addition, and it is why
the version bump was mandatory rather than bookkeeping.

⭐ **OBSERVED BEHAVIOUR, STATED WITHOUT OVERCLAIMING.** `egg|roasted` abstained
in **3 of 3 observed full builds**; sampled in ISOLATION the same row produced
abstain / clean-decline / clean-decline. Context sensitivity is plausible —
magnitude unmeasured, and three observations do not establish determinism. The
evidence supports an ASSOCIATION between batch context and abstention, not the
causal claim that batch context produces it. Registered under
`docs/REGISTERED_QUALIFICATION_NONDETERMINISM_2026-09-01.md`; a build whose
success depends on which way one borderline row falls is unreliable by
construction as the seed grows.

---

## RETRY CONTRACT — the two failure classes are not alike

```
RETRYABLE_PROVIDER      the query returned NO ANSWER
                        -> bounded retries + backoff
                        -> if exhausted, ABORT publication

SEMANTIC_UNRESOLVED     the judge answered, by abstaining
                        -> NOT retryable
                        -> authoritative evidence OR a matching reviewed decline
                        -> otherwise ABORT publication
```

⛔⛔ **RE-ASKING AN UNCERTAIN JUDGE UNTIL IT AGREES IS NOT A RETRY — IT IS
SAMPLING FOR THE ANSWER YOU WANT.** Retrying a provider that returned nothing
asks the same question again; retrying an abstention keeps rolling until the
uncertainty falls the convenient way. Sharing one retry policy between them
would quietly convert "the model was unsure" into "the model agreed", which is
the failure the whole authority ladder exists to prevent.

⚠ Until the bounded policy is implemented in the runner, "re-run the build when
a provider query fails" is an OPERATOR action, and operator-selected success is
its own bias: the build that happens to pass is the one that gets published.
`potato|` failed `1/2 provider queries` in attempt 3 and not in attempts 1-2 —
that is exactly the shape that lets an operator retry their way to a green
without noticing. `failure_class` is now recorded so the policy can be enforced
by the runner rather than by whoever is watching.

---

## `egg|roasted` — RE-REVIEWED under query expansion, 2026-09-03

**Subject moved, verdict did not.** Expansion changed the retrieved pool from
13 rows (fingerprint `6204a9d9`) to **15 rows (`sha256:a33a5128be741225`)**.
The old review correctly stopped applying — that is the binding working — and
was re-done from a single-identity `build_one` run rather than a full rebuild:

    status          failed | SEMANTIC_UNRESOLVED
    reason          1 of 15 rows unresolved; none annotated as priceable
    unresolved      usda:748967  "Eggs, Grade A, Large, egg whole"

**The same row, for the same reason.** It states no preparation, so against
`egg, roasted` it is genuinely unsettleable and `INSUFFICIENT_EVIDENCE` is
correct. Still absent from the v1 artifact; still zero coverage cost. The
review is re-bound to `a33a5128` and will expire again the next time retrieval
changes — which is the point.

### 2026-09-03 — the retry now lives IN the build, bounded, provider-only

Rebuild #2 failed on `egg|fried`: **one** timed-out USDA shape query out of five (`USDA search failed: ` — an
empty message, because a timeout's `str()` is empty). The build correctly refused to write, and because
annotations persist only inside the written artifact, 83 identities' qualification was discarded with it:
10.5 minutes to learn one HTTP call had timed out. `build_one` now re-issues the identity's retrieval round
up to `_PROVIDER_ATTEMPTS = 3` times (backoff `_PROVIDER_BACKOFF_S × attempt`) **before** qualification;
the semantic path never re-enters that loop. The USDA client now names the exception class in its warning.
Proven by `tests/test_a_provider_blip_is_retried_a_semantic_answer_is_not.py` (transient → 2 rounds and
`ok`; persistent → exactly 3 rounds, `RETRYABLE_PROVIDER … after 3 attempt(s)`; clean → 1 round; semantic
abstention → 1 round, `SEMANTIC_UNRESOLVED`), mutation-checked: attempts=1 and no-break both go red.

## 2026-09-03 — REVIEWED PINS: five seeds held on their v1 evidence (final, after the human layer was restored and expansion froze) (`data/reviewed_seed_pins.json`)

**Trigger.** Rebuild #3 (first expanded v2 build to write: 34 entries, 1041 annotations, two provider
timeouts recovered by the in-build retry) passed the build and the publication gate **blocked on 8 seeds** in V2-off; ranking the same artifact under V2 **on** exposed a ninth (`salmon|`), which is why the gate now runs both modes.
Every one has a causal explanation read from this build's own annotations — nothing was inferred.

| seed | v1 winner (kcal/100g) | v2 outcome | mechanism (from annotations) |
|---|---|---|---|
| `egg\|` | Egg, whole, cooked, omelet (154) | Egg, whole, raw, fresh (143) | omelet + scrambled labelled `DIFFERENT_IDENTITY`@0.95 |
| `mushrooms\|` | Mushrooms, shiitake, cooked (56) | Mushrooms, white, raw (22) | cooked shiitake `DIFFERENT_IDENTITY`@0.95 |
| `potato\|` | Potatoes, microwaved, cooked, in skin (132) | Potatoes, flesh and skin, raw (77) | cooked potato `DIFFERENT_IDENTITY`@0.95 |
| `mackerel\|roasted` | Fish, mackerel, Atlantic, cooked, dry heat (262) | **entry vanished** | all 4 "cooked, dry heat" rows `DIFFERENT_IDENTITY`@0.95 |
| `tilapia\|roasted` | Fish, tilapia, cooked, dry heat (128) | **entry vanished** | the single "cooked, dry heat" row `DIFFERENT_IDENTITY`@0.95 |
| `oats\|` | Cereals, oats, regular and quick, cooked (71; V2 on) | Cereals, QUAKER, Quick Oats, Dry (371) | expansion added a dry branded-legacy row that out-ranks in both modes |
| `beef\|` | Beef, NZ manufacturing beef, cooked (126) | V2 on: unchanged · V2 off: grass-fed ground raw (198) | lexical rank over 14 expansion-added cuts, V2 off only |
| `tofu\|` | Tofu, hard, prepared with nigari (145) | V2 on: unchanged · V2 off: MORI-NU silken firm (62) | lexical rank over 13 added rows, V2 off only |
| `salmon\|` | Fish, salmon, chinook, cooked, dry heat (231; V2 on) | V2 off: unchanged · V2 on: sockeye, cooked, dry heat (156) | rank over 7 added rows, V2 on only; no judged removal |

**RETRACTED the same day — "v2 semantics are stricter on PREPARATION than v1" was WRONG.** The real
mechanism: the committed artifact keeps its annotations under `meta.annotations` — 272 rows, **84 of them
`baseline_reviewed`**, and a person had ADMITTED exactly these rows (omelet + scrambled for `egg|`, the
microwaved potato, all four cooked mackerel rows for `mackerel|roasted`, tilapia dry-heat, capons, green
cauliflower, …). The producer read and wrote `annotations` at the TOP LEVEL, so every rebuild since the
layout moved printed `loaded 0 existing semantic annotation(s)`, re-rolled the model on the 84 signed pairs,
got the model's baseline opinion back (`DIFFERENT_IDENTITY` — the very opinion the reviewer had overridden),
and attribution-aware retention correctly refused to reinstate a "judged" rejection. v2 did not regress;
**the human layer was dropped by a loader/writer layout mismatch** — two implementations of one notion.
Fixed the same day: the loader reads both layouts with signed rows winning
(`_stored_annotations`, tests in `tests/test_a_rebuild_reads_the_human_layer_wherever_it_lives.py`), the
writer emits only `meta.annotations`, and the on-disk artifact had the 84 rows restored from HEAD before the
next build. The one genuinely model-level change is `mushrooms|` (`Mushrooms, shiitake, cooked` was an
UNSIGNED v1 model row that v2's model labels `DIFFERENT_IDENTITY`). The whole-vs-part rule (broccoli
leaves/stalks) behaved as intended.

**Decision (final): hold FIVE on their v1 candidate dicts — `beef|`, `egg|`, `mushrooms|`, `potato|`,
`tofu|`.** Two pins became unnecessary once the reviewer's admissions loaded (`mackerel|roasted`,
`tilapia|roasted` rebuild to exactly v1 in both modes). Three more became INERT once expansion was memoized
in the artifact (rebuild #6 froze the pools): with the frozen queries, `beef|grilled`, `oats|` and `salmon|`
rebuild to v1's winner in both modes, so a hold on them would do nothing today and would expire with the
instrument anyway. Of the five that act: `egg|` and `potato|` hold because expansion added a RAW row the
ranker prefers over the human-ADMITTED cooked winner (a consumed-form ranking matter, registered);
`mushrooms|` is the one true model relabel of an unsigned row; `beef|` and `tofu|` are V2-off lexical
re-ranks over the expanded pool with V2 on unchanged. Not a quota — each names its mechanism.

**Binding refinement (flagged for Danny).** Pins were first bound, like declines, to the expanded
population fingerprint. Between rebuilds #2 and #3 — same code, same instrument — `beef|` and `oats|`
populations moved (`1d981db0→30c05d7d`, `c37e6f0b→a0c65be2`) on nothing but expansion nondeterminism.
A hold that expires on a coin flip is not a hold, and the reviewed conclusion ("v1's candidates are this
seed's evidence under this resolver and this retrieval instrument") does not depend on which extra rows the
pool contained. **Pins now bind to `resolver_version` + `retrieval_fingerprint`; pool drift is printed as
`PIN NOTE … held`, and a non-applying pin prints `PIN DOES NOT APPLY` instead of silently publishing as
built.** Declines stay pool-bound — their conclusion is *about* the pool.

**Gate hardening (same day).** `verify_artifact_v2.py` ranked in one flag mode; it reported `beef|` and
`tofu|` repriced under V2 off while V2 on held the v1 winner, and would equally have passed a V2-on-only
reprice. It now classifies under **both** modes and blocks if either changes.
