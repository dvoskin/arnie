"""Food dashboards: funnels, latency and correction learning (PR #29).

`readiness.py` answers one question — is the new path safe to promote — and
answers it with gates and thresholds. This answers the other three, the ones
that come up every week rather than once per rollout:

    Where do turns stop?          the turn funnel
    Where do clarifications die?  the clarification funnel
    What do corrections teach?    the correction funnel
    What is slow?                 latency, by stage

They are funnels rather than counters on purpose. "18% of turns ask a
question" is a number with no action attached. "18% ask, 71% of those get an
answer, 62% of THOSE parse, and the rest fall back to the interpreter" names
the step to fix — and the step to fix is never the one the summary counter
points at.

Everything reads the `event=food_trace` spine plus the existing per-stage
events, through `readiness.parse_line`, so a mixed application log can be piped
in whole and there is exactly one parser to keep correct.

    python -m skills.nutrition.dashboards arnie.log
    python -m skills.nutrition.dashboards arnie.log --json

A note on what this deliberately does NOT do: it computes no thresholds and
returns no verdicts. Readiness owns those. A dashboard that also decides is a
dashboard whose numbers get argued with instead of read.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Sequence

DASHBOARD_VERSION = "food_dashboards_v1"

#: Events these read. A superset of readiness's, because the funnels need the
#: turn spine and the correction trace it does not use.
EVENTS = ("food_trace", "food_correction", "item_trace",
          "nutrition_promotion", "structured_food")


# ── shared shapes ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Step:
    """One rung of a funnel."""
    name: str
    count: int
    of_previous: Optional[float] = None
    of_first: Optional[float] = None
    note: str = ""


@dataclass(frozen=True)
class Funnel:
    """An ordered set of steps, each a subset of the one before it.

    The invariant — every step is a subset of its predecessor — is what makes
    the ratios meaningful, and it is checked rather than assumed: a funnel that
    grows partway down is a counting bug, and reporting 140% conversion as if
    it were a fact is worse than reporting nothing.
    """
    name: str
    steps: Sequence[Step] = ()
    note: str = ""

    @property
    def is_monotonic(self) -> bool:
        counts = [s.count for s in self.steps]
        return all(a >= b for a, b in zip(counts, counts[1:]))

    @property
    def biggest_drop(self) -> Optional[str]:
        """Where the most is lost, which is where to look first."""
        worst, worst_name = None, None
        for previous, current in zip(self.steps, self.steps[1:]):
            lost = previous.count - current.count
            if lost > 0 and (worst is None or lost > worst):
                worst, worst_name = lost, f"{previous.name}→{current.name}"
        return worst_name

    def as_dict(self) -> dict:
        return {"name": self.name, "note": self.note,
                "monotonic": self.is_monotonic,
                "biggest_drop": self.biggest_drop,
                "steps": [{"name": s.name, "count": s.count,
                           "of_previous": s.of_previous,
                           "of_first": s.of_first, "note": s.note}
                          for s in self.steps]}

    def render(self) -> str:
        lines = [f"  {self.name}"]
        if not self.is_monotonic:
            lines.append("    ! not monotonic — a step grew; counting is wrong")
        for step in self.steps:
            share = ("     -" if step.of_first is None
                     else f"{step.of_first * 100:5.1f}%")
            lines.append(f"    {step.name:<26} {step.count:>7}  {share}"
                         f"{'  ' + step.note if step.note else ''}")
        if self.biggest_drop:
            lines.append(f"    biggest drop: {self.biggest_drop}")
        return "\n".join(lines)


def _funnel(name: str, pairs: Sequence[tuple], note: str = "") -> Funnel:
    steps, first = [], None
    previous = None
    for label, count in pairs:
        note_text = ""
        if isinstance(count, tuple):
            count, note_text = count
        first = count if first is None else first
        steps.append(Step(
            name=label, count=count,
            of_previous=(None if previous in (None, 0)
                         else round(count / previous, 4)),
            of_first=(None if not first else round(count / first, 4)),
            note=note_text))
        previous = count
    return Funnel(name=name, steps=tuple(steps), note=note)


# ── percentiles ───────────────────────────────────────────────────────────────
def percentile(values: Sequence[float], p: float) -> Optional[float]:
    """The p-th percentile by nearest-rank.

    Nearest-rank rather than interpolation because a latency percentile should
    be a value that actually occurred. An interpolated p99 of 812 ms when no
    request took 812 ms is a number you cannot go and find in the logs.
    """
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    if p <= 0:
        return round(ordered[0], 1)
    rank = max(1, min(len(ordered), int(-(-len(ordered) * p // 1))))
    return round(ordered[rank - 1], 1)


@dataclass(frozen=True)
class Latency:
    """One timed thing, summarized the way an operator reads it."""
    name: str
    samples: int = 0
    p50: Optional[float] = None
    p90: Optional[float] = None
    p99: Optional[float] = None
    max_ms: Optional[float] = None

    def as_dict(self) -> dict:
        return {"name": self.name, "samples": self.samples, "p50": self.p50,
                "p90": self.p90, "p99": self.p99, "max_ms": self.max_ms}


def latency_for(name: str, values: Sequence[float]) -> Latency:
    values = [v for v in values if v is not None]
    return Latency(name=name, samples=len(values),
                   p50=percentile(values, 0.50), p90=percentile(values, 0.90),
                   p99=percentile(values, 0.99),
                   max_ms=(round(max(values), 1) if values else None))


# ── parsing ───────────────────────────────────────────────────────────────────
def parse_log(lines: Iterable[str]) -> list:
    """Structured records, via readiness's parser so there is only one."""
    from skills.nutrition.readiness import parse_line
    out = []
    for line in lines:
        record = parse_line(line)
        if record is not None:
            out.append(record)
    return out


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bool(value) -> Optional[bool]:
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _of(records, event: str) -> list:
    return [r for r in records if r.get("event") == event]


