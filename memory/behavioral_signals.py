"""Behavioral signals — turn the data Arnie already stores into inference fuel.

The profile synthesizer used to see only food/exercise NAME counts + a weight
trend, so it could learn what the user *said* but never what they *did*. These
helpers summarize the rich quantitative data (per-set lifts, daily macro totals,
meal timestamps, wearable snapshots) into compact text blocks fed to synthesis,
so Arnie can infer durable patterns: strength trends, adherence habits, meal
timing, recovery patterns.

IMPORTANT: these blocks are INPUT for inferring durable PATTERNS. The synthesizer
must store the pattern ("protein slips on rest days"), never the daily snapshot
numbers ("117g on 06-13") — those are live data (Lane 3, see BRAIN_TAXONOMY.md).
"""
import re
from statistics import mean
from typing import Optional

_KG_TO_LB = 2.20462


def _reps_val(reps_str) -> Optional[int]:
    """Representative rep count from a reps string ('12' or '12,12,10')."""
    if reps_str is None:
        return None
    nums = [int(p) for p in re.split(r"[^0-9]+", str(reps_str)) if p.isdigit()]
    return max(nums) if nums else None


def _e1rm(weight_kg: float, reps: int) -> float:
    """Epley estimated 1-rep max."""
    return weight_kg * (1 + reps / 30)


def adherence_summary(logs, prefs) -> str:
    """Per-day macro adherence vs target, split by weekday/weekend & train/rest."""
    closed = [l for l in logs if (l.total_calories or 0) > 0]
    if len(closed) < 5 or not prefs:
        return ""
    cal_t = prefs.calorie_target
    pro_t = prefs.protein_target
    bits = [f"{len(closed)} logged days"]

    if pro_t:
        pro_adh = mean(min((l.total_protein or 0) / pro_t, 1.0) for l in closed)
        avg_pro = mean((l.total_protein or 0) for l in closed)
        bits.append(f"protein avg {avg_pro:.0f}g vs {pro_t}g target ({pro_adh*100:.0f}% adherence)")
        train = [l for l in closed if l.workout_completed]
        rest = [l for l in closed if not l.workout_completed]
        if len(train) >= 2 and len(rest) >= 2:
            bits.append(f"training-day protein {mean((l.total_protein or 0) for l in train):.0f}g "
                        f"vs rest-day {mean((l.total_protein or 0) for l in rest):.0f}g")
    if cal_t:
        avg_cal = mean((l.total_calories or 0) for l in closed)
        bits.append(f"calories avg {avg_cal:.0f} vs {cal_t} target")
        wknd = [l for l in closed if l.date.weekday() >= 5]
        wkdy = [l for l in closed if l.date.weekday() < 5]
        if len(wknd) >= 2 and len(wkdy) >= 2:
            bits.append(f"weekday cal {mean((l.total_calories or 0) for l in wkdy):.0f} "
                        f"vs weekend {mean((l.total_calories or 0) for l in wknd):.0f}")
    return "MACRO ADHERENCE (recent): " + "; ".join(bits) + "."


def strength_progression(logs, *, max_lifts: int = 6) -> str:
    """Per-lift estimated-1RM trend (first vs latest session) across the window."""
    by_ex: dict[str, list] = {}
    for lg in logs:
        for ee in (lg.exercise_entries or []):
            if not ee.weight or ee.weight <= 0:
                continue
            reps = _reps_val(ee.reps)
            if not reps:
                continue
            name = (ee.exercise_name or "").strip()
            if not name or not ee.timestamp:
                continue
            by_ex.setdefault(name.lower(), []).append(
                (ee.timestamp, _e1rm(ee.weight, reps), name))

    rows = []
    for _, entries in by_ex.items():
        if len(entries) < 2:
            continue
        entries.sort(key=lambda x: x[0])
        first_e1, last_e1 = entries[0][1], entries[-1][1]
        disp = entries[-1][2]
        delta_lb = (last_e1 - first_e1) * _KG_TO_LB
        arrow = "↑" if delta_lb >= 5 else ("↓" if delta_lb <= -5 else "→")
        rows.append((len(entries), f"{disp} {first_e1*_KG_TO_LB:.0f}→{last_e1*_KG_TO_LB:.0f}lb {arrow}"))

    if not rows:
        return ""
    rows.sort(key=lambda r: -r[0])
    return "STRENGTH TREND (est. 1RM, first→latest session): " + " · ".join(
        r[1] for r in rows[:max_lifts]) + "."


