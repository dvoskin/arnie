# P17 closure directive — restore sequencing and close the remaining gaps

*Issued by Danny 2026-08-19 (evening). Verbatim. This is the execution
authority for P17 from here; `CANONICAL_MIGRATION_DIRECTIVE.md` CF5b–CF15
remain the evidence register. Phase reports are appended at the bottom.*

## Mission

Finish exact, evidence-bound packaged-food logging without heuristics, prove both the backend and camera producer in production, remediate the corrupted Barebells entries, and then return to the original sequence:

1. Close P17 packaged-food logging.
2. Proceed to oils and other volume-based foods.
3. Keep general meal-photo-to-logging for the later photo tranche.

A label-photo request used to repair weak barcode evidence is not "meal photo logging" and may be used earlier.

## Non-negotiable invariants

1. A scan establishes product identity only. It does not establish consumption, quantity, or preparation.
2. A scan-bound turn never reaches memory, legacy interpretation, legacy correction, or an unbound write.
3. Binding must be decided from the complete typed plan—not from approved writes after information has been discarded.
4. Every material clarification on a bound turn must durably hold the snapshot.
5. Snapshot identity is authoritative for a bound settlement. Board-row names, model names, and prior entries cannot replace it.
6. Explicit identity conflicts fail closed. If the barcode says Caramel Cashew and the message explicitly says Salty Peanut, do not silently choose either.
7. Exact nutrition may be scaled only by a sourced conversion:
   * "3 strands (30 g)" supports exactly 10 g per strand.
   * "30 g serving" without a strand count does not.
   * "55 g serving" does not prove one bar equals one serving.
   * A package-to-serving conversion is allowed only when the evidence explicitly states it.
8. No provider-quality heuristic may silently become exact evidence.
9. No canary is retried after a failure until its state and logs are understood.
10. P17 is not cleared merely because the refusal or ask path fired. It requires a correctly committed evidence-bound row.

## Frozen incident facts

Treat these as established unless new wire evidence disproves them:

* The consumed product was Barebells Caramel Cashew.
* Its UPC-A is `850000429093`; the equivalent EAN-13 representation is `0850000429093`.
* The server received `70004199`, not the Caramel Cashew GTIN.
* Snapshot 1 and rows 3030/3031 therefore carry the wrong product identity.
* `70004199` must not be used for any P17 canary.
* A valid EAN-8 check digit does not prove that a camera result is the intended retail product code.
* The server correctly bound the code it received; the wrong identity entered before the canonical backend.
* Commit `9cf29b9` is CI-green but is not deploy-approved.
* P17g remains blocked.

## Phase 0 — re-establish the exact baseline

Before editing or deploying:

1. Record:
   * `origin/main`
   * clean/dirty tree state
   * live application SHA
   * live schema head
   * pending migrations
   * CI status
2. Identify every code commit after reviewed `4045514`.
3. Confirm whether `9cf29b9` is contained in the proposed deploy tree.
4. Capture the production baseline:
   * user 26's active canonical asks
   * legacy pending food questions
   * food-row and ledger high-water marks
   * complete bytes for rows 3030 and 3031
   * snapshot 1
5. Do not deploy until the proposed SHA—not merely an ancestor—has been reviewed and tested.

## Phase 1 — remove the prompt overreach

Do not deploy `9cf29b9` as written.
Its global "scan means fresh statement/no correction" instruction is based on attachment before the typed binding decision. It can alter unrelated clauses in a mixed turn and violates the attachment-blind planning rule.
For P17 closure:

* Revert or supersede that global prompt change.
* Preserve the CF5c dominance gate as the correctness mechanism.
* A single scan-bound update shape may be lifted after `BOUND` is established.
* A mixed turn must retain every subject and operation until the complete plan is counted and classified.
* Do not globally suppress `update_food_entry`, replay, or prior handling merely because a barcode attachment exists.

Required tests:

* Scan + fresh product statement: bound log/ask.
* Scan + explicit correction to another food: both subjects remain visible; multi-item policy decides.
* Scan + "yes" while a confirmation is pending: previous food is not replayed under the new snapshot.
* Hidden held/deferred subject: prevents single-subject binding.
* Unbound correction: byte-for-byte unchanged.
* Ordinary bound log: still settles using snapshot identity.

Any future model-guidance improvement must be subject-scoped and shipped separately. It is not required to make the safety invariant correct.

## Phase 2 — finish canonical-operation durability before expansion

Close the remaining OpenResult/ask durability gaps:

1. Persist the fingerprint version and digest used when the operation is created.
   * Do not recompute an old row as though it used the current fingerprint rules.
2. Validate stored `schema_version`.
3. Decode stored items strictly:
   * Must be a dictionary.
   * Do not turn arbitrary falsy values into `{}`.
4. Verify stored ownership before reuse:
   * user
   * domain
   * source turn
   * operation ID
5. Render only from persisted authority:
   * interaction
   * item
   * revision
   * locale
   * cohort
   * capability/channel, if behavior depends on them
6. Same operation ID with different semantic material must refuse.
7. Race losers may reuse only the exact matching stored winner.
8. Refusal remains non-mutating:
   * no food row
   * no legacy pending question
   * no replacement canonical operation
   * conversation turn may commit normally
   * session remains usable afterward

Keep `oneask001` as the single-owner database backstop. Application behavior must still be correct without relying on an integrity exception as control flow.

## Phase 3 — implement CF14: one holder for every bound clarification

Generalize the CF9 quantity holder into a bound-clarification holder.
Once the complete plan is classified `BOUND`, any unresolved material field must open or reuse a canonical operation that holds the exact snapshot:

* quantity
* consumption
* preparation
* unit
* any other material settlement field

Identity-only behavior:

* The snapshot answers ordinary brand/flavor identity questions.
* An explicit conflict between prose identity and snapshot identity must ask/refuse; it must not rewrite the snapshot or silently follow the prose.
* Weak provider identity must be handled by the evidence-confidence policy below, not by guessing.

Answer behavior:

* A typed answer or chip answer resumes from the persisted snapshot.
* No rescan is required.
* No ordinary pending-question record is created.
* No answer turn reaches legacy.
* A new scan cannot accidentally answer an older product's ask.
* Expired, superseded, mismatched, or unreadable operations refuse without mutation.
* Retry and race behavior must use the canonical OpenResult contract.

Ask copy should lead with universal measures:

* Solids: `110 g — 2 servings`
* Liquids: `250 ml — 1 serving`

The machine value may remain `2 servings` so typed matching continues to work.
Required CF14 proofs:

* Consumed but missing quantity → asks and holds snapshot.
* Quantity stated but consumption unresolved → asks and holds snapshot.
* Preparation unresolved → asks and holds snapshot.
* Chip answer settles the held snapshot.
* Typed answer settles the held snapshot.
* New scan while an old ask is open does not settle the old item.
* Same-turn retry returns the same stored ask.
* Concurrent opens yield one owner.
* No scan, ordinary B-1 behavior remains unchanged.
* Multi-food scan turn never opens a single-product bound ask.

