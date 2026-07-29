#!/usr/bin/env python3
"""Turn `event=food_trace` lines into the numbers the sprint is scored on.

    python scripts/food_latency_report.py app.log
    render logs --tail 5000 | python scripts/food_latency_report.py

The success metrics are percentiles — first-visible p50 and p95, completion
p95, decision-model calls per turn — and until now nothing could compute them.
This reads whatever the trace emits and reports it broken down the way the
sprint asks: by route owner, by voice profile, by fallback path, by item count,
by cache hit.

Two deliberate refusals, because a latency report that guesses is worse than
one that abstains:

  * A field the trace wrote as `-` is MISSING, never zero. `first_visible_ms=-`
    means nothing ever reached the user on that turn, and scoring it as an
    instant response would flatter exactly the turns that failed worst.
  * A percentile over too few samples is not reported. `p95` of nine turns is
    the second-slowest turn wearing a statistical name, and it moves by
    hundreds of milliseconds when one more arrives.

Nothing here runs in the request path — this reads logs after the fact, which
is the whole reason the trace is a log line and not a database write.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

#: Below this, a percentile is a single unlucky turn with a name.
MIN_SAMPLES = 20

TOKEN = re.compile(r"(\w+)=(\S+)")


def parse(lines: Iterable[str]) -> List[dict]:
    rows = []
    for line in lines:
        if "event=food_trace" not in line:
            continue
        row = dict(TOKEN.findall(line))
        if row.get("event") == "food_trace":
            rows.append(row)
    return rows


def num(row: dict, key: str) -> Optional[float]:
    """A value the trace wrote as `-` is absent, not zero.

    This is the whole reason `_mark_str` prints `-`: a turn that showed the
    user nothing has no first-visible time, and averaging it in as 0 ms would
    make the worst turns improve the number.
    """
    raw = row.get(key)
    if raw is None or raw == "-":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    # Nearest-rank on the lower side, so a reported p95 is a turn that actually
    # happened rather than an interpolation between two that did.
    idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return ordered[idx]


def _fmt(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:,.0f}"


def summarise(rows: List[dict], field: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        v = num(r, field)
        if v is not None:
            out["all"].append(v)
    return out


def by(rows: List[dict], key: str, field: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        v = num(r, field)
        if v is not None:
            out[r.get(key) or "-"].append(v)
    return out


def table(title: str, groups: Dict[str, List[float]], *, note: str = "") -> None:
    print(f"\n{title}")
    if note:
        print(f"  {note}")
    print(f"  {'group':<26}{'n':>7}{'p50':>9}{'p75':>9}{'p95':>9}{'p99':>9}")
    for name, vals in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        thin = len(vals) < MIN_SAMPLES
        cells = [_fmt(pct(vals, p)) for p in (0.50, 0.75, 0.95, 0.99)]
        if thin:
            # Report the median and abstain on the tail: with this few samples
            # p95 is the second-slowest turn wearing a statistical name.
            cells = [cells[0]] + ["·"] * 3
        print(f"  {name[:26]:<26}{len(vals):>7}"
              + "".join(f"{c:>9}" for c in cells)
              + ("   (thin)" if thin else ""))


def counts(rows: List[dict], key: str) -> None:
    tally: Dict[str, int] = defaultdict(int)
    for r in rows:
        tally[r.get(key) or "-"] += 1
    total = sum(tally.values()) or 1
    print(f"\n{key}")
    for name, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {name[:34]:<34}{n:>7}  {n / total:>6.1%}")


def main(argv: List[str]) -> int:
    src = open(argv[1]) if len(argv) > 1 else sys.stdin
    rows = parse(src)
    if not rows:
        print("no event=food_trace lines found", file=sys.stderr)
        return 1

    print(f"food latency report — {len(rows):,} turns")
    if len(rows) < MIN_SAMPLES:
        print(f"  fewer than {MIN_SAMPLES} turns: tail percentiles are "
              f"withheld, medians only")

    table("first visible (ms)", by(rows, "route_owner", "first_visible_ms"),
          note="target p50 <= 2500, p95 <= 4000 · by route owner")
    table("complete (ms)", by(rows, "route_owner", "complete_ms"),
          note="target p95 <= 6000 · by route owner")
    table("interpreter total (ms)", by(rows, "interp_model", "interp_ttfb_ms"),
          note="time to FIRST byte, by model · budget < 700")
    table("voice (ms)", by(rows, "voice_profile", "complete_ms"),
          note="by compiled profile")

    counts(rows, "route_owner")
    counts(rows, "voice_profile")
    counts(rows, "fallback")
    counts(rows, "legacy_escape")

    # ── the two scored ratios ────────────────────────────────────────────────
    paid = sum(1 for r in rows
               if (r.get("route_owner") or "").startswith("gate_model"))
    print(f"\ndecision-model gate calls: {paid}/{len(rows)} "
          f"({paid / len(rows):.1%}) — every one is a round trip the free "
          f"signals could not settle")

    warm = [r for r in rows if num(r, "interp_cached") not in (None, 0)]
    if warm:
        ratio = sum(num(r, "interp_cached") / max(1.0, num(r, "interp_in") or 1.0)
                    for r in warm) / len(warm)
        print(f"prompt cache: {len(warm)}/{len(rows)} turns warm, "
              f"{ratio:.0%} of input tokens cached on those")

    retried = sum(1 for r in rows if (num(r, "retries") or 0) > 0)
    print(f"voice retries: {retried}/{len(rows)} turns paid for a second "
          f"composer call")

    silent = sum(1 for r in rows if num(r, "first_visible_ms") is None)
    if silent:
        print(f"\n{silent} turns never showed the user anything before "
              f"completing — excluded from first-visible above rather than "
              f"scored as instant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