def meal_timing_summary(logs, *, days_window: int = 21) -> str:
    """Eating window + late-night frequency + meal-type split from timestamps."""
    by_day: dict = {}
    type_counts: dict[str, int] = {}
    for lg in logs:
        for fe in (lg.food_entries or []):
            ts = fe.meal_time or fe.timestamp
            if not ts:
                continue
            d = ts.date()
            by_day.setdefault(d, []).append(ts.hour)
            mt = (fe.meal_type or "").strip().lower()
            if mt:
                type_counts[mt] = type_counts.get(mt, 0) + 1
    if len(by_day) < 4:
        return ""

    first_hours = [min(hs) for hs in by_day.values()]
    last_hours = [max(hs) for hs in by_day.values()]
    late_days = sum(1 for hs in by_day.values() if any(h >= 22 or h < 4 for h in hs))
    bits = [f"typical eating window ~{int(mean(first_hours))}:00–{int(mean(last_hours))}:00",
            f"food logged after 10pm on {late_days}/{len(by_day)} days"]
    if type_counts:
        total = sum(type_counts.values())
        split = sorted(type_counts.items(), key=lambda x: -x[1])[:4]
        bits.append("meal split " + ", ".join(f"{k} {c/total*100:.0f}%" for k, c in split))
    return "MEAL TIMING (recent): " + "; ".join(bits) + "."


def recovery_summary(snapshots, *, min_n: int = 3) -> str:
    """Recovery / sleep / HRV averages + direction from wearable snapshots."""
    if not snapshots or len(snapshots) < min_n:
        return ""
    sn = sorted(snapshots, key=lambda s: (s.date or s.received_at))

    def _avg(attr):
        vals = [getattr(s, attr) for s in sn if getattr(s, attr, None) is not None]
        return mean(vals) if vals else None

    def _trend(attr):
        vals = [getattr(s, attr) for s in sn if getattr(s, attr, None) is not None]
        if len(vals) < 4:
            return ""
        half = len(vals) // 2
        early, late = mean(vals[:half]), mean(vals[half:])
        if late > early * 1.05:
            return "↑"
        if late < early * 0.95:
            return "↓"
        return "→"

    bits = []
    rec = _avg("recovery_score")
    if rec is not None:
        bits.append(f"recovery avg {rec:.0f}% {_trend('recovery_score')}".strip())
    slp = _avg("sleep_hours")
    if slp is not None:
        bits.append(f"sleep avg {slp:.1f}h {_trend('sleep_hours')}".strip())
    hrv = _avg("hrv")
    if hrv is not None:
        bits.append(f"HRV avg {hrv:.0f}ms {_trend('hrv')}".strip())
    if not bits:
        return ""
    return f"RECOVERY (wearable, last {len(sn)} readings): " + "; ".join(bits) + "."


def detected_signals(logs, weights, prefs, user) -> str:
    """Surface the insights_engine discoveries so synthesis can LEARN them
    (today they're computed every turn at read-time and thrown away)."""
    from core.insights_engine import discover_pattern, weight_projection, personal_records, fmt_records

    out = []
    p = discover_pattern(logs, prefs)
    if p:
        out.append(f"- pattern: {p}")
    proj = weight_projection(weights, user)
    if proj:
        out.append(f"- projection: {proj}")
    recs = fmt_records(personal_records(logs, weights))
    if recs:
        out.append(f"- {recs}")
    if not out:
        return ""
    return ("DETECTED SIGNALS (already computed from logs — corroborate and store the "
            "durable PATTERN only, never the daily numbers):\n" + "\n".join(out))


def build_behavioral_block(logs, weights, snapshots, prefs, user) -> str:
    """Assemble all behavioral-signal sections into one input block (or '')."""
    sections = [
        adherence_summary(logs, prefs),
        strength_progression(logs),
        meal_timing_summary(logs),
        recovery_summary(snapshots),
        detected_signals(logs, weights, prefs, user),
    ]
    sections = [s for s in sections if s]
    if not sections:
        return ""
    return ("BEHAVIORAL DATA (what the user actually DID — infer durable patterns "
            "from this, store as confidence=inferred; NEVER store the raw daily "
            "numbers, those are live data):\n" + "\n".join(sections))