def _timings(record: Mapping) -> dict:
    """`timings=interpret:3,resolve:120,resolve:80` → {stage: total ms}.

    Repeated stages are SUMMED, not overwritten. A turn resolves once per item,
    so a three-food meal writes three `resolve:` pairs, and assigning them into a
    dict kept only the last — which reported the cheapest item's latency as the
    turn's and made multi-food resolution look as fast as single-food. The user
    waits for all of them, so the total is the honest per-turn figure.

    Parsed defensively: the field is written by a formatter and read by a
    dashboard, and a malformed pair should cost that pair rather than the run.
    """
    raw = str(record.get("timings") or "")
    out = {}
    for pair in raw.replace(",", " ").split():
        stage, _, ms = pair.partition(":")
        value = _num(ms)
        if stage and value is not None:
            out[stage] = out.get(stage, 0.0) + value
    return out


def _timing_occurrences(record: Mapping) -> dict:
    """`{stage: how many times it ran}` for one turn. Keeps the per-item count
    visible next to the summed duration, so a slow turn and a busy one are
    distinguishable rather than both showing as "resolve was slow"."""
    raw = str(record.get("timings") or "")
    out = {}
    for pair in raw.replace(",", " ").split():
        stage, _, ms = pair.partition(":")
        if stage and _num(ms) is not None:
            out[stage] = out.get(stage, 0) + 1
    return out


# ── the funnels ───────────────────────────────────────────────────────────────
# Each funnel counts ONE kind of thing. Mixing turns and items in a single
# funnel makes "items staged" exceed "food turns" the moment anyone logs two
# foods at once, which breaks the subset invariant the ratios depend on. The
# monotonic check caught exactly that in the first version of this file.
def turn_funnel(records) -> Funnel:
    """Turns → staged something → committed something → committed cleanly.

    Counted in TURNS, and every rung a genuine subset of the one above it. An
    earlier version had "reached resolve" as the second rung, which is not a
    superset of "committed something": with the resolver off, no turn records a
    resolve stage and turns still commit, so the funnel went non-monotonic in
    exactly the configuration production runs in today. Resolver coverage is a
    distribution, not a rung — it is visible in the latency sample counts.

    The last step is the one that matters: a turn that committed something
    while holding the rest is not a finished turn from the user's side, it is a
    turn they have to come back to.
    """
    traces = _of(records, "food_trace")
    staged_any = [t for t in traces if _int(t.get("staged")) > 0]
    committed_any = [t for t in staged_any if _int(t.get("committed")) > 0]
    committed_all = [t for t in committed_any
                     if _int(t.get("held")) == 0 and _int(t.get("asked")) == 0]

    return _funnel("turn funnel", [
        ("food turns", len(traces)),
        ("staged an item", len(staged_any)),
        ("committed something", len(committed_any)),
        ("committed cleanly", (len(committed_all),
                               "nothing held, nothing asked")),
    ], note="counted in turns")


