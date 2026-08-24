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

## Phase 2 — CODE REVIEW APPROVED, FORMAL CLOSURE PENDING CI (2026-08-20)

Danny's verdict on `9a71764`: **code approved, no additional correctness blockers.** Confirmed by him: whole-payload fingerprinting centralised in `_encode`; only the fingerprint itself excluded from the signed envelope; locked answer transitions re-sign the complete resulting payload atomically; missing `answered` means fresh while every present non-object form refuses; ask identity separate from mutable operation integrity; the corrected query uses the real constants; the freeze valid with code `HEAD 9a71764` / tree `41179f6` pinned; `9fc8b4b` documentation-only over that frozen code; branch 13 commits ahead with main untouched.

Gate state: code review ✅ · frozen PostgreSQL suite ✅ · **draft PR ❌ not opened** · GitHub CI ⏳ no checks on `9fc8b4b` · deploy approval ❌ · **P17g / END-TO-END SCAN: still BLOCKED**.

**Phase 2 code review approved; formal closure pending GitHub CI. Phase 3 development may proceed on a separate stacked branch. Not deploy-approved.**

⛔ An earlier revision of this section was headed "CLOSED PENDING CI" and described Phase 2 as closed. It was not, and is not: approval of the code is not closure of the phase. Closure requires CI green on the draft PR from the pinned review branch.

Branch topology: `review/p17-phase2-round3` is PINNED at the docs-only head below and receives no further pushes unless CI finds a defect. Phase 3 lives on `review/p17-phase3-cf14`, stacked on that head — no Phase 3 commit enters the Phase 2 PR.

## Phase 2 seventh review round — the ask identity is the stored ORIGINAL (2026-08-20)

* **Finding (Danny, after CI green on `477ce30`)**: the generation-strip fix was insufficient. A **real** B-1.6b shape change alters the FIELD SET — "yes, fat was added" retires `added_fat_present` and activates `added_fat_amount` + `added_fat_identity` — so the rebuilt surface hashes differently no matter which keys are stripped, and a delayed retry of the original opening turn refused `OpenedElsewhere` instead of reusing. The prior "shape change" retry proof re-issued the SAME fields at a new revision, so it could not see this.
* **Fix**: `ask_identity` is derived once at open and **persisted** — written by `_encode` (inside the fp2 whole-payload envelope, so an unsigned edit is caught by the digest), **required and non-empty** at the strict decode (presence alone would let `""` refuse every legitimate retry while looking like a working check), **preserved through every rebuild** (`hold_answer` merges into the stored dict and never touches it — proved by mutation H4, not assumed), and **reuse compares against the stored value**. The current interaction no longer participates in identity. `_without_generation` stays for open-side stability and the meaning-sensitivity boundary.
* **The required proof runs the real path**: conditional ask → `SetAddedFatPresent(present=True)` through `hold_answer` (revision 0→1; an in-proof guard asserts the field set actually changed) → retry of the original opening turn → **one operation, `created=False`, the rebuilt current surface rendered, identity unchanged**. Twins: edited identity refuses via the envelope; dropped-and-re-signed refuses via the required check, ownership preserved both times.
* **Mutations, each `applied` and RED**: H1 reuse derives from the CURRENT interaction again (the finding verbatim) · H2 open stops persisting · H3 required/non-empty checks removed · H4 `hold_answer` drops it on rebuild.
* **Authoritative freeze**: **9908 passed · 25 skipped · 17 deselected · 4 xfailed · `PYTEST_EXIT=0`**, zero `FAILED`/`ERROR` lines, **`HEAD 9f3eff4` and `HEAD^{tree} ffa9b1d` identical before and after**, `TEST_POSTGRES_URL` set. Focused + adjacent suites 202 passed.
* **PR #77 converted back to DRAFT** — it had been flipped Open/mergeable by something outside this session (`chatgpt-codex-connector[bot]` appears in reviewers; parallel sessions run against this repo). The draft state is a guard that can be flipped again; the durable guard remains that nothing merges without Danny's decision.
* **Deploy status**: NOT deployed, NOT deploy-approved, not on main. **P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED**. Awaiting re-review of the pushed head, then the fp1 production gate, then the merge decision.

## Phase 2 — MERGED, DEPLOYED, AND ONE POST-MERGE BLOCKER REMEDIATED (2026-08-20)

### What actually happened, in order

1. **Quiesce.** `B1_QUANTITY_HALT=1` was **not** set when the halt was ordered; it was added in the Render dashboard via **"Save and deploy"** — "Save only" stores the variable *without restarting*, so the halt would have existed in the dashboard and nowhere else. Restart live 12:09 on `ed97f7a` (37.8s).
2. **Authoritative fp1 gate, quiesced: ZERO rows** — 0 non-fp2, and 0 awaiting `b1_quantity` of *any* version (db clock 16:12Z).
3. **CI green** on `8b6c257`. **PR #77 merged as `71da768`.**
4. **Tree verified**: `origin/main^{tree}` = `50847ae` = `8b6c257^{tree}`; parents exactly `f35155f` + `8b6c257`. `release_check.py`: DEPLOYABLE.
5. **Deploy of `71da768`** — built in 50s, then the instance took 3m23s to bind its port and was not promoted for 22 minutes. Cancelled; two retry submissions created **no deploy row at all**. Cause: **an active Render platform incident** ("Deployment Issues", upstream Google Cloud), not the code.
6. ⛔ **THE CANCELLED DEPLOY PROMOTED ANYWAY, LATE.** `/health` now reports **`71da768`**. An interim report of "not deployed" was **wrong** and is corrected here. Auto-deploy remains disabled; this was the manual deploy landing after the incident, not an auto-deploy.

### Why the live build is safe despite the blocker below

The running app reports its own effective state: **`B1_QUANTITY = {"effective": "halted", "halted": true, "percent": 0.0, "allowlist_size": 1}`** — quiesced, not merely quiet. With **0 awaiting operations** and **0 operations created in 3h**, no answer transition can occur, so the defect is **unreachable in production**. No legitimate write can produce the bad payload either: `_encode` writes `locale or "en"`, always non-empty, so reaching it requires an external edit **plus** a re-sign.

### The blocker (Danny, post-merge review) — remediated on `fix/p17-strict-locale`

`_decode_stored_payload`'s required-key loop asked only whether `locale` **exists**, so `locale: ""` and `locale: null` decoded happily, and the two readers of one row disagreed:

| reader | code | result |
|---|---|---|
| ask path | `str(data["locale"])` | `""` — or the literal `"None"` |
| answer path | `str(… or "en")` | `"en"` |

A fingerprint-valid persisted authority **silently changed across an answer transition** — the one thing the whole-payload envelope exists to prevent. Same family as `answered or {}`: a falsy value coerced past its own type check by a second opinion downstream of the decoder that had already verified the row.

**Strictness calibrated to what the seam writes** — the part needing judgement rather than rigour:

* `locale` is written `locale or "en"` → always non-empty → **must be a non-empty `str`**.
* `cohort` is written `cohort or ""` → **empty is legitimate** → type-checked only. Rejecting `""` would refuse rows the open seam itself produces while looking like rigour (mutation **L4** proves that overreach fails).

The transition now **subscripts** (`_locked_data["locale"]`) rather than defaulting: if the decoder's guarantee regresses, it raises loudly instead of inventing `"en"` under the user.

