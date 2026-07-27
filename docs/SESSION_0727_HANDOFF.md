# Session handoff — 2026-07-27

Branch `claude/open-issues-composites-stall-usda-1ipqnu`, PR
[#68](https://github.com/dvoskin/arnie/pull/68) (draft). Five commits, base
`9393998`. Suite green at each: **5439 collected, 0 failed**.

Written so the next session — or you, locally — starts from what is known
rather than from the top.

---

## The one-line finding

**Every defect found today was deterministic application code**: control
flow, lookup tables, a config flag, and SQL. Not one was a model defect. This
matters because the session ended on "I might have to switch everything to
OpenAI" — that migration would carry all of these across unchanged.

Where the model IS implicated: the interpreter reported 0 calories for butter.
But any model will sometimes return a bad read. The bug was that **nothing
caught it** — USDA sat at 717 cal/100g and the code never consulted it. The
failures were in the layer whose job is catching a wrong answer, not in the
answer.

---

## Landed (pushed)

| commit | what |
|---|---|
| `d514efd` | the legacy stall reply |
| `460f0bf` | USDA per-100ml/per-100g density mismatch |
| `8997d92` | the food gate — `FOOD_GATE_MODEL=true` in render.yaml |
| `aad3416` | butter at 0 calories |
| `6a72208` | `scripts/audit_food_damage.py` |

### `d514efd` — one stall reply
`core/platform.Response.from_text` answered an empty reply with its own
`"still here. what's the move?"` — lowercase, off-voice, below every check
that reads a reply. The pool moved to `core/recovery.py` so the renderer and
the replay guard both read it. Two things fell out: `_RECOVERY_SIGS` had
already drifted (it listed the renderer's private line, never a real bubble),
and the replay guard had **two** call sites inlining the same check.

### `460f0bf` — the density mismatch
`api/usda.py` returned `per100g` and said nothing about what it meant;
`candidates.usda_candidates` hardcoded `Per100g()`; the gold set declared
`per_100ml` on thirteen USDA rows — a basis no live path can produce. The
mislabel was **load-bearing**: it was the only reason a drink scaled at all,
because `VOLUME_DENSITY_G_PER_ML` is keyed by the *portion* ontology and every
key in it is a solid.

Measured before the fix:

```
240ml of milk           source seated, calories NULL
240ml of orange juice   source seated, calories NULL
240ml of oat milk       41 cal, against a true ~110
```

`food_category("oat milk")` is `oats`, whose 0.38 g/ml is the packing density
of dry rolled flakes. After: 124 / 113 / 110, each agreeing with USDA's own
portion table. Olive oil moved 131 → 120 (USDA's own 13.5 g/tbsp says 119).

### `8997d92` — the gate
This is the answer to "I'm seeing none of the clarification work."
`core/turns/stages/route.py` → `food_relevance()` opens with
`if not model_gate_enabled(): return applies(t)`, and render.yaml set neither
`FOOD_GATE_MODEL` nor `FOOD_GATE_OPEN`. Measured, cold turn, empty board:
**2 of 10 ordinary food messages reached the lane the clarification work lives
in.** `applies()`'s own docstring records 64% missed over 1008 production
messages.

The pipeline behind it was healthy the whole time:

```
quick     asks=False  ready=3  held=0
moderate  asks=True   ready=2  held=1
strict    asks=True   ready=0  held=3
```

The work was not broken. It was dark.

### `aad3416` — butter at 0 cal
Three things had to be true at once:
1. Every enrichment branch in `analyze()` required `cal > 0`. A model
   reporting no calories fell through all of them and committed untouched —
   with `source` still naming whoever won the ladder.
2. `sanity.check_values` bounds energy density from *above* only. Zero passes,
   correctly — water and black coffee really are zero. What made this zero
   impossible was a zero standing next to a source saying otherwise.
3. `food_category("butter")` returned `"default"` — no density, so `1 tbsp`
   had no mass. And neither `pat` nor `stick` was in `_COUNT_UNITS`.

| interpreter reports 0 | before | after | true |
|---|---|---|---|
| 1 tbsp | 0 | 98 | 102 |
| a pat | 0 | 36 | 36 |
| a stick | 0 | 810 | 813 |

---

## Do this first, locally

```bash
git fetch && git checkout claude/open-issues-composites-stall-usda-1ipqnu

# 1. Is anything actually damaged? READ-ONLY, every statement a SELECT.
python scripts/audit_food_damage.py --user <your id> --days 30
```

The script separates **corruption** (`daily_logs.total_calories` disagreeing
with the SUM of its `food_entries`) from **bad values written faithfully**.
Expectation is *no corruption* — the storage is fine; the numbers in it are
not. My fix stops new zeroes; **the 0-cal rows already in the log are still
zero** and keep dragging totals, trends and coaching until re-resolved.

Caveat on one detector: the rapid-fire check can't tell "one thought split
across three messages" from genuinely eating the same thing twice. Read that
table, don't act on it blind.

If it reports drift, don't fix it silently — a rebuild is a write to real
history and you should see the rows first.

---

## Still open

### 1. Composites have no external authority — UNSTARTED
`component_estimate` is on the RESTAURANT ladder and `COMPONENT_BREAKDOWN` is
in the ambiguity enum, both with **nothing behind them**: `candidate_map()`
never seats anything on that rung. `b835700` already named the fix — *"pricing
a dish from its parts is the fix, and it is unbuilt"* — and measured the cost:
composite totals drift 18-21% across modes.

Design sketch from this session (not written):
- decompose the dish into components (ours, disclosed as an assumption)
- price each component from **USDA generics** — a taco isn't in USDA, but a
  corn tortilla, carnitas, cotija and salsa all are. That is the external
  authority.
- sum with a range, seat on `component_estimate` with per-role provenance
- `analyze()` is sync, so the fetch belongs in `handlers/tool_executor.py`
  alongside the usda/off/web lanes (call site ~line 2046)
- note: `classify()` sends "two carnitas tacos" to GENERIC, not RESTAURANT, so
  the GENERIC ladder needs `component_estimate` above `estimate`

### 2. "a burger" never asks — DIAGNOSED, NOT FIXED
In *any* mode, including strict (`ready=1`). `attach_ambiguities` returns
early when the interpreter reported nothing; `derive_vague_quantities` needs a
vague measure word in the message. "a burger" has neither.

`is_generic_food_name("burger")` is **True** — the system already knows a
burger is recipe-dependent — and the clarification pipeline never consults it.
Deliberately not fixed: wiring genericness into asks means inventing calorie
spans for every generic dish, and getting it wrong floods users with
questions. This is the same problem as #1.

### 3. Denys's missing 350-cal cheese — BLOCKED
No artifact anywhere in the repo, unlike the 2026-07-22 cola drop which is
documented in `core/scribe.py`. **Needs the transcript or the date.**

### 4. The clarification question is still a template
Live, after the gate fix:

> "I picked the other amounts myself. How much of the toast — closer to 30g or
> 200g?"

200g of butter is 1,434 calories; the butter category fix moved the question
off the butter but the nonsense range moved to the toast. The range is an
f-string over a default distribution. **Commit `78672f3` below is the fix.**

---

## Unmerged work worth taking

Four commits on `origin/claude/entrypoint-routing-coordinator-suijeu` are
**not in main**, and three explain symptoms seen today. (The
`a-split-conserves-the-total` branch DID land in main under different SHAs.)

| commit | why it matters |
|---|---|
| `78672f3` | *"the clarification question is content, not a script"* — its own message: **"the composer was a tone pass over a template and was explicitly forbidden from fixing the words that were wrong — which is why turning it on did not change how these read."** This is the missing clarification quality. |
| `01d904d` | iOS rapid-fire coalescing. iOS never had `schedule_message`, so "chicken" / "and rice" / "for lunch" reliably became three logs and three confirmations. |
| `6a87910` | a shipped card said "1,245 cal left · 102g protein" with "710 for the day, 133g protein to go" beneath it — 210 cal and 31g apart, same bubble. |
| `a8f77a9` | every macro card has shipped an Undo token since 07-24 with no endpoint behind it. |

```bash
git cherry-pick 78672f3 01d904d      # the two that map onto what you're seeing
```

---

## Config state

`render.yaml` now sets, in the food path:

```yaml
TURN_COORDINATOR_MODE: new_observe
NUTRITION_RESOLVER_MODE: live
FOOD_COMPOSER: "true"
FOOD_GATE_MODEL: "true"     # added this session
```

`FOOD_GATE_OPEN` is deliberately **not** set. `food_relevance` short-circuits
on `if applies(t): return True` before consulting the model, so setting both
pays for the model lane and keeps the open gate's precision. They are
alternatives, and `tests/test_food_gate_is_reachable.py` pins that.

**Unverified from the container**: the Haiku call itself — no
`ANTHROPIC_API_KEY` here and the proxy blocks the API. The *fallback* path is
verified: on any model failure `food_relevance` returns `applies(t)`, so the
floor is exactly the pre-flag behaviour. It can be neutral; it cannot be
worse.

---

## Reproducing the diagnostics

```bash
# which messages reach the clarification lane, and why the rest don't
PYTHONPATH=. python3 - <<'PY'
import asyncio
from core.food_turn import food_relevance, decline_reason
async def m():
    for t in ["Oh and a bag of quest chips", "a scoop of peanut butter",
              "two carnitas tacos", "cottage cheese", "chicken and rice"]:
        ok = await food_relevance(t, "")
        print(f"{'OK ' if ok else 'X  '} {t!r} {'' if ok else decline_reason(t)}")
asyncio.run(m())
PY

# the pipeline behind the gate, all three modes.
#
# PASS THE REAL MESSAGE. `derive_vague_quantities` reads the user's own words
# for the vague measure ("a scoop"), so a placeholder message derives nothing
# and all three modes come back identical — which looks exactly like the
# mode-awareness being broken. It isn't; the input was.
PYTHONPATH=. python3 -c "
from core.food_pipeline import plan_turn
MSG='I had like 15 peanut m&m, half a banana and a scoop of peanut butter'
D={'items':[{'food':'Peanut M&Ms','amount':15,'unit':'pieces','branded':True,'calories':135},
            {'food':'Banana','amount':0.5,'unit':'banana','calories':53},
            {'food':'Peanut Butter','amount':1,'unit':'tbsp','calories':95}]}
for m in ('quick','moderate','strict'):
    d=plan_turn(D,turn_id='t',message=MSG,mode=m)
    print(m, d.asks, len(d.clarification.ready_item_ids or ()), getattr(d.question,'prompt',None))
"

# the zero-calorie path
PYTHONPATH=. python3 -c "
from core.food_intelligence import analyze
u={'fdc_id':1,'description':'Butter, salted','per100g':{'calories':717,'fat':81},
   '_match':'exact','basis':'per_100g','serving_text':'','serving_mass_g':None,'serving_ml':None}
for q in ['1 tbsp','a pat','a stick']:
    print(q, analyze('butter',q,0,0,0,0,usda_candidate=u).calories)
"
```

The audit script was exercised against a real Postgres 16 (schema from
`db/models`, one row of every failure shape seeded) — not reasoned about. Note
`db.database._migrate` is SQLite-only (`PRAGMA`), so build test schemas with
`Base.metadata.create_all` in its **own** transaction; running `_migrate`
alongside it rolls the whole thing back.

---

## Open question for Danny

Nothing is blocked on it, but unanswered: the session started from a rollback
that was never visible in the container — `origin/main` stayed at `9393998`
throughout and `core/food_fast_path.py` was present and unmodified. If work
was rolled back locally and matters, it still needs pushing.
