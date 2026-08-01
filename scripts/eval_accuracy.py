"""Committed-number accuracy, decomposed — the eval that would have caught skirt steak.

`scripts/eval_meals.py` scores the LLM's PASS-1 guess (`chat()` → the calories in
the tool call). But the number that lands in a user's log is the output of the
RESOLUTION — `handlers.tool_executor._analyze_food`: the authority ladder, the
real USDA / Open Food Facts lookup, and portion x density. That number is
different from the guess by design (the ground-truth path overrides it, or backs
grams out of it). So eval_meals can be green while the committed number is wrong.
This runs the real committed path and scores what actually gets written.

And it DECOMPOSES the error, because "off by 40%" is not actionable and "the
portion was 40% low, the density was right" is. A committed calorie is:

    committed_cal  =  PORTION (grams)  x  DENSITY (per-100g)

so three independent things can be wrong, and the fix for each is different:

    PORTION       grams the resolver used vs a true/typical serving. The weak
                  link for an un-weighed whole food ("skirt steak"), where grams
                  are backed out of the model's ~19%-low calorie guess.
    DENSITY       the per-100g the resolver seated vs the truth for the RIGHT
                  food AND preparation. A raw row for a cooked food, a lean row
                  for a fatty cut, a wrong cousin.
    PREPARATION   a special case of density the system captures worst: grilled vs
                  fried, plain vs marinated/oiled/dressed. Encoded as pairs that
                  share a base food and differ only in preparation — if both
                  resolve to the same density, preparation was not captured, and
                  at most one of the pair can be right.

Ground truth is curated and defensible (USDA cooked per-100g x a standard
serving), NOT scraped and NOT heuristic. Each case carries the numbers and their
basis so the set is auditable and correctable.

    export USDA_API_KEY=...            # real lookups; the resolver needs it
    python scripts/eval_accuracy.py                    # all axes
    python scripts/eval_accuracy.py --axis portion     # one axis
    python scripts/eval_accuracy.py --json out.json

Read-only against a throwaway in-memory user (no history), so nothing here writes
to anyone's log. The LLM's pass-1 guess is SUPPLIED per case (deterministic given
USDA); `--live` fetches a real guess instead, at the cost of reproducibility.
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


# ── The gold set ─────────────────────────────────────────────────────────────
# Case = dict(id, msg, food, qty, guess, true_g, true_c100, axis, prep, note).
#   true_c100 = true calories per 100 g for the RIGHT food + preparation.
#   true_cal  = true_g * true_c100 / 100  (computed, never stored — one source).
#   guess     = the model's pass-1 calorie read (what production feeds `analyze`).
# Preparation pairs share (base food, portion) and differ only in prep, so a
# density that ignores prep makes them identical and at most one can pass.

GOLD: list[dict] = [
    # ── CONTROL: weighed, common, label/USDA-clean — should be accurate ───────
    dict(id="ctrl-chicken-6oz", msg="6 oz grilled chicken breast", food="grilled chicken breast",
         qty="6 oz", guess=280, true_g=170, true_c100=165, axis="control",
         prep="grilled", note="USDA chicken breast, cooked grilled ~165/100g; 6oz=170g"),
    dict(id="ctrl-quest-bar", msg="a Quest chocolate chip cookie dough bar", food="Quest Bar",
         qty="1 bar", guess=190, true_g=60, true_c100=333, axis="branded",
         prep="", note="published label 200 cal / 60g bar"),

    # ── PORTION: un-weighed whole food — grams inferred from the model guess ──
    dict(id="port-skirt-steak", msg="skirt steak", food="skirt steak",
         qty="", guess=300, true_g=200, true_c100=255, axis="portion",
         prep="cooked", note="USDA beef skirt steak, cooked, lean+fat ~255/100g; typical serving ~200g cooked (7oz)"),
    dict(id="port-ribeye", msg="ribeye", food="ribeye steak",
         qty="", guess=350, true_g=225, true_c100=291, axis="portion",
         prep="cooked", note="USDA ribeye cooked ~291/100g; ~8oz cooked serving"),
    dict(id="port-almonds", msg="handful of almonds", food="almonds",
         qty="handful", guess=120, true_g=28, true_c100=579, axis="portion",
         prep="", note="USDA almonds 579/100g; a handful ~28g (1 oz)"),

    # ── PREPARATION: same base food, prep changes the density ─────────────────
    dict(id="prep-thigh-grilled", msg="6 oz grilled chicken thigh", food="grilled chicken thigh",
         qty="6 oz", guess=280, true_g=170, true_c100=209, axis="preparation",
         prep="grilled", note="USDA chicken thigh, cooked, no skin ~209/100g"),
    dict(id="prep-thigh-fried", msg="6 oz fried chicken thigh", food="fried chicken thigh",
         qty="6 oz", guess=340, true_g=170, true_c100=270, axis="preparation",
         prep="fried/breaded", note="USDA fried/battered chicken thigh ~270/100g — breading + oil vs grilled 209"),

    # ── ADDED FAT / MARINADE / DRESSING: invisible in the base-food match ─────
    dict(id="fat-steak-plain", msg="8 oz sirloin steak", food="sirloin steak",
         qty="8 oz", guess=380, true_g=225, true_c100=212, axis="added_fat",
         prep="grilled, no added fat", note="USDA sirloin cooked ~212/100g, dry-cooked"),
    dict(id="fat-steak-butter", msg="8 oz sirloin steak cooked in butter", food="sirloin steak",
         qty="8 oz", guess=400, true_g=225, true_c100=257, axis="added_fat",
         prep="+1 tbsp butter", note="212/100g base + ~100 cal butter over 225g = ~257/100g effective"),
    dict(id="fat-salad-plain", msg="a big green salad, no dressing", food="green salad",
         qty="1 bowl", guess=60, true_g=200, true_c100=25, axis="added_fat",
         prep="undressed", note="mixed greens/veg ~25/100g"),
    dict(id="fat-salad-ranch", msg="a big green salad with ranch", food="green salad with ranch",
         qty="1 bowl", guess=180, true_g=230, true_c100=76, axis="added_fat",
         prep="+2 tbsp ranch ~145 cal", note="50 cal greens + 145 cal ranch over 230g = ~76/100g effective"),
]


def true_cal(c: dict) -> float:
    return round(c["true_g"] * c["true_c100"] / 100.0)


# ── Deterministic lookups: record once, replay forever ───────────────────────
# The only non-determinism is the NETWORK, and it is fixtured at the DEEPEST
# seam that still leaves the resolver real: the raw candidate lists from
# `api.usda.search_food` and `skills.nutrition.off.search`, plus the branded
# `_web_lookup_packaged`. Everything ABOVE those — `best_candidate` (the
# matcher), the authority ladder, portion x density, the cooked/prep logic —
# runs live against the fixtured candidates. So a change to the MATCHER is
# measurable here; fixturing one layer up (`_fetch_usda_off`, post-matcher)
# would have baked the old matcher's verdict into the fixture and made Part 1
# untestable. Recording is incremental; `--record` on the prod key fills it.

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
            branded = c["axis"] == "branded"
            off = await _off.search(food) if branded else None
            web = await TE._web_lookup_packaged(food, c["qty"] or None) if branded else None
            # NEVER store an empty capture: a throttled search returns [] here,
            # indistinguishable from a real no-match. Storing that poisons the
            # fixture (food marked captured, never re-fetched). Every gold food
            # returns SOME candidates from USDA, so "nothing came back" means
            # "retry with a real key". Left uncached → retried next --record.
            # (A food best_candidate later REJECTS still has raw candidates here;
            # that rejection is the resolver's job, tested live on replay.)
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
    print(f"\nfixture: {len(fx)}/{len(cases)} foods covered "
          f"({new} new, {got} already) → {_FIXTURE.relative_to(_FIXTURE.parent.parent.parent)}")
    return 0 if len(fx) == len(cases) else 1


# ── Run one case through the real committed-number path ──────────────────────

async def committed(db, user, c: dict):
    """`FoodAnalysis` as production would commit it, for this case's food + guess."""
    from handlers.tool_executor import _analyze_food
    inp = {
        "food_name": c["food"], "quantity": c["qty"] or None,
        "calories": c["guess"],
        # macros roughly Atwater-split off the guess so reconcile has something
        # plausible; density/portion is what we are measuring, not the split.
        "protein": round(c["guess"] * 0.3 / 4), "carbs": round(c["guess"] * 0.4 / 4),
        "fats": round(c["guess"] * 0.3 / 9),
        "is_packaged": c["axis"] == "branded",
    }
    return await _analyze_food(db, user, c["food"], inp)