* **Proofs**: `""`, `null`, an int and a list each refuse on **both** paths, ownership preserved, no mutation · one row cannot state two locales · a non-string cohort refuses (the funnel joins ask to answer on that field; `"26"` vs `26` breaks the join every promotion decision is read from) · an **empty** cohort still decodes. Every proof **re-signs** the edited payload on purpose — otherwise the envelope refuses first and the check under test is never reached.
* **Mutations, each `applied` and RED**: L1 presence-only decode · L2 the original defect with both halves restored · L3 cohort type check removed · L4 strictness overreaches. ⛔ **L3 was GREEN on the first sweep — not masked, not redundant, simply UNTESTED**; the non-string cohort proof was added for it, and it surfaced a second real divergence.

### Order from here

1. ✅ Verify no auto-deploy (disabled; the live build is the manual deploy of the merged SHA).
2. Remediation PR on its exact head → **CI green on that head**.
3. **Quiesced fp1 gate rerun** before rollout is re-enabled.
4. `B1_QUANTITY_HALT` **stays set** until 2–3 are done; it is what makes the live blocker unreachable.
5. Then restack Phase 3 (`review/p17-phase3-cf14`) on merged main.

**P17g: BLOCKED** · **END-TO-END SCAN: BLOCKED** · rollout NOT re-enabled.

---

## TRANCHE Q — rounds 2–3 (2026-08-20, PR #79, unmerged)

Ordered by Danny **ahead of Phase 3**, from the live canary that logged
170.1 g against a stated 100 g. Round 1 (the raw-substring fix) was approved;
rounds 2–3 are the two blockers found after it.

### Round 2 — the eval battery's flake was hiding a regression

The `environment: Cloud` fix made the battery genuinely run (3m 47s, 22 cases
× 3 reps) instead of aborting at the key gate in 27 s. Result: 21/22 clean,
0 failed outright, 1 flaky — and the flaky case's two failing reps were
**Anthropic credit exhaustion**, not behaviour.

⛔⛔ **Chasing it found a regression this branch introduced, in both
directions.** The case is `"had a bowl of white rice and two fried eggs"`,
expecting an ask. Measured against deployed main `76076b6`:

| case | main `76076b6` | PR `41297ca` | fixed |
|---|---|---|---|
| `a bowl`, `basis=estimate`/`regular` | False | **True** ← regression | False |
| `a bowl`, no `basis` | True | True | True |
| `two fried eggs`, `basis=estimate` | False | False ← req. 1 unmet | True |
| `100g` chicken, `basis=estimate` | False | True | True |
| `a scoop` as `1 tbsp` | False | False | False |

**Over-reach.** `normalize_quantity("a bowl of white rice")` reports
`user_stated_amount=1`, identical to `"1 bowl"`, because it reports what a
phrase **denotes** — not whether the user counted anything. Harmless while the
`basis` veto sat above that rung; moving the veto below it (so a typed `100g`
could outrank `basis`) handed the indefinite article the veto's authority.
⭐ **A GUARD THAT MOVES MUST BE JUDGED AGAINST EVERY PATH IT NOW SITS BELOW.**

The existing bare-article guard missed it because its fixture is `1 tbsp` — a
MEASURED unit, where the unit check vetoes independently. Only a unit carrying
no measure ("bowl") leaves the article alone with the decision. ⭐ **its single
fixture was load-bearing in a way nothing had stated.**

**Under-reach.** `"two fried eggs"` is a quantity the user typed and `basis`
was overruling it exactly as `100g` was: the normalizer takes whatever word
sits where a unit usually sits and reported `user_stated_unit="fried"`, so a
veto built to stop "scoop" masquerading as "tbsp" fired on a word that is not
a unit at all.

### Round 3 — a count has to be THIS food's count (Danny's blocker)

`_literal_amount_with_unit` drops the unit requirement for a COUNT unit —
correctly; people write "15 peanut m&m", never "15 pieces of peanut m&m". The
cost was never stated: with no unit to bind to, **any** number in the clause
satisfied the match, and round 1 had just removed the `basis` veto behind it.

⭐⭐ **THE REPORTED EXAMPLE DOES NOT REPRODUCE.** In `"I had 2 tacos and fried
eggs"`, `_clause_for` already cuts the eggs clause to `"fried eggs"` and the
`2` is never in scope. The defect is real but needs a connective the splitter
does **not** cut on: `"fried eggs after 2 tacos"` → clause
`"fried eggs after 2 tacos"` → stated **True** at `abf615d`. Both shapes are
pinned so the guard cannot be weakened back to the one that happened to be
safe.

Fix: a count literal must bind to this food's own words — its unit or any
recognised word of its name — inside a window that stops at a clause-breaking
connective or at the next number. **Head-noun-only was tried and refused two
shipped fixtures** (`Peanut M&Ms` tokenises to `peanut/m/ms`; the count
precedes an adjective in `"15 peanut m&m"`).

Two things that fix found on its own:

* **the round-2 unit stand-down had the same hole** — it asked whether the
  item's unit appeared *anywhere* in the clause, and in `"fried eggs after 2
  tacos"` the word "eggs" is indeed there. Same question, one helper now.
* ⛔ **sharing ONE noun set between the two callers put the 190-calorie defect
  straight back**: for `"1 scoop of peanut butter"` carried as 1 tbsp the
  food's own name sits beside the number, so a food-word set stood the unit
  veto down. "Does a count belong to this food" and "did the user name this
  unit" are different questions. Caught by the existing guard, same run.

### The battery: an absent answer is not a negative answer

A refused API call was scored `got=None want=ask` and reported
`[FLAKY] … (1/3)`, exit 1 — the battery's **loudest behavioural signal**,
borrowed by an outage. `core/llm.py` swallows the model failure deliberately
(a dead turn must still reply), so the signature is only in the log line it
writes; a handler now watches for it and marks the rep **unscored**.
Three outcomes, three exit codes: **0** clean, **2** not measured, **1**
measured and wrong. Verified without spending credit — the handler catches the
exact billing line from the PR #79 run and an auth line, ignores ordinary and
behavioural lines, and all four classification paths were driven end to end.

### Gates

* **Frozen suite** (PG-inclusive, `TEST_POSTGRES_URL` set) on `81f8605`:
  `PYTEST_EXIT=0`, **9962 passed / 25 skipped / 17 deselected / 4 xfailed**;
  `HEAD` and `HEAD^{tree}` identical before and after; worktree clean both
  times. Baselines: `abf615d` 9949, `0df6a1b` 9960.
  ⛔ **the first round-2 freeze was UNDER-INCLUSIVE** — 9851 passed / **123
  skipped** because `TEST_POSTGRES_URL` was unset; the count is the only thing
  that reveals it, and it was green.
* **Mutations: 9 RED, 0 GREEN, 1 INVALID**, each `applied=1`.
  ⛔⛔ **THE SWEEP WAS WRONG ONCE AND READ AS A FINDING.** M7 mutated
  `_BINDING_BREAK` to `frozenset() or frozenset({...})` — an empty frozenset is
  **falsy**, so `or` returned the full set. `applied=1`, GREEN, nothing
  changed, and it read as "the break words are redundant". ⭐ **`applied`
  proves the anchor matched; it does NOT prove the edit bit.** Every case now
  also measures a behaviour witness on the mutated module and reports
  **INVALID**, not GREEN.
  * **Two guards were real and unproven** — found only because the sweep was
    then honest: the binding **window** (`"2 corn tortilla chicken tinga fried
    eggs"`) and the **next-number break** (`"2 tacos 3 fried eggs"` states
    *three* eggs). Both flipped under mutation with no test noticing. A guard
    nobody can fail is where a guard that isn't there is.
  * **M5 is INVALID / EQUIVALENT — decided by Danny 2026-08-20, KEEP
    `_canon_unit`.** Reverting it to `.rstrip("s")` at the unit comparison
    changes no observable behaviour: the mutation is **equivalent at that
    particular comparison**, which is not evidence the code is harmful or
    unnecessary. Recording it as INVALID/equivalent rather than reverting to a
    second ad-hoc unit-normalisation rule. ⭐ **an equivalent mutant is a
    classification, not a verdict on the code** — the mutation-testing
    literature's own category, and the reason "GREEN" needed five names before
    it needed six.

