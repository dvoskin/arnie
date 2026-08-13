"""V2 IS TWO BEHAVIOURS OF DIFFERENT MATURITY, AND ONLY ONE IS FREEZABLE.

Phase 0 freezes the ranking regime the baseline is signed against. Signing 27
winners under a selector already known to decide dimensions it never
evaluates would write a transitional mistake into the record permanently, so
`as_eaten_over_trimmed` is split out of V2 and defaults OFF.

⭐ THE STRUCTURAL HALF ONLY EVER DECLINES A WRONG ROW OR REACHES A RIGHT ONE.
Folded morphology, the identity/coverage gate, cross-food refusal,
cooked-by-default, the typed artifact refusal. Measured over 600 real
production food names, V2 refuses 15 rows v1 seats — and at least 8 are
flatly the wrong food: asparagus for "boiled egg", shrimp for "squash", tofu
for "fried lamb", portabella for "grilled shrimp". Those refusals fall to an
honest estimate. On the committed artifact it reaches 27 of 27 against v1's
24.

⭐⭐ THE PREFERENCE HALF IS A ±0.4 TIE-BREAK, AND A TIE-BREAK CAN ONLY DECIDE
A NEAR-TIE. Of the six winners V2 moves, five are decided by this term alone
with every other term within 0.16 — so the row it seats differs from the
runner-up in dimensions the rule never looked at:

    beef|fried      knuckle      -> striploin lean+fat   +123 kcal  (CUT)
    beef|grilled    ribeye filet -> shoulder steak        -22 kcal  (CUT)
    beef|roasted    NZ ribs      -> chuck eye roast       +44 kcal  (CUT)
    chicken|fried   meat only    -> meat+skin, BATTER     +70 kcal  (COATING)
    chicken|roasted meat only    -> meat and skin         +56 kcal  (trim only)

Only the last isolates its variable. These are cut choices wearing a trim
rule's clothes: a rule named `as_eaten_over_trimmed` must not decide knuckle
vs striploin, or meat-only vs battered, unless cut and coating are separately
modelled. Until they are, it rides its own flag and its own canary.

⭐⭐⭐ AND THE SPLIT RESTORED A HUMAN SIGNATURE. `beef|roasted` under the
preference seats chuck eye roast, UNREVIEWED; without it, `usda:173089` — the
row a reviewer actually signed. A signature that applies under one policy and
not another is a signature that has not been kept.
"""
from __future__ import annotations

import importlib
import json
import os
from contextlib import contextmanager

import pytest

from skills.nutrition import pricing_artifact as art

#: ⚠ HISTORY, NOT EXPECTATION. These are the five winners the ORIGINAL ±0.4
#: term moved, four of them by cut or coating. The reworked preference moves
#: only `chicken|roasted` — see
#: `test_the_reworked_preference_moves_one_winner_not_five`. Kept as the
#: record of what the defect did, so a regression back to it is recognisable.
PREFERENCE_MOVES_BEFORE_THE_REWORK = {
    "beef|fried": (178.0, 301.0),
    "beef|grilled": (208.0, 186.0),
    "beef|roasted": (197.0, 241.0),
    "chicken|fried": (219.0, 289.0),
    "chicken|roasted": (167.0, 223.0),
}


@contextmanager
def _regime(v2: bool, as_eaten: bool):
    """Set both flags and PROVE they took effect before measuring."""
    keys = ("NUTRITION_ACCURACY_V2", "NUTRITION_AS_EATEN_PREFERENCE")
    previous = {k: os.environ.get(k) for k in keys}
    os.environ["NUTRITION_ACCURACY_V2"] = "1" if v2 else ""
    os.environ["NUTRITION_AS_EATEN_PREFERENCE"] = "1" if as_eaten else ""
    try:
        import core.food_intelligence as fi
        importlib.reload(fi)
        assert fi._nutrition_accuracy_v2() is v2
        assert fi._as_eaten_preference() is as_eaten
        yield fi
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import core.food_intelligence as fi
        importlib.reload(fi)


def _entries():
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    doc = json.loads(art.ARTIFACT_PATH.read_text())
    return {k: v for k, v in (doc.get("entries") or {}).items()
            if (v.get("candidates") or ())}


def _winners(fi):
    from core.canonical_pricing import _ranker_query
    out = {}
    for key, entry in _entries().items():
        entity, _, preparation = key.partition("|")
        out[key] = fi.best_candidate(_ranker_query(entity, preparation),
                                     list(entry.get("candidates") or ()))[0]
    return out


def _kcal(winner):
    return None if not winner else (winner.get("per100g") or {}).get("calories")


# ── the split itself ──────────────────────────────────────────────────────

