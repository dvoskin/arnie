"""
Superseded backward re-log guard for single-set logging.

Danny's 2026-06-15 back session over-logged every movement: he performed 3 sets
each of lat pulldown / chest-supported row / straight-arm pulldown but 4-6 rows
landed per exercise. The phantoms were EXACT re-logs of an earlier single set,
emitted after the movement had already moved on (170×10 re-fired after 175×7 was
logged; an 80×14 straight-arm set re-emitted 37 min later during a *food* turn).

These sit outside the tight 120s single-set window, so is_duplicate_of_recent
now also blocks an exact match that has been SUPERSEDED — a later same-exercise
set at a different load/reps exists — within a 1h session window. The guard must
stay narrow: legit straight sets (identical later set) and supersets (a different
movement intervenes) still write.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from skills.fitness.exercise_dedup import is_duplicate_of_recent

NOW = datetime(2026, 6, 16, 1, 0, 0)

# Representative kg loads (lb→kg) from the real session.
LAT_170, LAT_175, LAT_165 = 77.111, 79.379, 74.843
SA_80, SA_70 = 36.287, 31.751
PUSH_190 = 86.183
FP_70, UR_110 = 31.751, 49.895


def _e(name, reps, weight, ago, *, sets=1, id_=0):
    return SimpleNamespace(
        id=id_, exercise_name=name, sets=sets, reps=reps, weight=weight,
        timestamp=NOW - timedelta(seconds=ago),
    )


def _check(existing, *, name, reps, weight, sets=1, superseded=3600):
    return is_duplicate_of_recent(
        exercise_name=name, sets=sets, reps=reps, weight_kg=weight,
        existing_entries=existing, now_utc=NOW,
        window_sec=120, superseded_window_sec=superseded,
    )


# ── Phantoms that MUST now be blocked ────────────────────────────────────────

def test_superseded_relog_blocked():
    """170×10 re-fired after 175×7 was already logged (EX#205)."""
    s1 = _e("Lat Pulldown", "10", LAT_170, ago=200, id_=203)
    s2 = _e("Lat Pulldown", "7", LAT_175, ago=90, id_=204)
    dup = _check([s1, s2], name="Lat Pulldown", reps="10", weight=LAT_170)
    assert dup is s1


def test_far_relog_during_food_turn_blocked():
    """Straight-arm 80×14 re-emitted 37 min later, after 70×13 (EX#217)."""
    a = _e("Straight-Arm Pulldown", "14", SA_80, ago=2300, id_=213)
    b = _e("Straight-Arm Pulldown", "13", SA_70, ago=2000, id_=216)
    dup = _check([a, b], name="Straight-Arm Pulldown", reps="14", weight=SA_80)
    assert dup is a


# ── Legit patterns that MUST still write (dup is None) ───────────────────────

def test_identical_straight_sets_write():
    """Three identical singles logged individually — a real straight-set block."""
    s1 = _e("Cable Pushdown", "10", PUSH_190, ago=300, id_=1)
    s2 = _e("Cable Pushdown", "10", PUSH_190, ago=150, id_=2)
    dup = _check([s1, s2], name="Cable Pushdown", reps="10", weight=PUSH_190)
    assert dup is None


def test_superset_identical_rounds_write():
    """Face pull 70×12 round 2 — only a DIFFERENT movement (upright row)
    intervened, so the earlier round is still its movement's frontier."""
    a1 = _e("Face Pull", "12", FP_70, ago=200, id_=1)
    b1 = _e("Upright Row", "12", UR_110, ago=150, id_=2)
    dup = _check([a1, b1], name="Face Pull", reps="12", weight=FP_70)
    assert dup is None


def test_legit_second_single_frontier_writes():
    """One prior identical single, nothing logged after it — a real next set."""
    s1 = _e("Cable Pushdown", "10", PUSH_190, ago=180, id_=1)
    dup = _check([s1], name="Cable Pushdown", reps="10", weight=PUSH_190)
    assert dup is None


def test_relog_beyond_session_window_writes():
    """Superseded but >1h old — a separate mini-session, not a phantom."""
    a = _e("Straight-Arm Pulldown", "14", SA_80, ago=4000, id_=1)
    b = _e("Straight-Arm Pulldown", "13", SA_70, ago=3800, id_=2)
    dup = _check([a, b], name="Straight-Arm Pulldown", reps="14", weight=SA_80)
    assert dup is None


# ── Regression: tight window + opt-out still behave ──────────────────────────

def test_tight_window_still_blocks_rapid_refire():
    s1 = _e("Cable Pushdown", "10", PUSH_190, ago=30, id_=1)
    dup = _check([s1], name="Cable Pushdown", reps="10", weight=PUSH_190)
    assert dup is s1


def test_no_superseded_window_keeps_legacy_behavior():
    """Without superseded_window_sec, a superseded match older than 120s writes."""
    s1 = _e("Lat Pulldown", "10", LAT_170, ago=200, id_=1)
    s2 = _e("Lat Pulldown", "7", LAT_175, ago=90, id_=2)
    dup = _check([s1, s2], name="Lat Pulldown", reps="10", weight=LAT_170,
                 superseded=None)
    assert dup is None