### Open, and not mine to close

* **The Anthropic balance.** The battery cannot return a verdict until it is
  topped up. That is a payment on Danny's account.
* **Battery rerun** after the top-up — cases scored, not the check colour.

**Tranche D (P0): untouched.** **P17g: BLOCKED** · **END-TO-END SCAN:
BLOCKED** · PR #79 Draft, unmerged, awaiting approval.

### Round 4 (Danny, review of `9c4195b`) — two rungs still unbound

Both checks were green on `9c4195b` and the PR was still not approvable.

**1. `half` and a stated RANGE never bound to their food.** Round 3 bound bare
counts; these two rungs state a quantity *without a digit token* and were left
behind — both bare presence tests, both above the `basis` veto since round 1,
both reachable because `_clause_for` does not split on "after". Measured at
`81f8605`:

| message | item | classified |
|---|---|---|
| `Greek yogurt after half a banana` | 0.5 **cup** yogurt, `estimate` | **stated** |
| `French fries after 5-6 chicken nuggets` | 5.5 **fries**, `estimate` | **stated** |

Both now route through `_binds_nearby` with `_item_nouns` — the same helper the
digit counts use. ⭐ **`_binds_nearby` skips the quantity words themselves**,
which is what lets "half" work with no special case: *half a cup of greek
yogurt* reaches `cup` and binds; *half a banana* reaches `banana` and does not.
The truffle-fries message the range branch exists for still passes.

**2. The infra watcher discarded rescued answers.** `core/llm.py` logs the
primary failure **before** it retries, so every rep an Anthropic fallback saved
still carried the marker and was thrown away as unmeasured. ⭐⭐ **THE SAME
ERROR THE WATCHER EXISTS TO CORRECT, POINTING THE OTHER WAY** — v1 could not
tell an outage from a behaviour; v2 could not tell a recovery from an outage.
Both discard a real measurement.

A marker is now **pending** until the call resolves: a recovery clears it, and
a new PRIMARY failure banks the previous call's markers as dead first, so an
early recovery cannot forgive a later outage. ⛔ **"fallback ALSO failed" is
deliberately NOT terminal** — the OpenAI net runs after it, so a call can still
be answered once both Anthropic models are out; treating it as terminal
discarded exactly the measurement the net saved (found by the OpenAI proof
going red). That net had **no success log at all**, so `core/llm.py` now writes
`openai fallback OK`, symmetric with the Anthropic retry — production could not
previously tell whether the second net had ever caught anything.

⛔ **AND THE PER-REP RESET SILENTLY BROKE**: `hits` became a computed property,
so `main`'s `watch.hits.clear()` cleared a temporary and did nothing. Every
marker would leak into the following reps and one outage would condemn the
whole run **while still looking like a coherent report**. Now `watch.clear()`,
pinned by its own proof.

Five end-to-end scenarios verified without spending credit: all reps refused →
INFRA/2 · one rep refused → INFRA/2 · fallback rescued every rep → PASS/0 ·
**rescued but behaviourally WRONG → FAIL/1** (a recovery must not launder a
wrong answer into "unmeasured") · clean → PASS/0.

### Round 5 (Danny, review of `7fae549`) — nearness is not agreement

Blocker 2 (the infra watcher) **approved**. Blocker 1 was incomplete.

Round 4 bound `half` and a range with `_binds_nearby(..., _item_nouns(it))`,
and `_item_nouns` includes every word of the **food name**. That is right for a
bare count — "15 peanut m&m" binds on "peanut" — and wrong the moment the item
is measured in something the phrase contradicts, because the food's own name
then rescues a unit that disagrees:

| message | item | was |
|---|---|---|
| `half a scoop of peanut butter` | 0.5 **tbsp** | **stated** — "peanut" bound it |
| `5-6 oz grilled chicken` | 5.5 **g** | **stated** — "chicken" bound it |

⭐⭐⭐ **THE SCOOP DEFECT FOR THE THIRD TIME.** The same 190-calorie assumption —
"they said scoop; we said tablespoon" — has now arrived through the raw
substring fallback (round 1 review), through a shared noun set (round 3), and
through the half rung (round 5). **It reappears at whichever door is newest**,
because each new door re-answers "is this the user's number?" without
re-answering "in whose unit?". The second case is a **28× mass error**.

⭐ **THE DIGIT PATH NEVER HAD THIS.** `_literal_amount_with_unit` splits
measured units from counts and demands agreement for the former; round 4 routed
two new paths **around** that distinction instead of through it. It now lives in
one predicate, `_quantity_binds_to_item`, and all three paths go through it:

* **measured item** → the phrase must NAME a canonically compatible unit; the
  food's name cannot stand in for one.
* **count item** → nothing can contradict a count noun, so nearby
  food-or-unit binding is enough.

Eleven proofs: both conflicts, a foreign-food-**and**-conflicting-unit case,
four matching-unit twins (including the unit spelled in full), four count
twins. **Nine of the eleven were green before the fix** — the rule had to be
proven not to cost them.

**Gates.** Frozen suite on `f5ed65f`: `PYTEST_EXIT=0`, **9991 passed / 25
skipped**, HEAD and tree identical before and after. Mutations **6 RED, 0
GREEN, 0 INVALID**.

⭐ **AND ONE WITNESS WAS MIS-CHOSEN, WHICH READS EXACTLY LIKE AN INERT EDIT.**
R5-2 (invert the measured test) first reported `behaviour=SAME` → INVALID,
while pytest was already RED. The witness was a MEASURED item whose unit is
named — and `_item_nouns` is a SUPERSET of `_unit_nouns`, so that case binds
under **both** branches. Inverting the test sends COUNT items down the
unit-only branch, so only a count item can see it. **A behaviour witness has to
be chosen against the mutation's actual reach, not against the defect's
headline case** — otherwise the harness's own safeguard files a working
mutation as invalid.

### The cross-rung conflicting-unit corpus (Danny, approving `90888cf`)

Approved at `90888cf` — CI green with Postgres, battery 22/22 × 3 reps, 0
flaky/failed/infrastructure. The corpus was required before merge because it
proves the tranche's central invariant across every path rather than at the one
that last broke.

    A quantity whose unit contradicts this item's measured unit is NOT the
    user's statement of this item's amount — through ANY path.

⛔⛔ **THE FIRST VERSION OF THE CORPUS WAS A CLAIM, NOT A PROOF.** It ran each
pair through the whole function and labelled it with the rung it was "about".
Instrumented, **8 of 16 compatible twins were answered by the NORMALIZER rung**
— including *every* row labelled `digit` and most labelled `half`. Those pairs
proved the normalizer declines a contradicted unit, three times over, and said
nothing about the rungs they named. ⭐ **A per-rung label is a hypothesis until
something measures which rung answered.**

So each pair now runs with every rung ABOVE the one under test disabled:

| rung | disabled | reached by |
|---|---|---|
| normalizer | — (it is first) | the whole function |
| digit | normalizer | `_literal_amount_with_unit` |
| half | normalizer, digit | `_half_binds_to_food` |
| range | normalizer, digit, half | the stated-range branch |
| refine | normalizer | the refining clause |