def item_funnel(records) -> Funnel:
    """Items staged → not held → approved to write → written.

    Counted in ITEMS, and separate from the turn funnel for that reason. A turn
    is finished or not; an item is committed or not; one number cannot be both.

    "Approved to write" and "written" are two steps because they are two facts,
    and collapsing them hid the whole failure class where the clarifier approves
    an item and the write is refused. The drop between these two steps IS the
    failed-write rate.
    """
    traces = _of(records, "food_trace")
    staged = sum(_int(t.get("staged")) for t in traces)
    held = sum(_int(t.get("held")) for t in traces)
    ready = sum(_int(t.get("ready")) for t in traces)
    committed = sum(_int(t.get("committed")) for t in traces)

    return _funnel("item funnel", [
        ("items staged", staged),
        ("not held", max(0, staged - held)),
        ("approved to write", ready),
        ("written", committed),
    ], note="counted in items across all turns")


def clarification_funnel(records) -> Funnel:
    """Meals with a question → later committed → committed cleanly.

    Counted in MEAL GROUPS, because that is the unit a clarification spans. The
    question is asked on one turn and answered on another, so a turn-keyed
    funnel would score every clarification as abandoned — the meal group id
    exists precisely to survive that boundary.
    """
    traces = _of(records, "food_trace")
    with_meal = [t for t in traces if t.get("meal") and t.get("meal") != "-"]

    asked = {t["meal"] for t in with_meal if _int(t.get("asked")) > 0}
    committed = {t["meal"] for t in with_meal if _int(t.get("committed")) > 0}
    clean = {t["meal"] for t in with_meal
             if _int(t.get("committed")) > 0 and _int(t.get("held")) == 0}

    return _funnel("clarification funnel", [
        ("meals with a question", len(asked)),
        ("...later committed", (len(asked & committed),
                                "joined on meal, not turn")),
        ("...nothing left held", len(asked & clean)),
    ], note="an unanswered question is the most expensive outcome in the "
            "system: the user was interrupted and still has nothing logged")


def correction_funnel(records) -> Funnel:
    """Corrections received → to an assumption → typed → recurring.

    Counted in CORRECTIONS only. An earlier version put "assumptions made" at
    the top of this funnel, which read well and was wrong: assumptions come
    from the turn spine and corrections from a different event over a
    different window, so the top step was not a superset of the one below it
    and the funnel went non-monotonic the moment a correction arrived for a
    turn outside the log. Assumption volume is context, not a rung — it is
    reported alongside as `assumptions_made`.

    The rungs narrow toward what is actionable. A correction to an ASSUMPTION
    is teachable; one to a value the user stated is a parse failure. A
    correction with a typed ambiguity can be attributed to a specific
    ambiguity class. A pair seen more than once is a systematic confusion
    rather than an unusual pantry.
    """
    corrections = _of(records, "food_correction")
    on_assumption = [c for c in corrections if _bool(c.get("assumed")) is True]
    typed = [c for c in on_assumption
             if c.get("type") not in (None, "", "-")]
    recurring = sum(p["count"] for p in confused_pairs(records))

    return _funnel("correction funnel", [
        ("corrections received", len(corrections)),
        ("...to an assumption", (len(on_assumption),
                                 "teachable; the rest are parse failures")),
        ("...with a typed ambiguity", len(typed)),
        ("...in a recurring pair", (min(recurring, len(typed)),
                                    "systematic, not a one-off")),
    ], note="counted in corrections; assumption volume is reported separately "
            "because it comes from a different event over a different window")


