# B-1 in production — what happened, 2026-08-05

Written for engineers who were not in the session. Everything below is either a
verified production observation or a code fact with a file reference. Where I
am inferring, it says so.

---

## 1. Status — resolved and verified

*Updated 2026-08-06 after deploy and live verification. §1 was previously an
open incident notice; the incident is closed.*

| | |
|---|---|
| Production SHA | `80b7786` — **contains the fix** |
| `main` | `2ae83cb` |
| `B1_QUANTITY` in prod | `effective=allowlist`, `halted=false`, `percent=0.0`, `allowlist_size=1` |
| Blast radius during the incident | **exactly one user** (id 26, the operator). `percent=0.0`, so no one entered the cohort by hash. |
| Meals lost | 2, both belonging to that same user |
| Test suite | 7842 passed, 0 failed, 0 errors, 82 skipped |
| Data-loss defect | **fixed, deployed, and reproduced-then-verified in production** (§6b) |

No action outstanding on the incident. One accuracy defect was found *during*
the verification and is deliberately deferred, not dropped — see §6c.

**For reference, the kill switch:**

```bash
B1_QUANTITY_HALT=1
```

It is a **pre-ownership** switch by design — it prevents new canonical
operations from being created; it does not tear down an operation already in
flight (see §9, invariant C10). It was not needed in the end: the fix deployed
before another ownership window opened.

---

## 2. What B-1 is

B-1 is the first slice of the canonical-architecture migration where the new
path **owns a real production turn end to end**, for exactly one shape of turn:

> one food, identity already resolved, and the only material unresolved
> attribute is consumed mass — *"I had some rice."*

The turn asks a quantity question carrying typed, ID-addressed options; the
answer applies a typed `SetQuantity` patch; the meal commits through the
canonical spine (`commit_or_load_existing` → `write_canonical_meal`) rather than
the legacy `add_food_entry` writer.

Everything not matching that predicate stays on the legacy path, untouched.

**Why it is gated so tightly:** the legacy conversational food lane has four
separate clarification producers and a relay, ships empty option lists on ~39 of
40 asks, and iOS re-derives chips by parsing Arnie's own rendered prose. Widening
before a slice is proven in production is how four producers happened the first
time.

---

## 3. Timeline

Times are commit times (`git log`). Deploys were manual; each state below
reached production.

| Time | SHA | Event |
|---|---|---|
| 13:42 | `71f3bb3` | B-0c lands: typed clarification contracts proven to survive storage |
| 14:21–17:51 | `9b64c90`…`7b66802` | B-1 built: producer, rollout gate, operation lifecycle, answer boundary, instrumentation, card, probe, six hardening items |
| 18:03 | `0ec5b56` | **Merged to `main` and deployed.** `B1_QUANTITY_ALLOWLIST=26` set |
| — | | **Zero B-1 events observed.** Four rounds of diagnosis follow |
| 18:20 | `0189439` | Defect 4 fixed — `/health` could not report B-1's state |
| 18:54 | `5ca9bf8` | Defects 1 and 2 fixed — B-1 was unreachable on both ask origins |
| 19:05 | `4751508` | Telemetry added: name every reason material is absent |
| 19:19 | `ac45b28` | Defect 5 fixed — the trace ring could not read its own event names |
| 19:28 | `d6fb068` | Defect 3 fixed — capability check read a modality, not a channel |
| ~19:35 | `d6fb068` | **B-1 completes end to end in production.** First canonical conversational food commit in Arnie's history |
| ~23:46 | `d6fb068` | **Data loss.** Two meals reported as logged, neither written |
| 08-06 | `47fc344` | Fix on `main`. Not deployed at time of writing |

---

## 4. Why B-1 did nothing for five deploys — three code defects

### D1 — wired to the minority ask origin

`core/food_turn.py` has **two** places a clarification is raised, and I
instrumented one:

- the **interpreter** branch — the model proposes an ask;
- the **pipeline** branch — the system overrides a log, gated on `any(k == "log")`.