Both halves are load-bearing: the **compatible** twin must be True (the rung was
reached and accepts this shape) and the **conflicting** twin must be False (that
rung's own unit check declined it). Without the first, a False proves only that
the message was unreachable — a corpus of unparseable sentences passes by
declining everything.

**Proven to catch a regression AT EACH RUNG, causality checked:** removing the
normalizer's unit check reddens only `normalizer` rows · making the digit rung
treat measured units as counts reddens `digit`/`normalizer`/`refine` · collapsing
the measured/count split in `_quantity_binds_to_item` reddens `half`/`range`.

⭐ **One limit recorded in the file:** the `normalizer` rows disable nothing, so
a True there is attributable to it and a False is **not** — the rungs below also
ran and also declined. Every lower rung therefore has its own isolated rows.

A coverage test fails if a rung has no conflicting pair, no compatible pair, or
is absent from the corpus entirely, so the next path added is covered the day it
is added rather than after it ships.

**Also registered, NOT fixed here** (pre-existing, unchanged by Tranche Q): the
refining-clause matcher keys on the food's HEAD NOUN, so `"some peanut butter,
like 2 tbsp"` is not read as refining the peanut butter — `"butter"` is not
repeated. That is the anti-bleed rule working as designed (it is what stops
"half a banana" refining peanut butter), and widening it is a separate decision.

**Gate.** Frozen suite on `a5d4a80`: `PYTEST_EXIT=0`, **10032 passed / 25
skipped / 17 deselected / 4 xfailed**; HEAD and tree identical before and after.

---

## ⚠ TRANCHE D — MERGED, POST-MERGE REMEDIATION OPEN (2026-08-21)

⛔⛔ **NOT CLOSED.** `ef2bf63` carries two telemetry defects introduced by the
D2 durability fix itself, both found in post-merge review:

* **THE PERSIST-IN-FLIGHT RACE.** `flush_speculative()` returns early unless
  `self._persisted` is set, and `persist()` sets it only *after* the commit. A
  prewarm completing inside that window is dropped by BOTH paths — too late for
  `_stages_for_row()` to have seen it, too early for the flush to act. The
  fix's own contract ("speculative work stays auditable in the persisted row")
  fails exactly when the timing is tightest, which is the case it was written
  for.
* **"LATEST ROW BY turn_id" MISATTRIBUTION.** The flush selects
  `WHERE turn_id = … ORDER BY id DESC LIMIT 1`. ⭐ **turn_id IS NOT UNIQUE, and
  this repository documents that in CF19** — `h:`-prefixed ids are shared by
  genuinely separate requests, one `healthkit:h:` id covering six executions.
  So the flush can fold one request's speculative stage into a DIFFERENT
  request's row. Keying on the very field CF19 registers as ambiguous is the
  defect, not a hardening opportunity.

**Merged**: PR #80 at exact reviewed head `7b1dbdc` → `origin/main` **`ef2bf63`**
(parents `14de251` + `7b1dbdc`). Merge tree `26da5621…` is **byte-for-byte
identical** to the reviewed head's tree. D1 stands as reviewed; the open items
above are D2's, and P17g may proceed in parallel — they touch different code.

### D1 — one request opened two top-level turn scopes

Two variants of one class, both fixed. **Sequential**: the entrypoint closed and
persisted its trace in the `finally` around `coordinator.run`, which sits BEFORE
the native-no-plan delegation, so a turn the native lane could not execute
persisted its row and THEN ran legacy under a trace of its own. **Nested**: the
guard was one-sided — the entrypoint asks `current_trace()` before opening one;
`core/conversation.py` did neither.

⭐ **Nesting was never the defect.** Delegating a turn the native lane cannot
execute is correct, and a nested composer call is legitimate work. What was
wrong is that the work opened a second TOP-LEVEL scope. The rule is one
top-level EXECUTION, not one model call.

### D2 — redefined once the caller was traced, then closed

The premise was wrong, and that is the finding. `pricing.qualification` on a
canonical turn comes from a **fire-and-forget prewarm** launched from the
interpreter's token stream, before settlement ownership is decided;
`timed()` records onto the AMBIENT trace. Arithmetic settled it:
`llm 6601 + qualification 5379 = 11980 > total_ms 9523` — an overlap of at
least 2457 ms, so the stage was never on the critical path.

⭐⭐⭐ **A FALSE DIAGNOSTIC WAS RETIRED, NOT QUIETLY EDITED.**
"`pricing.qualification` present ⇒ legacy settled" is how the 2026-08-16 canary
was diagnosed. It is false, and both places carrying it now say so with the
measurement, because anyone re-reading that diagnosis needs to know the ground
moved.

Addressed on all seven points — **and note ADDRESSED, not closed**: the
durability fix that answered point 2 introduced the two defects listed at the
top of this section, which are open on PR #81. Points: domains separated (`speculative.<stage>`, added to
the row, never summed into it) · latency independence proven by a 10 s poisoned
prewarm · semantic non-authority · cross-turn **and** launching-turn isolation ·
lifecycle stated rather than inherited · production remeasured · and late
completions folded back into the **same** row, never a second one.

### Gates

Frozen suite on `7b1dbdc`: `PYTEST_EXIT=0`, **10049 passed / 25 skipped**, HEAD
and `HEAD^{tree}` identical before and after. CI #1525 and battery #52 green on
that exact head (**22/22 × 3 reps, 0 flaky, 0 failed, 0 UNMEASURED**). D2
mutations **4 RED / 0 GREEN / 0 INVALID**.

⭐ **Two instrument findings worth keeping.** A mutation exposed that isolation
from the LAUNCHING turn was untested — setting the flag around `ensure_future`
leaves the prewarm correctly marked while re-filing the turn's own `llm` as
speculative, and every existing assertion still passed. And **a stage sum is
not a latency**: turn 1860 sums 33989 ms of *critical* stages against a
`total_ms` of 25922, because awaited work overlaps itself. Request-start →
response-emitted remains the only trustworthy number.

---

## ⏭ P17g — WORK STARTS, CLOSURE STILL GATED

**Unblocked by Q, and by D's MERGE — but D is not closed.** The D2 remediation
is open on PR #81, so P17g may be BUILT on that branch while "repaired main"
does not exist until #81 merges.

⛔ **And P17g is not clearable yet for a SEPARATE reason:**
P17g's closure gate is BOTH canaries, and the DIRECT canary reads
**FAILED — MISROUTED**, "RERUN after deploy". The CF5b/CF5c fixes it needs are
on main and **NOT LIVE** — auto-deploy is disabled, deployed build `76076b6`,
main `ef2bf63`. So the predicate work may start; declaring P17g closed waits on
a manual deploy and the rerun.

Reminder carried forward: the scan proof must **not** use barcode `70004199` —
it is not a product code, and the OFF record behind it carries per-bar numbers
as per-100g. Use the wrapper's real 13-digit UPC with "I had 2 servings."

---

## ⛔⛔⛔ P17g — THE SHARED SELECTION CONTRACT *(Danny, 2026-08-21; written BEFORE the green side)*

An existential predicate is **not** admissible. "Some authoritative local path
exists" is a different claim from "the rung the pricer will actually choose is
authoritative", and the gap between them commits the wrong number.

### The split that makes an existential boolean wrong

`price()` walks, unbound: **`memory → product → artifact → estimate`**. So:

* the **artifact** rung has a sourced, authoritative egg conversion;
* the **memory** rung exists but scales only via heuristic piece weight;
* an existential `look()` sees "an authoritative local path" and admits;
* `price()` selects **memory first** and commits the heuristic path.

