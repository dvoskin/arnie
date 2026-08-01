"""RESOLVER accuracy, decomposed — the committed number for a FULLY-SPECIFIED food.

This is ONE of two accuracy evals, deliberately separated (Danny 2026-08-01):

  * eval_resolver.py     (this)  — given a food and everything stated about it,
                                   is the committed calorie/macro number right?
  * eval_conversation.py         — does the clarification FLOW detect uncertainty,
                                   ask the right question, apply the answer, and
                                   avoid unnecessary questions?

They must not be conflated. The butter-steak case is the reason: a steak whose
butter the user never stated is NOT a resolver failure — the resolver cannot
invent an ingredient nobody named. It is a CONVERSATION case (elicit the fat,
then apply it), and it lives in eval_conversation.py. Judging it here would
pressure the resolver to guess fat it cannot know — the exact distortion this
split exists to prevent. RULE: every case here states everything the resolver
needs; if the answer can only come from asking, it belongs in the other eval.

WHAT IT MEASURES. The number that lands in a log is the output of the RESOLUTION
(`handlers.tool_executor._analyze_food`: the authority ladder, the real USDA /
Open Food Facts lookup, portion x density), not the model's pass-1 guess. It
DECOMPOSES the error, because "off by 40%" is not actionable and "portion 40%
low, density right" is:

    committed_cal  =  PORTION (grams)  x  DENSITY (per-100g)

    PORTION       grams used vs a true/typical serving.
    DENSITY       per-100g seated vs the truth for the RIGHT food AND prep.
    PREPARATION   density's worst case: grilled vs fried, plain vs dressed.
                  Encoded as pairs sharing a base food; same density → not
                  captured, and at most one of the pair can be right.

SCORED BY CATEGORY, not one aggregate (Danny 2026-08-01). The categories are the
release-corpus taxonomy; the coverage report names which are populated and which
still need real captures. Ground truth is curated and defensible (USDA cooked
per-100g x a standard serving), NOT scraped, NOT heuristic, NOT fitted.

    export USDA_API_KEY=...
    python scripts/eval_resolver.py                       # all categories
    python scripts/eval_resolver.py --category vague_whole_food
    python scripts/eval_resolver.py --record             # capture missing foods
    python scripts/eval_resolver.py --json out.json

Read-only against a throwaway in-memory user (no history), so nothing writes to
anyone's log. The pass-1 guess is SUPPLIED per case (deterministic given USDA);
`--live` fetches a real guess instead, at the cost of reproducibility.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# The resolver builds a DB engine on import; point it at a scratch DB so a clean
# checkout runs this with no environment beyond USDA_API_KEY.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ── The release-corpus taxonomy ──────────────────────────────────────────────
# The categories a release corpus must cover (Danny 2026-08-01). Declared in full
# so the coverage report can flag the EMPTY ones — the 10 cases below are
# development controls, not broad validation, and the gaps must be visible rather
# than hidden behind one green number. Populating the empty categories needs real
# captures (`--record` on the prod USDA key) + sourced ground truth; they are NOT
# faked here. Conversational-only categories (partial consumption, corrections)
# live in eval_conversation.py, not this list.
RESOLVER_CATEGORIES = [
    "weighed_whole_food",     # mass stated ("8 oz sirloin")
    "vague_whole_food",       # un-weighed, resolver uses the portion prior
    "branded_single",         # one labeled serving
    "branded_multipack",      # a multi-serving package (per-serving vs whole)
    "restaurant",             # chain item with published nutrition
    "cooking_fat_stated",     # oil/butter NAMED in the input
    "sauce_dressing_stated",  # sauce/dressing NAMED in the input
    "raw_vs_cooked",          # the same food raw vs cooked (density shift)
    "skinless_vs_skinon",     # trim: meat-only vs meat-and-skin / lean vs lean+fat
    "misleading_usda",        # USDA returns wrong species/cut cousins
    "repeated_personal_food", # the user's own logged history is authority
]


# ── The gold set (development controls) ──────────────────────────────────────
# Case = dict(id, msg, food, qty, guess, true_g, true_c100, category, prep, note).
#   true_c100 = true calories per 100 g for the RIGHT food + preparation.
#   true_cal  = true_g * true_c100 / 100  (computed, never stored — one source).
#   guess     = the model's pass-1 calorie read (what production feeds `analyze`).

GOLD: list[dict] = [
    dict(id="ctrl-chicken-6oz", msg="6 oz grilled chicken breast", food="grilled chicken breast",
         qty="6 oz", guess=280, true_g=170, true_c100=165, category="weighed_whole_food",
         prep="cooked", note="USDA chicken breast, cooked, meat only ~165/100g; 6oz=170g"),
    dict(id="whole-steak-plain", msg="8 oz sirloin steak", food="sirloin steak",
         qty="8 oz", guess=380, true_g=225, true_c100=212, category="weighed_whole_food",
         prep="cooked", note="USDA sirloin, cooked, lean+fat ~212/100g; 8oz=225g. Plain: no added fat."),
    dict(id="branded-quest-bar", msg="a Quest chocolate chip cookie dough bar", food="Quest Bar",
         qty="1 bar", guess=190, true_g=60, true_c100=333, category="branded_single",
         prep="", note="Quest bar label: 200 cal / 60 g"),
    dict(id="vague-skirt-steak", msg="skirt steak", food="skirt steak",
         qty="", guess=300, true_g=200, true_c100=255, category="vague_whole_food",
         prep="cooked", note="USDA beef skirt steak, cooked, lean+fat ~255/100g; typical serving ~200g cooked"),
    dict(id="vague-almonds", msg="handful of almonds", food="almonds",
         qty="handful", guess=120, true_g=28, true_c100=579, category="vague_whole_food",
         prep="", note="USDA almonds ~579/100g; a handful ~28g (1 oz)"),
    dict(id="vague-salad-plain", msg="a big green salad, no dressing", food="green salad",
         qty="1 bowl", guess=60, true_g=200, true_c100=25, category="vague_whole_food",
         prep="", note="leafy greens ~25/100g; ~200g bowl. Resolver residual: estimates instead of a greens density."),
    dict(id="misleading-ribeye", msg="ribeye", food="ribeye steak",
         qty="", guess=350, true_g=225, true_c100=291, category="misleading_usda",
         prep="cooked", note="USDA returns bison + ribeye CAP; real beef ribeye cooked ~291/100g; ~225g"),
    dict(id="skinon-thigh-grilled", msg="6 oz grilled chicken thigh", food="grilled chicken thigh",
         qty="6 oz", guess=280, true_g=170, true_c100=209, category="skinless_vs_skinon",
         prep="cooked", note="chicken thigh, meat AND skin, cooked ~209/100g; 6oz=170g (as-eaten, not meat-only)"),
    dict(id="skinon-thigh-fried", msg="6 oz fried chicken thigh", food="fried chicken thigh",
         qty="6 oz", guess=340, true_g=170, true_c100=270, category="skinless_vs_skinon",
         prep="cooked", note="fried thigh, meat+skin+breading ~270/100g; 6oz=170g"),
    dict(id="sauce-salad-ranch", msg="a big green salad with ranch", food="green salad with ranch",
         qty="1 bowl", guess=180, true_g=230, true_c100=76, category="sauce_dressing_stated",
         prep="+2 tbsp ranch ~145 cal", note="50 cal greens + 145 cal ranch over 230g = ~76/100g effective"),
]


def true_cal(c: dict) -> float:
    return round(c["true_g"] * c["true_c100"] / 100.0)


def _is_branded(c: dict) -> bool:
    """Categories that carry label data → fetch Open Food Facts + the web label."""
    return c["category"] in ("branded_single", "branded_multipack", "restaurant")


# ── Deterministic lookups: record once, replay forever ───────────────────────
# The only non-determinism is the NETWORK, fixtured at the DEEPEST seam that still
# leaves the resolver real: the raw candidate lists from `api.usda.search_food`
# and `skills.nutrition.off.search`, plus the branded `_web_lookup_packaged`.
# Everything ABOVE — `best_candidate` (the matcher), the authority ladder,
# portion x density, cooked/prep — runs live against the fixtured candidates, so a
# change to the MATCHER is measurable here. Recording is incremental; `--record`
# on the prod key fills it.

_FIXTURE = pathlib.Path(__file__).resolve().parent.parent / "tests" / "corpus" / "food_lookup_fixtures.json"


def _load_fixture() -> dict:
    try:
        return json.loads(_FIXTURE.read_text())
    except FileNotFoundError:
        return {}


def _install_replay(fx: dict) -> None:
    """Patch the raw lookup seams to read the fixture, no network — leaving the
    matcher and the whole resolver live. A food the fixture doesn't cover
    returns nothing, which surfaces as the estimate path, honestly flagged."""
    import api.usda as _usda
    import skills.nutrition.off as _off
    import handlers.tool_executor as TE

    async def _replay_search(query, page_size=5):
        return list((fx.get(query) or {}).get("usda_raw") or [])

    async def _replay_off(query):
        return (fx.get(query) or {}).get("off")

    async def _replay_web(food_name, quantity):
        return (fx.get(food_name) or {}).get("web")

    _usda.search_food = _replay_search
    _off.search = _replay_off
    TE._web_lookup_packaged = _replay_web


async def _record(cases: list[dict]) -> int:
    """Fill the fixture with the REAL lookups for any gold food it is missing.
    Incremental + idempotent; needs a working USDA key. Never overwrites a
    captured entry, so a good capture is never lost to a later throttled run."""
    import api.usda as _usda
    import skills.nutrition.off as _off
    import handlers.tool_executor as TE
    fx = _load_fixture()
    got = new = 0
    for c in cases:
        food = c["food"]
        if food in fx:
            got += 1
            continue
        try:
            usda_raw = await _usda.search_food(food, 8)          # RAW candidate list
            branded = _is_branded(c)
            off = await _off.search(food) if branded else None
            web = await TE._web_lookup_packaged(food, c["qty"] or None) if branded else None
            # NEVER store an empty capture: a throttled search returns [] here,
            # indistinguishable from a real no-match. Storing that poisons the
            # fixture (food marked captured, never re-fetched). Left uncached →
            # retried next --record.
            if not (usda_raw or off or web):
                print(f"  EMPTY {food!r} (throttled) — left uncached")
                continue
            fx[food] = {"usda_raw": usda_raw, "off": off, "web": web,
                        "_captured_for": c["id"]}
            new += 1
            print(f"  captured {food!r} (usda_raw={len(usda_raw or [])} off={'y' if off else '-'})")
        except Exception as e:
            print(f"  MISS {food!r}: {type(e).__name__}: {str(e)[:60]}")
        await asyncio.sleep(float(os.getenv("EVAL_ACCURACY_DELAY", "3")))
    _FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    _FIXTURE.write_text(json.dumps(fx, indent=1, ensure_ascii=False))
    print(f"\nfixture: {len([c for c in cases if c['food'] in fx])}/{len(cases)} foods covered "
          f"({new} new, {got} already)")
    return 0 if all(c["food"] in fx for c in cases) else 1


# ── Run one case through the real committed-number path ──────────────────────

async def committed(db, user, c: dict):
    """`FoodAnalysis` as production would commit it, for this case's food + guess."""
    from handlers.tool_executor import _analyze_food
    inp = {
        "food_name": c["food"], "quantity": c["qty"] or None,
        "calories": c["guess"],
        "protein": round(c["guess"] * 0.3 / 4), "carbs": round(c["guess"] * 0.4 / 4),
        "fats": round(c["guess"] * 0.3 / 9),
        "is_packaged": _is_branded(c),
    }
    return await _analyze_food(db, user, c["food"], inp)