Most real asks come from the first. Fixed by extracting `derive_semantics()` out
of `plan_turn` in `core/food_pipeline.py`, so both origins run one evidence pass
and both can be evaluated by the same predicate.

### D2 — the predicate keyed on a field that does not exist

Eligibility required `field_name == "estimated_mass_g"`. That is a
`FoodAssumption` field in `clarify_policy` — **not an ambiguity**. Real portion
questions carry `AmbiguityType.CONSUMED_QUANTITY` / `field_name="consumed_fraction"`.

This would have declined every turn on both origins. It is the more serious of
the two because **152 tests passed against it** — the fixtures built
`_ambiguity(field_name="estimated_mass_g")`, the shape I assumed. The assertions
were sound; the fixture could not fail.

### D3 — the capability check read a modality, not a channel

`client_capable` was computed from `_source = source_type or platform`.
`source_type` carries `text` / `voice` / `photo`. So a Telegram **text** message
arrived as `"text"`, matched no channel, and declined `client_incapable`.

This is the same platform/modality conflation recorded once before in this
codebase. Capability now reads `platform`, and an unrecognized modality logs an
error rather than falling through.

---

## 5. Three instruments that reported "nothing happened" when they meant "I could not read that"

These cost more than the defects. Each one turned a diagnostic into a source of
false conclusions, which I then acted on.

### D4 — `/health` flattened the rollout state to nulls

The public reshaper allowlisted `{effective, env_set}`. `B1_QUANTITY` is not a
plain flag, so it published `{"effective": null, "env_set": null}` — *"cannot
say"* rendered as *"off"*.

### D5 — the trace ring could not parse its own event names *(the expensive one)*

```python
_EVENT_RE = re.compile(r"\bevent=([a-z_]+)")   # no digits
```

`event=b1_shown` was captured under the event name `"b"`, which is not in
`WATCHED`, and discarded. **Every `b1_*` event was emitted correctly by
production and dropped at the ring.** `/admin/food-traces?event=b1_shown` could
not have returned them under any configuration.

I read `matched: 0` as evidence about B-1's *behaviour* — across several rounds
of diagnosis, in a commit message, and in two wrong conclusions about which code
path production takes.

Now: `([a-z][a-z0-9_]*)`, plus a prefix rule (`b1_`, `canonical_`) so a new event
family is visible without editing an allowlist, plus
`tests/test_the_trace_ring_can_report_what_it_watches.py`, which **scans the repo
for every `event=` name and asserts the ring can read each one back**. Not a list
to maintain — derived from the source.

### D6 — `/admin/food-traces?q=` is ignored

Substring queries return **everything**, not nothing. Only `event=` filters.
Noted, not yet fixed.

---

## 6. The data-loss incident

**What the user saw:**

```
23:46:57  telegram:9128   "I had some rice"    → "Logged White rice, steamed, 64 cal, 1g protein."
23:49:36  telegram:9130   "Had some oatmeal"   → "Logged White rice, steamed, 64 cal, 1g protein."
```

**What the database shows:** neither meal was written. Rows for that day end at
entry 2849 — the rice logged ~4 hours earlier, at the operation that proved B-1
worked.

### Mechanism

`core/b1_quantity_operation.py` defines `SETTLED_OWNERSHIP_MINUTES = 30`. After
an operation commits, it keeps owning the user's food lane for 30 minutes. That
exists for a real reason: a duplicate chip tap arriving after commit must
**replay the stored result**, not form a second valid claim and write a second
meal. (Settlement advances the revision, so without this the late tap's claim is
structurally valid.)

The flaw is that `owning()` keys on **the user**, not on **what the message
says**. So for 30 minutes after any B-1 commit, *every* food message was routed
into `answer_from_text`, which dutifully parsed `"Had some oatmeal"` as a
quantity, applied it, and replayed the rice result.

### Severity

