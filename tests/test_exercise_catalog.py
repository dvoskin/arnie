"""Unit tests for the canonical exercise registry.

Pins the user-typed → canonical name mappings that Phase 2 relies on.
If a future PR adds an alias that collides with another canonical, the
_build_alias_map import-time assert fires and the whole catalog refuses
to load — caught here, before any user data is mis-routed.
"""
import pytest

from skills.fitness.exercise_catalog import (
    EXERCISES,
    canonicalize,
    lookup_canonical,
    _norm_key,
    _ALIAS_MAP,
)


# ── catalog integrity ────────────────────────────────────────────────────────

def test_catalog_not_empty():
    """Sanity: the catalog must have entries. A regression that drops the
    list silently would otherwise canonicalize() everything to no-match."""
    assert len(EXERCISES) >= 50, f"catalog shrunk to {len(EXERCISES)} entries"


def test_every_entry_has_required_fields():
    """Every entry must have the fields Phase 3's [SESSION STATE] block
    will read. A missing field is a typo, not intentional."""
    required = {"canonical", "aliases", "primary", "equipment",
                "rest_seconds", "category"}
    for e in EXERCISES:
        missing = required - set(e.keys())
        assert not missing, f"{e.get('canonical')!r} missing {missing}"
        assert isinstance(e["aliases"], list)
        assert isinstance(e["rest_seconds"], tuple)
        assert len(e["rest_seconds"]) == 2


def test_no_alias_collisions_across_canonicals():
    """If two entries share an alias, _build_alias_map raises at import.
    This test passes by virtue of the module loading — failure is a
    crash on import, not a green-but-broken state.

    Also defensively asserts no canonical names collide with each other."""
    canonicals = [e["canonical"] for e in EXERCISES]
    assert len(canonicals) == len(set(canonicals)), \
        "duplicate canonical names in catalog"


def test_alias_map_includes_canonical_as_self_alias():
    """Looking up a canonical name should always resolve to itself.
    Otherwise downstream code (e.g. dedup using canonical key) breaks."""
    for e in EXERCISES:
        canon, found = canonicalize(e["canonical"])
        assert canon == e["canonical"], e["canonical"]
        assert found is e, e["canonical"]


# ── canonicalize: core matching ──────────────────────────────────────────────

def test_exact_alias_resolves():
    canon, e = canonicalize("pushdowns")
    assert canon == "Cable Pushdown"
    assert e is not None
    assert e["primary"] == "triceps"


def test_canonical_name_resolves_to_self():
    canon, e = canonicalize("Cable Pushdown")
    assert canon == "Cable Pushdown"
    assert e["canonical"] == "Cable Pushdown"


def test_case_insensitive():
    assert canonicalize("CABLE PUSHDOWN")[0] == "Cable Pushdown"
    assert canonicalize("Cable PushDown")[0] == "Cable Pushdown"


def test_whitespace_normalized():
    assert canonicalize("cable  pushdown")[0] == "Cable Pushdown"
    assert canonicalize("  cable pushdown  ")[0] == "Cable Pushdown"


def test_hyphens_normalized():
    assert canonicalize("pull-up")[0] == "Pull-Up"
    assert canonicalize("Pull-up")[0] == "Pull-Up"
    assert canonicalize("pullup")[0] == "Pull-Up"


def test_plural_fallback_resolves():
    """The plural-strip fallback catches 'pull ups' / 'squats' / 'leg curls'
    without requiring every entry to enumerate plural forms."""
    assert canonicalize("PULL UPS")[0] == "Pull-Up"
    assert canonicalize("pull ups")[0] == "Pull-Up"
    assert canonicalize("squats")[0] == "Back Squat"
    assert canonicalize("hamstring curls")[0] == "Hamstring Curl"
    assert canonicalize("leg curls")[0] == "Hamstring Curl"
    assert canonicalize("Tricep Dips")[0] == "Dip"


def test_unknown_name_falls_back_to_raw():
    """No alias hit, no fuzzy guess. The raw name is returned so the
    caller can still log under it. Coverage is graceful, not all-or-nothing."""
    raw = "This Exercise Definitely Does Not Exist"
    canon, e = canonicalize(raw)
    assert canon == raw
    assert e is None


def test_empty_and_none_inputs():
    """Don't crash on bad input."""
    assert canonicalize("") == ("", None)
    assert canonicalize(None) == ("", None)
    assert canonicalize("   ")[1] is None  # whitespace-only after norm


