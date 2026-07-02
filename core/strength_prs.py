"""
Exercise PR tracker — the strongest set per movement, all-time, from logged sets.

Arnie doesn't store PRs as facts; they're *derived* from the `ExerciseEntry` rows
the user logs. This mirrors the Epley 1RM already computed for context in
`core.context_builder.fmt_strength_prs`, but returns structured data (not prose)
so the iOS Coach page can render a real PR card, and layers on bodyweight-scaled
strength standards (see `core.strength_standards`).

The "PR" for a movement is the single set with the highest estimated 1RM across
all logged history — reported as the actual weight × reps you did, plus the Epley
estimate. Per-set loads (`ExerciseEntry.weights`, a CSV parallel to `reps`) are
considered individually, so a top single inside a pyramid set counts.
"""
from __future__ import annotations

from typing import List, Optional

from db.models import DailyLog
from skills.fitness.exercise_catalog import canonicalize
from core import strength_standards

_KG_TO_LB = 2.20462
_EPLEY_MIN_REPS = 1
_EPLEY_MAX_REPS = 20   # Epley is unreliable past ~20 reps


def _epley_1rm(weight_kg: float, reps: int) -> float:
    return weight_kg * (1.0 + reps / 30.0)


def _parse_int_list(csv: Optional[str]) -> List[int]:
    out: List[int] = []
    for part in str(csv or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(float(part)))
        except ValueError:
            continue
    return out


