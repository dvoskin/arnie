# Branch disposition — 2026-07-31

Phase 10. Every branch below was compared against `origin/main` @ `433cdf3`.
**Nothing was merged wholesale.** The test applied is patch-equivalence
(`git cherry`) *plus* a content check, because a commit can be missing by
patch-id and still be fully present in the tree — which is exactly what
168 commits of drift did to PR #67.

---

## PR #67 — `168 behind`, `4 ahead` → **CLOSE, extract nothing**

`git cherry -v origin/main pr67` reports only 1 of 4 commits as already in
main. That number is misleading, and acting on it would have meant
re-landing three features that are already shipped. Each commit was checked
for its own distinguishing content in main:

| Commit | Goal | `git cherry` | Marker searched in main | Verdict |
|---|---|---|---|---|
| `a8f77a9` | the card's Undo token gets an endpoint | `-` (in main) | `api/undo.py` **byte-identical** | shipped |
| `01d904d` | rapid-fire iOS messages coalesce into one turn | `+` (missing) | `_debounce_seconds`, coalescing block present in `api/chat.py:51`; `bot/message_debounce.py` byte-identical | shipped |
| `78672f3` | the clarification question is content, not a script | `+` (missing) | `"The food, as it reads MID-SENTENCE."` at `skills/nutrition/clarify_policy.py:260` | shipped |
| `6a87910` | the card and the sentence read one day, not two | `+` (missing) | `"ONE DAY, ONE SOURCE"` at `core/conversation.py:2270` | shipped |

**Action:** close PR #67 with the explanation that all four features landed
through later work, and that the branch is 168 commits behind. **Do not merge
it** — its versions of `core/food_response.py`, `core/food_turn.py` and
`core/conversation.py` are 168 commits stale and would revert live behaviour.

---

## Composite food — **still-valid work, and the only genuinely open item**

Unlike PR #67, this problem is **not** solved on main:

- `skills/nutrition/composites.py` **does not exist** on `origin/main`.
- `skills/nutrition/authority.py:439` nonetheless ships the user-facing label
  `"component_estimate": "Estimated from its components"`.
- `handlers/tool_executor.py:1283` names the defect in main's own words:
  *"the same defect as `component_estimate` rendering 'Estimated from its
  components' with no engine behind it … prose asserting an action nobody
  performed."*

So the rung is reachable and the sentence is shipped, with nothing computing
it. Two branches independently built the missing engine:

| Branch | Head | Behind | Adds | Distinguishing asset |
|---|---|---|---|---|
| `claude/open-issues-composites-stall-usda-1ipqnu` | `40d4d9b` | 115 | `composites.py` (642), tests (437), `tests/gold/usda_component_rows.py` (136) | **ground-truth USDA component rows** |
| `dvoskin/composites-component-estimate` | `e4d651d` | 121 | `composites.py` (462), tests (290), `shadow.py` wiring | shadow-comparison wiring |

**Recommended action:** extract from
`claude/open-issues-composites-stall-usda-1ipqnu`, onto a **fresh branch off
`433cdf3`**, and take `dvoskin/composites-component-estimate`'s
`skills/nutrition/shadow.py` wiring on top. The deciding factor is
`tests/gold/usda_component_rows.py`: the 2026-07-30 architecture audit recorded
that composite accuracy is *unmeasurable from production and needs ground
truth*, and that file is the ground truth. An engine without it cannot be
scored, and an unscoreable engine cannot pass a promotion gate.

**Not done in this pass, deliberately.** This is ~1,400 lines of P2 nutrition
quality work, and the required implementation order puts P0 data integrity
first. Extracting it while `NUTRITION_RESOLVER_MODE=shadow` would also be
building on an inert foundation — the resolver that would own the committed
values is switched off in production (see `DEPLOYED_STATE_2026-07-31.md` §3).
**Resolve the resolver-mode question first**; it changes whether this engine
would affect anything at all.

---

## The 47 fully-contained branches — DONE

`git branch -r --merged origin/main` gave 47 branches whose every commit is
already an ancestor of main. That is arithmetic, not judgement, so they were
archived and deleted: each tagged `archive/<name>`, the tags pushed and
**verified present on origin**, and only then the branches removed. Recovery
was proven rather than asserted — `fix/briefing-context` was restored from its
tag to the identical commit `e5c1fbc`.

    git branch <name> archive/<name>      # brings any of them back

69 → 22 remote branches.

## The 17 that hold unique commits

### Extracted — the flaky CI, explained

`claude/danny-ios-logs-analysis-0si1fb` @ `d268506` (2026-06-25) diagnosed the
order-dependent test failure that made `08ce423` red: both
`test_compound_meal_logging.py` and `test_food_logging_simulation_suite.py`
built the system prompt as a module-level constant, so it ran during pytest
COLLECTION and was sensitive to sibling-module ordering under
pytest-randomly's shuffle.

**Extracted and applied to BOTH files** (the branch fixed only one; the
simulation suite has 60 usages and the same bug). The branch's remaining three
commits are unreviewed.

### Probably superseded — capability landed, call sites drifted

| Branch | "missing" |
|---|---|
| `claude/food-branded-source` | 3/48 |
| `claude/food-copy-polish` | 3/42 |
| `claude/food-drop-diagnosable` | 3/36 |
| `claude/food-memory-authority` | 2/30 |
| `claude/food-conversation-quality` | 2/24 |
| `claude/food-failed-item-contract` | 5/54 |

All six are ~280 commits behind and share the same handful of unmatched
markers — `derive_vague_quantities(...)`, `build_failure_notice(...)`. **Both
functions exist on main.** So the capability landed and only the literal call
lines differ, refactored over 280 commits.

**Not deleted.** "The function exists" is not the same as "this branch's
changes landed", and six branches is a small enough set to confirm by hand.
Recommend a per-branch look, then archive-and-delete as a batch.

> **Known false-positive mode of `scripts/branch_triage.py`:** a marker that is
> a CALL SITE drifts when the callee is refactored, so a branch whose work is
> fully present reads as UNIQUE. This is the same trap that made `git cherry`
> report three of PR #67's four commits missing. The tool is a filter, not a
> verdict — always check whether the missing symbol *exists* in main.

### Genuinely open

| Branch | Holds |
|---|---|
| `feat/decision-receipt` | 48/65 missing — the parked backend receipt work |
| `claude/entrypoint-routing-coordinator-suijeu` | `clarification_subject/needs/kind/stakes` — **Phase 5 clarification-state fields**, directly relevant to the state machine |
| `integration/food-combined` | one food trace + one time budget per turn |
| `feat/arnie-brain-tab` | brain-tab graph layout, behind `BRAIN_TAB_ENABLED` |
| `claude/ironclad-evaluation-7mhapr` | retires 14 stale contract pins |
| composites ×2 | see above |
| `claude/parse-user-turns-6h-0ujgel`, `ozonated-product-mockups`, `justin-apple-health` | unexamined |

## Remaining branches

69 remote branches exist. The ones above are the ones the brief named. A full
sweep was not performed — flagged here rather than silently omitted. The two
composite branches are the only ones found whose subject matter is absent from
main; every other branch inspected during the deployed-state pass was either
merged or superseded.

**Suggested standing rule:** a branch more than ~50 commits behind `main`
should be treated as a *specification*, not as mergeable code. Both composite
branches, and PR #67, would each have reverted live behaviour if merged.
