# Arnie food lane — plan

**Date:** 2026-07-29 · **Base:** `bdd5a52` · **Predecessors:**
[`NUTRITION_LANE_AUDIT_2026-07-28.md`](NUTRITION_LANE_AUDIT_2026-07-28.md) ·
[`ARCHITECTURE_AUDIT_2026-07-29.md`](ARCHITECTURE_AUDIT_2026-07-29.md)

Those two describe the lane's behaviour and its architecture. This one is built from **production
traffic**, and it exists to answer the question the architecture audit's §9 says only a production
window can: what is actually still broken, and in what order should it be fixed.

**Evidence key**, same convention as the architecture audit:
`P` production data · `C` read from code at `bdd5a52` · `M` measured locally · `?` unverified

---

## 1. What this is built from

Every turn in production from **07-28 22:41 → 07-29 14:03 UTC** `P`: 49 turns, 6 users, all iOS —
full message, full reply, full step trace, cards, ledger events, the rows each turn wrote, the
pending questions it opened, and the memory rows it created. Read from `conversation_logs`,
`ledger_events`, `food_entries`, `pending_questions`, `user_food_matches`.

**Latency, end-to-end, n=36** `P`: **p50 7.0s · p90 12.5s · max 16.2s.** This is the `P` evidence the
architecture audit's §5 is missing — its wins are all `M`. The three slowest turns (16.2s, 16.1s,
14.1s) are all **re-enrichment of a food the system had already priced one turn earlier**.

---

## 2. Corrections to earlier readings

Recorded because the reasons generalise.

**2.1 — "Legacy writes 39 % of food events" was true of the window and wrong as a ranking.**
Splitting the same events at the Day-4 commits (authored 00:08–01:16 on 07-29) `P`:

| | lane events | structured | legacy | ios_edit |
|---|---|---|---|---|
| before 01:16 | 25 | 10 | **12** | 3 |
| after 01:16 | 16 | 10 | **4** | 2 |
| after 02:10:27 | 7 | 5 | **0** | 2 |

The label is trustworthy — the structured lane stamps `source` on log (`core/food_turn.py:2713`),
update (`:2803`) and delete (`:2817`), and `handlers/tool_executor.py:3104` defaults unstamped calls
to `legacy:{source_type}` `C`. The four remaining escapes are **two turns**, both shapes named below
as causes B and C. Twelve hours, three users and six food turns after that produced zero legacy writes.
**Caveat:** deploys are manual, so 01:16 is authorship, not shipping; post-cut sample is 14 events `?`.

**2.2 — "The perf work is probably not deployed" is withdrawn.** The architecture audit §1 documents
the deployed configuration, including that `NUTRITION_RESOLVER_MODE=live` really is live, and that
`FOOD_FAST_PATH_SHADOW` and `FOOD_VOICE_DEADLINE_S=6.0` are new `C`. The flat p50 is a statement about
end-to-end production latency, not about whether the work shipped.

**2.3 — Two proposed deletions are withdrawn**, because the architecture audit's S7 documents them as
deliberate: `_strict_needs_confirm` (it gates the live `review_plan`) and the fast-path decision
(shadow is on and accumulating). `meal_resolution.py` was deleted on identical "zero callers"
reasoning once and had to be restored; that scar is the reason.

**2.4 — The architecture audit's §9 prediction that "silent escapes should now be zero" is not yet
met** `P` — four remained, concentrated in the correction path.

---

## 3. Root causes

Seven, each producing several visible defects. The plan fixes causes. A guard appears exactly once,
and is labelled as a backstop rather than a fix.

### A · A clarification carries a question, not the item it is about

The ask persists text, not the resolved, priced item, so the answering turn re-interprets the raw
message and re-runs the whole enrichment ladder from zero `C`.

| Turn `P` | Evidence |
|---|---|
| 22:59 → 23:00 | The ask says "around 580 cal…10g protein". The answer turn runs a full search for *Junior's Original Cheesecake*, costs **16.2s**, and logs **8g**. The estimate was computed one turn earlier and discarded; the two pricings disagree. |
| 00:49 → 14:03 | Photo held. User states "It's sopresseta" at 00:54. Thirteen hours later the answering turn searches **"Dollar pizza slices, plain"** and logs 855 cal under that name — *"how'd you come up with that"*. |
| 23:07 → 23:08 | "2 cavendish and Harvey wild berry drops" is split on the conjunction into a **banana** and a candy. The user corrects the premise; the next turn still prices a banana at 105 and asks again. Three turns to log a 40-cal candy. |