# ── distributions ─────────────────────────────────────────────────────────────
def stop_distribution(records) -> dict:
    """Where turns ended. The single most useful chart in the set."""
    traces = _of(records, "food_trace")
    counts = Counter(t.get("stopped_at") or "-" for t in traces)
    total = sum(counts.values())
    return {stage: {"count": n,
                    "share": (round(n / total, 4) if total else None)}
            for stage, n in counts.most_common()}


def cohort_split(records) -> dict:
    """Turns by rollout cohort — the denominator for every canary comparison."""
    traces = _of(records, "food_trace")
    by_cohort = defaultdict(lambda: {"turns": 0, "committed": 0, "asked": 0,
                                     "errors": 0})
    for trace in traces:
        row = by_cohort[trace.get("cohort") or "-"]
        row["turns"] += 1
        row["committed"] += _int(trace.get("committed"))
        row["asked"] += _int(trace.get("asked"))
        if (trace.get("error") or "-") != "-":
            row["errors"] += 1
    return dict(by_cohort)


def source_distribution(records) -> dict:
    """Which authority won, which is how a source outage looks in aggregate."""
    traces = _of(records, "food_trace")
    counts = Counter(t.get("source") or "-" for t in traces)
    total = sum(counts.values())
    return {source: {"count": n,
                     "share": (round(n / total, 4) if total else None)}
            for source, n in counts.most_common()}


def error_distribution(records) -> dict:
    traces = _of(records, "food_trace")
    counts = Counter(t.get("error") for t in traces
                     if (t.get("error") or "-") != "-")
    return dict(counts.most_common())


def confused_pairs(records, *, min_count: int = 2) -> list:
    """(chosen → corrected) pairs seen more than once.

    A pair that recurs is a systematic confusion — a resolver ranking problem
    or a missing product family rule — while a one-off is a user with an
    unusual pantry. Only the recurring ones are worth a code change, which is
    why the floor is here rather than in the reader's head.
    """
    pairs = Counter()
    for record in _of(records, "food_correction"):
        chosen = str(record.get("chose") or "").strip("'\"")
        corrected = str(record.get("meant") or "").strip("'\"")
        if chosen and corrected and chosen != corrected:
            pairs[(chosen, corrected)] += 1
    return [{"chosen": a, "corrected": b, "count": n}
            for (a, b), n in pairs.most_common() if n >= min_count]


# ── latency ───────────────────────────────────────────────────────────────────
def latency_report(records) -> dict:
    """Total and per-stage timings.

    Per-stage matters more than total here: a food turn is slow for exactly one
    reason at a time, and a total tells you it was slow without telling you
    which of seven stages to look at.
    """
    traces = _of(records, "food_trace")
    totals = [_num(t.get("total_ms")) for t in traces]
    by_stage = defaultdict(list)
    runs_per_turn = defaultdict(list)
    for trace in traces:
        # One sample per TURN per stage, holding that turn's total time in the
        # stage. Appending each occurrence separately would weight a three-food
        # turn three times in the percentiles and quietly turn a turn-latency
        # report into an item-latency one.
        for stage, ms in _timings(trace).items():
            by_stage[stage].append(ms)
        for stage, runs in _timing_occurrences(trace).items():
            runs_per_turn[stage].append(runs)

    from core.food_trace import STAGE_ORDER
    ordered = [s for s in STAGE_ORDER if s in by_stage]
    ordered += sorted(s for s in by_stage if s not in STAGE_ORDER)

    def _stage_row(stage: str) -> dict:
        row = latency_for(stage, by_stage[stage]).as_dict()
        runs = [r for r in runs_per_turn.get(stage, []) if r]
        if runs:
            row["runs_per_turn_max"] = max(runs)
            row["runs_per_turn_avg"] = round(sum(runs) / len(runs), 2)
        return row

    return {
        "turn_total": latency_for("turn_total", totals).as_dict(),
        "stages": [_stage_row(s) for s in ordered],
    }