# ── canonicalize: Danny's session resolutions ────────────────────────────────

def test_dannys_2026_06_11_session_all_resolve():
    """The 6 exercises Danny logged in his 2026-06-11 arms session all
    have catalog entries — this is a regression pin: any future PR that
    deletes one of these aliases breaks the canonical resolution that
    Phase 1's dedup depends on."""
    expected = {
        "Overhead Cable Extension": "Overhead Cable Extension",
        "overhead extension cable": "Overhead Cable Extension",
        "Cable Pushdown": "Cable Pushdown",
        "Crunches (Cable/Machine)": "Cable Crunch",
        "Straight Bar Cable Curl": "Straight Bar Cable Curl",
        "Forearm Cable Curl": "Forearm Cable Curl",
        "forearm straight bar curls": "Forearm Cable Curl",
        "Dips": "Dip",
        "Stationary Bike": "Stationary Bike",
    }
    for user_typed, expected_canon in expected.items():
        canon, _ = canonicalize(user_typed)
        assert canon == expected_canon, (
            f"{user_typed!r} should resolve to {expected_canon!r}, got {canon!r}"
        )


def test_two_different_user_phrasings_resolve_to_same_canonical():
    """'Crunches (Cable/Machine)' and 'cable crunch' must collide on the
    same canonical — that's what makes Phase 1 dedup catch a re-log even
    when the model uses a different name string."""
    a, _ = canonicalize("Crunches (Cable/Machine)")
    b, _ = canonicalize("cable crunch")
    c, _ = canonicalize("rope crunch")
    assert a == b == c == "Cable Crunch"


# ── lookup_canonical ─────────────────────────────────────────────────────────

def test_lookup_canonical_finds_entry():
    e = lookup_canonical("Cable Pushdown")
    assert e is not None
    assert e["canonical"] == "Cable Pushdown"
    assert e["rest_seconds"] == (60, 90)


def test_lookup_canonical_only_matches_canonical_not_alias():
    """lookup_canonical is for downstream code with the canonical already in
    hand. It must NOT resolve aliases — that's canonicalize()'s job."""
    e = lookup_canonical("pushdowns")
    assert e is None


# ── _norm_key ────────────────────────────────────────────────────────────────

def test_norm_key_handles_edge_cases():
    assert _norm_key("") == ""
    assert _norm_key(None) == ""
    assert _norm_key("  ") == ""
    assert _norm_key("Bench-Press") == "bench press"
    assert _norm_key("BENCH  PRESS") == "bench press"


# ── prod history/PR split regression pins (Danny 2026-07-02) ─────────────────

def test_split_variants_collapse_to_one_canonical():
    """Regression pins for the prod splits that fragmented history/PRs."""
    assert canonicalize("Dip")[0] == canonicalize("Dips")[0] == "Dip"
    assert canonicalize("Face Pull")[0] == canonicalize("Face Pulls")[0] == "Face Pull"
    assert canonicalize("Upright Row")[0] == canonicalize("Upright Rows")[0] == "Upright Row"
    assert canonicalize("Cable Shrug")[0] == canonicalize("Cable Shrugs")[0] == "Shrug"


def test_straight_arm_pulldown_spaced_variants_resolve():
    for v in ["Straight-Arm Pulldown", "Straight Arm Pulldown",
              "straight arm pull down", "stiff arm pull down",
              "straight arm pulldowns"]:
        assert canonicalize(v)[0] == "Straight-Arm Pulldown", v


def test_machine_shoulder_press_is_distinct_entry_not_overhead_press():
    """All machine phrasings collapse to ONE machine canonical — and it is NOT
    merged into barbell Overhead Press (different movement, different load
    curve; merging would corrupt PRs)."""
    for v in ["Shoulder Press Machine", "shoulder press machine",
              "Machine Shoulder Press", "seated shoulder press machine",
              "plate loaded shoulder press", "smith machine shoulder press"]:
        canon, e = canonicalize(v)
        assert canon == "Machine Shoulder Press", v
        assert e is not None and e["equipment"] == "machine"
    assert canonicalize("Machine Shoulder Press")[0] != canonicalize("Overhead Press")[0]


def test_barbell_shoulder_press_still_maps_to_overhead_press():
    """Guard: the bare 'shoulder press' alias must stay on Overhead Press."""
    assert canonicalize("shoulder press")[0] == "Overhead Press"
    assert canonicalize("Shoulder Press")[0] == "Overhead Press"
