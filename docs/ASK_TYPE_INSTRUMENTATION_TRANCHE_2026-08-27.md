# TRANCHE — ASK-TYPE INSTRUMENTATION (next production-code tranche)

**Authorized 2026-08-27. Precedes any T1 defaulting policy.** The system cannot
currently measure its own clarification behaviour: **103 of 105 recorded asks
carry no type at all.**

## ⛔⛔⛔ THIS IS NOT "ADD A FIELD" — TWO VOCABULARIES ALREADY EXIST AND DISAGREE

```
structured lane   core/food_turn.py:4069 _KIND_PHRASING
                  portion · identity · preparation · extras · detail

tool path         core/tools.py  note_food_clarification.kind enum
                  portion · brand · cook_method · ingredient · other
```

They agree on `portion` and diverge everywhere else — `preparation`/`cook_method`,
`identity`/`brand`, `extras`/`ingredient`, `detail`/`other`. **This is the
four-tables condition `skills/nutrition/materiality.py` was written to end,
recreated one layer up.** Two vocabularies for one concept, in the two producers,
that agree today and will disagree later.

## Two defects in the existing vocabularies, not just duplication

**1 — `portion` conflates three types with DIFFERENT defaults.**

| taxonomy type | today | default strength |
|---|---|---|
| T1 menu size option — *"small, medium, or large?"* | `portion` | ⭐ STRONG (enumerable, modal) |
| T2 continuous portion — *"how much rice?"* | `portion` | MEDIUM (standard serving) |
| T6 portion multiplier — *"single or double scoop?"* | `portion` | STRONG (assume single) |

A single `portion` bucket cannot support a T1-only policy, which is exactly the
first policy experiment queued.

**2 — T3 consumption completeness is INEXPRESSIBLE in both vocabularies.**
*"Did you finish both, or leave some?"* is not portion, identity, preparation,
extras, brand, ingredient or cook_method. It falls to `detail`/`other`. **The one
ask type with NO defensible food-knowledge default is the one the system cannot
name.** It would be invisible in any production denominator built on today's
fields.

## The work

1. **ONE vocabulary**, in one module, with a structural test forbidding a second
   — same shape as `test_there_is_exactly_ONE_materiality_POLICY`:
   `menu_size | continuous_portion | consumption_complete | preparation_fat |
    unstated_extras | portion_multiplier | identity_variant`
2. **Emit at the DECISION POINT, durably.** `core/food_turn.py` has **8
   ask-shaped return sites** (1377, 6032, 6120, 6343, 6428, 6497, 6533, plus the
   `_sft` ask path) and **only 2 set a `kind` at all** — and those two set
   `"clarify"` / `"confirm"`, which are turn SHAPES, not question subjects.
   Every site must emit a type.
3. **No text inference. No post-hoc classifier.** `scripts/classify_ask_types.py`
   exists only because the field does not; it reads `questions[0]`, leaves 23 %
   unclassified, and must not become the production mechanism.
4. Map the legacy values forward so historical rows remain readable.

## What it buys

A real production denominator: how often each type occurs, which correlate with
abandonment, which get answered, which could have been defaulted — and
**whether T1 is common enough outside this 158-turn corpus to be worth a
policy at all.** That last question currently has no evidence either way.

## Sequence after this lands

```
ask-type telemetry  ->  T1 menu-size policy  ->  T5 / T6  ->  T2
                        (OILS owns T4, canonical identity owns T7, in their own lanes)
```

- **T1 first**: 23 observed turns, 6 cases, enumerable choices, a modal default,
  and a held-out matched-pair demonstration already exists (101/102 ask `AAAA`;
  105/106 — same utterance, size specified — log `LLLL`).
- **T3 is EXPLICITLY EXCLUDED from DEFAULTABILITY.** *"Did you finish it?"* is
  user state, not food knowledge.
- **T2 is the largest eventual prize and the most dangerous** — "standard
  serving" is inherently softer than "default menu size".

## Gate

Any criterion arising from this tranche is bound by
`tests/test_no_criterion_promoted_from_its_own_corpus.py`.


---

# SHIPPED 2026-08-27 — scope as frozen

| requirement | status |
|---|---|
| one canonical vocabulary module | ✅ `skills/nutrition/ask_type.py` |
| exactly the 7 semantic subjects | ✅ (+ `unclassified`, which is the ABSENCE of one) |
| all ask-shaped return sites emit a canonical type | ✅ **7** sites (AST-verified) |
| legacy values forward-mapped only, never second-class canon | ✅ `from_legacy` reads; writes are canonical |
| structural test: no second ask-type declaration | ✅ |
| structural test: every ask site types before returning | ✅ AST, not grep |
| negative invariant: `consumption_complete` distinguishable | ✅ incl. at the storage layer |
| read compatibility, no retroactive prose reinterpretation | ✅ |
| no policy change · no DEFAULTABILITY change · no `27983be` deploy | ✅ |