def test_the_preference_is_off_by_default_even_with_v2_on():
    """⭐ THE WHOLE POINT. Turning V2 on must NOT drag the tie-break in."""
    previous = os.environ.get("NUTRITION_AS_EATEN_PREFERENCE")
    os.environ.pop("NUTRITION_AS_EATEN_PREFERENCE", None)
    try:
        with _regime(v2=True, as_eaten=False) as fi:
            assert fi._nutrition_accuracy_v2() is True
            assert fi._as_eaten_preference() is False
    finally:
        if previous is not None:
            os.environ["NUTRITION_AS_EATEN_PREFERENCE"] = previous


def test_the_preference_has_its_own_allowlist_not_v2s():
    """Two canaries, independently steerable — otherwise the split is
    cosmetic and the preference still ships wherever V2 does."""
    from skills.nutrition import v2_gate
    previous = {k: os.environ.get(k) for k in
                ("NUTRITION_ACCURACY_V2", "NUTRITION_ACCURACY_V2_ALLOWLIST",
                 "NUTRITION_AS_EATEN_PREFERENCE",
                 "NUTRITION_AS_EATEN_PREFERENCE_ALLOWLIST")}
    try:
        os.environ["NUTRITION_ACCURACY_V2"] = ""
        os.environ["NUTRITION_ACCURACY_V2_ALLOWLIST"] = "26"
        os.environ["NUTRITION_AS_EATEN_PREFERENCE"] = ""
        os.environ["NUTRITION_AS_EATEN_PREFERENCE_ALLOWLIST"] = ""
        with v2_gate.for_user(26):
            assert v2_gate.v2_active() is True
            assert v2_gate.as_eaten_active() is False, (
                "user 26 is on V2 and must NOT thereby be on the preference")
            assert v2_gate.ranking_policy_version() == "rank_v2"

        os.environ["NUTRITION_AS_EATEN_PREFERENCE_ALLOWLIST"] = "26"
        with v2_gate.for_user(26):
            assert v2_gate.as_eaten_active() is True
            assert v2_gate.ranking_policy_version() == "rank_v2+as_eaten"
        with v2_gate.for_user(99):
            assert v2_gate.as_eaten_active() is False
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_the_regime_is_recorded_not_assumed():
    """"Which policy picked this row" is the question the mode-divergence
    finding showed nobody could answer. It is now answerable."""
    from skills.nutrition import v2_gate
    for v2, as_eaten, expected in [(False, False, "rank_v1"),
                                   (True, False, "rank_v2"),
                                   (True, True, "rank_v2+as_eaten"),
                                   (False, True, "rank_v1")]:
        with _regime(v2=v2, as_eaten=as_eaten):
            assert v2_gate.ranking_policy_version() == expected, (
                f"v2={v2} as_eaten={as_eaten}")


# ── what each half actually buys ──────────────────────────────────────────

def test_the_structural_half_alone_reaches_every_committed_identity():
    """⭐ THE REASON TO PROMOTE IT. 27 of 27, with no preference term."""
    with _regime(v2=True, as_eaten=False) as fi:
        winners = _winners(fi)
    unreachable = sorted(k for k, w in winners.items() if w is None)
    assert unreachable == [], unreachable
    assert len(winners) == 27


def test_the_structural_half_is_unaffected_by_the_preference_flag():
    """⭐ THE SPLIT, RESTATED FOR THE REWORKED PREFERENCE. With the preference
    OFF, every winner must be the structural regime's own choice — and the
    four rows the OLD term moved by cut or coating must now be identical in
    both modes, because the rework cannot reach them at all."""
    with _regime(v2=True, as_eaten=False) as fi:
        safe = _winners(fi)
    with _regime(v2=True, as_eaten=True) as fi:
        full = _winners(fi)

    for identity in ("beef|fried", "beef|grilled", "beef|roasted",
                     "chicken|fried"):
        assert (safe[identity].get("fdc_id") == full[identity].get("fdc_id")), (
            f"{identity} still moves under the preference — it differs in CUT "
            f"or COATING and the rework must not be able to decide it")
        assert identity in PREFERENCE_MOVES_BEFORE_THE_REWORK

    moved = {k for k in safe
             if (safe[k] or {}).get("fdc_id") != (full[k] or {}).get("fdc_id")}
    assert moved == {"chicken|roasted"}, moved


def test_cooked_by_default_is_structural_and_survives_the_split():
    """⭐ THE ONE DIVERGENCE THAT WAS NEVER THE PREFERENCE'S. `salmon|` moves
    raw -> cooked on `cooked_by_default`, decided by +1.160 of ordinary
    scoring with the preference contributing exactly 0.0. Splitting the
    preference out must not cost it."""
    with _regime(v2=True, as_eaten=False) as fi:
        winners = _winners(fi)
    salmon = winners["salmon|"]
    assert "cooked" in str(salmon.get("description", "")).lower()
    assert float(_kcal(salmon)) == 231.0
    assert "salmon|" not in PREFERENCE_MOVES_BEFORE_THE_REWORK