Canonical would then settle a meal on exactly the evidence class CF4 forbids,
with the predicate's blessing. ⭐ **The predicate must describe the rung that
WINS, not the best rung available.**

### Why this is live today, not hypothetical

`core/canonical_pricing.py` applies the authoritative test **only when
`bound`**:

```text
resolution = resolve_scaling(source_basis, consumed, measures)
except ScalingRefused -> continue          # fall to the next rung
if bound and not resolution.authoritative: raise PricingRefused
```

For an **unbound** item a heuristic resolution is accepted and priced, and no
later rung's sourced conversion is ever consulted. The rung order decides the
authority, and nothing checks that it should.

### The contract, in four clauses

1. **CANDIDATES IN PRICING ORDER.** The eligible evidence/rung candidates are
   built in the order `price()` walks them — the same sources, the same
   sequence. Not a set; a list with a first element.
2. **PER-CANDIDATE, WITH ITS OWN BASIS.** `can_scale(…, authoritative_only=True)`
   is asked of **each candidate using that candidate's exact `source_basis` and
   `measures`**, from that candidate's own `_from_*` builder. A basis borrowed
   from another rung answers a question nobody asked.
3. **THE RUNG `price()` WOULD ACTUALLY RETURN DECIDES.** ⛔⛔ **NOT "the first
   whose `resolve_scaling` succeeds"** — that was this contract's first draft
   and it is one step short of the pricer. `price()` also skips a rung when:

   * its `_from_*` **builder** raises or yields nothing (`if not chosen:
     continue`);
   * **artifact ranking** produces no winner, so `_from_artifact` returns None;
   * the resulting price is **indefensible** — `if priced.is_defensible():
     break`, and an indefensible price such as a non-evidence zero falls
     through to the next rung.

   So the selector is: **the first evidence rung the current `price()` loop
   would actually RETURN, after builder, resolver AND defensibility checks.**
   `decide()` may admit **only if that selected rung's resolution is
   authoritative**. A later authoritative rung does not rescue an earlier
   heuristic one — and an earlier rung that merely *looks* scalable does not
   count as the winner if it cannot produce a defensible price.

   ⭐ **REQUIRED REGRESSION:** an earlier apparent candidate that cannot
   produce a defensible price, and a later authoritative rung that can. The
   contract must follow the real pricing winner, not the first
   scalable-looking item — and only a case where those two DIFFER can prove
   which one it follows.
4. **ONE SELECTION RULE, CONSUMED TWICE.** `price()` must consume the same rule
   — either applying the authoritative test to canonical settlement generally
   (not only `bound`), or explicitly SKIPPING a higher-priority heuristic-only
   rung. ⛔ **No second "close enough" predicate.** Two implementations of
   "which rung wins" is the defect this contract exists to prevent, wearing the
   costume of a fix.

### Boundary change this requires, stated not smuggled

`look()`'s docstring forbade "`assemble()` … the resolver". P17g cannot be
built under that rule, since the predicate's question *is* a resolver question.
The boundary is restated in the code: **retrieval and writes stay forbidden;
reading local evidence and asking the one resolver purely is permitted.**
Introducing the resolver while leaving that docstring intact would have left
the contract self-contradictory.

### Still explicit negatives until the producer slice lands

**Barebells / Fairlife** decline because **no authoritative PRODUCT producer
exists** for an unbound item — `assemble()` supplies a product rung only for a
scan-BOUND item carrying `product_evidence_id`, and those return before this
branch. They are negative twins with that reason asserted, **not** omitted
twins, and **not** a test-only producer. They become positive twins only after
the sourced-`ConversionEvidence` producer slice.

### Measured consequence, and the gate that does not move

P17g is a coverage **reduction** on today's producers: `_from_memory` declares
`Per100g()` with **empty measures**, so a count-only item cannot scale
authoritatively and is declined — where today it is admitted on heuristic
piece-weight mass (`normalize_quantity("2 eggs")` → 100 g, `mass_is_exact`
False). ⛔ **The fixed 40% threshold does not move.** Update the measured
result, never the goalpost. If coverage falls below it, P17g's correctness
change may still merge; the **coverage/rollout gate stays unmet** until the
producer slice restores legitimate coverage.

---

## P17g — MEASURED. THE GATE IS UNMET, AND THE THRESHOLD DID NOT MOVE

Remeasured on the **frozen population `p16b_0817`** — 361 rows, 232 meals —
with the predicate **EXECUTED, not modelled**, at predicate commit `2bf36a3`:

```text
                      RE-MEASURED (08-17)      P17g @ 2bf36a3
population            362 rows · 233 meals     361 rows · 232 meals  (frozen)
A  routing rate                 83.0%                   83.3%
B  support rate                 24.3%                   13.5%   <- flattering
C  OWNERSHIP RATE               20.2%                   11.3%   =  A x B
```

**25 of 185 structured-route meals supported.** Ownership roughly halves:
**20.2% → 11.3%**.

⛔ **THE 40% THRESHOLD HAS NOT MOVED, AND IS UNMET.** It was already unmet at
20.2%; P17g moves further from it. That is the honest consequence of declining
meals canonical cannot price authoritatively, and it is the same shape as the
08-17 drop: ⭐ **the number did not get worse — the instrument stopped
overstating it.** Counts were being admitted on piece-weight mass and priced
from a number nobody measured; 11.3% is what ownership is once that stops.

**P17g's correctness change may merge. The coverage/rollout gate stays UNMET**
until the sourced-`ConversionEvidence` producer slice restores *legitimate*
count coverage. That slice is the next separate work, and it is what turns the
P17h count positives (`2 eggs`, `2 large eggs`, `1 medium banana`) from
declines into admissions on evidence rather than on a table.

⚠ **AND P17g CANNOT CLOSE ON THIS NUMBER ALONE.** Closure needs the reviewed
main deployed and BOTH canaries passing; the direct canary still reads
FAILED — MISROUTED, "RERUN after deploy", and the deployed build is `76076b6`.

⭐ **A ROLLING WINDOW IS NOT THIS NUMBER.** Rolling measurements over the same
tree gave 0.0% / 22.7% / 44.0% at 3 / 7 / 14 days — the population underneath
changes, which is the error this instrument's own docstring names. The 30-day
rolling run **WITHHELD** entirely: 75 of 539 entries carry no `created` ledger
event, so every rate would have been computed over survivors. Only the frozen
population is comparable to 20.2%.

---

## ⛔⛔⛔ P17g — REVIEW ROUND 2 *(Danny, 2026-08-21, on head `61eaf4e`)*

`61eaf4e` was **rejected as unchanged source**. The CI analysis attached to it
was accepted as credible, and explicitly ruled insufficient: *"it does not
address the source blockers"* and *"the current flaky battery can be treated as
preexisting evidence, but it cannot make the unchanged source mergeable."*
Battery #53 was **not** to be re-run — the head had to change anyway.

⭐ **TWO OF THE FIVE WERE LIVE SOURCE DEFECTS; THREE WERE PROOFS THAT PASSED
FOR THE WRONG REASON.** That split matters for how each was validated. A proof
whose defect is in the TEST passes both before and after the repair, so its
colour proves nothing — only a mutation can show it is no longer vacuous.

### 1 — `price()` returned `selection.priced` without enforcing `.authoritative`

The field was computed one line above the return and never read, so the promise
`decide()` publishes had **no enforcement at the only place that writes**.