CF14 is required before barcode logging is expanded beyond the controlled canary.

## Phase 4 — harden and instrument the barcode producer (CF15)

Build a diagnostic/hardened TestFlight scanner. Do not wait for another wrapper observation.

### Camera rules

For the food-barcode flow:

* Accept retail GTIN symbologies only:
   * EAN-8
   * EAN-13
   * UPC-E
   * UPC-A as represented by the platform
* Do not accept Code 39, Code 93, Code 128, PDF417, or ITF as food GTINs merely because their payload is numeric.
* Preserve the raw string exactly.
* Preserve leading zeros.
* Record the reported symbology.
* Require multiple consistent frames with the same raw value and symbology.
* Do not choose `metadataObjects.first`.
* Do not prefer a code merely because it is longer.
* If competing credible codes remain, show the user the candidates instead of guessing.
* Handle UPC-A and its leading-zero EAN-13 representation as equivalent after check-digit validation, while retaining the raw capture.

Send and persist:

* raw code
* normalized GTIN
* symbology
* consistent-frame count
* scanner version
* capture timestamp/session identifier

Log those fields on `product_acquired`.

### Acquisition timing

Instrument acquisition independently from model execution:

* request-start-to-response wall time
* lock wait, if applicable
* provider fetch duration
* cache/live/miss outcome
* attempt count
* timeout/error outcome
* snapshot create/reuse time
* model/planner/executor time

Do not attribute total latency to the model while acquisition occurs outside the existing stage timer.

## Phase 5 — fail closed on weak product evidence

Separate identifier syntax, identity confidence, and nutrition authority.
A checksum-valid GTIN proves only that the digits are structurally valid. It does not prove:

* the camera decoded the intended symbol,
* the provider matched the wrapper,
* the provider's flavor is correct,
* the provider stored nutrition in the correct basis.

For weak OFF records—such as automated creation, no usable photo, little provenance, or suspicious serving/per-100 g structure:

* A provider response may be retained as a provisional candidate.
* It must not automatically become authoritative identity and nutrition.
* Ask for label confirmation/photo or manual label values.
* Never silently "repair" the record using expected product knowledge.
* Never price exact nutrition using a guessed mass.
* Never fall back to legacy.

Quarantine `70004199` for this incident path so it cannot silently settle another Barebells scan. This is an incident safeguard, not a claim that all eight-digit GTINs are invalid.

## Phase 6 — test and release gates

Each code slice must pass:

1. Focused unit and integration tests.
2. Real-producer tests with only the model boundary mocked where necessary.
3. Local PostgreSQL tests, including both races.
4. Migration/model/schema gate.
5. Mutation proofs that actually report each mutation as applied and red.
6. Full suite with `+psycopg`.
7. Directly captured pytest exit status.
8. Frozen-tree fingerprint before and after the suite.
9. No edits while the suite is running.

Do not trust a shell's final `exit 0` if the captured pytest status is nonzero.
Deploy one reviewed SHA at a time.
After deployment, verify independently:

* `/health` reports the exact SHA.
* `schema.applied == schema.expected == oneask001` or the newly reviewed head.
* Schema is in sync.
* General settlement is reachable.
* User 26 is in the intended cohort/allowlist.
* The partial unique index exists with the reviewed definition.
* No duplicate awaiting operations exist.

Stop before canaries if any field differs.

## Phase 7 — production proofs

Use fresh client message IDs and one attempt per proof.

### Canary A — backend/server proof

Acquire the real Caramel Cashew code through the controlled server test path:

* UPC-A: `850000429093`
* Equivalent EAN-13: `0850000429093`
* Message: `I had 2 servings of this.`

Before sending, confirm acquisition resolves to the expected Caramel Cashew provider record. If the provider record has changed or fails confidence checks, stop rather than forcing expected values.
Required result:

* A new snapshot—not snapshot 1.
* Identity contains Barebells Caramel Cashew, never Salty Peanut.
* 110 g.
* Approximately 400 kcal.
* Protein 40 g.
* Carbohydrate 36 g.
* Fat 16 g.
* New food row with the new `product_evidence_id`.
* Product evidence rung and provider provenance.
* Existing rows untouched.
* `settlement_route=Supported`.
* Zero `correction_apply`.
* Zero memory.
* Zero legacy.

Abort if `product_acquired` is absent or names the wrong normalized GTIN. Do not retry.
This proves the canonical backend, not the phone camera.

### Canary B — held clarification proof

Use the same valid product but deliberately omit one material field while stating consumption.
Example:

* Scan valid Caramel Cashew GTIN.
* Message: `I had some of this.`
* Confirm a canonical bound ask opens holding the new snapshot.
* Answer: `110 g`.

Required result:

* One bound row with the same identity and evidence.
* No rescan.
* No legacy.
* No memory.
* No duplicate ask.
* The first turn performs no food write.

### Canary C — real camera proof

Using the hardened TestFlight build:

* Scan the actual Caramel Cashew wrapper.
* Confirm telemetry reports its real retail GTIN and symbology across the required consistent frames.
* Send: `I had 2 servings of this.`

Required database and settlement result is identical to Canary A.
If the camera again produces `70004199`, stop and retain:

* raw code
* symbology
* frame sequence
* scanner version
* image/session context
* request trace

Do not allow it to settle.
P17's backend canary may be recorded after A, but the end-to-end barcode gate remains blocked until C passes.

## Phase 8 — repair the incident data

Do not rename row 3031 to Caramel Cashew while retaining `product_evidence_id=1`. That would attach a correct-looking name to known-wrong evidence.
After the correct Caramel snapshot exists:

1. Preserve an audit record of rows 3030/3031 and snapshot 1.
2. Mark snapshot 1 rejected/quarantined if the model supports it; do not destroy forensic evidence.
3. Delete the false legacy row 3030.
4. For 3031:
   * Prefer an authoritative canonical rebind/correction to the new Caramel snapshot, or
   * Delete and relog accurately if evidence rebinding is not supported.
5. Verify:
   * 110 g / approximately 400 kcal
   * P40 / C36 / F16
   * new Caramel `product_evidence_id`
   * canonical correction/replacement provenance
   * no reference to snapshot 1 from the corrected row

Direct database surgery is acceptable only through an audited, narrowly targeted repair script if the application cannot express the repair safely.

## Definition of done

P17 closes only when all of the following are true:

* The global `9cf29b9` prompt behavior is absent or properly subject-scoped.
* CF5c dominates every route.
* CF14 durably holds bound snapshots across all material asks.
* Canonical operations are ownership-safe, version-safe, strict-decoding, and race-safe.
* The scanner sends validated GTIN plus symbology and frame evidence.
* Acquisition and total latency are measured.
* Weak OFF evidence fails closed.
* Backend Canary A passes.
* Bound-clarification Canary B passes.
* Real-camera Canary C passes.
* Rows 3030/3031 are repaired without retaining wrong evidence.
* Full suite, PostgreSQL races, migrations, mutations, health, schema, and index gates are green.
* Production logs show zero memory, legacy, or correction execution on all bound canaries.