def test_beef_roasted_keeps_its_signature_in_BOTH_regimes_now():
    """⭐⭐⭐ THE SPLIT RESTORED THIS SIGNATURE; THE REWORK KEEPS IT UNDER THE
    PREFERENCE TOO. Under the ORIGINAL ±0.4 term `beef|roasted` seated chuck
    eye roast — unreviewed — because the term was deciding a CUT. Now the
    reviewer's row holds whether the preference is on or off, which is what a
    signature is supposed to mean."""
    from scripts import baseline_signatures as bs
    signed = bs.by_pair()

    with _regime(v2=True, as_eaten=False) as fi:
        safe = _winners(fi)["beef|roasted"]
    with _regime(v2=True, as_eaten=True) as fi:
        full = _winners(fi)["beef|roasted"]

    assert str(safe.get("fdc_id")) == "173089"
    assert str(full.get("fdc_id")) == "173089"
    assert signed[("beef|roasted", "usda:173089")][0] == bs.ADMIT


def test_the_preference_still_works_when_it_is_asked_for():
    """The flag must not be a way to delete the behaviour by neglect. It is
    parked for a canary, not retired."""
    with _regime(v2=True, as_eaten=True) as fi:
        winners = _winners(fi)
    assert float(_kcal(winners["chicken|roasted"])) == 223.0
    assert "meat and skin" in str(
        winners["chicken|roasted"].get("description", "")).lower()


# ── 3. the reworked preference: comparability, not a bigger number ────────

def test_the_preference_may_only_decide_its_own_dimension():
    """⭐ THE REWORK. A ±0.4 tie-break decided CUT and COATING because a
    tie-break can only overturn a near-tie. The preference now applies AFTER
    ranking and only between rows identical except in skin/trim — so a
    differing cut blocks it STRUCTURALLY, with no cut vocabulary anywhere."""
    from skills.nutrition.preference_dimensions import comparable, residue

    # the ONE comparison the rule was written to make
    assert comparable("Chicken, roasting, meat only, cooked, roasted",
                      "Chicken, roasting, meat and skin, cooked, roasted")

    # ...and the four it was silently making instead
    blocked = [
        ("Beef, New Zealand, imported, knuckle, cooked, fast fried",
         "Beef, New Zealand, imported, striploin, separable lean and fat, "
         "cooked, fast fried"),
        ('Beef, ribeye filet, boneless, separable lean only, trimmed to 0" '
         'fat, choice, cooked, grilled',
         'Beef, shoulder steak, boneless, separable lean and fat, trimmed to '
         '0" fat, choice, cooked, grilled'),
        ("Chicken, broilers or fryers, meat only, cooked, fried",
         "Chicken, broilers or fryers, meat and skin, cooked, fried, batter"),
    ]
    for one, other in blocked:
        assert not comparable(one, other), (one, other)
        assert residue(one) != residue(other)


def test_a_batter_blocks_the_skin_preference():
    """Batter introduces ANOTHER COMPONENT. Skin being present alongside it
    must not carry the coating in on skin's authority."""
    from skills.nutrition.preference_dimensions import comparable, residue
    plain = "Chicken, broilers or fryers, meat only, cooked, fried"
    battered = "Chicken, broilers or fryers, meat and skin, cooked, fried, batter"
    assert not comparable(plain, battered)
    assert "batter" in (residue(battered) - residue(plain))


def test_the_reworked_preference_moves_one_winner_not_five():
    """⭐⭐ MEASURED. The old term moved 5 winners, 4 of them by cut or
    coating. The reworked one moves exactly the trim comparison."""
    with _regime(v2=True, as_eaten=False) as fi:
        safe = _winners(fi)
    with _regime(v2=True, as_eaten=True) as fi:
        reworked = _winners(fi)

    moved = {k for k in safe
             if (safe[k] or {}).get("fdc_id") != (reworked[k] or {}).get("fdc_id")}
    assert moved == {"chicken|roasted"}, moved
    assert float(_kcal(reworked["chicken|roasted"])) == 223.0
    assert "meat and skin" in str(
        reworked["chicken|roasted"].get("description", "")).lower()

    # the four cut/coating cases stay exactly where the safe regime put them
    for identity in ("beef|fried", "beef|grilled", "beef|roasted",
                     "chicken|fried"):
        assert (safe[identity].get("fdc_id")
                == reworked[identity].get("fdc_id")), identity


def test_the_refinement_cannot_reach_outside_the_candidate_set():
    """It exchanges a winner for a SIBLING, never invents one."""
    from skills.nutrition.preference_dimensions import prefer_as_eaten
    winner = {"fdc_id": "1", "description": "Chicken, meat only, cooked"}
    others = [{"fdc_id": "2", "description": "Beef, meat and skin, cooked"}]
    assert prefer_as_eaten(winner, others) is winner
    assert prefer_as_eaten(winner, []) is winner
    assert prefer_as_eaten(None, others) is None