They are not guaranteed to agree by construction, because they do not run over
the same rungs: `look()` builds `(memory, None, artifact)`, `assemble()`
supplies `(memory, product, artifact, ESTIMATE)`. Routing can admit on an
authoritative artifact while the pricer — artifact ranking having found no
winner under its own composed query — falls through to **ESTIMATE** and commits
a heuristic price under an admission that promised authority.

`price()` now takes `require_authoritative` **from the caller**, exactly as it
already takes `bound`, and `GeneralSettlementOwner._price` passes it. ⭐ A
heuristic estimate is a legitimate PRICE and simply not a canonical
SETTLEMENT — a global rule would refuse most ordinary meals and delete the B-1
quantity and correction paths. ⚠ Clause 4's other option (SKIP a higher-priority
heuristic rung in favour of a later authoritative one) was **deliberately not
taken**: it changes committed numbers on paths outside this slice, and this
tranche is a predicate change, not a repricing. `PricingRefused` is raised
BEFORE any write (A8), so a divergence costs a refused turn, never a wrong row.

### 2 — the PRODUCT twins passed for "no canonical identity"

One product, `entity=""` forced, so `decide()` returned at the **identity**
rung and never reached the producer question. Its lone assertion (`"mass" not
in reason`) then held trivially — and had been *fitted* to that verdict,
because the honest rung-3 reason contains the words "a user-stated exact mass".
⛔ **A twin that declines at a rung above the one under test proves nothing
about the rung under test.**

Now **both** twins, real identity and quantity, and the claim proven positively
against the real selector: (1) with the rungs `look()` builds, PRODUCT's
evidence is `None` and no rung wins; (2) the SAME identity and quantity given a
real per-serving producer scale **authoritatively** via `direct_basis`; (3) so
the decline is the producer's absence, and it lifts the day the producer lands.
⭐ **An absence is only attributable when you can show the presence changing
the answer.**

### 3 — `drain_speculative()` timed out and left tasks running

`asyncio.wait(..., timeout=)` **does not cancel what it gives up on**. So in the
one case the timeout exists for, the guarantee evaporated: the prewarm stayed
alive holding its connection, teardown proceeded, and `DROP SCHEMA … CASCADE`
ran into it — the deadlock the registry was added to prevent, reached through
the registry's own escape hatch. ⛔ **A bound and a guarantee are not
alternatives.**

Stragglers are now cancelled **and awaited** — `cancel()` only *requests* it,
and a task whose `finally` has not run may still hold a connection — so the
postcondition is unconditional: *when the drain returns, no registered task is
running*. `DrainResult` reports `drained` vs `cancelled`, because "everything
finished cleanly" and "I killed three writes mid-flight" must not be the same
return value. ⭐ Cancelling here is not a lifecycle reversal: settlement still
never cancels, this is teardown, and only after a task outlived its budget.

### 4 — the data-flow proof accepted any `.authoritative` read

It asserted that *some* `<name>.authoritative` appears somewhere in `look()`,
which passes for `_ = _sel.authoritative` followed by a hard-coded constant. It
proved a READ happened, never that the value reaches the `ItemFacts` `decide()`
reads. ⭐ **A structural test can say the wire exists; only a driven one can say
the current arrives.** Replaced by a sentinel selector and assertions on both
returned fields over three selections — including a `None` rung — so no single
frozen value survives the set.

### 5 — `look()` claimed pricing was forbidden while running the pricer

The docstring listed "pricing" as forbidden while the body ran
`select_priced_rung`, which builds `PricedFood` objects with real macros for
every candidate. ⛔ **A boundary comment that contradicts the code twenty lines
below it is worse than no comment** — the next reader trusts the sentence.
Restated to what the rule always protected: retrieval and mutation stay
forbidden; pure in-memory selection is permitted. ⭐ And the honest claim is
about what ESCAPES: every price computed here is discarded, `ItemFacts` carries
a rung name and two booleans and never a macro. **Pricing to decide is not
pricing to write.**

### Gates on the round-2 head

* Mutations **15 RED / 0 GREEN / 0 INVALID**. N5–N8 exist specifically to
  validate the three proofs whose colour could not. ⛔ **N3 scored INVALID on
  its first form and the harness was right**: it removed `task.cancel()` while
  leaving the `gather`, so the drain awaited a live 30 s task and by the time
  the witness looked the task had FINISHED — the suite went red, but the
  witness asked "is it still running", which was False either way. *A witness
  must observe the change the mutation makes, not the headline of the defect.*
* **Ownership is UNCHANGED at 11.3%** — frozen population `p16b_0817`, 361 rows
  / 232 meals, predicate commit `1fc7a21`. None of the five touched `look()`'s
  or `decide()`'s behaviour, and that was measured rather than assumed.
* The **40% threshold has not moved and remains unmet**, and closure still
  requires the reviewed main deployed plus BOTH canaries.

---

## ⛔⛔⛔ WHAT ACTUALLY BLOCKS THE P17h COUNT POSITIVES — MEASURED, AND I HAD IT WRONG

*(2026-08-21, after P17g merged at `a3b6b9c`)*

I stated repeatedly — in this directive, in PR #82, and to Danny — that the
**sourced-`ConversionEvidence` producer does not exist yet**, and that landing
it is the slice that turns `2 eggs` / `2 large eggs` / `1 medium banana` into
admissions. ⛔ **That is false.** P17c.3b hydrated the artifact at FDC 15.3 —
120/124 candidates, 259 portions, every measure stamped — and `_from_artifact`
has been passing `_candidate_measures(winner)` the whole time. Probed against
the real committed artifact:

```text
egg     'large egg' = 61.0 g   usda_fdc@15.3   as_basis_conversion() -> yes
banana  'medium (7" to 7-7/8" long)' = 118.0 g, 'large (8" ...)' = 136.0 g, ...
```

`2 eggs` and `1 medium banana` resolve **`path=sourced_conversion`,
`authoritative=True`** on the artifact rung *today*. The producer is not the
blocker.

### So what is? Ranked on the frozen population, read-only

Two candidates, each measured as a counterfactual over `p16b_0817`
(361 rows / 232 meals), reported at MEAL level because a meal declines if ANY
item declines:

```text
VARIANT                          MEALS AUTHORITATIVE     of total
BASELINE                                          28        12.1%
A  precedence (skip a heuristic-only rung)        28        12.1%
B  folding (artifact key is singular-only)        29        12.5%
A+B                                               29        12.5%
```

* **A recovers ZERO meals.** Clause 4's option (b) — the one I declined in
  round 2 as out-of-slice repricing — buys nothing on this population. That
  decision was right for a reason I had not measured.
* **B recovers ONE meal**, and it is `'Eggs' / '100g'` — an **exact-mass** case,
  not a count. The artifact is keyed singular-only (`egg` 6 candidates, `eggs`
  0; `banana` 2, `bananas` 0), which is real, but it is not where the count
  positives live either.

⭐ **RANK TRANCHES BY RECOVERABLE OWNERSHIP POINTS, NOT BY BUCKET NAME** — the
rule this instrument already carries, applied to my own plan. Both slices I was
about to propose are worth ~0 and ~0.4 points respectively.

### And the probe found a live wrong-nutrition defect: CF20

Chasing why `1 banana` fell to `heuristic:piece_weight` surfaced the ladder
above it:

```text
"1 large banana"        -> matched 'extra large (9" or longer)'  ->  152 g
                           artifact ALSO holds 'large (8" ...)'  =   136 g
"1 extra large banana"  -> matched the SAME record               ->  152 g
```

