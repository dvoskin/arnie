"""Live readiness gates (directive 29).

The shadows are running and emitting structured lines. This reads them back and
answers the only question that matters before promotion: is the new path
actually better, and by how much?

The gates are split by what can honestly be measured from what:

  FROM LOGS       agreement rates, source distribution, unresolved rate,
                  large-move frequency, rejection frequency. These need no
                  ground truth — they compare two systems to each other.

  FROM THE GOLD   top-1 and top-3 identity accuracy, ambiguity recall. These
  SUITE           need labels, and the gold set is where labels live.

  FROM CORRECTIONS wrong-item binding, confused pairs. These need a user to
                  have told us we were wrong, which only production produces.

Keeping that split explicit matters. A readiness report that computes an
"accuracy" from unlabelled logs is measuring agreement and calling it
correctness — and agreement with a system you are trying to replace is not
evidence that the replacement is right.

Run it over a log dump:

    python -m skills.nutrition.readiness arnie.log
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

READINESS_VERSION = "readiness_v1"

#: The thresholds from the directive. Stated as data so a gate can be retuned
#: from production without touching the code that computes it.
GATES = {
    # Must be exactly zero — each is a correctness violation, not a rate to
    # optimize.
    "wrong_item_binding": {"max": 0, "absolute": True},
    "duplicate_commit": {"max": 0, "absolute": True},
    "stale_clarification_mutation": {"max": 0, "absolute": True},
    "snapshot_card_mismatch": {"max": 0, "absolute": True},
    "package_vs_consumed_confusion": {"max": 0, "absolute": True},
    # Quality targets.
    "branded_top1_accuracy": {"min": 0.97},
    "branded_top3_recall": {"min": 0.99},
    "material_ambiguity_recall": {"min": 0.95},
    "unnecessary_clarification_quick": {"max": 0.08},
    "unnecessary_clarification_moderate": {"max": 0.18},
    "strict_unresolved_after_3_rounds": {"max": 0.05},
}

#: Log events this reads. Anything else is ignored, so a mixed application log
#: can be piped in whole.
_EVENTS = ("turn_observe", "nutrition_shadow", "nutrition_promotion",
           "nutrition_promotion_large_move", "item_trace", "food_correction")

_EVENT_RE = re.compile(r"event=([a-z_]+)")
_KV_RE = re.compile(r"([a-z_]+)=('[^']*'|\"[^\"]*\"|[^\s]+)")


def parse_line(line: str) -> Optional[dict]:
    """One structured log line → a dict, or None if it is not one of ours."""
    m = _EVENT_RE.search(line or "")
    if m is None or m.group(1) not in _EVENTS:
        return None
    out = {}
    for key, raw in _KV_RE.findall(line):
        value = raw.strip()
        if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
            value = value[1:-1]
        out[key] = value
    return out


def parse_log(lines: Iterable[str]) -> list:
    return [rec for rec in (parse_line(l) for l in lines) if rec]


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Metric:
    """One measured number, with what it was measured from.

    `sample` is not decoration: a 100% agreement rate over four turns is not
    the same claim as one over four thousand, and a report that hides the
    denominator invites reading it as though it were.
    """
    name: str
    value: Optional[float] = None
    sample: int = 0
    detail: Mapping = field(default_factory=dict)
    source: str = "logs"

    @property
    def measured(self) -> bool:
        return self.value is not None and self.sample > 0

    def verdict(self, min_sample: int = 30) -> str:
        """pass | fail | insufficient — the third is a real answer, and the one
        most likely to be true early in a rollout."""
        gate = GATES.get(self.name)
        if gate is None or not self.measured:
            return "unmeasured"
        if self.sample < min_sample and not gate.get("absolute"):
            return "insufficient"
        if "max" in gate and self.value > gate["max"]:
            return "fail"
        if "min" in gate and self.value < gate["min"]:
            return "fail"
        return "pass"

    def describe(self) -> str:
        if not self.measured:
            return f"{self.name}: not measured"
        shown = (f"{self.value:.3f}" if abs(self.value) < 1000
                 else f"{self.value:.0f}")
        return f"{self.name}: {shown} (n={self.sample}, {self.source})"


# ── metrics computable from the shadow logs ───────────────────────────────────
def coordinator_agreement(records) -> Metric:
    """Route agreement between the coordinator and run_turn()."""
    rows = [r for r in records if r.get("event") == "turn_observe"
            and r.get("actual_lane") not in (None, "", "-")]
    if not rows:
        return Metric("coordinator_route_agreement")
    agree = sum(1 for r in rows if r.get("agree") == "yes")
    return Metric("coordinator_route_agreement", agree / len(rows), len(rows),
                  detail=dict(Counter(
                      f"{r.get('actual_lane')}→{r.get('predicted_lane')}"
                      for r in rows if r.get("agree") != "yes")))


def nutrition_agreement(records) -> Metric:
    """How often the resolver and the legacy cascade land on the same number."""
    rows = [r for r in records if r.get("event") == "nutrition_shadow"]
    if not rows:
        return Metric("nutrition_agreement")
    agree = sum(1 for r in rows if r.get("agree") == "yes")
    return Metric("nutrition_agreement", agree / len(rows), len(rows))


def agreement_by_source(records) -> Metric:
    """Disagreement broken down by which source the resolver picked.

    This is the diagnostic that says WHERE the two systems differ. A high
    branded disagreement rate is the resolver doing its job — that is the
    failure class it was built for. A high generic disagreement rate is a
    reason to look harder before promoting.
    """
    rows = [r for r in records if r.get("event") == "nutrition_shadow"]
    totals, disagreed = Counter(), Counter()
    for r in rows:
        source = r.get("new_source", "-")
        totals[source] += 1
        if r.get("agree") == "NO":
            disagreed[source] += 1
    detail = {s: {"n": n, "disagreed": disagreed[s],
                  "rate": round(disagreed[s] / n, 3)}
              for s, n in totals.items() if n}
    return Metric("nutrition_disagreement_by_source",
                  value=(sum(disagreed.values()) / sum(totals.values())
                         if totals else None),
                  sample=sum(totals.values()), detail=detail)


def macro_delta(records) -> Metric:
    """Median absolute calorie difference on disagreeing turns. The size of the
    correction, not just its frequency."""
    deltas = []
    for r in records:
        if r.get("event") != "nutrition_shadow" or r.get("agree") != "NO":
            continue
        legacy, new = _num(r.get("legacy_cal")), _num(r.get("new_cal"))
        if legacy is not None and new is not None:
            deltas.append(abs(new - legacy))
    if not deltas:
        return Metric("median_calorie_delta")
    deltas.sort()
    median = deltas[len(deltas) // 2]
    return Metric("median_calorie_delta", median, len(deltas),
                  detail={"p90": deltas[int(len(deltas) * 0.9)],
                          "max": deltas[-1]})


def unresolved_rate(records) -> Metric:
    """How often the resolver declines to answer at all. A rising number here
    means promotion would hand more turns back to the cascade, not fewer."""
    rows = [r for r in records if r.get("event") == "nutrition_shadow"]
    if not rows:
        return Metric("resolution_unresolved_rate")
    unresolved = sum(1 for r in rows if r.get("new_source") == "unresolved")
    return Metric("resolution_unresolved_rate", unresolved / len(rows),
                  len(rows))


def micronutrient_rejection_rate(records) -> Metric:
    """How often a nutrient was dropped to unknown for being impossible. This
    is a SAFETY metric, and a high number is good news about the validators
    rather than bad news about the data."""
    rows = [r for r in records if r.get("event") == "nutrition_shadow"]
    if not rows:
        return Metric("micronutrient_rejection_rate")
    rejected = sum(1 for r in rows if _num(r.get("rejected"), 0) > 0)
    return Metric("micronutrient_rejection_rate", rejected / len(rows),
                  len(rows))


def large_move_rate(records) -> Metric:
    """Promotions that moved calories by more than the loud threshold."""
    promoted = [r for r in records if r.get("event") == "nutrition_promotion"
                and r.get("outcome") == "promoted"]
    loud = [r for r in records
            if r.get("event") == "nutrition_promotion_large_move"]
    if not promoted:
        return Metric("large_move_rate")
    return Metric("large_move_rate", len(loud) / len(promoted), len(promoted),
                  detail={"largest": max((_num(r.get("x"), 0) for r in loud),
                                         default=0)})


def clarification_rate(records, mode: str) -> Metric:
    """Share of items in `mode` that produced a question.

    Named "unnecessary" in the gates, and the name is aspirational: from logs
    alone this is the clarification rate, and only a correction or an
    abandonment tells you a given question was unnecessary. Reported under the
    gate name because it is the best available proxy, and flagged as a proxy.
    """
    rows = [r for r in records if r.get("event") == "item_trace"
            and r.get("mode") == mode]
    if not rows:
        return Metric(f"unnecessary_clarification_{mode}")
    asked = sum(1 for r in rows if r.get("decision") == "ask")
    return Metric(f"unnecessary_clarification_{mode}", asked / len(rows),
                  len(rows), detail={"proxy": "clarification rate, not "
                                              "necessarily unnecessary"})


def wrong_item_binding(records) -> Metric:
    """Corrections whose field indicates an answer landed on the wrong entity.

    Zero-tolerance: this is the failure the whole staged-item model exists to
    prevent, so a single occurrence is a defect rather than a rate.
    """
    rows = [r for r in records if r.get("event") == "food_correction"]
    if not rows:
        return Metric("wrong_item_binding", 0.0, 0)
    wrong = sum(1 for r in rows
                if r.get("field") in ("staged_item", "entry_id", "wrong_item"))
    return Metric("wrong_item_binding", float(wrong), len(rows))


# ── metrics that need the gold suite ──────────────────────────────────────────
def gold_identity_accuracy(cases=None) -> tuple:
    """Top-1 and top-3 identity accuracy over the gold set.

    Labelled data, so this is genuinely accuracy rather than agreement. Runs the
    real resolver over the fixed cases and checks the selected identity against
    the expectation.
    """
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import (FoodResolutionRequest,
                                         profile_from_values)
    from skills.nutrition.resolver import resolve, score
    from skills.nutrition.scaling import Per100g, Per100ml, PerServing, PerUnit

    if cases is None:
        from tests.gold.nutrition_cases import ALL_CASES as cases

    bases = {"per_100g": Per100g, "per_100ml": Per100ml}

    def _basis(spec):
        kind = spec.get("basis", "per_100g")
        if kind in bases:
            return bases[kind]()
        if kind == "per_serving":
            return PerServing(serving_mass_g=spec.get("serving_mass_g"))
        return PerUnit(unit_mass_g=spec.get("serving_mass_g"))

    branded = [c for c in cases
               if c["category"] == "branded" and "identity" in c["expect"]]
    top1 = top3 = 0
    for case in branded:
        request = FoodResolutionRequest(**case["request"])
        candidates = [
            Candidate(source=s["source"], tier=s["tier"], name=s["name"],
                      profile=profile_from_values(s["source"],
                                                  basis=s["basis"],
                                                  confidence=0.8,
                                                  **s["values"]),
                      basis=_basis(s), brand=s.get("brand"),
                      variant=s.get("variant"), reported_grade=s["grade"])
            for s in case["candidates"]]
        expected = case["expect"]["identity"]
        out = resolve(request, candidates)
        if out.canonical_name == expected:
            top1 += 1
        ranked = sorted(candidates, key=lambda c: score(request, c))[:3]
        if any(c.name == expected for c in ranked):
            top3 += 1

    n = len(branded)
    return (Metric("branded_top1_accuracy", (top1 / n if n else None), n,
                   source="gold"),
            Metric("branded_top3_recall", (top3 / n if n else None), n,
                   source="gold"))


def gold_ambiguity_recall(cases=None) -> Metric:
    """Of the gold cases that SHOULD ask in strict mode, how many do."""
    from skills.nutrition.resolver import should_ask
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import (FoodResolutionRequest,
                                         profile_from_values)
    from skills.nutrition.resolver import resolve
    from skills.nutrition.scaling import Per100g, Per100ml, PerServing, PerUnit

    if cases is None:
        from tests.gold.nutrition_cases import ALL_CASES as cases

    bases = {"per_100g": Per100g, "per_100ml": Per100ml}
    expected_asks = [c for c in cases
                     if (c["expect"].get("asks") or {}).get("strict") is True]
    if not expected_asks:
        return Metric("material_ambiguity_recall", source="gold")

    hit = 0
    for case in expected_asks:
        request = FoodResolutionRequest(**{**case["request"], "mode": "strict"})
        candidates = []
        for s in case["candidates"]:
            kind = s.get("basis", "per_100g")
            basis = (bases[kind]() if kind in bases
                     else PerServing(serving_mass_g=s.get("serving_mass_g"))
                     if kind == "per_serving"
                     else PerUnit(unit_mass_g=s.get("serving_mass_g")))
            candidates.append(Candidate(
                source=s["source"], tier=s["tier"], name=s["name"],
                profile=profile_from_values(s["source"], basis=s["basis"],
                                            confidence=0.8, **s["values"]),
                basis=basis, brand=s.get("brand"), variant=s.get("variant"),
                reported_grade=s["grade"]))
        out = resolve(request, candidates)
        if should_ask(out.ambiguities, "strict") is not None:
            hit += 1
    return Metric("material_ambiguity_recall", hit / len(expected_asks),
                  len(expected_asks), source="gold")


# ── the report ────────────────────────────────────────────────────────────────
def build_report(records, *, include_gold: bool = True) -> dict:
    metrics = [
        coordinator_agreement(records),
        nutrition_agreement(records),
        agreement_by_source(records),
        macro_delta(records),
        unresolved_rate(records),
        micronutrient_rejection_rate(records),
        large_move_rate(records),
        clarification_rate(records, "quick"),
        clarification_rate(records, "moderate"),
        wrong_item_binding(records),
    ]
    if include_gold:
        try:
            top1, top3 = gold_identity_accuracy()
            metrics.extend([top1, top3, gold_ambiguity_recall()])
        except Exception as e:                       # pragma: no cover
            metrics.append(Metric("gold_suite_error", detail={"error": str(e)}))

    gated = [m for m in metrics if m.name in GATES]
    verdicts = Counter(m.verdict() for m in gated)
    return {
        "version": READINESS_VERSION,
        "records": len(records),
        "metrics": {m.name: {"value": m.value, "sample": m.sample,
                             "source": m.source, "detail": dict(m.detail),
                             "verdict": m.verdict() if m.name in GATES else None}
                    for m in metrics},
        "gates": {"pass": verdicts["pass"], "fail": verdicts["fail"],
                  "insufficient": verdicts["insufficient"],
                  "unmeasured": verdicts["unmeasured"]},
        "ready": verdicts["fail"] == 0 and verdicts["insufficient"] == 0
        and verdicts["unmeasured"] == 0,
    }


def format_report(report: Mapping) -> str:
    lines = [f"nutrition readiness — {report['records']} log records",
             ""]
    for name, m in report["metrics"].items():
        verdict = m.get("verdict")
        mark = {"pass": "PASS", "fail": "FAIL", "insufficient": "LOW-N",
                "unmeasured": "  — "}.get(verdict, "    ")
        value = ("     —" if m["value"] is None else f"{m['value']:>10.3f}")
        lines.append(f"  [{mark}] {name:<38} {value}  n={m['sample']:<6} "
                     f"{m['source']}")
        for key, detail in (m["detail"] or {}).items():
            lines.append(f"           {key}: {detail}")
    g = report["gates"]
    lines += ["",
              f"gates: {g['pass']} pass, {g['fail']} fail, "
              f"{g['insufficient']} insufficient sample, "
              f"{g['unmeasured']} unmeasured",
              f"ready to promote: {'YES' if report['ready'] else 'NO'}"]
    if not report["ready"]:
        lines.append("  (an unmeasured or low-sample gate is not a pass — it "
                     "is a gate you cannot yet answer)")
    return "\n".join(lines)


def main(argv=None) -> int:      # pragma: no cover - CLI wrapper
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__.strip().splitlines()[-1])
        return 2
    records = []
    for path in argv:
        with open(path, "r", errors="replace") as fh:
            records.extend(parse_log(fh))
    report = build_report(records)
    print(format_report(report))
    print()
    print(json.dumps(report["gates"]))
    return 0 if report["ready"] else 1


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
