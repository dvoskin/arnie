"""Regression tests for the home / bands / bodyweight coverage fix.

Anya (prod user 44) asked for a bands + bodyweight home program and got a
degenerate one: "Full Body B" was ONLY a Nordic Curl, "Full Body D" was ONLY
Box Jumps — because the catalog had almost no bands/bodyweight coverage, so the
builder silently dropped every muscle it couldn't fill, and picked plyometric
finishers (Box Jumps) / advanced staples (Nordic Curl, Pull-Up) as "mains" for
a beginner.

These pin the fix:
  • no degenerate sessions (>= MIN_EXERCISES) on thin equipment,
  • conditioning finishers are never programmed as lifts,
  • beginners on bands get band regressions, not Pull-Ups / Nordic Curls,
  • weekly volume is capped to the evidence band even on a 5-day full body,
  • fully-equipped users still get barbell movements first (no regression).
"""
from __future__ import annotations

from skills.fitness.program_builder import build_program, MIN_EXERCISES
from skills.fitness.exercise_catalog import EXERCISES, lookup_canonical


# Conditioning / plyometric movements that must never be prescribed as program
# lifts (they stay in the catalog for logging + canonicalization).
_FINISHERS = {e["canonical"] for e in EXERCISES if e.get("category") == "finisher"}


def _all_canonicals(program: dict) -> list[str]:
    return [ex["canonical"] for s in program["sessions"] for ex in s["exercises"]]


def _anya_program(**overrides):
    kw = dict(goal="hypertrophy", days_per_week=5, split="full_body",
              equipment=["bands", "bodyweight"], experience="beginner")
    kw.update(overrides)
    return build_program(**kw)


# ── No degenerate sessions ────────────────────────────────────────────────────

def test_anya_bands_bodyweight_no_degenerate_session():
    """The exact prod config that shipped a 1-exercise day. Every session must
    now clear the minimum floor."""
    p = _anya_program()
    assert len(p["sessions"]) == 5
    for s in p["sessions"]:
        assert len(s["exercises"]) >= MIN_EXERCISES, (
            f"{s['name']} has {len(s['exercises'])} exercises — degenerate: "
            f"{[e['canonical'] for e in s['exercises']]}"
        )


def test_bands_only_no_degenerate_session():
    p = build_program(goal="general", days_per_week=4, split="full_body",
                      equipment=["bands"], experience="beginner")
    for s in p["sessions"]:
        assert len(s["exercises"]) >= MIN_EXERCISES, s["name"]


def test_bodyweight_only_no_degenerate_session():
    p = build_program(goal="general", days_per_week=4, split="full_body",
                      equipment=["bodyweight"], experience="beginner")
    for s in p["sessions"]:
        assert len(s["exercises"]) >= MIN_EXERCISES, s["name"]


# ── Finishers are never programmed as lifts ───────────────────────────────────

def test_no_finisher_movements_in_any_program():
    """Box Jumps / Burpees / Battle Ropes are met-con, not prescriptions.
    Programming Box Jumps as Anya's quad 'main' was the bug."""
    for eq in (["bands", "bodyweight"], ["bodyweight"], None):
        for exp in ("beginner", "intermediate"):
            p = build_program(days_per_week=5, split="full_body",
                              equipment=eq, experience=exp)
            picked = set(_all_canonicals(p))
            leaked = picked & _FINISHERS
            assert not leaked, f"finisher(s) programmed for eq={eq}: {leaked}"


def test_box_jumps_never_the_quad_main():
    p = _anya_program()
    quad_mains = [
        ex["canonical"] for s in p["sessions"] for ex in s["exercises"]
        if ex.get("notes") == "main lift"
        and (lookup_canonical(ex["canonical"]) or {}).get("primary") == "quads"
    ]
    assert "Box Jumps" not in quad_mains
    # A real squat pattern should carry the quad main slot instead.
    assert any("Squat" in c for c in quad_mains), quad_mains


# ── Beginner-appropriate selection on bands ───────────────────────────────────

def test_beginner_on_bands_avoids_advanced_staples():
    """With bands available, a beginner should get Band Lat Pulldown /
    Band RDL — not Pull-Ups or Nordic Curls (level='advanced')."""
    picked = set(_all_canonicals(_anya_program()))
    assert "Pull-Up" not in picked, "beginner got a Pull-Up despite bands"
    assert "Nordic Curl" not in picked, "beginner got a Nordic Curl despite bands"
    assert "Band Lat Pulldown" in picked
    assert "Band Romanian Deadlift" in picked


def test_intermediate_may_still_get_advanced_moves():
    """avoid_advanced only applies to beginners — an intermediate bodyweight
    program can still use Pull-Ups."""
    p = build_program(goal="hypertrophy", days_per_week=4, split="full_body",
                      equipment=["bodyweight"], experience="intermediate")
    # Not asserting it's ALWAYS there, just that the gate doesn't forbid it:
    # bodyweight lats main is Pull-Up, so an intermediate should see it.
    assert "Pull-Up" in set(_all_canonicals(p))


# ── Weekly volume stays in the evidence band ──────────────────────────────────

def test_five_day_beginner_volume_capped_to_band():
    """A 5-day full body stacks the same muscle every session. Volume must be
    trimmed to the beginner high-band (12), not the raw 21 the un-capped
    builder produced — so the rationale ('10-12 sets') matches the program."""
    p = _anya_program()
    for muscle, vol in p["weekly_volume"].items():
        assert vol <= 12, f"{muscle} weekly volume {vol} exceeds beginner band"


def test_capped_program_keeps_frequency():
    """Capping trims per-exercise sets but must NOT remove a muscle entirely —
    frequency (train each muscle across the week) is preserved."""
    p = _anya_program()
    # quads/chest/lats appear in multiple sessions; each should still be trained.
    for muscle in ("quads", "chest_mid", "lats"):
        assert p["weekly_volume"].get(muscle, 0) >= 6, muscle


# ── Fully-equipped regression: barbell first ──────────────────────────────────

def test_full_gym_still_prefers_barbell_mains():
    """The home coverage layer is appended LAST in the catalog, so a
    fully-equipped user must still get Back Squat / Bench Press, never the
    Bodyweight Squat fallback."""
    p = build_program(goal="hypertrophy", days_per_week=6, split="ppl",
                      equipment=None, experience="intermediate")
    picked = set(_all_canonicals(p))
    assert "Back Squat" in picked
    assert "Bench Press" in picked
    assert "Bodyweight Squat" not in picked
    assert "Band Chest Press" not in picked


def test_every_home_pick_resolves_in_catalog():
    """No fabricated movement names — every prescribed canonical resolves."""
    for eq in (["bands", "bodyweight"], ["bodyweight"], ["bands"]):
        p = build_program(days_per_week=5, split="full_body",
                          equipment=eq, experience="beginner")
        for c in _all_canonicals(p):
            assert lookup_canonical(c) is not None, f"unresolved: {c!r}"