## Return to the original roadmap

After P17 closes:

1. Freeze the packaged-food contract.
2. Start oils and volume-based foods:
   * sourced `ml`, teaspoon, tablespoon, and serving conversions
   * density only when explicitly sourced
   * no generic oil-density or utensil-size heuristics presented as exact
   * the same bound-ask behavior when conversion evidence is absent
3. Continue broader food coverage.
4. Implement general meal-photo-to-logging afterward, using the canonical evidence and clarification contracts established here.

Do not allow the scanner incident to turn into an open-ended OFF cleanup project. Implement the minimum mechanical trust boundary needed to fail closed, prove the lane, repair the incident, and return to oils.

## Required reporting format after each phase

Report only:

* exact SHA
* files materially changed
* invariant established
* focused tests and mutations
* full-suite count and captured exit
* migration impact
* deploy status
* production evidence
* remaining blockers
* explicit `P17g: BLOCKED` or `P17g: PASSED`
* explicit `END-TO-END SCAN: BLOCKED` or `END-TO-END SCAN: PASSED`

No phase is complete because code was pushed or CI started. It is complete only when its stated evidence exists.

---

# Phase reports

## Phase 0 — baseline (2026-08-19 16:46 UTC)

* `origin/main` = `79e6faf7f21a602f7a8328129c840eecffa4a60e` (= branch `dvoskin/food-lane-0803`); working tree CLEAN.
* Live application SHA (`/health.commit`) = `ed97f7a33149`; `/health.schema` = applied `oneask001` == expected `oneask001`, `in_sync: true`; `general_settlement_reachable: true`; coordinator lanes `structured_food, ledger_undo`; cohort size 1 (user 26); `alembic_version` in prod = `oneask001`. Pending migrations: NONE (local head `oneask001` = prod).
* CI on `79e6faf`: `in_progress` at capture (docs-only commits after `9cf29b9`, which was `checks green`).
* Commits after reviewed `4045514`, oldest first: `6d043cb` (docs) · `1931413` (docs) · `ed97f7a` (CODE — `run_turn` consults the scan authority before `native_no_plan`; LIVE) · `6c66ed1` (docs) · `9cf29b9` (CODE — interpreter scan-intent line; NOT deploy-approved) · `c8dff63` (docs) · `79e6faf` (docs). Code files changed after `4045514`: `core/food_turn.py` (+37/-3), `core/turns/entrypoint.py` (+36/-2), `core/turns/stages/food.py` (+5/-1).
* `9cf29b9` IS contained in `origin/main` — any deploy of `origin/main` as-is would ship the global prompt line. Phase 1 supersedes it before any deploy.
* Production baseline (user 26): ACTIVE canonical asks = 0 (latest op 87 committed/settled); UNANSWERED legacy `pending_questions` = 0 (latest 2199 answered 08-19 13:42:40 — by the legacy re-send, itself forensic: 2198 at 08-18 18:10:24 was the interpreter asking "Salty Peanut or Caramel Cashew?" on the very first scan turn); no duplicate awaiting operations for any user; index `uq_pending_operations_one_awaiting` present with the reviewed definition.
* High-water marks: `food_entries` max 3033 (2158 rows) · `ledger_events` max 2197 · `turn_metrics` max 1899 · `pending_operations` max 87 · `product_evidence` max 1 (1 row) · `product_unit_evidence` 0 rows · `conversation_logs` max 9315.
* Row 3030: ABSENT (deleted 08-19 13:39:09 via `ios_edit`, ledger 2170; created 08-18 19:39:12 by `structured_food:food_interpreter_v2` as "Barebells Salty Peanut Protein Bar / 2 bar / 400 kcal", ratio-corrected to "4 bar / 800" at 21:01:06 by the CF5b incident, ledger 2152).
* Row 3031 (complete): daily_log 542 · ts 2026-08-18 21:02:29.422733 · raw/parsed "Barebells Salty Peanut Protein Bar" · quantity "220 g" · 400 kcal · P34.5 C34.5 F13.8 · fiber 6.18 · source_type structured_food · pricing_rung product · nutrition_evidence_id `off:70004199` · source_basis per_100g · conversion `["off:70004199"]` · source_amount 100 g · scaling 0.55 · **product_evidence_id 1** · resolved_grams 55. Ledger: created 2154 `canonical:create` (55 g / 110 kcal); `ios_edit` updates 2171, 2173, 2189, 2190.
* Snapshot 1 (complete): provider off · canonical_code `70004199` · rev 1 · modified_t 1724712330 · fingerprint `dd262280859e125e` · name "Barebell salty peanut protein bar" · brands "Barebell" · per100g `{calories 200, protein 20, carbs 18, fat 8, fiber 3}` · serving_mass_g 55 · no per-serving, no unit evidence · created 2026-08-18 18:10:00.856459.
* Byte copy of the baseline: session scratchpad `phase0_prod_baseline.txt`.
* Deploy status: nothing deployed; `P17g: BLOCKED`; `END-TO-END SCAN: BLOCKED`.

## Phase 1 — remove the prompt overreach (2026-08-19 late)