def decompose(c: dict, fa) -> dict:
    """Committed number vs truth, split into portion / density / total."""
    committed_cal = float(getattr(fa, "calories", 0) or 0)
    per100 = getattr(fa, "per100", None) or {}
    c100 = per100.get("calories")
    tcal = true_cal(c)

    row = {
        "id": c["id"], "category": c["category"], "msg": c["msg"],
        "true_cal": tcal, "committed_cal": round(committed_cal),
        "source": getattr(fa, "source", "?"), "confidence": getattr(fa, "confidence", "?"),
        "cal_err_pct": round(100 * (committed_cal - tcal) / tcal) if tcal else None,
        "density_err_pct": None, "portion_err_pct": None,
        "committed_g": None, "committed_c100": (round(c100) if c100 else None),
    }
    if c100:
        row["density_err_pct"] = round(100 * (c100 - c["true_c100"]) / c["true_c100"])
        committed_g = committed_cal / (c100 / 100.0)
        row["committed_g"] = round(committed_g)
        row["portion_err_pct"] = round(100 * (committed_g - c["true_g"]) / c["true_g"])
    else:
        row["note"] = "estimate path — no seated density, error is all model guess"
    return row


def _fmt(v, suffix="%"):
    return "  -  " if v is None else f"{v:+d}{suffix}"


