"""TWO SIGNATURES, AND WHAT BREAKS IF THEY COLLAPSE INTO ONE.

    ADMISSION      "is this legitimate evidence for this food identity?"
    WINNER REVIEW  "is this the representative row we want pricing to choose?"

⛔ THE FAILURE THESE GATES EXIST TO PREVENT is using `REJECT` to fix a ranking
problem. "Mushrooms, shiitake, cooked" wins over white mushrooms and is the
wrong representative — and rejecting it would write down that shiitake is not
a mushroom. A durable semantic falsehood, kept forever, to work around a
ranker the next fix will change anyway.

So `ADMIT + HELD` is a real state: valid evidence whose selection as the
canonical winner rests on a policy known to be provisional. It is the same
distinction `UNRESOLVED` draws one layer up — "we have not decided" is not
"we decided no".
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager

import pytest

from scripts import baseline_signatures as bs
from scripts import winner_review as wr
from skills.nutrition import pricing_artifact as art


@contextmanager
def _canonical_regime():
    """The regime Phase 0 freezes against: V2 structural, preference OFF."""
    keys = ("NUTRITION_ACCURACY_V2", "NUTRITION_AS_EATEN_PREFERENCE")
    previous = {k: os.environ.get(k) for k in keys}
    os.environ["NUTRITION_ACCURACY_V2"] = "1"
    os.environ["NUTRITION_AS_EATEN_PREFERENCE"] = ""
    try:
        import importlib
        import core.food_intelligence as fi
        importlib.reload(fi)
        assert fi._nutrition_accuracy_v2() is True
        assert fi._as_eaten_preference() is False
        yield fi
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import importlib
        import core.food_intelligence as fi
        importlib.reload(fi)


def _canonical_winners(fi):
    from core.canonical_pricing import _ranker_query
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    doc = json.loads(art.ARTIFACT_PATH.read_text())
    out = {}
    for key, entry in (doc.get("entries") or {}).items():
        candidates = list(entry.get("candidates") or ())
        if not candidates:
            continue
        entity, _, preparation = key.partition("|")
        winner, _conf = fi.best_candidate(_ranker_query(entity, preparation),
                                          candidates)
        if winner is not None:
            out[key] = f"usda:{winner.get('fdc_id')}"
    return out


# ── the two states are genuinely independent ──────────────────────────────

def test_a_row_can_be_admitted_evidence_and_a_held_winner():
    """⭐ THE STATE THE STANDING RULE EXISTS FOR."""
    held = dict((identity, cause) for identity, _e, cause in wr.held())
    assert "mushrooms|" in held and "rice|" in held and "salmon|" in held
    # ⭐ RE-FILED: these three were held under AS_EATEN_REWORK, a blocker that
    # could never resolve them — the preference was never going to touch
    # shiitake-vs-white. A hold whose cause cannot unblock it is a hold nobody
    # can act on.
    for identity in ("mushrooms|", "rice|", "salmon|"):
        assert held[identity] == wr.SPECIALTY_BEATS_GENERIC_CAUSE

    reviewed = wr.by_identity()
    for identity, _evidence, _cause, note in wr.RANKING_DEFECTS:
        _e, status, _c, _n = reviewed[identity]
        assert status == wr.HELD
    # ...and none of them is rejected evidence
    signatures = bs.by_pair()
    for identity, evidence, _cause, _note in wr.RANKING_DEFECTS:
        assert signatures.get((identity, evidence), ("",))[0] != bs.REJECT


def test_no_rejected_row_may_hold_any_winner_state():
    """⛔ The two signatures may not contradict. A row identity review has
    ruled is NOT this food cannot be the row pricing chooses, in any state."""
    signatures = dict(bs.by_pair())
    for identity, evidence, disposition, *_ in wr.ADMISSION_DECISIONS:
        signatures[(identity, evidence)] = (disposition, "")
    reviewed = wr.by_identity()
    for (identity, evidence), (disposition, *_rest) in signatures.items():
        if disposition == bs.REJECT and identity in reviewed:
            assert reviewed[identity][0] != evidence, (
                f"{identity}: {evidence} is REJECTED evidence and is carrying "
                f"a winner state")


def test_every_hold_names_a_policy_gap_from_a_closed_vocabulary():
    """A hold must say WHAT unblocks it, or it expires by being forgotten
    rather than by being fixed."""
    assert wr.held(), "nothing is held — re-measure before trusting this"
    for identity, _evidence, cause in wr.held():
        assert cause in wr.BLOCKING_CAUSES, f"{identity}: {cause!r}"


def test_a_signed_winner_carries_no_blocking_cause():
    reviewed = wr.by_identity()
    for identity, (_e, status, cause, note) in reviewed.items():
        if status == wr.SIGNED:
            assert cause == "", f"{identity} is SIGNED but names a blocker"
        assert note.strip(), f"{identity}: {status} with an empty reason"


# ── the review must track the regime it was made under ────────────────────

def test_the_review_covers_the_regime_phase_zero_freezes_against():
    """⭐ THE REVIEW IS CHECKED AGAINST THE RANKER, NEVER DERIVED FROM IT. A
    sheet that silently tracked whatever the ranker currently does would
    record agreement rather than a decision — so a moved winner must FAIL."""
    with _canonical_regime() as fi:
        winners = _canonical_winners(fi)
    # ⭐ NOW ZERO. `potato|` was the one outstanding failure — its winner was
    # the part-of-food row this round rejected — and the artifact rebuild
    # cleared it. The population is complete and reconciled: every identity
    # the ranker produces carries a winner state, and no rejected row holds
    # one. THIS IS THE FREEZE CONDITION.
    assert wr.accounting(winners) == (), wr.accounting(winners)
    assert len(winners) == 27 == len(wr.by_identity())


def test_a_moved_winner_is_caught_rather_than_absorbed():
    """ANTI-VACUITY: the accounting must go red when the ranker moves."""
    with _canonical_regime() as fi:
        winners = _canonical_winners(fi)
    winners["tofu|"] = "usda:999999"
    failures = wr.accounting(winners)
    assert any("tofu|" in f and "moved under the review" in f
               for f in failures), failures


def test_an_unreviewed_identity_is_caught():
    with _canonical_regime() as fi:
        winners = _canonical_winners(fi)
    winners["kiwi|"] = "usda:1"
    assert any("kiwi|" in f and "no winner-review state" in f
               for f in wr.accounting(winners))


# ── the frozen baseline is not amended ────────────────────────────────────

def test_this_round_does_not_amend_the_frozen_seventy_seven():
    """⭐ The Phase 1.5 population was signed, gated and closed behind
    `baseline_migration`. Editing it now would make the record stop saying
    what was signed — the same class of error as amending a pushed
    migration. Phase 0.9's decisions are ADDITIVE and attributable."""
    assert bs.EXPECTED_POPULATION == 77
    assert len(bs.SIGNATURES) == 77
    frozen = set(bs.by_pair())
    for identity, evidence, *_ in wr.ADMISSION_DECISIONS:
        assert (identity, evidence) not in frozen, (
            f"{identity}/{evidence} is inside the frozen population; a "
            f"decision about it belongs to that round, not this one")