**Root fix.** The pending payload becomes the staged item's **resolution** — identity (fdc_id / OFF
code / label), per-100g basis, the portion candidates the question is choosing between, the
assumptions already made. The answering turn *applies* the answer to that stored resolution, a pure
function, and re-resolves only when the answer changes identity. `fd2266a` put
`response_schema`/`options`/`staged_item_id` on the payload; the resolution is still absent, which is
why only `parse_command` is reachable and everything else re-interprets `C`.

**Second half — segmentation runs before resolution**, so "cavendish and Harvey" became two foods.
Resolution must be able to reject a split: if a segment does not resolve, try the unsplit span before
asking about it. A structural ordering change, not a conjunction heuristic.

**Third half, newly found — the ask that started the banana was never recorded as a food ask.** See
cause G; it is the mechanism behind this example.

### B · A correction relabels the row; it does not re-price it

The update path takes the interpreter's mutated *string* and re-searches it, instead of applying a
typed change to the resolved item `C` (`handlers/tool_executor.py:3765` gates re-resolution on
`_identity_changed`, then prices by handing the new name to `_analyze_food`).

| Turn `P` | Evidence |
|---|---|
| 01:38:04 | "Yea they were deep fried" → name becomes *"Shrimp, deep fried, 7 small"*, **calories stay 35, protein stays 9**. Reply: *"that's a real jump from a light sauté."* Nothing jumped. Receipt: "Corrected the serving · Macros rescaled" — no serving changed. |
| 01:38:36 | The user has to ask *"How does it change the total then?"* — and **that question performs the write** (→180). A question wrote because the correction did not. |
| 02:10:03 | "Switch those back to regular small shrimp" → receipt says **"Corrected the macros · Used the numbers you gave"**. No numbers were given. Calories stay 180 (the fried value); quantity blanked to `""` on the card. |
| 03:18:25 / :36 | The user fixes it by hand in the dashboard, twice, 11s apart — the first edit's `_reconcile_macros` rewrote protein 14→3, carbs 10→2, fat 10→2, which is why a second was needed. |
| 14:03:56 | Same bug, second user, **newest code**: "they're the sopresseta" → name changes, **855 cal unchanged**, quantity blanked, receipt claims user figures. |

"Shrimp, deep fried" searches as shrimp — the preparation is lost in the string. And when the
re-resolution comes back unpriced, the previous row's numbers stand while the receipt still reports a
successful correction.

**Root fix.** A correction is a typed operation on a resolved item:

- **preparation / form** (fried, boiled, grilled) → apply the form to the *same* resolved food; the
  ladder can price "shrimp, breaded and fried" asked for as a form, not as a name suffix.
- **identity** → full re-resolve; if it cannot be priced, the turn says so (`fc682d5`'s disclosure —
  verify it is reachable from this path).
- **portion** → arithmetic on the stored basis, no lookup.
- **macros** → the user's numbers win, no lookup.

- **day** ("that was yesterday") → **move the row to that day's log**. See B.1 — this type already
  exists end to end and is not being reached.