def _coverage(cases: list[dict]) -> None:
    """Which release categories are populated, which still need real captures.
    The point of scoring by category: an empty category is a KNOWN gap, not a
    silent pass."""
    counts: dict = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    print("\ncorpus coverage (release categories):")
    for cat in RESOLVER_CATEGORIES:
        n = counts.get(cat, 0)
        tag = f"{n} case(s)" if n else "NEEDS CORPUS — real captures required"
        print(f"  {cat:<24} {tag}")
    extra = sorted(set(counts) - set(RESOLVER_CATEGORIES))
    for cat in extra:
        print(f"  {cat:<24} {counts[cat]} case(s)  (not in the release taxonomy)")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", choices=sorted({c["category"] for c in GOLD}))
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--tolerance", type=int, default=10,
                    help="cal error %% within which a case PASSES (default 10)")
    ap.add_argument("--record", action="store_true",
                    help="fetch + cache real USDA/OFF lookups for missing foods (needs USDA_API_KEY)")
    ap.add_argument("--live", action="store_true",
                    help="hit the real network instead of the fixture (needs USDA_API_KEY)")
    args = ap.parse_args()

    cases = [c for c in GOLD if not args.category or c["category"] == args.category]

    if args.record:
        if not os.getenv("USDA_API_KEY"):
            print("--record needs USDA_API_KEY (DEMO_KEY works but throttles).")
            return 2
        return await _record(cases)

    fx = _load_fixture()
    if args.live:
        if not os.getenv("USDA_API_KEY"):
            print("--live needs USDA_API_KEY.")
            return 2
    else:
        if not fx:
            print(f"no fixture at {_FIXTURE} — run `--record` once (with USDA_API_KEY) "
                  "to capture the lookups, then this replays them offline.")
            return 2
        _install_replay(fx)
        missing = [c["food"] for c in cases if c["food"] not in fx]
        if missing:
            print(f"note: {len(missing)} food(s) not in the fixture, will show as "
                  f"estimate path: {', '.join(missing)}\n")

    from db.database import engine, Base, AsyncSessionLocal
    import db.models as models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        rows = []
        for i, c in enumerate(cases):
            if i and args.live:
                await asyncio.sleep(float(os.getenv("EVAL_ACCURACY_DELAY", "2")))
            try:
                # A FRESH user per case: `_analyze_food` re-caches a confident hit,
                # so a shared user turns the second log of a food into a MEMORY hit,
                # contaminating the measurement. Each case resolves from scratch.
                user = models.User(telegram_id=f"eval-{i}", name="Eval",
                                   onboarding_completed=True)
                db.add(user)
                await db.commit()
                fa = await committed(db, user, c)
                rows.append(decompose(c, fa))
            except Exception as e:
                rows.append({"id": c["id"], "category": c["category"], "msg": c["msg"],
                             "error": f"{type(e).__name__}: {e}"})

    print(f"\nRESOLVER accuracy — {len(rows)} cases, "
          f"PASS = cal error within +/-{args.tolerance}%\n")
    print(f"{'id':<22} {'category':<22} {'cal':>10} {'cal_err':>8} "
          f"{'portion':>8} {'density':>8}  source")
    print("-" * 96)
    by_cat: dict = {}
    for r in rows:
        if "error" in r:
            print(f"{r['id']:<22} {r['category']:<22}  ERROR: {r['error'][:40]}")
            by_cat.setdefault(r["category"], []).append(False)
            continue
        p = abs(r["cal_err_pct"]) <= args.tolerance if r["cal_err_pct"] is not None else False
        by_cat.setdefault(r["category"], []).append(p)
        print(f"{r['id']:<22} {r['category']:<22} "
              f"{r['committed_cal']:>4}/{r['true_cal']:<5} {_fmt(r['cal_err_pct']):>8} "
              f"{_fmt(r['portion_err_pct']):>8} {_fmt(r['density_err_pct']):>8}  "
              f"{r['source']} ({'PASS' if p else 'FAIL'})")

    print("\nby category:")
    for cat in sorted(by_cat):
        res = by_cat[cat]
        print(f"  {cat:<24} {sum(res)}/{len(res)} within tolerance")
    total = [p for res in by_cat.values() for p in res]
    print(f"  {'TOTAL':<24} {sum(total)}/{len(total)}")

    _coverage(cases)

    # Preparation pairs: if a pair sharing a base food resolves to the SAME
    # density, preparation was not captured and the pair is called out.
    print("\npreparation capture (paired cases sharing a base food):")
    _pairs = [("skinon-thigh-grilled", "skinon-thigh-fried"),
              ("vague-salad-plain", "sauce-salad-ranch")]
    idx = {r["id"]: r for r in rows if "error" not in r}
    for a, b in _pairs:
        ra, rb = idx.get(a), idx.get(b)
        if not ra or not rb:
            continue
        da, dbb = ra.get("committed_c100"), rb.get("committed_c100")
        captured = da is not None and dbb is not None and abs(da - dbb) > 5
        print(f"  {a} vs {b}: committed density {da} vs {dbb} — "
              f"{'CAPTURED' if captured else 'NOT captured (same density → prep ignored)'}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {len(rows)} rows to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