* **Exact SHA**: `5230456` (built on `e999b30`; supersedes the code of `9cf29b9`, whose docs remain).
* **Files materially changed**:
  `skills/nutrition/product_acquisition.py` (the scan state: `UnverifiedScanAttachment` → `VerifiedScanEvidence` (immutable; partial construction refuses) → `ScanDecision` (immutable: outcome · evidence · disposition · reason); one request-scoped `ScanTurnState` holder, `begin_turn()` at ingress, `claim(turn_id)` at run_turn — a holder claimed by another turn is discarded unread; `attach()` dedupes only field-identical evidence, same-id-different-metadata and two-distinct-attachments are explicit `ATTACHMENT_CONFLICT`; `verify(db)` is the ONE repository validation; `evidence_from_stored_reference(db, id, fingerprint)` is the separately named retry path; compatibility adapters for the historical test contextvars, production-banned by AST gate) ·
  `core/scan_authority.py` (rewritten: pure classification over the complete typed plan + verified evidence; typed literal-mention comparison — `FoodSubject.labels` verified word-by-word against the user's message, only the verified mention compared with the evidence aliases; typed fresh-statement signals (consumption/amount/deictic) for identity-free binding; negation/question refusal; PRIOR_CONFLICT by causal provenance only (plan origin, `_prior_held` ops); `raise_if_refused()` = the gate; `require_bound_evidence()` = the only door to settlement; `scan_unused_note()` for DISCARDED) ·
  `core/turns/stages/food.py` (no pre-plan hook — replay and prior run attachment-blind; FoodValidationStage: verify → decide → raise, in order, before execution; `bind_plan` sheds `_prior_held` writes on a BOUND plan; `food_subjects_of` carries labels per occurrence, keys prior-held writes `prior:`, links a lone relabelled write to the lone raw row) ·
  `core/turns/stages/deterministic.py` (replay plans carry typed subjects + `origin="confirm_replay"`) ·
  `core/turns/models.py` (`FoodSubject.labels`, `TurnPlan.origin`) ·
  `core/food_turn.py` (the 9cf29b9 scan parameter and SCAN ATTACHED prompt line REMOVED; `_settle_deferred` stamps `_prior_held`) ·
  `core/turns/stages/execute_native.py` (`_bind_scanned_product` and `_name_from_snapshot` accept only `require_bound_evidence()` — no row reloads at settlement; the CF9 ask stamps evidence id + fingerprint) ·
  `core/turns/entrypoint.py` (claims the scan state per request; refusal copy per reason incl. prior/attachment/identity conflicts, no-fresh-statement, negated/questioned consumption; the unused-scan note is appended to the reply) ·
  `api/chat.py` (ingress attaches the acquisition-built verified evidence via `attach_acquired`).
* **Invariant established**: a barcode attachment cannot alter how a message is read (no prompt line, no plan suppression, no interpreter parameter — asserted by construction); binding is decided once, at the validation gate, from the complete typed plan beside verified evidence; a REFUSED decision raises before any execution; discarded evidence is auditable and confers no settlement authority; the six directive-required behaviours plus the two review rounds' eight additional proofs hold.
* **Focused tests and mutations**: `tests/test_p17_phase1_the_planner_is_attachment_blind.py` — 41 passed (fresh statements bind incl. deictic; unverified/partial evidence refuses; correction to another food survives + note; scan+yes+pending confirm = PRIOR_CONFLICT refused at the gate with zero mutation and the confirm left open; scan+quantity with another product's ask pending binds fresh, sheds the held write, pending op byte-identical; prior-held-only plans refuse; hidden deferred subject prevents binding; unbound correction byte-identical; bound log settles with verified identity 220 kcal; literal Salty Peanut vs Caramel label = IDENTITY_CONFLICT, surviving a producer relabel; "with coffee" is not a flavour; bare yes/thanks/emoji/empty cannot bind; "I didn't eat this"/"should I eat this?" refuse; identical attachments dedupe, same-id-different-fingerprint and two-distinct refuse; discarded evidence auditable, request scoping, 3 AST/construction gates). Seven scan suites: 210 passed, exit 0. **Mutation sweep: 21 mutations, every one printed `applied` and went RED (PYTEST_EXIT=1)** — two were green on the first sweep (EXPLICIT_OTHER_FOOD binds; note dropped) and gained dedicated proofs before re-running.
* **Full suite**: 9771 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, tree fingerprint `2a44c08f5d27` before = after — run with `TEST_POSTGRES_URL` set so both PG races RAN (an earlier same-tree green run without it silently skipped 97 PG-gated tests and was discarded as evidence).
* **Migration impact**: NONE (no schema change; `oneask001` remains head).
* **Deploy status**: NOT deployed; nothing is deploy-approved.
* **Production evidence**: none this phase (no canary may run before Phases 2–6 complete and a reviewed SHA is deployed).
* **Remaining blockers**: Phase 2 (canonical-operation durability), Phase 3 (CF14), Phase 4 (producer + acquisition timing), Phase 5 (weak-evidence policy + 70004199 quarantine), Phase 6 gates, canaries A/B/C, Phase 8 repair.
* **P17g: BLOCKED**
* **END-TO-END SCAN: BLOCKED**

## Phase 1 finishing patch — findings 1–5 closed (2026-08-19/20)

* **Exact SHA**: `1558a09` (on `5230456`; `95185f5` confirmed docs-only).
* **Files materially changed**: `skills/nutrition/product_acquisition.py` (F1: `decide()` is TERMINAL — identical second decision idempotent, different or post-consumption refuses `decision_conflict`; F5: `VerifiedScanEvidence` requires a usable product identity at construction — a nameless snapshot can no longer become "verified"; acquisition stashes nothing for such a row, so the gate refuses `identity_unknown:partial`) · `core/scan_authority.py` (F1: consumed authority is SPENT — `is_bound()` false and `require_bound_evidence()` refuses `consumed` after `consume_binding()`; F2: a stated amount is value + food unit — the bare-number alternative is gone, and a bare deictic no longer counts as a fresh signal; F3: `identity_residual()` — content words nothing accounts for; non-empty residual with no verified mention refuses `unattributed_identity_words` instead of taking the identity-free amount path, so a producer that relabels EVERY carrier cannot erase the conflict it is checked against; F4: Unicode tokenizer (`\w`, the `normalize_name`-empties-Cyrillic lesson) and exact-or-stemmed matching only — no prefix identity, kind≠kindly, quest≠question) · `core/turns/entrypoint.py` (F1: `_claim_scan_state` — a claim failure CLEARS the holder (the turn runs unscanned, loudly) and refuses by propagation when even the clear fails; never continues over unclaimed state; refusal copy for `consumed` and `decision_conflict`).
* **Invariant established**: the authority lifecycle is immutable and terminal (decide-once, consume-spends, claim-or-clear); identity-free binding requires a real parsed amount or consumption language — never a bare number, deictic, or hallucinated subject; an erased user mention refuses rather than falling through to the amount path; tokenization is Unicode and matching exact/stemmed; verified evidence always carries a usable product identity, so the gate (never the executor) refuses nameless snapshots.
* **Focused tests and mutations**: Phase 1 proof file now 55 passed (new: F1 decide-terminal, consumed-spent, claim-clears-or-refuses; F2 glucose/version/`it was 110`/`around 2`/bare-deictic red twins; F3 relabel-every-carrier strict UNDECIDABLE naming the erased words; F4 Cyrillic mention + kind/kindly, quest/question; F5 construction + gate refusal for nameless snapshots). Seven scan suites: 226 passed, exit 0. **Mutation sweep: 31 mutations (M1–M21 rerun post-patch + N1–N10), every one printed `applied` and went RED.** N5 (bare-number amount) was GREEN on its first run — the glucose/version twins were masked by the residual check — and got the unmasked `it was 110`/`around 2` twins before passing red.
* **Full suite**: 9785 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `7b6360a6211c` before = after, `TEST_POSTGRES_URL` set (both PG races ran).
* **Migration impact**: none.
* **Deploy status**: NOT deployed; not deploy-approved.
* **Production evidence**: none (no canary before Phases 2–6).
* **Remaining blockers**: Phases 2–6, canaries A/B/C, Phase 8 — plus the two explicitly preserved **deploy blockers** below.
* **P17g: BLOCKED**
* **END-TO-END SCAN: BLOCKED**

## Deploy blockers (open — must close before any deploy, tracked under Phase 4)

1. **Acquisition returning None silently drops the scan attempt** — `attach_acquired(None)` does nothing, so a barcode that failed acquisition leaves no attachment and the message continues UNBOUND, indistinguishable from an unscanned turn (`api/chat.py`). Required: a failed acquisition still records the scan attempt so the turn refuses (`identity_unknown`) rather than running unbound.
2. **WebSocket coalescing keeps only the newest barcode** — two distinct scans in one coalesced send never reach the attachment-conflict authority (`api/chat.py` `_pending["barcode"] = barcode` overwrites). Required: every received barcode reaches `attach()` so two distinct codes refuse as `ATTACHMENT_CONFLICT`.

## Phase 1 second review round — blockers 1–3 closed (2026-08-20)

* **Exact SHA**: `e6ecac3` (on `1558a09`; `6ea5923` confirmed docs-only).
* **Files materially changed**: `core/turns/entrypoint.py` (B1: `_claim_scan_state` returns a typed `ScanAuthorityRefusal("claim_failed")` after clearing; `run_turn` answers it through `_result_from_state` via `_PreCoordinatorRefusal` — one result assembly; refusal copy) · `core/scan_authority.py` (B2: the no-unit `half a` / `half of` alternative deleted from `_AMOUNT_RE`; B3: `identity_residual` replaced by `unaccounted_identity` — a positive utterance grammar over closed roles, with the EVIDENCE role reading the label's raw words) · the Phase 1 proof file.
* **Invariant established**: a scan-state claim failure refuses the whole turn, non-mutating, through the real response seam — never continues unscanned; a stated amount is value + food unit; and identity is decided by positive accounting (every token has a role, or the turn refuses), so a producer that relabels every carrier cannot erase the words it is checked against.
* **Focused tests and mutations**: Phase 1 file 64 passed (new: full-turn claim-refusal proof with zero writes and session recovery; `half a` / `half of` negatives and `half a bar` / `half of a bar` positives; relabel-every-carrier twins for `I had 2 plain bars` and `I had 2 Perfect Bars`; the protein-bar pair proving evidence — not a list — accounts for generic words). Seven scan suites 237 passed. **7 new mutations (B1a, B1b, B2, B3a–B3d) each printed `applied` and went RED; 38 across the phase.**
* **Full suite**: 9794 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `99f9b0aad661` before = after, `TEST_POSTGRES_URL` set (both PG races ran).
* **Migration impact**: none.
* **Deploy status**: NOT deployed; not deploy-approved. Phase 2 not started.
* **Production evidence**: none.
* **Remaining blockers**: Phases 2–6, canaries A/B/C, Phase 8, and the two preserved deploy blockers (acquisition-`None` unbinds silently; WS coalescing drops a second barcode).
* **P17g: BLOCKED**
* **END-TO-END SCAN: BLOCKED**

## Phase 1 third review round — grammar defects 1–2 closed (2026-08-20)

* **Exact SHA**: `504b0cd` (on `e6ecac3`; `eeefb85` confirmed docs-only).
* **Files materially changed**: `core/scan_authority.py` (closed class trimmed to genuinely closed word classes — adjectives out, `one`/`ones` no longer deictics; `identity_modifiers()` adds the POSITIONAL rule over `QUANTITY [determiner|of]* X* UNIT`; `_UNIT_FORMS` declares the unit forms once and both `_UNIT_WORDS` and `_unit_vocabulary()` are generated from it) · `core/turns/entrypoint.py` (refusal copy for `unaccounted_identity`) · the Phase 1 proof file.
* **Invariant established**: a token's role depends on its POSITION — anything in the modifier slot of a quantity phrase is a product-identity claim whatever global role it has, so `2 Good Bars`, `2 ONE bars`, `2 other bars` and `2 different bars` refuse while `2 bars`, `half a bar`, `2 of these bars` and `2 Barebells bars` still bind; and the amount parser and the grammar share ONE declaration of the unit forms, so a unit the parser accepts can never be unaccounted identity.
* **Focused tests and mutations**: Phase 1 file 82 passed; seven scan suites 255 passed. **Mutations C1, C2, C3, C4, C6 and C5′ each printed `applied` and went RED** — C5 as first written was GREEN (scraping a plain literal alternation yields the right words; the defect needs the hand-written regex too) and was replaced by C5′, which reproduces the reported failure exactly. 44 mutations across the phase.
* **Full suite**: 9812 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `c33f2c05467e` before = after, `TEST_POSTGRES_URL` set (both PG races ran).
* **Migration impact**: none.
* **Deploy status**: NOT deployed; not deploy-approved. Phase 2 paused.
* **Production evidence**: none.
* **Remaining blockers**: Phases 2–6, canaries A/B/C, Phase 8, and the two preserved deploy blockers.
* **P17g: BLOCKED**
* **END-TO-END SCAN: BLOCKED**

## Phase 1 fourth review round — the quantity grammar is one typed parser (2026-08-20)

* **Exact SHA**: `2edab8c` (on `504b0cd`; `b3324dd` confirmed docs-only).
* **Files materially changed**: `core/scan_authority.py` (the `AmountPhrase` dataclass and `parse_amount_phrases()`; `fresh_statement_signal` and `unaccounted_identity` both read its spans; the hand-written `_AMOUNT_RE` and the global quantifier list are retired) · the Phase 1 proof file.
* **Invariant established**: one grammar produces typed spans and both readers consume them, so the amount signal and the identity accounting cannot disagree. Only a quantifier INSIDE a parsed quantifier span is accounted as a quantifier — "2 bars from ONE" and "2 bars by ONE" are identity claims about ONE and refuse — while multi-word quantifiers the parser recognises ("a couple of bars", "a few bars") are accounted everywhere and bind.
* **Focused tests and mutations**: Phase 1 file 91 passed; seven scan suites 264 passed. **Mutations D1–D6 each printed `applied` and went RED**; D5's first anchor matched nothing — no `applied` was printed, so that green was the unmutated tree's and was discarded, then rerun red against both deictic-head branches. 50 mutations across the phase.
* **Full suite**: 9821 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `6c63cadf9599` before = after, `TEST_POSTGRES_URL` set (both PG races ran).
* **Migration impact**: none. **Deploy status**: NOT deployed; not deploy-approved. Phase 2 paused.
* **Remaining blockers**: Phases 2–6, canaries A/B/C, Phase 8, and the two preserved deploy blockers.
* **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**

## Phase 1 — article-quantity regression closed (2026-08-20)

* **Exact SHA**: `088fd35` (on `2edab8c`; `8c6af90` docs-only).
* **Files materially changed**: `core/scan_authority.py` (`_ARTICLE_CORES`; the parser's quantifier branch) · the Phase 1 proof file.
* **Invariant established**: `a`/`an` head the quantifier when they introduce no other core, so "a bar", "an ounce", "a serving" state an amount again; `the` does not quantify; and an article quantity still checks the identity it names ("a Barebells bar" binds only against a Barebells label).
* **Focused tests and mutations**: Phase 1 file 98 passed; seven scan suites 271 passed. **E1 (article-core branch removed) and E2 (`the` as a core) each printed `applied` and went RED.** 52 mutations across the phase.
* **Full suite**: 9828 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `b150fb9c677d` before = after, `TEST_POSTGRES_URL` set (both PG races ran).
* **Migration impact**: none. **Deploy status**: NOT deployed; not deploy-approved. Phase 2 paused.
* **Remaining blockers**: Phases 2–6, canaries A/B/C, Phase 8, and the two preserved deploy blockers.
* **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**

## Phase 2 — canonical-operation durability (2026-08-20)

* **Exact SHA**: `d749a4f` (on `088fd35`, Phase 1 signed off).
* **Files materially changed**: `core/b1_quantity_operation.py` (payload carries `fingerprint_version`, `fingerprint` and `capability`; `StoredFingerprintVersionMismatch`; `_stored_open_result` verifies operation id / user / domain / turn, validates `schema_version`, decodes the item strictly and reads the STORED fingerprint rather than recomputing under today's rules; `OpenResult.capability`; `owning()` strict on schema and item) · `core/product_bound_ask.py` (opens with the channel, renders `opened.capability`) · new `tests/test_p17_phase2_canonical_operation_durability.py`.
* **Invariant established**: a persisted operation is proved before it is reused — its rules, its schema, its item, its owner and its digest — and a reuse renders only what persisted. A refusal writes nothing and leaves the session usable. `oneask001` stays a backstop: the application keeps one awaiting operation per user without the constraint ever firing.
* **Focused tests and mutations**: 31 in the Phase 2 file; 287 with the scan suites. **Mutations P1–P11 each printed `applied` and went RED.** The first by-construction gate was a grep trap (it matched its own docstring) and is now structural.
* **Full suite**: 9859 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `ed0ad8f143c5` before = after, `TEST_POSTGRES_URL` set (both PG races ran).
* **Migration impact**: none — the new payload fields are additive and unknown fields were already tolerated by readers.
* **Deploy status**: NOT deployed; not deploy-approved.
* **Remaining blockers**: Phases 3–6, canaries A/B/C, Phase 8, and the two preserved deploy blockers.
* **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**

## Phase 2 second review round — durability gaps 1–3 closed (2026-08-20)

* **Exact SHA**: `15b5da5` (on `d749a4f`; `676f359` docs-only).
* **Files materially changed**: `core/conversation.py` (the version mismatch joins the canonical-refusal tuple) · `core/b1_quantity_operation.py` (`_decode_stored_payload` shared by the reuse seam and `owning()`; `fingerprint_of_payload` hashes the STORED FORM; the answer merge re-derives the digest under its lock; locale/cohort/capability required; `RECOGNISED_CAPABILITIES` validated on read and write) · `core/canonical_lane.py` (`capability_for`, so only the lane module reads the channel table) · `core/product_bound_ask.py` (takes the capability from the lane, not the table; renders exactly the persisted one) · two multi-field fixtures keep their digest consistent.
* **Invariant established**: a stored operation is verified identically wherever it is read — reuse or consumption — and a failure preserves ownership and repairs rather than falling to legacy; every rendering fact is persisted, required and validated, never synthesized from the live turn; and a fingerprint-version refusal is a canonical refusal, never a legacy question.
* **Focused tests and mutations**: 46 in the Phase 2 file; 265 across every operation-related suite. **Mutations Q1–Q9 each printed `applied` and went RED** (20 for Phase 2).
* **Two real defects surfaced and fixed**: the digest was computed over the interaction OBJECT rather than the stored payload (`to_payload(from_payload(p))` is not identity, so a legitimate multi-field ask read back as tampered and the operation FAILED under the user); and a shape change legitimately rebuilds the interaction at the answer merge, so the digest is re-derived at that one write.
* **Full suite**: 9876 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `ede60bb29ca5` before = after, `TEST_POSTGRES_URL` set. ⛔ The prior run for this phase reported **PYTEST_EXIT=1 with 8 failures** and was not green; it is recorded here as such.
* **Migration impact**: none. **Deploy status**: NOT deployed; not deploy-approved. Phase 3 paused.
* **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**

## Phase 2 third review round — durability blockers 1–2 closed (2026-08-19)

* **Exact SHA**: `31c5daa` (on `f35155f`). **Held UNPUSHED pending sign-off** — `origin/main` is `f35155f` and main auto-deploys, so pushing would be a deploy, which this phase forbids.
* **Files materially changed**: `core/b1_quantity_operation.py` · `core/pending_repository.py` · `core/b1_answer_turn.py`.
* **Invariant established**: every mutation of a canonical operation is decided from the row as it exists **under the lock** — refreshed, strictly decoded, fingerprint-verified — and the caller cannot keep reading its pre-lock copy, because the post-lock authority arrives as one immutable `HeldAnswerResult` carrying a NEW frozen `OwnedOperation`. Unreadability is decided in exactly ONE place: an operation whose payload cannot be read still **owns** the meal and routes to repair; only a positively recognised different slice is skipped.
* **Blocker 1 — the locked mutation rests on verified locked authority.** `hold_answer()` executes the required sequence: lock with `populate_existing=True` (SQLAlchemy does not repopulate a row already in the identity map, so the "locked" payload was the pre-lock snapshot) → strictly decode and fingerprint-verify the refreshed payload → recheck locked status/storage and confirm `patch.field_id` still exists in the LOCKED interaction (else `StaleAnswerField`) → merge → reconcile and rebuild **from the locked interaction and item** → recompute the digest over the verified resulting payload → write once → construct a new frozen `OwnedOperation`. Both answer branches consume the transition and translate `StaleAnswerField` into `Outcome.REFUSED` / `refusal_reason=stale_field`. This removes a **latent `FrozenInstanceError`**: `owned.interaction = rebuilt` would have raised on every shape change.
* **Blocker 2 — "not proven to be B-1" is not "safe for legacy".** The prefilter now decides one thing only: is this a positively recognised DIFFERENT slice (`RECOGNISED_OTHER_SLICES`, empty today). The **second door is deleted** — it used to detect invalid JSON, a non-object payload and a missing/unknown slice itself and return the repairing operation, pre-empting the strict decoder and having to agree with it forever. All four cases are already refused by `_decode_stored_payload`; the one door now reports the precise reason the deleted branch gave.
* **The two mutations that were GREEN, and why neither needed merely more assertions**:
  * **R5** was **masked by its own subject** — `_reconcile_after` unions the HELD answers' attributes into `previously_active`, so the field the old proof checked was present under both shapes. The real defect is sharper: `next_generation` rebuilds every group from `renderable(active=reconciliation.active)`, so an attribute missing from that set is **deleted from the ask**. The new proof answers the one unconditional yes/no that activates two conditional attributes (a legitimate rebuild) while a concurrent writer adds an **unanswered** `preparation` field; computed from the pre-lock shape that question silently disappears while the answer commits normally. RED.
  * **R9** survived because **the guard was redundant** — with it disabled, all four malformed-payload cases still preserved ownership. Making it bite would have meant asserting a **log string**, a grep trap. The redundancy was removed instead and the mutation retargeted at the surviving single door, where dropping ownership falls to legacy. RED, 10 failures.
* **Focused tests and mutations**: 58 proofs in the Phase 2 file + 8 in the answer race file (including a real two-session PostgreSQL race where **both** sessions call `owning()` before either calls `hold_answer()`) — **66 passed / 0 skipped, exit 0** with `TEST_POSTGRES_URL`. **Mutations R1–R9: every one printed `applied` and every one went RED** (failure counts 5·5·1·1·1·1·3·2·10). Tree verified mutation-free after the sweep.
* **Full suite**: 9889 passed / 25 skipped / 17 deselected / 4 xfailed, `PYTEST_EXIT=0`, fingerprint `c13db68b9d56` before = after, `TEST_POSTGRES_URL` set (both PostgreSQL races ran; the 25-skip shape confirms this is not the under-inclusive 122-skip run).
* **Migration impact**: none — no schema change; `oneask001` remains head and stays a backstop, not control flow.
* **Deploy status**: NOT deployed, NOT deploy-approved, **not pushed**. No canary attempted.
* **Production evidence**: none — deliberately, no canary before Phases 2–6.
* **Remaining blockers**: Phases 3–6, Canaries A/B/C, Phase 8 incident repair, plus the two preserved **deploy blockers** (acquisition `None` silently unbinds the scan attempt; WS coalescing drops a second barcode before the attachment-conflict authority).
* **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**

### Phase 2 third round — authoritative freeze and review series (2026-08-19)

The report above was written at `4278f9b`, before three further commits. **That earlier 9889-test freeze is superseded**; these are the authoritative numbers.

* **Review series** (`origin/main..`): `31c5daa` (locked authority + one door) · `4278f9b` (report) · `cfe44e0` (the two unproven seams) · `2f23aca` (the race actually exercises a shape change) · `ba64d80` (`HeldAnswerResult` refuses two authorities). Net: 6 files, +993/−16.
* **Pushed to `review/p17-phase2-round3` only. `origin/main` is untouched at `f35155f`.** Note `ci.yml` triggers on push to `main` and PRs *targeting* `main`, so a review-only branch runs **no CI**; a draft PR into main would run CI without deploying (Render auto-deploys from main pushes; `render.yaml` is reference-only).
* **Full suite, frozen**: **9892 passed · 25 skipped · 17 deselected · 4 xfailed · `PYTEST_EXIT=0`** in 397.30s, zero `FAILED`/`ERROR` lines in the log, tree fingerprint **`e3b0c44298fc` before = after** (an empty diff — the tree was fully committed), `TEST_POSTGRES_URL` set. The 25-skip shape confirms the PostgreSQL races ran (not the under-inclusive 122-skip run).
* **Focused**: 69 proofs in the Phase 2 file + 8 in the answer-race file — **77 total, 0 skipped, exit 0**.
* **Construction invariant (Danny's)**: `HeldAnswerResult.__post_init__` refuses a result whose `interaction` is not `owned.interaction`, or whose `revision` disagrees with the refreshed locked ROW or with the interaction's generation. Proven at a revision that actually moved (1, not 0 == 0). **The row half is proven independently of the generation half** — bumping `revision` alone trips both, so R13 (row check reduced to a tautology) was GREEN until a case was added that drifts only the row.
* **Mutations**: R1–R9 plus R10 (locked field membership), R11 (rebuilt surface not returned), R12 (`__post_init__` neutered), R13 (row check tautological) — **every one printed `applied` and every one went RED against a reachable, correctly targeted proof**. Reported honestly: R5/R6 are inert against the two-session race (nothing changes the shape before writer A, so its pre-lock state equals the locked one) and are RED in the deterministic proofs that inject a reshape between `owning()` and the lock.
* **Deploy status**: NOT deployed, NOT deploy-approved, **not on main**. No canary attempted. **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**. Phase 2 closes and Phase 3 begins only after sign-off on the reviewed series.

## Phase 2 fifth review round — the digest signs the held answers, `fp2` (2026-08-20)

* **Finding (Danny)**: `answered` sat OUTSIDE the fingerprint. Strict decoding rejects a MALFORMED held patch but cannot see a well-formed one swapped for another well-formed one, so an edit landing between `owning()` and the lock — 120 g becomes 900 g — was indistinguishable from what the user said, and `hold_answer` treated it as persisted authority.
* **`FINGERPRINT_VERSION` → `fp2`**, because this changes what the digest MEANS. The new argument is **required positional**, so every site that signs a payload had to be visited rather than silently signing a body without the answers — four call sites announced themselves that way (two in the first pass, two more in the freeze).
* **The digest was answering two questions and only one wants the answers.** "Has this row been altered?" must cover them. "Is this the same ask I would have written?" must NOT — an awaiting operation may legitimately already hold an answer, and a same-turn retry would then compare a fresh ask against a stored one and refuse a valid reuse. Identity moved to `ask_fingerprint()`: **derived at read time, never persisted**, so there is no second stored digest to fall out of agreement with the first. `OpenResult.ask_identity` sits beside the stored `fingerprint`; reuse compares identity, integrity having been proved by the strict decoder above it.
* **Verified under the lock** before any held answer is accepted, and **recomputed in the same single write** whenever answers change.
* **Fail-closed for rows already in flight**: an AWAITING operation written under `fp1` is not comparable and is NOT re-judged under today's rules. It still **owns** the meal (it does not read as unowned, so nothing falls to legacy), settles nothing, writes nothing, and is left exactly as it was — old version marker included.
* **Operational consequence, stated plainly**: at deploy, any awaiting canonical operation written under `fp1` stops being answerable and that user must be re-asked. The lane is allowlist-gated, so that cohort is the blast radius. Pre-deploy check: ⛔ **the query first published here was WRONG on two fields** (`domain='chat_quantity'`, `status='awaiting'`; production writes `DOMAIN = "food"` and `AWAITING = "awaiting_answer"`), so it would have reported zero while fp1 operations were still live — the exact failure it exists to prevent. The corrected query is in the sixth-round section below.
* **Honest scope note**: the digest is **not a MAC**. Anything that can edit the row can recompute it, so it detects edits that do not re-sign; malformed content is refused independently by the strict decoder. That is why the malformed proof now **re-signs on purpose** — otherwise the new digest refuses it first and masks the decoder that proof exists to test.
* **The version check is redundant for integrity** and is reported as such rather than given a manufactured proof: an `fp1` row fails the digest comparison anyway, because the version is inside the hashed body. Its value is a distinct diagnosis (`StoredFingerprintVersionMismatch`) routing to the same fail-closed repair.
* **Proofs**: a well-formed answer substituted before the lock refuses with payload and digest unchanged · the malformed case (re-signed, isolating the decoder) refuses without deleting the entry, through a real answer turn with no food row, no ledger event, no legacy · an awaiting `fp1` row fails closed the same way.
* **Mutations**: R17 (digest stops covering the answers) RED · R14 (answers decoded permissively again) RED · R9-family (unreadable row loses ownership) RED · R12, R15, R16 re-verified RED.
* ⛔ **THE FIRST fp2 FREEZE WAS RED AND IS RECORDED AS SUCH**: `PYTEST_EXIT=1`, 3 failed + 5 errors, while the shell reported "exited with code 0". Two multi-field fixtures still signed without the answers. Fixed, then the whole tree swept by AST for wrong-arity calls rather than finding them one suite at a time.
* **Authoritative freeze**: **9897 passed · 25 skipped · 17 deselected · 4 xfailed · `PYTEST_EXIT=0`**, zero `FAILED`/`ERROR` lines, **`HEAD` `c79b34b` and `HEAD^{tree}` `cf44bc4` identical before and after** (dirty-diff hash kept only as a worktree-clean witness — it is `sha256("")` and proves nothing about the committed tree), `TEST_POSTGRES_URL` set.
* **Deploy status**: NOT deployed, NOT deploy-approved, not on main. **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**.

## Phase 2 sixth review round — whole-payload envelope, and the SQL gate corrected (2026-08-20)

### 1. The pre-deploy query was wrong on two fields

Published as `domain='chat_quantity'` / `status='awaiting'`. Production writes `DOMAIN = "food"` (`core/b1_quantity_operation.py:38`) and `AWAITING = "awaiting_answer"` (`:68`), so the query **would have reported zero while fp1 operations remained active** — the operational failure it was written to prevent. Corrected (Danny's form, verified against the constants and against `canonical_payload` being a nullable `Text` column, so the `::jsonb` cast is valid):

```sql
SELECT
    operation_id,
    user_id,
    created_at,
    canonical_payload::jsonb->>'fingerprint_version' AS fingerprint_version
FROM pending_operations
WHERE domain = 'food'
  AND status = 'awaiting_answer'
  AND storage_status = 'active'
  AND canonical_payload::jsonb->>'slice' = 'b1_quantity'
  AND COALESCE(canonical_payload::jsonb->>'fingerprint_version', '') <> 'fp2';
```

⚠ `canonical_payload` is nullable `Text`: if any row holds text that is not valid JSON the cast raises for the whole query. Such a row is itself a finding — it would refuse at runtime too.

### 2. `answered` was coerced before it was checked

`data.get("answered") or {}` turned `null`, `[]`, `""`, `0` and `false` into a valid EMPTY answer map **before** the `isinstance` check could see any of them, so a payload nothing legitimate wrote decoded as "this ask has no answers yet". Now `data.get("answered", {})` then the type check: **absent is a fresh ask; present-and-not-an-object refuses.** The same `or {}` is gone from the digest, which is what had made `{}` → `[]` fingerprint-equivalent.

### 3. Digest scope — widened rather than narrowed

The claim could have been narrowed to "settlement-material integrity". It was widened instead: **the digest signs the whole payload minus its own digest**, so `locale`, `cohort`, `capability`, `decision_id`, `candidate_set_id`, `asked_at` and the retraction history are all covered — every one of them an authority something reads (the reply renders in `locale`, the client contract is `capability`, the funnel joins on `cohort`). A field added later is signed because it is IN the payload, not because someone remembered a list.

Safe for a checked reason: `canonical_payload` has exactly **two** writers — the insert at open and `LockedOperation.write` under the lock — and both sign; all four `save_revision` call sites change status columns only. Signing moved INTO `_encode`, so the value signed and the value stored are no longer two statements that must agree.

**Not a MAC**: anything that can edit the row can recompute it. It detects edits that do not re-sign; malformed CONTENT is refused independently by the strict decoders. Both the malformed-answer and non-object-answer proofs therefore **re-sign on purpose**, isolating the decoder from the digest.

* **Consequence that confirms the widening bit**: the locked-metadata proof now performs a LEGITIMATE re-signed write, because an unsigned `locale`/`cohort` edit is correctly tampering under the new envelope.
* **Mutations**: R18 (`or {}` coercion restored) RED on all five parametrisations (`[]`, `""`, `0`, `False`, `None`); R14, R17 and the R9-family re-verified RED.
* **Authoritative freeze**: **9902 passed · 25 skipped · 17 deselected · 4 xfailed · `PYTEST_EXIT=0`**, zero `FAILED`/`ERROR` lines, **`HEAD 9a71764` and `HEAD^{tree} 41179f6` identical before and after**, `TEST_POSTGRES_URL` set.
* **Deploy status**: NOT deployed, NOT deploy-approved, not on main. **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**.

## ⛔ MANDATORY PHASE 6 PRE-DEPLOY GATE — fp1 awaiting operations (Danny, 2026-08-20)

**Rerun this IMMEDIATELY BEFORE deployment, not once at review time.** Awaiting operations are created by live traffic, so a clean result today says nothing about the moment the deploy lands. `fp2` changes what the digest means: any awaiting operation still carrying `fp1` stops being answerable the instant the new build serves, and that user must be re-asked.

```sql
SELECT
    operation_id,
    user_id,
    created_at,
    canonical_payload::jsonb->>'fingerprint_version' AS fingerprint_version
FROM pending_operations
WHERE domain = 'food'
  AND status = 'awaiting_answer'
  AND storage_status = 'active'
  AND canonical_payload::jsonb->>'slice' = 'b1_quantity'
  AND COALESCE(canonical_payload::jsonb->>'fingerprint_version', '') <> 'fp2';
```

* **Zero rows** → proceed.
* **Any rows** → those users lose their open question. Decide deliberately: hold the deploy, or accept and re-ask them. Do not discover this after the fact.
* The constants are `DOMAIN = "food"` and `AWAITING = "awaiting_answer"` (`core/b1_quantity_operation.py:38`, `:68`). ⛔ An earlier version of this gate used `domain='chat_quantity'` / `status='awaiting'` and would have reported zero while fp1 operations were live.
* ⚠ `canonical_payload` is nullable `Text`: a row holding non-JSON text makes the `::jsonb` cast raise for the whole query. That row is itself a finding — it would refuse at runtime too.

## Phase 2 — CLOSED PENDING CI (2026-08-20)

Danny's verdict on `9a71764`: **code approved, no additional correctness blockers.** Confirmed by him: whole-payload fingerprinting centralised in `_encode`; only the fingerprint itself excluded from the signed envelope; locked answer transitions re-sign the complete resulting payload atomically; missing `answered` means fresh while every present non-object form refuses; ask identity separate from mutable operation integrity; the corrected query uses the real constants; the freeze valid with code `HEAD 9a71764` / tree `41179f6` pinned; `9fc8b4b` documentation-only over that frozen code; branch 13 commits ahead with main untouched.

Gate state: code review ✅ · frozen PostgreSQL suite ✅ · **draft PR ❌ not opened** · GitHub CI ⏳ no checks on `9fc8b4b` · deploy approval ❌ · **P17g / END-TO-END SCAN: still BLOCKED**.

**Phase 3 begins only after CI is green on the PR.**