**+11.8% on a log, `authoritative=True`, citing a record about a different
piece** — and the two phrases were indistinguishable, so a user who said
"extra large" got the identical row either way. Two defects that compound:

* **PRODUCER** — `_size_descriptor` compared **one word at a time** against a
  vocabulary containing the two-word `"extra large"`. An entry no input can
  produce is not coverage, whatever the set literal says.
* **CONSUMER** — the guard tested token **membership**, and `"large"` IS in
  `{extra, large}`. The wrong record sits EARLIER in the USDA portion list, so
  the correct one was never reached.

Either fix alone still mis-prices — with the producer fixed, `"extra large"`
fails a membership test; with the consumer fixed, `"extra large"` never
arrives. Both landed together. Registered **CF20**; 6 mutations RED, and one of
them scored INVALID first for the same reason P17g's N3 did: *the witness must
observe the change the mutation makes, not the headline of the defect.*

⛔ **P17g MAKES THIS CLASS WORSE, NOT BETTER**, which is why it is worth
recording here rather than in a corner. Before P17g a sourced conversion merely
priced; after P17g it is the thing that lets canonical **own** the meal. An
authoritative path committing a mass from the wrong record is precisely the
trust P17g was built to establish.

### Consequence for sequencing

The next slice is **not** "the producer". The honest open questions are the
artifact's singular-only keying, the `_SIZE_TOKENS` / `_SIZE_WORDS` vocabulary
drift (`mini`, `tiny`, `venti` are stateable but invisible to the matcher), and
the dominant `IDENTITY:no_resolution_row` mechanism — **86 items**, far larger
than anything quantity-shaped. None of these is authorised here; they are
registered so the next decision is made on measured points rather than on my
recollection.

---

## CF20 ROUND 2 — OWNERSHIP RE-MEASURED ON THE FINAL HEAD *(Danny's requirement)*

⛔ **11.3% COULD NOT BE CARRIED FORWARD.** Round 2 changes `_matching_measure`,
which is the resolver P17g's selector calls — so the earlier number was
measured on a tree that no longer exists. Re-run, not inherited:

```text
                         P17g @ 2bf36a3      CF20 r2 @ 686a607
population          361 rows / 232 meals   361 rows / 232 meals  (frozen)
A  routing rate                   83.3%                  83.3%
B  support rate                   13.5%                  13.5%
C  OWNERSHIP RATE                 11.3%                  11.3%
   declining meals              160/222                160/222
```

⭐ **AND "UNCHANGED" IS ATTRIBUTED, NOT ASSUMED.** A number that happens to
match is not the same claim as a number that had to match. On this population:

```text
rows stating ANY size                                      11 of 361
   medium 4 · small 4 · regular 2 · venti 1
rows whose stated size the matcher CANNOT represent          3
   'Quest Chips Sweet Chili'          '1 regular bag'
   'Starbucks Venti Iced Latte...'    '1 venti (24 fl oz)'
   'Peanut Butter Protein Smoothie'   '1 regular (~16oz)'
```

Round 2 is **strictly stricter** — it refuses where it previously bound, and
adds no new admission on this population (`extra small` appears in none of
these rows, and it was already authoritative, merely from the wrong record).
So no row can flip declining → supported, and at most those 3 could flip the
other way. Ownership is unchanged, therefore **none of the 3 flipped a meal**:
each already sat inside a meal that was declining for another reason. That is
the whole argument, and it is why the two numbers agree rather than merely
coinciding.

⚠ The 40% gate is untouched and still unmet; closure still requires the
reviewed main deployed and BOTH canaries.

---

## ⛔⛔⛔ CF21 — THE RANKING INSTRUMENT WAS DEAD, AND ITS ZEROS READ AS FINDINGS

*(2026-08-22; taxonomy supplied by Danny)*

Asked to measure `IDENTITY:no_resolution_row`, the answer was that it could not
be measured. **P17g changed the predicate and the attribution instrument was
not moved with it**, so two layers went stale at once and both failed silently:

* **FLIPS.** `_COUNTERFACTUAL` flipped `has_mass` / `has_artifact` /
  `has_memory` / `has_identity` / `has_quantity`. P17g replaced those in
  `decide()` with `selected_rung_authoritative`. Tested directly: **every flip
  is inert**, and the only fact that moves the predicate was not in the table.
  That is why all eight mechanisms reported `0.0%` recoverable points.
* **CLASSIFIER.** `_mechanism` still branched on `facts.has_mass`, so items
  that HAD a mass and declined for the P17g reason fell through into the
  evidence buckets. Measured: **310 of 313 declining items fired the SAME
  predicate branch** while spread across eight differently-named buckets. The
  taxonomy had stopped partitioning anything.

⭐ **A COLUMN OF ZEROS IS NOT EVIDENCE THAT NOTHING IS RECOVERABLE** — it is the
instrument's own silence. And my own sequencing claim ("86 items is the only
candidate with evidence of meaningful points") had no basis: the table reported
0.0% for that bucket exactly as for the others, and I read an item count as
points evidence.

### The repaired instrument

Terminal mechanisms, **exactly one per item**, classified from the REAL
selected-rung result; **mass is an orthogonal field, never a bucket**;
counterfactuals rerun the real selector and are judged by the real `decide()`;
an intervention that cannot be executed against concrete evidence reports
**UNMEASURED**, which is neither zero nor the sole-blocked count.

```text
MECHANISM                        ITEMS  w/ mass  SOLE-BLOCKED   RECOVERED (measured)
MEMORY_WINNER_NONAUTHORITATIVE      77       35            44   0 / 2 evaluable · 42 UNMEASURED
NO_LOCAL_EVIDENCE                  165       65           100                      UNMEASURED
ARTIFACT_WINNER_NONAUTHORITATIVE     3        3             1                      UNMEASURED
ARTIFACT_PRESENT_NO_WINNER           1        1             1                      UNMEASURED

MULTIPLE_BLOCKERS: 14 meals — EXCLUDED (no sole-cause attribution)
partition holds: True (246 addressable items vs 246 declining items)
```

### ⛔ ROUND 2 — TWO INSTRUMENT DEFECTS *(Danny, review of `d8113d5`)*

**THE CLASSIFIER MISLABELLED MEMORY-ONLY EVIDENCE.** `if has_memory or
has_artifact -> ARTIFACT_PRESENT_NO_WINNER` filed a memory candidate that would
not build as an artifact-RANKING defect, with no artifact anywhere in sight.
⭐ **The name IS the tranche** — artifact selection and memory usability are
different repairs, and the table would have looked well-attributed while
pointing at the wrong one. ⛔ And my own test PINNED the wrong mapping, so it
did not merely fail to catch the defect: it defended it. Split into
`MEMORY_PRESENT_NO_WINNER` / `ARTIFACT_PRESENT_NO_WINNER`, plus
`LOCAL_EVIDENCE_PRESENT_NO_WINNER` when both were present and neither won —
the item-level analogue of MULTIPLE_BLOCKERS, because naming one repair there
would be inventing an attribution.

**THE THREE-STATE AGGREGATION WAS ORDERED WRONG.** It asked `any(unsimulatable)`
FIRST, so a meal holding one unsimulatable item AND one simulated item that
still declines was filed UNMEASURED — throwing away a settled answer. The
simulated item blocks the meal on its own, whatever the other would have done.
⭐ **A definite NO outranks an unknown.** Corrected precedence: any simulated
item still unsupported → measured non-recovery; else any unsimulatable →
UNMEASURED; else recovered.