This is the worst failure mode this system has: **a confident false confirmation
with silent data loss.** The user is told the meal is logged, their day's totals
are wrong, and there is no error anywhere to notice.

### The fix — `core/b1_answer_turn.py`

Narrow the settled window to what it was for. Once `awaiting` is false, a message
replays **only if it is addressed to the closed question** — a structured
`option_id`, or the exact text of an option we offered. Anything else is a new
report and falls through to the normal lane untouched.

Deliberately **not** a fix to the quantity parser. `"some oatmeal"` being read as
a quantity is only harmful because we asked the parser a question it had no
business being asked. **The boundary is the bug.**

Three regression tests added. Verified by mutation: with the guard removed the
new test fails with the production symptom; restored, all 49 ownership tests
pass.

---

## 6b. The fix, verified in production

Deployed `80b7786`. The same four-message sequence was then run live on Telegram
against a fixed baseline (last existing row: entry **2849**).

**Trace, in order — the middle line is the fix:**

```
b1_shown        operation=…:9132  options=2 sources=ontology free_text=True
b1_answered     operation=…:9132  outcome=applied modality=text provenance=user_stated
canonical_meal_written operation=…:9132 revision=1 lane=canonical:create cal=96.0
b1_committed    operation=…:9132  entry=2851

b1_not_a_replay operation=…:9132  — settled operation left alone; this message is a new report

b1_shown        operation=…:9139  options=3 sources=ontology free_text=True
b1_answered     operation=…:9139  outcome=applied modality=text provenance=user_stated
canonical_meal_written operation=…:9139 revision=1 lane=canonical:create cal=150.0
b1_committed    operation=…:9139  entry=2852
```

**Database verification:**

| check | result |
|---|---|
| new food rows | 2 — entry 2851 (chicken breast), 2852 (oatmeal). Both meals written. |
| `meal_commits` | exactly 1 per operation, all three `committed`, all `revision=1` |
| ledger events | 1 `created` per entry, source `canonical:create` |
| non-canonical ledger writes | **0** |
| pending operations | all three terminal |

Under the old code, message 3 replied *"Logged White rice, steamed, 64 cal"* and
wrote nothing. It now declines the claim and opens its own operation.

**Two things proven for the first time**, beyond the fix itself:

1. a settled operation correctly **declines** a message not addressed to it;
2. a **second** operation can open and commit after a first settles — until this
   run, exactly one operation had ever existed in production.

The fix was also verified by mutation before deploy: with the guard removed the
new regression test fails with the exact production symptom; restored, all 49
ownership tests pass.

## 6c. Found during verification, deliberately deferred — B-1.75

Comparing each operation's stored ask-time item against its committed row
surfaced a separate defect. It is recorded here because it was found here, and
in `docs/CANONICAL_MIGRATION_DIRECTIVE.md` as **B-1.75** because that is where
it will be fixed.

| entry | item at ask | answer actually sent | committed | verdict |
|---|---|---|---|---|
| 2849 rice | 100 **g** → 161/4/34/1 | *(typed grams)* | 39.6 g → 64/1.4/13.4/0.5 | scaled correctly |
| 2851 chicken | 6 **oz** → 280/52/0/7 | "Half a breast grilled with a little spray oil" | 87 g → 96/20/**4**/0 | **confounded** — the answer changed the food's description |
| 2852 oatmeal | 1 **cup cooked** → 150/5/27/3 | "Half a cup Made with milk nothing else in it" | 45 g → 150/5/27/3 | **not a defect** — ½ cup dry ≈ 45 g, and 1 cup cooked oatmeal is made from ½ cup dry |

**Corrected 2026-08-06.** This section first claimed two of the three were
defects, from inferring the answers sent rather than reading
`conversation_logs.raw_message`. Neither claim survives the actual messages:
oatmeal is correct, and chicken is confounded by preparation content in the
answer. Same root cause as §7 — a world assumed rather than sampled — which is
why the correction is left in place rather than quietly edited out.