**28 tests. 5 mutations RED / 0 GREEN / 0 INVALID.**

## ⛔⛔ THE ACCEPTANCE GATE WAS VACUOUS ON FIRST WRITE

*"If the renderer can change wording without changing ask_type, you've got the
boundary right."* The first version of that test used **"Small, medium, or
large?" on a BRANDED item** — so the text answer and the structural answer both
said `menu_size`, and a text-dependent implementation was **unobservable**.
Mutation M2 (return `MENU_SIZE` whenever the text contains "large") stayed
**GREEN** through it.

Rewritten with an **UNBRANDED** item: the prose reads as a menu-size question
while the structure says `continuous_portion`, so any implementation that
consults text now returns the wrong value. M2 goes RED.

⭐ **A boundary test whose fixture makes both sides agree tests nothing.** Only
mutation testing found it — the positive suite was 10/10 green either way.

## Proven on the real path

Live turns, production config, reading the DURABLE row back:

```
menu_size           "A McDonald's Big Mac and fries"
continuous_portion  "8 oz grilled salmon with a side of white rice"
preparation_fat     "8 oz sirloin, a loaded baked potato, and a Caesar salad"
COMPOUND            "A bowl of oatmeal" -> [continuous_portion, preparation_fat]
```

Remaining types pinned through `record_pending_question` + the same
`payload_json` shape `core/conversation.py` writes — the real persistence path,
not a manufactured one.

## Two findings recorded, NOT investigated in this tranche

**⛔ `portion_multiplier` is REGISTERED UNREACHABLE, pending producer evidence.**
The Panda Bigger Plate probe — the utterance that produces *"regular single
scoop, or did you double it up?"* — called the typing helper with an **EMPTY
`ambiguities` list**. No interpreter field maps to it. The constant exists;
nothing produces it. **Deliberately not investigated here** (Danny): it is a
producer/reachability question, not a blocker on making the vocabulary
canonical, and chasing it would make this a mixed tranche. Investigate only if
T1 shows its absence materially affects the population, or a real producer
path appears.

**⚠ Some asks carry no structured ambiguity at all**, so they type as
`unclassified`. The typing is only as good as its input. This is now the honest
coverage metric for the denominator T1 will be sized against.

## Judgement calls, ratified

- `_RENDER_PHRASING` / `_render_facet` stay **presentation-only** and are never
  merged into the durable vocabulary. Text-derived categorisation cannot
  separate `menu_size` from `continuous_portion`; promoting it would rebuild
  the inference layer this tranche removes.
- `unclassified` is **durable and visible but not model-selectable** — an
  honest drift/coverage metric, without pretending missing structure is a
  semantic subject.
- The split-refusal site stays `unclassified` until structured evidence exists.
  Fabricating a subject to avoid an empty bucket is worse than the bucket.

## Next

T1 menu-size, using the new durable denominator. **The enum is not the point —
the point is that T1 can now measure ask subjects without reading prose.**

## Regression gate

**Full suite GREEN: 10261 passed, 25 skipped, 17 deselected, 4 xfailed, 0
failures** (443 s). The first run was **RED with 2 failures, both mine**, and
the focused 28 were green through both:

**1 — the rename broke a cross-module import inside a bare `except`.**
`skills/nutrition/clarification_adapter.py` imported `_facet_kind` from
`core.food_turn`; after the rename it raised, was swallowed, and every
clarification field silently degraded to `"detail"`. ⭐ **A cross-module import
behind `except Exception` is one rename away from being permanently dead** —
the same class as the `except: pass` that left `_backfill_city` dead since
P17f.5, and the `float('exact')` that made the canonical memory rung return
zero rows for 836 turns.

**2 — the pending-mutation ratchet, NOT raised.**
`test_pending_mutation_authority_does_not_spread` caps sites at 30 and its
contract is that the number goes DOWN. The `pq.payload_json` write added to the
tool path made it 31. **Raising the bound to fit my own change is exactly what
the ratchet exists to prevent**, so the write was reverted: the tool path's
canonical value rides the pre-existing `tier` piggyback, and the real win there
was DELETING the second enum, not adding a writer. It carries ~1 of 27 asks,
which does not justify spreading pending-lifecycle authority.

⭐ **Only the full suite caught either.** The focused suite was green through a
silently-dead import.