⭐ **AND IT MOVED THE NUMBER.** `43 unsimulatable` became **42 UNMEASURED**, with
the evaluable denominator rising from 1 to 2 — one meal whose outcome was
already known had been filed as unknown. The presentation is now
`0 / 2 evaluable · 42 UNMEASURED` rather than `0 (43 unsimulatable)`, because
"zero out of what" had two readings that differ by a factor of twenty.

### ⛔ NEITHER TRANCHE IS AUTHORIZED

* **memory sourced measures** — the one tranche that CAN be simulated:
  **0 / 2 evaluable meals recovered · 42 / 44 meals UNMEASURED**. The artifact
  holds no portions for those entities at all
  (`Cheesecake`, `Homemade miso soup`, `Limesalt Burrito Bowl`). So the tranche
  cannot be evaluated for the large majority of its own addressable population
  — which points back at coverage rather than at measures.

  ⚠ **THE EVALUABLE DENOMINATOR IS TWO, AND THAT IS THE POINT.** `0 / 44` and
  `0 / 2` are different claims: the first would say the tranche was measured
  and failed, the second says almost none of it could be measured at all. Only
  the second is true, and only the second explains why the next question is a
  coverage question.
* **evidence coverage** — UNMEASURED. There is no concrete evidence to supply,
  so recovery is unknown. Its 100 sole-blocked meals are an addressable
  population, not a recovery.

Per the standing instruction, neither is authorized: **the repaired ranking has
not produced measured recovery for either.**

⚠ The published **11.3% is untouched** — the rollup no longer derives an
ownership-point column at all, because a second, differently-computed ownership
number invites exactly the comparison it cannot support.

### CF21 GATES — current state

```text
head                 9755b9f
freeze               PYTEST_EXIT=0 · 10127 passed / 25 skipped / 17 deselected
                     / 4 xfailed · tree identical before and after
mutations            12 RED / 0 GREEN / 0 INVALID
CI                   exact-head green
Food eval battery    INTENTIONALLY ABSENT — no changed file matches its paths
                     filter (core/food_*.py · core/prompts/** ·
                     skills/nutrition/** · handlers/tool_executor.py ·
                     scripts/eval_food_matrix.py). This branch changes a
                     measurement instrument and nothing the app runs; the
                     lane's standing battery evidence is #58, 22/22 x 3, zero
                     flaky, on the tree that shipped in `aee47fc`.
memory measures      0 / 2 evaluable meals recovered · 42 / 44 UNMEASURED
evidence coverage    UNMEASURED (100 sole-blocked meals, addressable only)
```

⛔ **NEITHER PRODUCT TRANCHE BECOMES AUTHORIZED BY THIS MERGE.** CF21 repairs
the instrument that ranks them; it delivers no coverage and no measures, and
the repaired ranking has still produced measured recovery for neither.

---

## ⛔⛔⛔ CF22 — THE RELEASE ORDER CHANGED. DO NOT DEPLOY `baa0f81`.

*(Danny, 2026-08-23)*

`baa0f81` was reviewed and ready to promote. It must **not** be promoted,
because CF22 proves that **P17g's rollout would activate a 150x nutrition
error**.

### The defect

`skills/nutrition/normalize.py` had no entry for `г` or `мл`, so a Russian
user's stated exact mass parsed as a **count**:

```text
"300 г"  ->  count=300.0, grams=None, mass_is_exact=False
"300 g"  ->  grams=300.0,             mass_is_exact=True
```

And a count MULTIPLIES. The ESTIMATE rung declares `PerServing(as_served=True)`
— countable on purpose so "2 servings" scales — so `300 г` of tvorog priced at
**60,000 kcal** against an honest 400.

### It COMMITS, and it is LATENT

```text
production entries with a Cyrillic unit      399
max calories among them                      825
entries over 5000 kcal, ALL-TIME               0
```

Unreachable today only because canonical settlement is cohort-gated and dark.
⛔ **Rolling P17g out is precisely what switches it on** — release-blocking for
the rollout while invisible in current data, which is the worst combination for
anything a canary is relied on to catch.

### THE CORRECTED RELEASE SEQUENCE

```text
1. CF22 reviewed and merged            <- NOT YET DONE
2. promote the RESULTING new main SHA  (never `baa0f81`)
3. verify /health reports that SHA
4. run BOTH canaries
5. close P17g only if both pass
```

### ⛔ CF22 IS FIXED BUT **OPEN**, NOT CLOSED

Fixed, proven and frozen is not the same as reviewed and merged. It stays OPEN
until independently reviewed and merged.

---

## CORRECTIONS TO THE SINGLE-FOOD MEASUREMENT *(Danny, 2026-08-23)*

### The 53 meals do NOT await a human label-versus-scale judgement

That was my framing and it was wrong. Whether a user has a label in hand is
**absent from the corpus** — it is not a judgement someone can supply from
intuition either. Replacing an invented classifier with human intuition is the
same error wearing a different hat.

Recorded as:

```text
CONVERSION_EVIDENCE_ADDRESSABLE     53
DIRECT_LOW_FRICTION_RECOVERY         0
USER_CONTEXT_UNMEASURED             53
```

⛔ **Do not manually call bars packaged or ears weighable.**

### `79/158 ~ 50%` is a MAXIMUM, not projected ownership

It is the ceiling **if every user supplies a mass**. It is not a projection, not
an expectation, and must never be quoted as one.


### CF22 — THE VOLUME BOUNDARY, PROVEN CAUSALLY *(Danny, review of PR #85)*

The density asymmetry recorded as "metadata-only, out of scope" was a claim
about CAUSALITY, and had to be demonstrated at the layer that commits — the
same argument CF22 makes about the gram defect being invisible at the parser
and catastrophic at the pricer.

**The boundary, proven to the committed row:**

```text
г       exact MASS
мл / л  exact VOLUME
мл / л  NOT exact mass without an authoritative density/conversion
```

**It cannot commit wrong nutrition.** `Кефир` is absent from the density table,
so `250 мл` carries `mass_is_exact=True` with `grams=None` and precedence rung
1 (`user_stated_exact`) FIRES. What happens next is a refusal: `_factor` raises
`ScalingRefused` — *"per-100g values need a mass, and this portion has none"* —
so no mass is manufactured and rung 1's authority is never handed to an
invented number. The known-density branch (`Kefir`, 257.5 g, heuristic) is
refused at the authority gate instead. **Both refuse; neither commits.**

⛔ **BUT IT IS NOT PURELY METADATA, AND THAT MATTERS.** Against a `Per100ml`
basis the resolver gives the SAME FACTOR (2.500) DIFFERENT AUTHORITY:

```text
Кефир (no density)     250 мл -> user_stated_exact  authoritative=True
Kefir (density 1.03)   250 мл -> heuristic:vessel   authoritative=False
```

The known-density food is denied authority for a conversion the per-100 ml path
never uses.

⭐ **IT CANNOT REACH SETTLEMENT, AND THE REASON IS STRUCTURAL: NOTHING
CONSTRUCTS `Per100ml`.** `_from_memory` and `_from_artifact` declare
`Per100g()`, `_from_product` declares `PerServing` or `Per100g`,
`_from_estimate` declares `PerServing`. An AST sweep over `core/`, `skills/`,
`api/` and `handlers/` finds zero emitters, and the committed artifact carries
no per-100 ml entry.

**PARKED — with a self-invalidating guard.** CF22 exists because a latent defect
sat one rollout away from live, so this parking carries a test that fails the
day any producer emits `Per100ml`. Verified non-vacuous: injecting a real
emitter made it fire, naming the file and line.

Cyrillic and ASCII are identical on every path measured — normalized fields,
resolver authority, committed calories, rung and provenance.