"""Read the three C-rerun arms against the PREREGISTERED conditions.

`docs/PREREG_C_RERUN_2026-08-31.md` fixed the refusal conditions, the metrics
and the prediction before the first turn ran. This script checks them in that
order and REFUSES to report an effect if any refusal condition holds — a run
that fails its own validity checks is VOID, not noisy.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scripts.config_pin import comparable, differs_only_in   # noqa: E402

ARMS = {
    "E1 (C off)":       "data/corpus/census_E1_repaired_Coff_2026-08-31.jsonl",
    "E2 (C off, twin)": "data/corpus/census_E2_nulltwin_Coff_2026-08-31.jsonl",
    "E3 (C ON)":        "data/corpus/census_E3_Con_2026-08-31.jsonl",
}
CORPUS = json.load(open("data/corpus/real_meal_expectations_v1.json"))
EXPECTED = {c["id"]: c for c in CORPUS["cases"]}


def load(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    return rows[0]["_config"], rows[1:]


def ambiguities(rec):
    for s in (rec.get("staged_state") or ()):
        for it in (s.get("staged_items") or ()):
            for a in (it.get("ambiguities") or ()):
                yield it, a


def main():
    cfg, rows = {}, {}
    for name, path in ARMS.items():
        if not pathlib.Path(path).exists():
            raise SystemExit(f"missing arm output: {path}")
        cfg[name], rows[name] = load(path)

    # ── REFUSAL CONDITIONS, before any number is reported ────────────────────
    print("── refusal conditions ───────────────────────────────────────────")
    void = []
    shas = {n: c["_code_sha"] for n, c in cfg.items()}
    print(f"  _code_sha: {shas}")
    if len(set(shas.values())) != 1:
        void.append(f"_code_sha differs across arms: {shas}")
    for n, c in cfg.items():
        want = "true" if "ON" in n else "false"
        got = c.get("FOOD_EXTRAS_REPORT_ONLY")
        arm = (c.get("_arm") or {}).get("FOOD_EXTRAS_REPORT_ONLY")
        print(f"  {n:18s} FOOD_EXTRAS_REPORT_ONLY={got!r} _arm={arm!r}")
        if got != want:
            void.append(f"{n}: flag {got!r}, expected {want!r}")
    ok, reasons = comparable(cfg["E1 (C off)"], cfg["E2 (C off, twin)"])
    print(f"  E1 vs E2 comparable: {ok} {reasons}")
    if not ok:
        void.append(f"the null pair is not comparable: {reasons}")
    only, stray = differs_only_in(cfg["E1 (C off)"], cfg["E3 (C ON)"],
                                 {"FOOD_EXTRAS_REPORT_ONLY"})
    print(f"  E1 vs E3 differs ONLY in the arm: {only} {stray}")
    if not only:
        void.append(f"E1 vs E3 differ beyond the arm: {stray}")

    # instrument liveness: the basis must be FILLED, not merely readable
    for n in ARMS:
        vals = [a.get("impact_basis_cal") for r in rows[n] for _, a in ambiguities(r)]
        missing = [v for v in vals if v == "MISSING"]
        filled = [v for v in vals if isinstance(v, (int, float))]
        print(f"  {n:18s} ambiguities={len(vals):3d}  basis filled={len(filled):3d}"
              f"  MISSING={len(missing)}")
        if missing:
            void.append(f"{n}: {len(missing)} ambiguities have no basis field")
        if vals and not filled:
            void.append(f"{n}: EVERY basis is None — inert read")
    if void:
        print("\n⛔ RUN IS VOID:")
        for v in void:
            print("   -", v)
        raise SystemExit(1)
    print("  ✓ all refusal conditions clear\n")

    # ── 1. ask rate ──────────────────────────────────────────────────────────
    def askrate(n):
        rs = rows[n]
        asks = sum(1 for r in rs if "food_structured_ask" in (r.get("q_kinds") or []))
        return asks, len(rs)
    print("── 1. ask rate (food_structured_ask) ────────────────────────────")
    rate = {}
    for n in ARMS:
        a, t = askrate(n)
        rate[n] = a
        print(f"  {n:18s} {a:2d}/{t}  = {100*a/t:.0f}%")
    null = abs(rate["E1 (C off)"] - rate["E2 (C off, twin)"])
    base = (rate["E1 (C off)"] + rate["E2 (C off, twin)"]) / 2
    effect = rate["E3 (C ON)"] - base
    print(f"\n  NULL ENVELOPE |E1-E2| = {null}")
    print(f"  EFFECT  E3 - mean(E1,E2) = {effect:+.1f}")
    verdict = ("INSIDE the envelope — no reliable effect"
               if abs(effect) <= null else
               "OUTSIDE the envelope — an effect survives")
    print(f"  -> {verdict}")

    # ── 2. Danny's second clause ─────────────────────────────────────────────
    print("\n── 2. did re-parenting change any materiality decision? ─────────")
    bad = []
    for n in ARMS:
        for r in rows[n]:
            for it, a in ambiguities(r):
                if a.get("field_name") in ("extras", "ingredient", "add_on"):
                    if a.get("impact_basis_cal") is not None:
                        bad.append((n, r["case"], a))
    print(f"  extras facts carrying a PARENT basis: {len(bad)}")
    if bad:
        for n, c, a in bad[:5]:
            print(f"    ⛔ {n} c{c} basis={a.get('impact_basis_cal')}")
    else:
        print("  ✓ every component-scoped fact carries NOT-ESTABLISHED, as designed")

    print("\n  extras facts and their outcome (arm D3 only):")
    for r in rows["E3 (C ON)"]:
        for it, a in ambiguities(r):
            if a.get("field_name") in ("extras", "ingredient", "add_on"):
                print(f"    c{r['case']} rep{r['rep']}  span={a.get('calorie_span')}"
                      f"  basis={a.get('impact_basis_cal')}  score={a.get('score')}"
                      f"  material={a.get('material')}  on {it.get('text','')[:34]!r}")

    # ── 3. c1 — the preregistered prediction ─────────────────────────────────
    print("\n── 3. c1: did the mayo ask come back under C? ───────────────────")
    for n in ARMS:
        for r in rows[n]:
            if r["case"] != 1:
                continue
            fs = [(a.get("field_name"), a.get("material"), a.get("calorie_span"),
                   a.get("impact_basis_cal")) for _, a in ambiguities(r)]
            print(f"  {n:18s} rep{r['rep']}  asked={bool(r.get('q_kinds'))}"
                  f"  staged={r.get('staged_raised')}  items="
                  f"{len((r.get('staged_state') or [{}])[0].get('staged_items') or [])}"
                  f"  {fs}")

    # ── 4. c17 must hold ─────────────────────────────────────────────────────
    print("\n── 4. c17 (the case both rejected variants destroyed) ───────────")
    for n in ARMS:
        got = [bool(r.get("q_kinds")) for r in rows[n] if r["case"] == 17]
        print(f"  {n:18s} asked={got}")

    # ── 5. component structure vs the frozen labels ──────────────────────────
    print("\n── 5. staged item count vs expected_component_range ─────────────")
    for n in ARMS:
        off = []
        for r in rows[n]:
            st = (r.get("staged_state") or [{}])[0]
            k = len(st.get("staged_items") or [])
            lo, hi = EXPECTED[r["case"]]["expected_component_range"]
            if k and not (lo <= k <= hi):
                off.append(f"c{r['case']}r{r['rep']}:{k}∉[{lo},{hi}]")
        print(f"  {n:18s} out-of-range: {len(off)}  {off[:8]}")


if __name__ == "__main__":
    main()
