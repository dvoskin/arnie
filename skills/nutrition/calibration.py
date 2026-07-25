"""Threshold calibration (PR #31).

Every threshold in the ask ladder was picked by judgement: 200 calories for
moderate, 0.5 for the fraction rule, 0.15 for the coin-toss margin. Judgement
was the right way to get a first number — there was nothing to calibrate
against — and it is the wrong way to keep one.

This is the machinery for replacing them with measurements, and the honest
statement of what each kind of data can and cannot tell us:

    THE GOLD SUITE tells us whether a threshold is CORRECT. Every case states
    what each mode should do, so a sweep produces the exact set of cases a
    candidate threshold would get wrong, in both directions.

    PRODUCTION LOGS tell us how OFTEN each situation occurs. They cannot tell
    us whether an ask was right — nobody recorded the counterfactual — so
    treating an ask rate as an error rate is the mistake this module exists to
    avoid.

    CORRECTIONS tell us where we were WRONG, and only there. A correction is
    ground truth about one turn, produced by the only oracle that exists.

Put together: gold gives correctness, production gives frequency, corrections
give the failures. A recommendation weights the first by the second and checks
it against the third. Any one alone is misleading, which is why the report
prints all three and refuses to collapse them into a single score.

    python -m skills.nutrition.calibration              # gold sweep only
    python -m skills.nutrition.calibration arnie.log    # with production shape

The asymmetry that drives every default here: a **missed** material ambiguity
writes a wrong number into someone's day silently. A **needless** ask costs
them one tap. Those are not the same size of mistake, so the sweep reports them
separately and never sums them.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

CALIBRATION_VERSION = "calibration_v1"

MODES = ("quick", "moderate", "strict")


# ── outcomes ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Miss:
    """One case a candidate threshold would get wrong."""
    case_id: str
    mode: str
    expected: bool
    actual: bool

    @property
    def kind(self) -> str:
        """`silent` when we should have asked and did not — the expensive
        direction. `needless` when we asked and should not have."""
        return "silent" if self.expected and not self.actual else "needless"


@dataclass(frozen=True)
class Point:
    """One threshold setting, and what it would cost.

    `silent` and `needless` are deliberately not summed. A missed material
    ambiguity writes a wrong number into someone's day; a needless ask costs
    one tap. Adding them would let ten saved taps pay for one wrong meal.
    """
    label: str
    settings: Mapping[str, float]
    cases: int = 0
    silent: int = 0
    needless: int = 0
    misses: Tuple[Miss, ...] = ()

    @property
    def clean(self) -> bool:
        return self.silent == 0 and self.needless == 0

    def as_dict(self) -> dict:
        return {"label": self.label, "settings": dict(self.settings),
                "cases": self.cases, "silent": self.silent,
                "needless": self.needless,
                "misses": [{"case": m.case_id, "mode": m.mode,
                            "kind": m.kind} for m in self.misses]}


# ── the gold sweep ────────────────────────────────────────────────────────────
def _gold_expectations(cases=None) -> List[tuple]:
    """[(case, mode, should_ask)] for every case that states an expectation.

    Only stated expectations count. Inferring "probably should not ask" from
    silence would manufacture ground truth, and a sweep scored against
    manufactured labels optimizes toward whatever the inference assumed.
    """
    if cases is None:
        from tests.gold.nutrition_cases import ALL_CASES as cases
    out = []
    for case in cases:
        for mode, expected in (case.get("expect", {}).get("asks") or {}).items():
            out.append((case, mode, bool(expected)))
    return out


def _resolve_case(case):
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import (FoodResolutionRequest,
                                         profile_from_values)
    from skills.nutrition.resolver import resolve
    from skills.nutrition.scaling import Per100g, Per100ml, PerServing, PerUnit

    bases = {"per_100g": Per100g, "per_100ml": Per100ml}

    def _basis(spec):
        kind = spec.get("basis", "per_100g")
        if kind in bases:
            return bases[kind]()
        if kind == "per_serving":
            return PerServing(serving_mass_g=spec.get("serving_mass_g"))
        return PerUnit(unit_mass_g=spec.get("serving_mass_g"))

    candidates = [
        Candidate(source=s["source"], tier=s["tier"], name=s["name"],
                  profile=profile_from_values(s["source"], basis=s["basis"],
                                              confidence=0.8, **s["values"]),
                  basis=_basis(s), brand=s.get("brand"),
                  variant=s.get("variant"), reported_grade=s["grade"])
        for s in case["candidates"]]
    return resolve(FoodResolutionRequest(**case["request"]), candidates)


def sweep(settings_grid: Sequence[Mapping], cases=None) -> List[Point]:
    """Score each candidate setting against every stated gold expectation.

    Resolutions are computed ONCE and reused across settings, which is both
    faster and the point: a threshold change must not change the numbers, only
    the friction, so re-resolving per setting would hide a violation of that
    rule rather than expose it.
    """
    from skills.nutrition import resolver

    expectations = _gold_expectations(cases)
    resolved = {}
    for case, _, _ in expectations:
        if case["id"] not in resolved:
            resolved[case["id"]] = _resolve_case(case)

    originals = {name: getattr(resolver, name)
                 for name in ("ASK_SPANS", "ASK_PROTEIN_SPANS",
                              "MATERIAL_FRACTIONS", "MATERIAL_FRACTION",
                              "FRACTION_FLOOR")
                 if hasattr(resolver, name)}

    points = []
    try:
        for settings in settings_grid:
            for name, value in settings.items():
                if name in originals:
                    setattr(resolver, name, value)
            misses = []
            for case, mode, expected in expectations:
                actual = resolver.should_ask(
                    resolved[case["id"]].ambiguities, mode) is not None
                if actual != expected:
                    misses.append(Miss(case["id"], mode, expected, actual))
            points.append(Point(
                label=settings.get("label", "?"),
                settings={k: v for k, v in settings.items() if k != "label"},
                cases=len(expectations),
                silent=sum(1 for m in misses if m.kind == "silent"),
                needless=sum(1 for m in misses if m.kind == "needless"),
                misses=tuple(misses)))
    finally:
        # Restore whatever was there, always. A sweep that leaks its last
        # setting into the process would silently reconfigure the resolver for
        # every caller after it.
        for name, value in originals.items():
            setattr(resolver, name, value)
    return points


#: Candidate protein thresholds. The lower bound is deliberately aggressive so
#: the sweep can say whether tightening costs anything, rather than the number
#: being chosen to be safe and never tested.
PROTEIN_GRID = (
    {"label": "protein_off",
     "ASK_PROTEIN_SPANS": {"quick": 1e9, "moderate": 1e9, "strict": 1e9}},
    {"label": "protein_30_20_12",
     "ASK_PROTEIN_SPANS": {"quick": 30.0, "moderate": 20.0, "strict": 12.0}},
    {"label": "protein_25_15_8",
     "ASK_PROTEIN_SPANS": {"quick": 25.0, "moderate": 15.0, "strict": 8.0}},
    {"label": "protein_20_12_6",
     "ASK_PROTEIN_SPANS": {"quick": 20.0, "moderate": 12.0, "strict": 6.0}},
    {"label": "protein_15_8_4",
     "ASK_PROTEIN_SPANS": {"quick": 15.0, "moderate": 8.0, "strict": 4.0}},
    {"label": "protein_10_5_2",
     "ASK_PROTEIN_SPANS": {"quick": 10.0, "moderate": 5.0, "strict": 2.0}},
)

#: The fraction rule is per MODE, so the grid sweeps the mapping. Sweeping the
#: back-compat scalar instead made every row identical and the sweep silently
#: uninformative — a grid that perturbs nothing reports the incumbent as
#: optimal for every candidate.
FRACTION_GRID = (
    {"label": "fraction_mod0.5_str0.5",
     "MATERIAL_FRACTIONS": {"quick": 1.01, "moderate": 0.5, "strict": 0.5}},
    {"label": "fraction_mod0.5_str0.3",
     "MATERIAL_FRACTIONS": {"quick": 1.01, "moderate": 0.5, "strict": 0.3}},
    {"label": "fraction_mod0.5_str0.2",
     "MATERIAL_FRACTIONS": {"quick": 1.01, "moderate": 0.5, "strict": 0.2}},
    {"label": "fraction_mod0.4_str0.2",
     "MATERIAL_FRACTIONS": {"quick": 1.01, "moderate": 0.4, "strict": 0.2}},
    {"label": "fraction_mod0.3_str0.15",
     "MATERIAL_FRACTIONS": {"quick": 1.01, "moderate": 0.3, "strict": 0.15}},
)

CALORIE_GRID = (
    {"label": "calorie_300_200_100",
     "ASK_SPANS": {"quick": 300.0, "moderate": 200.0, "strict": 100.0}},
    {"label": "calorie_300_150_80",
     "ASK_SPANS": {"quick": 300.0, "moderate": 150.0, "strict": 80.0}},
    {"label": "calorie_250_120_60",
     "ASK_SPANS": {"quick": 250.0, "moderate": 120.0, "strict": 60.0}},
)


def recommend(points: Sequence[Point]) -> Optional[Point]:
    """The tightest setting that costs nothing.

    "Costs nothing" means no needless interruption on any labelled case. Among
    those, prefer the one catching the most — a threshold that could have been
    tighter for free is leaving real ambiguity unasked.

    None when every candidate would introduce a needless ask, which is itself
    the answer: leave the threshold alone and get more labelled cases.
    """
    clean = [p for p in points if p.needless == 0]
    if not clean:
        return None
    return min(clean, key=lambda p: (p.silent, _tightness(p)))


#: A threshold at or above this is a rule that is switched OFF, not a tight one.
#: Excluding these from the tightness sum made "off" score 0 and win as the
#: tightest setting — the sweep recommended disabling the rule it was there to
#: calibrate.
DISABLED_AT = 1e8


def _tightness(point: Point) -> float:
    """Lower is tighter. Sums the numeric settings so a sweep can prefer the
    more aggressive of two equally-correct rows.

    A disabled threshold counts as maximally loose rather than being skipped:
    skipping it is how `protein_off` came out ahead of every real candidate.
    """
    total = 0.0
    for value in point.settings.values():
        values = (value.values() if isinstance(value, Mapping)
                  else [value] if isinstance(value, (int, float)) else [])
        for v in values:
            total += DISABLED_AT if float(v) >= DISABLED_AT else float(v)
    return total


# ── production shape (frequency, never correctness) ──────────────────────────
def production_shape(records) -> dict:
    """How often each situation occurs, from logs.

    Explicitly NOT an accuracy measurement. An ask rate is not an error rate:
    the logs record what we did, never what we should have done. What they are
    good for is weighting — a threshold that mishandles a situation nobody
    encounters matters less than one that mishandles the common case.
    """
    from skills.nutrition.dashboards import _int, _of

    traces = _of(records, "food_trace")
    items = _of(records, "item_trace")
    corrections = _of(records, "food_correction")

    turns = len(traces)
    asked = sum(1 for t in traces if _int(t.get("asked")) > 0)
    return {
        "turns": turns,
        "ask_rate": (round(asked / turns, 4) if turns else None),
        "by_mode": dict(Counter(t.get("mode") or "-" for t in traces)),
        "ambiguity_fields": dict(Counter(
            f for i in items
            for f in str(i.get("ambiguities") or "").split(",") if f
            and f != "-")),
        "item_decisions": dict(Counter(i.get("decision") or "-"
                                       for i in items)),
        "corrections": len(corrections),
        # The only ground truth production supplies. Everything else here is
        # frequency.
        "corrections_to_assumptions": sum(
            1 for c in corrections
            if str(c.get("assumed", "")).lower() == "true"),
        "note": ("ask_rate is frequency, not error. The logs record what we "
                 "did, never what we should have done."),
    }


def confused_pairs(records, *, min_count: int = 2) -> list:
    """Pairs we keep getting wrong, from user corrections.

    Empty without production data, and that is the honest state rather than a
    gap to paper over: a confused pair is defined by a user having told us we
    were wrong, and no synthetic substitute exists for that. The adversarial
    near-neighbour cases in the gold suite (`BRANDED_CASES_3`) are the standing
    guard in the meantime — they encode the pairs we EXPECT to be confusable
    and fail if the resolver starts confusing them. What they cannot do is
    discover a pair nobody predicted, which is exactly what this returns once
    corrections exist.
    """
    from skills.nutrition.dashboards import confused_pairs as pairs
    return pairs(records, min_count=min_count)


# ── the report ────────────────────────────────────────────────────────────────
def build_report(records=None) -> dict:
    grids = {"protein": PROTEIN_GRID, "fraction": FRACTION_GRID,
             "calories": CALORIE_GRID}
    sweeps, recommendations = {}, {}
    for name, grid in grids.items():
        points = sweep(grid)
        sweeps[name] = [p.as_dict() for p in points]
        best = recommend(points)
        recommendations[name] = best.as_dict() if best else None

    report = {
        "version": CALIBRATION_VERSION,
        "labelled_expectations": len(_gold_expectations()),
        "sweeps": sweeps,
        "recommendations": recommendations,
    }
    if records is not None:
        report["production"] = production_shape(records)
        report["confused_pairs"] = confused_pairs(records)
    else:
        report["production"] = None
        report["note"] = (
            "No production log supplied. The sweep is scored against the gold "
            "suite only, which measures correctness but not frequency — a "
            "threshold clean on 175 labelled cases may still be wrong for the "
            "distribution real users produce.")
    return report


def format_report(report: Mapping) -> str:
    lines = [f"calibration ({report.get('version')})",
             f"  labelled expectations: {report.get('labelled_expectations')}",
             ""]
    for name, points in (report.get("sweeps") or {}).items():
        lines.append(f"  {name}")
        for point in points:
            flag = "  ←" if point["needless"] == 0 and point["silent"] == 0 else ""
            lines.append(f"    {point['label']:<24} "
                         f"silent={point['silent']:<3} "
                         f"needless={point['needless']:<3}{flag}")
        best = (report.get("recommendations") or {}).get(name)
        lines.append(f"    recommend: {best['label'] if best else 'no change'}")
        lines.append("")

    production = report.get("production")
    if production:
        lines.append("  production shape (frequency, not accuracy)")
        lines.append(f"    turns={production['turns']} "
                     f"ask_rate={production['ask_rate']} "
                     f"corrections={production['corrections']} "
                     f"(to assumptions: "
                     f"{production['corrections_to_assumptions']})")
        for name, count in (production.get("ambiguity_fields") or {}).items():
            lines.append(f"      {name:<24} {count}")
        lines.append("")
        for pair in report.get("confused_pairs") or []:
            lines.append(f"    confused: {pair['chosen']} → "
                         f"{pair['corrected']} ×{pair['count']}")
    elif report.get("note"):
        lines.append(f"  ! {report['note']}")
    return "\n".join(lines)


def main(argv=None) -> int:                # pragma: no cover - CLI wrapper
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    paths = [a for a in argv if not a.startswith("--")]

    records = None
    if paths:
        from skills.nutrition.dashboards import parse_log
        lines: List[str] = []
        for path in paths:
            with open(path, "r", errors="replace") as handle:
                lines.extend(handle)
        records = parse_log(lines)

    report = build_report(records)
    print(json.dumps(report, indent=2) if as_json else format_report(report))
    return 0


if __name__ == "__main__":                 # pragma: no cover
    raise SystemExit(main())


# ── release certification ─────────────────────────────────────────────────────
#: What each gate needs before it can be answered at all. Stated so a
#: certification can distinguish "failing" from "not yet measurable", which are
#: different facts with different next actions and were previously both just
#: "not clear".
EVIDENCE = {
    "gold": "labelled cases in tests/gold — available now",
    "logs": "shadow or live log volume — available once deployed",
    "native": "native writes — available only after the resolver owns commits",
    "corrections": "user corrections — available only from production",
}

#: Gate → what kind of evidence answers it.
GATE_EVIDENCE = {
    "branded_top1_accuracy": "gold",
    "branded_top3_recall": "gold",
    "material_ambiguity_recall": "gold",
    "coordinator_route_agreement": "logs",
    "resolution_unresolved_rate": "logs",
    "resolver_crash_rate": "logs",
    "wrong_item_binding": "corrections",
    "duplicate_commit": "native",
    "stale_clarification_mutation": "native",
    "snapshot_card_mismatch": "native",
    "package_vs_consumed_confusion": "native",
    "clarification_rate_quick": "logs",
    "clarification_rate_moderate": "logs",
    "strict_unresolved_after_3_rounds": "logs",
}


def certify(records=None) -> dict:
    """The release statement: what is answered, what is not, and why.

    The distinction this exists to make is between a gate that FAILED and a gate
    that cannot yet be measured. The readiness report reports both as "not
    clear", which is correct and unhelpful — one means fix something, the other
    means deploy something, and a release decision needs to know which.

    Deliberately does not produce a single pass/fail. A certification that
    collapses "three gates await production data" into "not ready" throws away
    the only information the reader needs.
    """
    from skills.nutrition.readiness import GATES, build_report

    report = build_report(list(records or []))
    metrics = report.get("metrics") or {}

    rows = {}
    for name in GATES:
        metric = metrics.get(name) or {}
        verdict = metric.get("verdict") or "unmeasured"
        needs = GATE_EVIDENCE.get(name, "logs")
        rows[name] = {
            "verdict": verdict,
            "stage": metric.get("stage"),
            "evidence": needs,
            "blocked_on_data": (verdict in ("unmeasured", "insufficient")
                                and needs != "gold"),
            "sample": metric.get("sample"),
        }

    answered = [n for n, r in rows.items() if r["verdict"] == "pass"]
    failing = [n for n, r in rows.items() if r["verdict"] == "fail"]
    awaiting = [n for n, r in rows.items() if r["blocked_on_data"]]
    # A gold-backed gate that is unmeasured is a REAL gap: the data exists, so
    # nothing is stopping it from being answered except missing cases.
    gaps = [n for n, r in rows.items()
            if r["verdict"] in ("unmeasured", "insufficient")
            and r["evidence"] == "gold"]

    return {
        "version": CALIBRATION_VERSION,
        "gates": rows,
        "answered": sorted(answered),
        "failing": sorted(failing),
        "awaiting_production_data": sorted(awaiting),
        "measurable_but_unanswered": sorted(gaps),
        "next_action": _certification_action(failing, gaps, awaiting),
        "evidence_key": EVIDENCE,
    }


def _certification_action(failing, gaps, awaiting) -> str:
    if failing:
        return (f"fix first: {', '.join(sorted(failing)[:3])}"
                f"{' …' if len(failing) > 3 else ''}")
    if gaps:
        return (f"add labelled cases for: {', '.join(sorted(gaps)[:3])}"
                f"{' …' if len(gaps) > 3 else ''}")
    if awaiting:
        return (f"deploy to gather: {', '.join(sorted(awaiting)[:3])}"
                f"{' …' if len(awaiting) > 3 else ''} — nothing measurable is "
                f"failing")
    return "all gates answered and passing"


def format_certification(cert: Mapping) -> str:
    lines = [f"release certification ({cert.get('version')})", ""]
    for name, row in (cert.get("gates") or {}).items():
        mark = {"pass": "ok  ", "fail": "FAIL"}.get(row["verdict"], "----")
        suffix = ("" if not row["blocked_on_data"]
                  else f"  (needs {row['evidence']})")
        lines.append(f"  {mark} {name:<34} {row['verdict']:<13}"
                     f"{row['stage'] or '-':<14}{suffix}")
    lines.append("")
    lines.append(f"  answered/passing        {len(cert.get('answered') or [])}")
    lines.append(f"  failing                 {len(cert.get('failing') or [])}")
    lines.append(f"  awaiting production     "
                 f"{len(cert.get('awaiting_production_data') or [])}")
    lines.append(f"  measurable, unanswered  "
                 f"{len(cert.get('measurable_but_unanswered') or [])}")
    lines.append("")
    lines.append(f"  next: {cert.get('next_action')}")
    return "\n".join(lines)