def _parse_float_list(csv: Optional[str]) -> List[float]:
    out: List[float] = []
    for part in str(csv or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def _sets_for_entry(entry) -> List[tuple[float, int]]:
    """Expand one ExerciseEntry into (weight_kg, reps) pairs — one per logged set.

    Handles the three shapes the logger produces:
      • per-set loads   → `weights`="102,107,107" alongside `reps`="5,5,4"
      • single load     → `weight`=100 with `reps`="5,5,5" (or "5")
      • single set      → `weight`=100, `reps`="5"
    """
    reps_list = _parse_int_list(entry.reps)
    weights_list = _parse_float_list(entry.weights)
    base_weight = entry.weight

    pairs: List[tuple[float, int]] = []

    if weights_list:
        # Per-set loads. Pair with reps by index; if reps run short, reuse the
        # last known rep count (a coach logging "3x5" then adding a load list).
        for i, w in enumerate(weights_list):
            if i < len(reps_list):
                r = reps_list[i]
            elif reps_list:
                r = reps_list[-1]
            elif base_weight:
                r = 1
            else:
                continue
            pairs.append((w, r))
        return pairs

    if not base_weight:
        return pairs

    if reps_list:
        for r in reps_list:
            pairs.append((base_weight, r))
    return pairs


# Big compound-lift targets — a movement on any of these always earns a board row.
_LARGE_GROUP_IDS = {"lats", "mid_back", "lower_back", "back", "legs",
                    "quads", "hamstrings", "glutes"}
# Small-muscle isolation — never a board row (curls, pushdowns, raises, crunches).
_SMALL_ISOLATION_IDS = {"biceps", "triceps", "forearms", "calves", "abs",
                        "obliques", "traps", "neck"}


def _board_includes(rec: dict) -> bool:
    """Board = movements on large muscle groups (chest / back / legs), shoulder
    PRESSES, and weighted calisthenics (added load > 5 lb). Small-muscle isolation
    and shoulder raises are left off so the board reads as real lifts.

    Gate on muscle group, NOT the catalog's `category`: some isolation is mislabeled
    `main` there (e.g. cable curls), so trusting category alone leaks curls and
    pushdowns onto the board. Category is only consulted to split shoulder presses
    (main) from lateral / rear-delt raises (accessory), where it is reliable."""
    primary = (rec.get("primary") or "").lower()
    if primary in _SMALL_ISOLATION_IDS:
        return False
    if primary.startswith("chest") or primary in _LARGE_GROUP_IDS:
        return True
    if primary == "shoulders":            # presses in, lateral / rear raises out
        return (rec.get("category") or "").lower() == "main"
    if (rec.get("equipment") or "").lower() == "bodyweight" and rec.get("weight_kg", 0.0) * _KG_TO_LB > 5.0:
        return True
    return False


def compute_strength_prs(
    logs: List[DailyLog],
    bodyweight_kg: Optional[float] = None,
    sex: Optional[str] = None,
    limit: int = 50,
    recent_days: int = 14,
) -> List[dict]:
    """Best set per movement, ranked by estimated 1RM (strongest first).

    Cardio and unloaded movements are skipped. Names are folded to their canonical
    form so "bench" and "barbell bench press" count as one lift. Each result:

        {
          "name": "Bench Press", "primary": "chest", "equipment": "barbell",
          "top_weight_lbs": 225.0, "top_reps": 5, "e1rm_lbs": 253.1,
          "date": "2026-06-28", "is_recent": true,
          "standard": { ...see strength_standards.classify... } | null
        }
    """
    from datetime import date, timedelta

    # canonical -> best record dict (kept in kg internally, converted at the end)
    best: dict[str, dict] = {}
    # canonical -> total working sets logged (weight > 0) across all logs = volume
    sets_count: dict[str, int] = {}
    # canonical -> [(date, weight_kg, reps)] every working set, for the last-3
    # recent-sets reference the iOS PR row expands into
    all_sets: dict[str, list] = {}

    for log in logs:
        log_date = getattr(log, "date", None)
        for e in (log.exercise_entries or []):
            if e.cardio_type:            # strength only
                continue
            canonical, entry_meta = canonicalize(e.exercise_name)
            canonical = (canonical or "").strip()
            if not canonical:
                continue
            for weight_kg, reps in _sets_for_entry(e):
                if weight_kg <= 0:
                    continue
                sets_count[canonical] = sets_count.get(canonical, 0) + 1   # volume
                if log_date:
                    all_sets.setdefault(canonical, []).append((log_date, weight_kg, reps))
                if reps < _EPLEY_MIN_REPS or reps > _EPLEY_MAX_REPS:
                    continue
                e1rm = _epley_1rm(weight_kg, reps)
                cur = best.get(canonical)
                if cur is None or e1rm > cur["e1rm_kg"]:
                    best[canonical] = {
                        "weight_kg": weight_kg,
                        "reps": reps,
                        "e1rm_kg": e1rm,
                        "date": log_date,
                        "primary": (entry_meta or {}).get("primary"),
                        "equipment": (entry_meta or {}).get("equipment"),
                        "category": (entry_meta or {}).get("category"),
                    }

    # Board = compounds + large-muscle-group movements + weighted calisthenics.
    meaningful = {n: r for n, r in best.items() if _board_includes(r)}
    ranked = sorted(meaningful.items(), key=lambda kv: kv[1]["e1rm_kg"], reverse=True)[:limit]

    today = date.today()
    recent_cutoff = today - timedelta(days=recent_days)

    out: List[dict] = []
    for name, rec in ranked:
        d = rec["date"]
        is_recent = bool(d and d >= recent_cutoff)
        # Last 3 logged working sets, newest first — the compact frame of
        # reference the iOS PR row expands into.
        last3 = sorted(all_sets.get(name, []), key=lambda t: t[0])[-3:]
        out.append({
            "name": name,
            "primary": rec["primary"],
            "equipment": rec["equipment"],
            "sets": sets_count.get(name, 0),
            "top_weight_lbs": round(rec["weight_kg"] * _KG_TO_LB, 1),
            "top_reps": rec["reps"],
            "e1rm_lbs": round(rec["e1rm_kg"] * _KG_TO_LB, 1),
            "date": str(d) if d else None,
            "is_recent": is_recent,
            "standard": strength_standards.classify(
                name, rec["e1rm_kg"], bodyweight_kg, sex
            ),
            "recent_sets": [
                {"date": str(sd), "weight_lbs": round(sw * _KG_TO_LB, 1), "reps": sr}
                for sd, sw, sr in reversed(last3)
            ],
        })
    return out