def decompose(c: dict, fa) -> dict:
    """Committed number vs truth, split into portion / density / total."""
    committed_cal = float(getattr(fa, "calories", 0) or 0)
    per100 = getattr(fa, "per100", None) or {}
    c100 = per100.get("calories")
    tcal = true_cal(c)

    row = {
        "id": c["id"], "axis": c["axis"], "msg": c["msg"],
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
        # Pure-estimate path: no seated density, so there is nothing to split —
        # the whole number is the model's guess, which is itself the finding.
        row["note"] = "estimate path — no seated density, error is all model guess"
    return row


def _fmt(v, suffix="%"):
    return "  -  " if v is None else f"{v:+d}{suffix}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", choices=sorted({c["axis"] for c in GOLD}))
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--tolerance", type=int, default=10,
                    help="cal error %% within which a case PASSES (default 10)")
    ap.add_argument("--record", action="store_true",
                    help="fetch + cache real USDA/OFF lookups for missing foods (needs USDA_API_KEY)")
    ap.add_argument("--live", action="store_true",
                    help="hit the real network instead of the fixture (needs USDA_API_KEY)")
    args = ap.parse_args()

    cases = [c for c in GOLD if not args.axis or c["axis"] == args.axis]

    if args.record:
        if not os.getenv("USDA_API_KEY"):
            print("--record needs USDA_API_KEY (DEMO_KEY works but throttles).")
            return 2
        return await _record(cases)

    # Default: replay the fixture — deterministic, offline, a real gate. --live
    # opts back into the network for a fresh (non-reproducible) measurement.
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
        user = models.User(telegram_id="eval-accuracy", name="Eval",
                           onboarding_completed=True)
        db.add(user)
        await db.commit()

        rows = []
        for i, c in enumerate(cases):
            if i and args.live:
                # Only when hitting the network: gentle on the public DEMO_KEY,
                # whose 429 would silently drop a case to the estimate path.
                # The fixture replay is offline, so it needs no wait.
                await asyncio.sleep(float(os.getenv("EVAL_ACCURACY_DELAY", "2")))
            try:
                fa = await committed(db, user, c)
                rows.append(decompose(c, fa))
            except Exception as e:
                rows.append({"id": c["id"], "axis": c["axis"], "msg": c["msg"],
                             "error": f"{type(e).__name__}: {e}"})

    print(f"\ncommitted-number accuracy — {len(rows)} cases, "
          f"PASS = cal error within +/-{args.tolerance}%\n")
    print(f"{'id':<20} {'axis':<12} {'cal':>10} {'cal_err':>8} "
          f"{'portion':>8} {'density':>8}  source")
    print("-" * 88)
    by_axis: dict = {}
    for r in rows:
        if "error" in r:
            print(f"{r['id']:<20} {r['axis']:<12}  ERROR: {r['error'][:44]}")
            continue
        p = abs(r["cal_err_pct"]) <= args.tolerance if r["cal_err_pct"] is not None else False
        by_axis.setdefault(r["axis"], []).append(p)
        print(f"{r['id']:<20} {r['axis']:<12} "
              f"{r['committed_cal']:>4}/{r['true_cal']:<5} {_fmt(r['cal_err_pct']):>8} "
              f"{_fmt(r['portion_err_pct']):>8} {_fmt(r['density_err_pct']):>8}  "
              f"{r['source']} ({'PASS' if p else 'FAIL'})")

    print("\nby axis:")
    for axis, res in sorted(by_axis.items()):
        print(f"  {axis:<14} {sum(res)}/{len(res)} within tolerance")

    # Preparation pairs: if a grilled/fried (or plain/added-fat) pair resolves to
    # the SAME density, preparation was not captured and the pair is called out.
    print("\npreparation capture (paired cases sharing a base food):")
    _pairs = [("prep-thigh-grilled", "prep-thigh-fried"),
              ("fat-steak-plain", "fat-steak-butter"),
              ("fat-salad-plain", "fat-salad-ranch")]
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
        import pathlib
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {len(rows)} rows to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