**What the defect rests on instead is the code.** `core/b1_quantity_operation.py`
builds the pricing input as `inp = {**item, "quantity": quantity_text}`, so
`_analyze_food` (`handlers/tool_executor.py:2896`) receives the macros belonging
to the ask-time quantity alongside the answered quantity. `analyze()` documents
its own conflict policy — *"The LLM's calories/protein anchor the portion unless
the quantity is an explicit mass and the winner is trustworthy"* — so which of
the two governs is decided by that policy rather than by the user's answer.
The answered quantity should be the only quantity authority.

**This is not a nutrition-accuracy finding**, and no improvement to the resolver
can fix it — the contradiction exists before the resolver is called. The fix is
a **deletion** (replace the quantity fields rather than shadowing them), never
scaling arithmetic, which would violate the standing no-heuristics rule.

**Sequencing decision (2026-08-06):** downstream nutrition refinement owns this;
it does not gate B-1. It *does* gate B-1 **promotion**, since promotion asserts
that the answered quantity produces the committed numbers — so it must close
before the legacy quantity path is deleted.

It also explains itself: the fixtures were gram-based, which is the one case
that works. Same root cause as §7.

## 7. The common root cause

Four of the six defects are the same failure, not four different ones:

> **Every one of them shipped green because the test constructed the world I
> expected, rather than sampling the world that exists.**

- D2 — 152 tests passed against a field name production never emits.
- D5 — no test ever asked whether the ring could read the events being added.
- The incident — **204 B-1/B-0c tests**, and every single one answered the open
  question. Not one sent an **unrelated new meal afterwards**. I tested the
  conversation I imagined (ask → answer → done) and never the one that actually
  happens: someone logs rice, then eats oatmeal twenty minutes later.

The coverage number said 204. What it covered was my mental model.

**Two rules adopted as a result:**

1. **An instrument's silence is not evidence.** Before treating `matched: 0`, an
   empty log, or a null field as a fact about behaviour, prove the instrument
   *can* report the thing being asked about — emit a signal known to have
   happened and check it comes back. The tell is a filter that silently defaults
   on input it cannot parse: *"nothing happened"* and *"I could not read that"*
   must never look alike. This is the discipline
   `scripts/b1_operation_probe.py` already encodes — a check it cannot evaluate
   **fails** the run rather than passing.
2. **A lifecycle test must continue past the happy path.** For any stateful
   operation, the test must include the *next unrelated interaction*, not only
   the completion of the current one.

---

## 8. What is proven, and what is not

### Proven in production — operation `chat_quantity:26:telegram:9119`

```
b1_shown  options=3 sources=ontology free_text=True
b1_answered outcome=repair → b1_answered outcome=applied provenance=user_stated grams=39.6
canonical_meal_written revision=1 lane=canonical:create items=1 cal=64.0
b1_committed entry=2849
```

Database verification:

| check | result |
|---|---|
| `food_entries` | one row, 2849, "White rice, steamed", 39.6 g / 64 cal, `estimated_flag=False` |
| `meal_commits` | exactly one, revision 1, `status=committed` |
| ledger events | one `created`, source `canonical:create`; **zero legacy-sourced** |
| pending operation | terminal (`committed` / `settled`) |
| duplicate answer | two `b1_replayed` events, still one row |

The `repair → applied` pair is terminal ownership working correctly: an
unparseable answer re-asked the **same field** instead of falling to the
interpreter and becoming a second meal.

Verified again on 2026-08-06 across two further operations (§6b), which added
**settled-operation decline** and **a second operation after settlement** to the
proven list. Duplicate-answer replay is also proven — two `b1_replayed` events,
still one row.

### Not yet proven in production