The receipt is then *derived* from which ran, so "Used the numbers you gave" cannot print on a turn
that supplied none (`core/reasoning.py:325`). **A correction that moves no number is an invalid
outcome** — the turn either moves the row or discloses that it could not. And the correction card must
read the committed row (`2a4c839`'s shape) on every update, not only on re-identifications.

#### B.0 · The unpriced disclosure was wired to a dead channel — **found during implementation**

`fc682d5` ("a correction that cannot be priced says so") taught the executor to stash
`correction_unpriced` and taught the reply to disclose it. The two halves never met `C`:

- `stash()` writes to the ambient `CALL_CTX` and states that *"the command input is NEVER written"*
  (executor immutability, P0.3e).
- `ExecutionResult.ok_tool_calls()` returns `{name, input: raw_input}` — the command, with none of
  that context.
- `core/conversation.py` read `_ci.get("correction_unpriced")` off that raw input.

So `unpriced_corrections` was `()` on every turn and **the disclosure has never fired in production**.
It matches the trace: the 01:38 correction changed the name, moved no number, and said nothing.

Its test asserts that the executor's **source text** contains the string `"correction_unpriced"` —
which it does (`tests/test_a_correction_re_resolves.py:138`). A grep stood in for the behaviour, so the
gap survived a release. This is the audit's "tests lying about coverage" pattern with a user-visible
cost, and it is worth a sweep: any other disclosure reading execution state off `raw_input` has the
same defect.

Fixed by reading the outcome from the typed call, joined by `id(raw_input)` — the join
`build_reasoning` already uses — and by widening the condition. `correction_unpriced` only fires when
the ladder returns *nothing*; a re-resolution that returns **the same number** passes that test and is
indistinguishable to the reader. "Deep fried" re-resolved as shrimp and came back at the same 35 cal.

#### B.1 · Re-dating is built, documented, unreached — and its fallback destroys data

The capability is complete `C`:

- `core/tools.py:81` — `update_food_entry` takes `date`: *"Move this entry to another day: 'yesterday',
  '2 days ago', or YYYY-MM-DD"*, and the tool description tells the model *"To move an entry to
  another day, set date= (e.g. 'yesterday')."*
- `handlers/tool_executor.py:436 _resolve_log` gets-or-creates that day's log and re-parents the row.
- `core/reasoning.py` already renders the receipt step *"Moved the entry to another day."*

**Production, 11:05:57, u=3** `P` — *"Вареная индейка была вчера и в салате курица"* (the boiled
turkey was **yesterday**). The turn:

1. logged `Рис отварной` and `Салат Цезарь с курицей` to **today** (entries 2570, 2571),
2. narrated that the turkey was excluded *"так как она была вчера"* — so the day was understood,
3. and on the next turn **deleted both rows** rather than moving them.

Result: 07-28 holds 6 entries and no Caesar salad and no turkey; 07-29 holds **zero entries**. The
food the user reported exists on no day. **This is the only data-loss case in the window.**

Two fixes, and the second is the general principle:

1. **Reach the capability.** A stated day is a `date=` on the operation — at log time it selects the
   target log, at correction time it moves the row. Note the instruction the model is meant to follow
   is English (*"set date= (e.g. 'yesterday')"*) and the message was Russian (*"было вчера"*); this is
   plausibly the same EN-keyed blindspot as cause E, and should be checked in both languages.
2. **Delete is not a substitute for move.** When the correct operation is a re-parent, deleting is
   silent data loss dressed as a correction. A destructive operation may not stand in for a
   non-destructive one that the vocabulary already contains.

### C · A turn's writes are not bounded by its own message

02:10:03 carried three intents — *"Switch those back to regular small shrimp / I also had half a
boiled corn on the cob / And I'm gonna have a Royo everything bagel rn"*. The turn executed **only the
correction**. The corn and the bagel were written by the **next** turn, whose entire content was
**"Thanks"** — 12.5s, `update + log + log`, three cards `P`.

Two structural failures: the interpreter returned fewer operations than the message contained and the
turn treated that as success; and the residue survived into a later turn through conversation context.

**Root fix.** The interpreter enumerates every operation its message supports; returning fewer than
the message's item count is an interpretation *failure* (ask, or hand back), not a partial success.
A turn's operations derive from that turn's message alone — prior-message items reach a later turn
only through the staged store of cause A, where they are explicit.

**Backstop, and the only one in this plan:** at `execute_tool_calls`, a turn whose message carries no
consumption evidence may not write. `consumption_evidence` (`core/food_turn.py:310`) already
implements this but lives in the planner, so it did not protect the two illegitimate writes above `C`.
Moving it to the write is insurance; the fix is B and C.

### D · The legacy escape — nearly closed, and downstream of B and C

See §2.1. Not an independent workstream: the four remaining escapes are the correction turn and the
"Thanks" turn. **One item survives**, worth doing first because it makes everything else measurable:
put the `_to_legacy` reason on the trace line and on `reasoning_json`, so the next window *attributes*
escapes instead of inferring them from a source label.

### E · Deterministic output is English-only, and additive

`P`, both from the newest code:

- 00:34:13 (RU) — `"That's already on the board from earlier, nothing new logged.|||Already on the
  board: Авокадо (0.5 авокадо, 120 cal), logged 00:34 (9s ago)."`
- 11:05:57 (RU) — `"Logged Рис отварной and Салат Цезарь с курицей. Записал рис и Цезарь…"` — an
  English floor **prepended to a Russian composed reply**. The `and` is `_join_names`.

Two causes in one line: the floors are English literals, and the floor is emitted *alongside* the
composer's text rather than instead of it.

**Root fix.** The turn knows the language it is answering in — pass it to the deterministic renderers
(`core/food_ledger.py` `_deterministic_line`/`render_committed`/`_FOLLOW_UPS`,
`core/food_response.fallback`/`_commit_text`, the duplicate notice in `handlers/tool_executor.py`), and
make the floor **mutually exclusive** with a composed reply. Every EN-keyed deterministic string is a
bug for these users — two of six users in this window.

Same turn: `skills_fired='log_food'` with **zero ledger events** — a duplicate rejection recorded as a
log. Derive `skills_fired` from what executed, not from what was planned.

### F · Food memory models *trust*, but never *identity*

The design gap, and the largest piece of work here. It has its own section — §4.

### G · Two open-question ledgers, and they do not share state — **new**

`P`, proven in `pending_questions`: the same question text is written twice, seconds apart, under two
kinds.

| ids | kinds | gap |
|---|---|---|
| 1962 / 1963 | `food_structured_ask` / `conversation_hook` | 47s |
| 1965 / 1966 | `food_structured_ask` / `conversation_hook` | 12s |

Consequences, all visible in this one window:

- **The banana.** Turn 23:07:00 asked two questions and recorded **only** a `conversation_hook`
  (pending 1961) — no `food_structured_ask`. So the next turn had no food pending to route to, went
  cold, re-interpreted from scratch, and kept the invented banana. This is the mechanism behind cause
  A's third example.
- **The 13-hour pending.** Food ask 1965 sat unanswered from 00:49 to 14:03 — far past
  `FOOD_ASK_TTL_MIN=240` `C`. Meanwhile `conversation_hook` 1968 reached `follow_up_count=1` and
  **generated the 13:00 proactive message** *"How many slices of that sopressata did you end up
  having?"*. One system chased the user; the other, which owns routing, did not, and had none of the
  thread's facts when the answer arrived.

This is the production form of the seam the 07-28 audit described statically: a prompt-driven
clarification (`note_food_clarification`) and a deterministic one, on different kinds, only one of
which is answerable.

**Root fix.** One open-question record per open question. The structured ask owns identity, routing
and TTL; the conversation-hook layer may *reference* it for proactive follow-up but must not be a
second copy with its own lifecycle. Every ask the lane emits — including the ones from the four return
points that currently store empty payloads — is recorded as a `food_structured_ask`, or it is not an
ask.

**Correction to an earlier reading in this document: "make expiry actually fire" was wrong.** It
fired. `pending_expired` (`core/food_ledger.py:112`) is evaluated on the next inbound turn against
`last_asked_at or asked_at`; at 14:03 the pending was 13.2 h old against a 240-minute TTL, so it
expired, was stamped, and the turn was correctly treated as cold. The defect is not that the question
outlived its TTL — it is that **expiring the question discarded what the thread had resolved**. The
sopressata was a *fact the user stated*, not a stale question, and it was thrown away with the
question that no longer applied. That is cause A's fix, not a TTL change.

There is a second-order effect worth naming, because it is why the two halves of this fix belong
together. The TTL clock reads `last_asked_at`, which a follow-up refreshes. Once the food ask carries
its own follow-up policy, the 13:00 chase would have moved that timestamp to 13:00 — leaving the
pending ~63 minutes old at 14:03, **inside** the TTL. The answer would have landed on a live question
instead of on a cold turn. Giving the record that owns the question the right to chase it does not
merely preserve the chase; it keeps the question answerable.

### H · The say contract governs digits, not entities — **new**

`enforce_say_contract` (`core/food_turn.py:2382`) is, by its own description, absolute about numbers:
a digit that is not present in the tool-call inputs is rejected and the sentence is rebuilt `C`.
There is **no equivalent contract for named entities or stated attributes**. So a brand, a platform, a
preparation or a product that the user never mentioned passes freely — and then becomes an input to
every later turn in the thread.

Four instances in one window `P`, from two mechanisms:

| Asserted | User actually said | Where it came from |
|---|---|---|
| *"Got it, **Seamless** order from Seppe."* | "Having this from seppe" | **fabricated** — "Seamless" appears nowhere in this user's history: no conversation, no entry, ever |
| *"**Cavendish**, that's just a regular Cavendish banana, right?"* | "2 cavendish and Harvey wild berry drops" | **fabricated** from a conjunction split |
| logged as *"**Dollar pizza slices, plain**"* | "Finished the 3 slices of pizza this morning at 6am" | **history leak** — they really do have `Dollar pizza slices, plain` on 07-16 and 07-21, so the cold re-interpretation reached for their most common pizza and discarded the sopressata stated 13h earlier *in the same thread* |
| logged as *"Skirt steak, **pan fried**"* | "6 oz of skirt steak" | **over-generalised**, not fabricated — the user's own word from a *different* steak on 07-26; see §4.2b |

The two mechanisms need different fixes and interact badly:

- **Fabrication** is a contract gap. Extend the say contract from digits to **entities and attributes**:
  anything the reply asserts as fact must be traceable to the user's message, the board, or a resolved
  source. What cannot be traced is either marked as an assumption — which is exactly the disclosure
  shape §4.2b already needs — or dropped. Note this is *not* a ban on inference; it is a ban on
  inference presented as recall.
- **History leak** is causes A and F interacting: when the ask carries no resolution (A), the
  answering turn re-interprets cold, and history matching (F) fills the vacuum with a confident wrong
  prior. **This is why F must not ship before A** — a better matcher without thread state produces a
  more confident wrong answer, not a better one.

---

## 4. The memory design (cause F)

The system has invested heavily in **how much to trust** a remembered row: a 90-day staleness horizon,
a shorter expiry when a generic row stands in for a named product, `user_confirmed` rows that never
expire, a `generic` gate, ladder seating by `food_class` and `origin_tier`
(`handlers/tool_executor.py:1944–1975`, `skills/nutrition/authority.py:290–313`) `C`.

It has invested **nothing** in whether it is the same food. Identity is `db/queries.py:2737` — exact
equality on `normalize_food_name`, which is `lower()` plus whitespace-collapse and whose own docstring
says *"no fuzzy matching, no token splitting… future work"* `C`. One dimension, evaluated silently,
never asked.

**One food, one day** `P`:

- **23:04** "Having a cucumber" → *"your saved match answered it"* → logged **0.5 cup / 8 cal**. The
  saved row was **"Mini Cucumber"** — a different food. Corrected by the user to 1 cucumber / 45 cal.
- **13:37** "Just ate a cucumber" → `"cucumber"` ≠ `"mini cucumber"` by one token → **miss**, a full
  **9.1s** search, and a *second* identity written: row 886, **cal_100 = 179, protein_100 = 7.14**,
  tier `generic_exact`. A medium cucumber is ~30 cal with ~0.1g fat.
- The user now holds two contradictory cucumber identities, one impossible, and the next "cucumber"
  hits 886 **silently**. The only write-side check is `cal_100 > 900`; 179 passes. `generic_exact` is
  not in `_MEMORY_RUNG_BY_ORIGIN`, so it seats at the default `C`.

Loose loses the food, tight pays full price for a food logged fifty times. No threshold fixes that,
because the missing thing is not a better string comparison — it is **evidence, and when the evidence
is thin, a question**.

### 4.1 Identity as a scored claim

| Dimension | Signal |
|---|---|
| **Anchor** | does the row carry an `fdc_id` / OFF code? An anchored row is a claim about a *product*; an unanchored generic row is a claim about a *word*. |
| **Lexical distance** | nearness, not equality — and *direction* matters: "cucumber" is a **superset** of "Mini Cucumber", so the remembered row does not answer it. Exactly the 23:04 failure. |
| **Intrinsic variability** | `FoodClass` already separates MANUFACTURED / GENERIC / RESTAURANT. A barcoded bar is the same food every time; "chicken", a deli salad, a restaurant dish are not. Today this only sets trust; it should be identity evidence. |
| **How the row was earned** | user-confirmed or corrected vs *our own earlier guess* (`generic_exact`). Modelled for trust; it should gate **silence**. |
| **Context** | meal slot, time of day, portion shape, and whether the phrasing implies recurrence ("my usual") or novelty ("a", "some"). |
| **Corroboration** | does the row agree with the entry it was born from, and survive an Atwater check. |

### 4.2 What to do with the claim: spread × prior shape, not confidence

A uniform *"is this your usual?"* is wrong in both directions, and this user's own history shows why `P`:

| | Real history (u=26) | Spread | Right move |
|---|---|---|---|
| **cucumber** | one real cucumber at 45 cal; the two other lexical "matches" are a *salad* and a *Cava bowl* | ~8–45 cal | **never ask, never mention** — the whole range cannot move the day |
| **coffee** | **7 logs, 6 distinct variants** — black 5, oat creamer 25, Splenda+oat 45, low-fat milk 30, iced half-and-half 120, Birch iced latte 180 | **5 → 180 cal (36×)** | there is **no usual** — don't claim one, and don't ask an open question either |

(u=5 is the same: 5 coffee logs, 5 variants, 30 → 535, one of them a *breakfast bowl* from "Cinico
Coffee Company". Substring matching is finding false friends in both users' histories.)

The prior is a **distribution**, and its shape picks the move:

| Prior shape | Spread material? | Move | Voice |
|---|---|---|---|
| any | **no** | log the modal prior, say nothing about identity | *"Cucumber, logged."* — today's good behaviour, keep it |
| **concentrated** | yes | **assume and disclose** — do not ask | *"Your usual black coffee, 5 cal — logged."* A statement with a one-word correction handle. |
| **split** | yes | **ask with their own priors as the options** | *"Black, or the oat creamer one?"* — one tap, grounded in what they log |
| **none** | yes | today's clarification path, unchanged | — |

### 4.2b Per *dimension*, not per identity — and an assumption may not become the name

§4.2 decides whether the remembered **food** is the same food. That is not enough, because the
question a repeat log usually raises is about a dimension the user **did not state at all**.

**Production, u=26** `P`:

| `parsed_food_name` | date | qty | cal |
|---|---|---|---|
| Skirt steak, **pan fried** | 07-28 | 6oz | 420 |
| Skirt steak, **pan fried** | 07-28 | 6oz | 420 |
| Skirt steak, **pan fried** | 07-26 | ~3oz | 210 |

Memory row: `Skirt steak, pan fried` · `times_used = 3` · `origin_tier = generic_exact` ·
**`user_confirmed = False`**.

"Pan fried" was **not fabricated** — it is the user's own word, from 07-26 02:11: *"I also had a
small piece of skirt steak pan fried."* What went wrong is what happened to it afterwards. The full
chain `P`:

| when | user said | Arnie |
|---|---|---|
| 07-26 02:11 | *"a small piece of skirt steak **pan fried**"* | asked how much — correct; the name is born, from the user's words |
| 07-27 21:15 | *"Just had some steak"* → *"6 oz, and butter"* | **asked** *"did you cook it dry, or with butter or oil?"* — correct; logged *"Steak, pan-cooked with butter"* |
| 07-28 23:49 | *"6 oz of skirt steak and 100g rice rn"* | **asked nothing**; logged *"Skirt steak, pan fried"*, 420 cal |

**The inversion is the finding.** On 07-27, with no matching memory, the lane asked exactly the right
question. On 07-28, *having* history **removed** that question. History made Arnie less curious rather
than more precise — the opposite of what a food memory is for.

Four failures compound, each needing its own fix:

1. **A fact stated once, about one instance, became a standing default.** The user described one
   07-26 steak; the preparation was then applied silently to every later skirt steak. A statement
   about an instance is not a statement about the food.
2. **Having a prior must make the question cheaper and more specific, never absent.** The spread ×
   prior-shape decision in §4.2 has to run **per unstated dimension** — preparation, portion, variant,
   brand — not once per item. On 6oz skirt steak, preparation is a material spread; on a cucumber
   there is no such dimension and no question.
3. **The dimension is laundered into the identity key.** It lands in `parsed_food_name`, so it becomes
   `name_norm`, so it *is* the identity from then on — unfalsifiable by construction, and the reason
   the later turn saw a "hard match" at all. **A dimension the user did not state on THIS turn may not
   enter the name.** It is an assumption attached to the row, carried and disclosed. Note the cost of
   getting this wrong in the other direction too: 07-27's *"pan-cooked with butter"* and 07-26's
   *"pan fried"* became two adjacent identities, and on 07-28 the leaner one won silently.
4. **Provenance is recorded as a guess even when the user supplied it.** `origin_tier` is
   `generic_exact` — our-own-guess — and `user_confirmed` is `False`, on a value the user stated
   aloud. `authority.py` has a `user_label` tier for exactly this and nothing sets it `C`. The row
   ends up with the worst of both: trusted enough to skip the question, unconfirmed enough to be
   re-derived. And `times_used = 3` climbs on reuse, so an unconfirmed value looks stronger each time
   it is silently reapplied. **Reuse may not raise trust; only an answer may.**

**The right turn**, and it is the §4.2 "concentrated prior" row done properly — a statement that
names its own provenance and doubles as the correction handle:

> *"6oz skirt steak and rice, logged — 420. Pan fried like the other day?"*

One line, no extra turn, nothing withheld from the board, and the answer **earns** the dimension:
answered once, it is `user_label`/`user_confirmed` and is never asked again. Compare what shipped —
silence, and a preparation carried forward from a different steak two days earlier.

Note this is the *same* question the lane already asks well when it has no memory to lean on
(07-27: *"did you cook it dry, or with butter or oil?"*). The work is not inventing a new ask. It is
stopping a prior from suppressing one, and letting the prior make the ask shorter.

### 4.3 The voice rules that fall out

1. **A disclosed assumption is a statement, not a question.** Questions cost a turn; statements cost
   nothing and stay correctable. Only a genuinely split prior earns an interrogative.
2. **Options come from their history, never invented.** At 23:07 Arnie invented a *banana*, asked two
   questions about a 40-cal candy, and carried the invention into the next turn. Nothing in that
   user's history was consulted.
3. **Never ask about an item whose entire plausible range is immaterial**, and never more than one
   question per item. Materiality must be computed over the **identity spread** (max−min across
   plausible identities), not over a point estimate. `FoodAmbiguity.calorie_span` survived `faa7ccd`
   as exactly this width; it is simply not fed by identity variance yet `C`.
4. **An answered question earns the identity permanently** — it upgrades the row, links the variants,
   and is never asked again for that food.

**This makes the lane faster, not slower.** A concentrated prior skips the lookup — the fast path
memory was always meant to be. A split prior resolves in one tap instead of a 9–16s search. And it
composes with cause A: because the ask carries its candidates, answering is a zero-lookup commit. The
23:04 cucumber should have been silent and right; instead it silently logged the wrong food, absorbed
a correction, and 14 hours later paid a full search anyway.

### 4.4 Write side — identity is earned, not assumed

- One resolution object produces both the entry and the memory row, and the pair must agree:
  `entry.calories ≈ cal_100 × grams / 100`. Row 886 violates this by 12×. An invariant over one
  object — a backstop, not the fix.
- A row written from our own guess is stored as a guess and may never short-circuit silently. Today it
  does, which is how 886 becomes authoritative.
- Two near-identical keys may not hold contradictory identities unlinked. "cucumber" and "mini
  cucumber" are one identity with variants, or an explicit disambiguation — never two silent answers.
- Sweep the table for entry/basis disagreement and unlinked near-duplicate keys.
- **`frequent_foods` (`db/queries.py:2848`) returns the most-logged names with the *most recent* row's
  macros** — precisely the wrong summary for a split distribution: recency over modality, spread
  hidden. It should return the distribution — variants, counts, recency, span.
- **There is more than one memory.** `user_food_matches` (read by the executor as a row) and
  `frequent_foods` (injected into the interpreter's prompt as text) are two memories with different
  rules answering the same question, and they can disagree inside one turn. One identity store, read
  by both.

---

## 5. Smaller findings, recorded so they are not lost

All `P`, all from this window.

- **Per-item cards carry a turn-level verdict.** 00:34:07 rendered three cards — Рыба, Бейгл, Авокадо
  — all three with the identical verdict *"Strong protein hit — the da…"*. Same at 23:05:20, where a
  tomato and three olives both read *"Calories are getting tight, so…"*. The verdict is computed once
  per turn and stamped on every card, so per-item cards say the same thing about different foods.
- **"Gonna have" is handled two ways.** 23:03:11 *"Also gonna have a rice cake"* → asked. 23:49:13
  *"Gonna have like 6 oz of skirt steak and 100g rice rn"* → logged immediately. Whatever the rule is,
  it is not legible from the outside.
- **Reply richness is bimodal.** *"Logged Shrimp."* and *"Logged Cucumber."* sit next to fully-voiced
  replies on neighbouring turns — the deterministic floor answering where the composer answered a
  minute earlier. Related to E's floor-or-composer fix.

---

## 6. Order of work

**Ranking criterion: what still failed in the newest code.** Counting defects across the whole window
over-weights turns that predate the Day-4 commits. The last four food turns of the window — all after
every commit on `main` — failed four different ways, one per cause:

| Turn `P` | Failure | Cause |
|---|---|---|
| 11:05:57 (RU) | English floor prepended to a Russian reply | **E** |
| 13:37:16 | 9.1s search on a repeat food; impossible second identity written | **F** |
| 14:03:20 | 13h pending answered cold → *"Dollar pizza"* | **A** + **G** |
| 14:03:56 | correction changed the name, not the number | **B** |

1. **Attribution** — the `_to_legacy` reason on the trace and `reasoning_json`. Half a day; unblocks
   scoring everything else. (cause D's only remaining item)
2. **B — the typed correction.** Still failing in the newest code, on two users; it caused the
   illegitimate write in C, the dashboard double-edit, and two of the four remaining legacy escapes.
3. **G — one open-question record.** Small, and it is the mechanism behind A's worst example. Doing it
   before A means A is built on a ledger that is actually authoritative.
4. **A — the ask carries the resolution.** Removes the slowest turns, the ask↔log disagreement,
   "Dollar pizza", and the premise-correction failure. **Before F**: F's confirming question is only
   cheap because A makes an answered ask a zero-lookup commit.
5. **F — identity.** Order within it: (a) write-side invariants + sweep — cheap, stops new poisoning
   today; (b) `frequent_foods` returns the distribution; (c) materiality over identity spread, which
   alone silences the cucumber and unlocks the coffee; (d) the scored identity claim; (e) the
   split-prior ask with their own variants as options.
6. **E — locale.** Small, self-contained, failing for two of six users. Parallelisable with anything
   above.
7. **C — complete operation sets**, plus the write-side backstop.
8. **D — re-measure.** After B and C, re-pull the window and confirm legacy writes reach zero.

### Carried backlog (unchanged, still after the above)

Unify the tap-log/dashboard write paths through `execute_tool_calls` — `api/quick_log.py:61`,
`api/food_edit.py:62,128`, `api/app.py:3604` bypass enrichment, dedup, receipts and cards, and
`api/food_edit.py:170 _reconcile_macros` is a second macro reconciler that caused the 03:18 double
edit. Cherry-pick `77f89f5`+`44de3f3` (no `release_processed` on main — a crash between claim and write
strands "Already got that one" for 60 min) and `11dbe39` from
`dvoskin/credentials-food-turn-fixes-80e9b7` **without merging it** (`be65fb6` would silently disable
partial commit). Delete the duplicate `_join_names` (`core/food_ledger.py:384` and `:456`; the survivor
lost its empty guard → latent `IndexError`). Continue the deletion groups via
`scripts/reachability.py` / `dead_code_report.jsonl`, respecting S7's deliberately-kept list. Then the
extractions (`core/conversation.py:786–1158` → `core/turns/lanes/structured_food.py` first) and
composites (adopt `40d4d9b`, graft `components_could_win()` from `e4d651d`). Mode collapse stays
deferred.

---

## 7. Verification

Work from a worktree on `main` — the primary checkout is on `feat/coach-card-microviz`, a month stale
and dirty.

```bash
python -m pytest -q
```
Baseline 0 failures, ~5,628 passing (`tests/conftest.py` hermetic since `7643816`).

```bash
python scripts/eval_food_matrix.py
```
Keep it green and **add one case per defect** — every case in that harness is a real production
failure, which is its stated bar. This window supplies: an answer turn must not re-search; "deep
fried" must move the number; "switch those back" must not claim user-supplied figures; a three-intent
message must emit three operations; "Thanks" must write nothing; a Russian turn must contain no
English scaffolding; a logged row and its memory row must agree on basis; a mention *less specific*
than a remembered row must not resolve to it silently; one question must produce one pending record;
a message naming yesterday must not write to today.

**Re-run the trace as the acceptance test** — same queries, 18-hour window, prod URL in `arnie/.env`,
raw `psycopg` (the async engine hangs):

| Metric | 07-28/29 `P` | Target |
|---|---|---|
| Ledger events from `legacy*` | 16 of 41 overall; **4 of 14 after Day-4** | 0 |
| Turns where a question or an ack wrote | 2 | 0 |
| Corrections that changed a name but no number | 3 | 0 |
| Receipts claiming user numbers when none given | 2 | 0 |
| Corrections that moved no number and disclosed nothing | 3 | 0 |
| Disclosures reading execution state off `raw_input` | 1 (never fired) | 0 |
| Answer turns that re-ran a full search | 3 | 0 |
| Questions stored as two pending records | 2 of 5 | 0 |
| Pendings answered past TTL | 1 (13.2 h) | 0 |
| RU replies with English scaffolding | 2 users | 0 |
| Writes per corrected entry | 6 across 4 lanes | ≤2, one lane |
| Memory rows inconsistent with their entry | ≥1 | 0 |
| Contradictory identities under near-identical keys | 2 (cucumber) | 0 |
| Repeat foods paying a full search | 1 of 2 cucumbers | 0 |
| Questions asked about an immaterial spread | 2 (the candy) | 0 |
| Ask options invented rather than drawn from history | 1 (the banana) | 0 |
| Entities asserted that the user never said | 4 (Seamless, banana, dollar slices, pan fried) | 0 |
| Unstated dimensions written into an identity name | 3 rows ("pan fried") | 0 |
| Turns where history overrode a fact stated in-thread | 1 (sopressata → dollar) | 0 |
| Food reported for another day that landed on no day | 2 rows (u=3 Caesar, turkey) | 0 |
| Deletes standing in for a re-parent | 2 | 0 |
| p50 / p90 end-to-end | 7.0s / 12.5s | re-baseline after step 1 |

---

## 8. Coordination

`ARCHITECTURE_AUDIT_2026-07-29.md` shows another session working this lane — routing, latency, voice,
reachability. **B, C, E, F and G are untouched by it. A is adjacent to its S1/S2.** Confirm ownership
before taking A. Deploys are manual, from an isolated worktree; `git fetch` before starting anything.