# ── the report ────────────────────────────────────────────────────────────────
def build_dashboards(records) -> dict:
    funnels = [turn_funnel(records), item_funnel(records),
               clarification_funnel(records), correction_funnel(records)]
    return {
        "version": DASHBOARD_VERSION,
        "records": len(records),
        "traces": len(_of(records, "food_trace")),
        "funnels": [f.as_dict() for f in funnels],
        "stopped_at": stop_distribution(records),
        "cohorts": cohort_split(records),
        "sources": source_distribution(records),
        "errors": error_distribution(records),
        "confused_pairs": confused_pairs(records),
        # Resolver coverage: how many turns actually reached the resolver.
        # Reported here rather than as a funnel rung — see turn_funnel.
        "turns_reaching_resolve": sum(
            1 for t in _of(records, "food_trace") if "resolve" in _timings(t)),
        # Context for the correction funnel rather than a rung of it: see the
        # docstring there for why it cannot be one.
        "assumptions_made": sum(_int(t.get("assumed"))
                                for t in _of(records, "food_trace")),
        "latency": latency_report(records),
        # Surfaced rather than left for the reader to notice: a funnel that
        # grew partway down means the counting is wrong, and every ratio below
        # it is fiction.
        "counting_warnings": [f.name for f in funnels if not f.is_monotonic],
    }


def format_dashboards(report: Mapping) -> str:
    lines = [f"food dashboards ({report.get('version')})",
             f"  records {report.get('records')}   "
             f"traces {report.get('traces')}", ""]

    for warning in report.get("counting_warnings") or ():
        lines.append(f"  ! {warning}: a step grew — counting is wrong")
    if report.get("counting_warnings"):
        lines.append("")

    for funnel in report.get("funnels") or ():
        lines.append(f"  {funnel['name']}")
        for step in funnel["steps"]:
            share = ("     -" if step["of_first"] is None
                     else f"{step['of_first'] * 100:5.1f}%")
            suffix = f"   {step['note']}" if step["note"] else ""
            lines.append(f"    {step['name']:<26} {step['count']:>7}  "
                         f"{share}{suffix}")
        if funnel.get("biggest_drop"):
            lines.append(f"    biggest drop: {funnel['biggest_drop']}")
        lines.append("")

    lines.append("  where turns stop")
    for stage, row in (report.get("stopped_at") or {}).items():
        share = "-" if row["share"] is None else f"{row['share'] * 100:.1f}%"
        lines.append(f"    {stage:<26} {row['count']:>7}  {share:>6}")
    lines.append("")

    lines.append("  latency (ms)")
    total = report.get("latency", {}).get("turn_total", {})
    lines.append(f"    {'turn total':<26} n={total.get('samples', 0):<6} "
                 f"p50={total.get('p50')} p90={total.get('p90')} "
                 f"p99={total.get('p99')} max={total.get('max_ms')}")
    for stage in report.get("latency", {}).get("stages") or ():
        lines.append(f"    {stage['name']:<26} n={stage['samples']:<6} "
                     f"p50={stage['p50']} p90={stage['p90']} "
                     f"p99={stage['p99']} max={stage['max_ms']}")
    lines.append("")

    cohorts = report.get("cohorts") or {}
    if cohorts:
        lines.append("  cohorts")
        for name, row in cohorts.items():
            lines.append(f"    {name:<26} turns={row['turns']:<6} "
                         f"committed={row['committed']:<6} "
                         f"asked={row['asked']:<5} errors={row['errors']}")
        lines.append("")

    pairs = report.get("confused_pairs") or []
    if pairs:
        lines.append("  confused pairs (recurring)")
        for pair in pairs[:10]:
            lines.append(f"    {pair['chosen']} → {pair['corrected']}"
                         f"   ×{pair['count']}")
        lines.append("")

    errors = report.get("errors") or {}
    if errors:
        lines.append("  errors")
        for name, count in errors.items():
            lines.append(f"    {name:<26} {count}")
    return "\n".join(lines)


def main(argv=None) -> int:            # pragma: no cover - CLI wrapper
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    paths = [a for a in argv if not a.startswith("--")]

    lines: List[str] = []
    if paths:
        for path in paths:
            with open(path, "r", errors="replace") as handle:
                lines.extend(handle)
    else:
        lines = list(sys.stdin)

    report = build_dashboards(parse_log(lines))
    print(json.dumps(report, indent=2) if as_json
          else format_dashboards(report))
    return 0


if __name__ == "__main__":             # pragma: no cover
    raise SystemExit(main())