def test_the_undecided_cooked_axis_is_derived_not_hand_listed():
    """⭐ THE HAND-LIST WAS THREE TIMES TOO SHORT. Holding the rows whose kcal
    gap a reviewer happened to notice is not the same as holding the rows a
    missing policy actually decided. Derived: a BARE identity, on an UNDECIDED
    axis, whose ladder carries BOTH raw and cooked rows."""
    import json

    from skills.nutrition import cooking_state
    from core.food_intelligence import (COOKED_AXIS_UNDECIDED,
                                        cooked_preference_state)

    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    doc = json.loads(art.ARTIFACT_PATH.read_text())

    consequential = set()
    for key, entry in (doc.get("entries") or {}).items():
        entity, _, preparation = key.partition("|")
        if preparation:
            continue
        if cooked_preference_state(entity) != COOKED_AXIS_UNDECIDED:
            continue
        states = [cooking_state.classify(c.get("description", "")).value
                  for c in (entry.get("candidates") or ())]
        if "raw" in states and "cooked" in states:
            consequential.add(key)

    # ⭐ FIVE, NOT SIX — AND `potato|` LEFT FOR A REASON WORTH RECORDING.
    # Removing "Potatoes, raw, SKIN" took the only RAW row off that ladder, so
    # the identity no longer has a raw-vs-cooked choice for a missing policy
    # to make. An admission fix closed a ranking ambiguity as a side effect;
    # `potato|` is still HELD, but now for representativeness rather than for
    # an undecided axis.
    assert consequential == {"asparagus|", "broccoli|", "cauliflower|",
                             "mackerel|", "tilapia|"}, consequential

    held = {identity for identity, _e, cause in wr.held()
            if cause == wr.COOKING_YIELD_COVERAGE}
    assert held == consequential, held
    assert wr.by_identity()["potato|"][1] == wr.HELD
    assert (wr.by_identity()["potato|"][2]
            == wr.SPECIALTY_BEATS_GENERIC_CAUSE)


def test_an_undecided_axis_with_one_state_available_is_not_held():
    """The rule is not "undecided => hold". `banana|`, `egg|`, `mushrooms|`,
    `oats|`, `rice|` and `tofu|` are all undecided and carry ONE state on the
    ladder, so the missing policy had nothing to decide between. Holding them
    would make the signal mean nothing."""
    held = {identity for identity, _e, cause in wr.held()
            if cause == wr.COOKING_YIELD_COVERAGE}
    for identity in ("banana|", "egg|", "mushrooms|", "oats|", "rice|", "tofu|"):
        assert identity not in held, identity


def test_absence_is_distinguishable_from_a_yield_of_one():
    """⭐ THE ROOT FIX. `cooking_yield` returns 1.0 for BOTH 'does not
    concentrate' and 'never heard of it'. `cooking_yield_known` returns None
    for the second, which is what lets the policy layer tell them apart."""
    from core.portions import cooking_yield, cooking_yield_known
    from core.food_intelligence import (COOKED_AXIS_UNDECIDED, COOKED_PREFERRED,
                                        cooked_preference_state)

    assert cooking_yield("mackerel") == 1.0
    assert cooking_yield_known("mackerel") is None
    assert cooked_preference_state("mackerel") == COOKED_AXIS_UNDECIDED

    assert cooking_yield_known("salmon") == 1.20
    assert cooked_preference_state("salmon") == COOKED_PREFERRED

    # ⭐⭐ AND THE TABLE IS NOT MISSING TWO ENTRIES — it already carries
    # "fish". The QUERY is what never contains that substring, which is why
    # adding "mackerel" and "tilapia" would fix two examples and leave cod,
    # halibut and trout to reproduce it.
    assert cooking_yield_known("fish") == 1.20
    assert cooking_yield_known("fish, mackerel, atlantic") == 1.20
    for unheard in ("cod", "halibut", "trout", "sardine"):
        assert cooking_yield_known(unheard) is None, unheard


def test_the_signed_winners_are_the_only_ones_that_may_freeze():
    signed = dict(wr.frozen_winners())
    held = {identity for identity, _e, _c in wr.held()}
    assert not (set(signed) & held), "an identity is both signed and held"
    assert len(signed) + len(held) == len(wr.by_identity())
    assert len(signed) == 13 and len(held) == 14