- stale revision / foreign `field_id` refusal
- structured chip tap — **blocked until B-1b**; no channel sends `option_id` yet
- staged rollout past the allowlist (1% → 5% → 25% → 100%)
- voice rendering over committed facts
- **history-sourced options** — all five asks so far were `sources=ontology`,
  none from user history. Expected at this sample size (token-set-exact match
  against rows with `estimated_flag=False`, and no prior chicken/oatmeal rows
  qualify), but it is one of the two indicators named as able to falsify the
  design, so it needs watching as the cohort widens rather than assuming.

### Known tooling gap

`scripts/b1_operation_probe.py` **cannot exercise B-1.** It drives
`/api/v1/chat`, and `api/chat.py` sets `PLATFORM = "ios"` — iOS is deliberately
`client_incapable` until B-1b. Telegram and iMessage arrive by webhook, so
nothing scriptable currently reaches a capable channel. The probe's real target
is B-1b.

**This is the gap that let the incident reach a user instead of me.** The
incident itself needed no production access at all — it is two turns against a
local database. The missing piece was never access; it was the test. A local
harness that drives `_run_turn` with `platform="telegram"` across multiple turns
is the right investment and is the next thing to build.

---

## 9. Design decisions that held under production pressure

Worth recording, because they were load-bearing when things went wrong:

- **The gate is evaluated once, pre-ownership.** Once a `PendingOperation`
  exists, the turn completes through canonical apply, repair, cancel, or commit
  — no mid-flight fallback to legacy. A narrowed cohort or a tripped kill switch
  cannot strand a meal. Enforced as invariant **C10**, including an AST test
  asserting the answer path cannot even *import* the rollout module.
- **`owning()` is tri-state** — `OwnedOperation` / `None` / raise
  `OwnershipUnknown`. A read failure is never silently "not owned."
- **Near-duplicate options are suppressed by label, not grams** — the real
  ontology produced `5 oz / 6 oz / 16 oz`.
- **`LABEL_TEXT` ≠ `ID_ADDRESSED`** as channel capabilities.
- **One `CanonicalResponseFacts`** feeds copy, card and voice. Voice is
  post-commit and may never reinterpret, recompute, or override committed facts.

---

## 10. Pre-existing production defects found along the way

Live before B-1, unrelated to it, now fixed:

- `normalize_quantity("about 6 ounces")` → `amount=1.0, unit="about"` — the
  anchored regex missed on a leading hedge.
- `parse_command`'s bare `cancel` was unanchored — it fired on *"I didn't cancel
  my order"*, destroying meals.
- Negation was not handled — *"don't skip it"* matched `SKIP_ITEM` and closed
  operations.
- Command matching was English-only with no locale gate — a Russian message
  could match an English command substring.
- The admin token was a **literal** in `scripts/minimal_smoke.py` and
  `scripts/parity_corpus.py`. Now read from `ARNIE_ADMIN_TOKEN` only.

---

## 11. Next

1. ~~Deploy the fix, or halt the cohort~~ — **done**, `80b7786`, verified live (§6b).
2. **Build the local multi-turn Telegram harness.** (§8) In progress. The
   absence of this is why the incident reached a user instead of CI, and it
   also removes the need to hand-send messages for items 3 and 5.
3. Prove the remaining negative gates: stale revision, foreign `field_id`.
   Currently hand-sent; moves into the harness once it exists.
4. Fix `/admin/food-traces?q=` to fail loudly rather than return everything.
5. B-1b: iOS renders the canonical interaction — unblocks the chip tap path and
   makes `scripts/b1_operation_probe.py` usable.
6. **B-1.75** (§6c) — before promotion, not before rollout.
7. Only then: widen 1% → 5% → 25% → 100%, then scoped legacy deletion.

---

## Changelog

- **2026-08-05** — written during the incident; §1 was an open action notice.
- **2026-08-06** — fix deployed (`80b7786`) and verified live; §1 rewritten as
  resolved; §6b (verification) and §6c (B-1.75, deferred) added; §8 and §11
  updated.

Unrelated, flagged during this work: `reask_refused` is firing for user `ios:5`
on the legacy lane. Not investigated.
