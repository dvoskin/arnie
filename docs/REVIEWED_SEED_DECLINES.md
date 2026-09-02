> ⚠ **DESIGN RECORD — THE CODE IS NOT IN THE TREE.** The reviewed-decline and
> retry contracts below were implemented, exercised and proven during the
> Identity Reachability tranche (2026-09-01), then REVERTED with the blocked v2
> artifact chain: their runtime meaning depends on an artifact that fails the
> reachability contract suite. This file records the design and the evidence so
> it is not re-derived. Nothing here is currently enforced.

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
