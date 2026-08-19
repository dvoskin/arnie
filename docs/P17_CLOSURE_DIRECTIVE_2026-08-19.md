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
