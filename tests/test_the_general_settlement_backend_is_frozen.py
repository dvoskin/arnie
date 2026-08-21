"""⛔⛔ THE GENERAL-SETTLEMENT BACKEND IS FROZEN *(Danny, 2026-08-17)*.

Backend hardening for the general canonical settlement owner is CLOSED. A1-A12
are built, gated, mutation-proven, dual-engine, and verified in production on
BOTH settlement branches. What comes next is COVERAGE work — oils, materiality,
branded, non-English — and coverage widens by landing EVIDENCE, never by
loosening this backend.

⭐ WHAT THIS FILE ADDS THAT THE A-GATES DO NOT. Each A-criterion already has its
own test, and copying them here would be redundant. What no test asserted is
that **the SET is closed**:

    the frozen CONSTANTS keep their values   — a change is a directive change,
                                               not an implementation detail
    the frozen GATES still exist             — the cheapest way to defeat an
                                               invariant is to delete the test
                                               that names it, and nothing was
                                               watching for that
    the coverage ladder keeps its ORDER      — each A-gate pins one rung; none
                                               pinned the SEQUENCE, and the
                                               sequence is the contract

⚠ A NAME-ONLY MANIFEST WOULD BE VACUOUS, which is the failure this repository
keeps finding in its own instruments. So the gates are IMPORTED and asserted
callable rather than grepped, and every constant is pinned BY VALUE with the
consequence of changing it written next to it.

⭐ THIS FILE IS NOT A VETO. Changing a frozen value is allowed — it just has to
be a decision someone made on purpose, in the directive, with this file edited
in the same commit. That is the whole difference between a freeze and a drift.
"""
from __future__ import annotations

import importlib

import pytest

from core.general_settlement import (DUPLICATE_WINDOW_SEC, ItemFacts,
                                     LOCALLY_EVIDENCED, Supported, Unsupported,
                                     decide, meal_identity, meal_surface)


# ══ the frozen constants ════════════════════════════════════════════════════

def test_estimate_is_not_locally_evidenced():
    """⛔ ESTIMATE IS DELIBERATELY ABSENT. `assemble()` retrieves nothing, so a
    food in neither artifact nor memory is WORSE off canonically than on the
    legacy path, which would have found a live USDA row. Adding "estimate" here
    would make the coverage number look better and the meals worse."""
    assert LOCALLY_EVIDENCED == ("memory", "artifact")


def test_the_duplicate_window_is_legacys_hour():
    """⛔ 60 MINUTES, MATCHING `claim_processed_turn`. A12 moved WHO decides what
    a duplicate is, deliberately not WHAT is decided. Changing this number
    changes a user-visible invariant on both branches at once."""
    assert DUPLICATE_WINDOW_SEC == 3600.0


def test_the_meal_identity_is_the_message_and_nothing_else():
    """⛔ NEVER THE TURN ID, NEVER THE MODEL'S PLAN (A12). The turn id absorbs a
    redelivery and nothing else; a plan-derived key is only as stable as the
    model. Both were live defects."""
    assert meal_surface(" 100G  of White   Rice ") == "100g of white rice"
    # Same message, different turn -> one identity.
    assert meal_identity(26, source_text="100g of white rice",
                         source_turn_id="ios:A") == \
           meal_identity(26, source_text="100G OF WHITE RICE",
                         source_turn_id="ios:B")
    # Different user -> never one identity, whatever the words.
    assert meal_identity(26, source_text="x", source_turn_id="t") != \
           meal_identity(27, source_text="x", source_turn_id="t")


def test_the_native_food_policy_version_is_distinguishable_from_the_ledgers():
    """⛔ NOT `food_policy_v1`. `core.food_ledger.POLICY_VERSION` is already
    that string, and both ride the SAME log line for one turn — so a shared
    identifier means `policy=` cannot be read as evidence that the native stage
    ran, which is the one question it exists to answer."""
    from core.food_ledger import POLICY_VERSION as LEDGER
    from core.turns.stages.food import FoodValidationStage

    assert FoodValidationStage.POLICY_VERSION == "food_policy_native_v1"
    assert FoodValidationStage.POLICY_VERSION != LEDGER


# ══ the frozen ladder, in order ═════════════════════════════════════════════

def _facts(**over):
    base = dict(identity="chicken", entity="chicken", preparation="",
                has_identity=True, has_quantity=True, has_mass=True,
                has_memory=False, has_artifact=False)
    base.update(over)
    return ItemFacts(**base)


#: The ladder, top to bottom. Each row is (facts, expected verdict marker).
#: ⭐ THE ORDER IS THE CONTRACT. Every A-gate pins ONE rung; none pinned that
#: identity is checked before quantity, quantity before mass, mass before
#: evidence, and memory before artifact. A predicate that asked about evidence
#: first would return `Supported` for a meal no rung can price — which is
#: exactly the production defect A11's mass branch was added to close ("I had a
#: corn on the cob": a memory row, an estimate, no gram mass, and
#: `PricingRefused`). P17g keeps that rung and sharpens its question.
#: ⛔⛔⛔ RUNG 3 CHANGED IN P17g, DELIBERATELY AND IN THE SAME COMMIT.
#:
#: It was `has_mass=False -> "count-only quantity"`: canonical declined when no
#: gram mass rode along. That asked the wrong question in BOTH directions —
#: `normalize_quantity("2 eggs")` returns 100 g from a PIECE-WEIGHT TABLE, so
#: `has_mass` was TRUE for a count no rung can scale authoritatively, and
#: canonical settled it by scaling exact-looking nutrition with an invented
#: mass. CF4's forbidden shape, at the general rung.
#:
#: It is now `selected_rung_authoritative=False`: the rung `price()` would
#: actually return — after builder, resolver AND defensibility — must scale by
#: a user-stated exact mass, a directly compatible basis, or a sourced
#: conversion. ⭐ THE SELECTED rung, not any rung: an existential test would
#: let the artifact's sourced conversion bless a commit memory actually made.
#:
#: ⚠ THIS IS A COVERAGE REDUCTION on today's producers, and it is intended.
#: `_from_memory` declares `Per100g()` with EMPTY measures, so no count-only
#: item can scale authoritatively until the sourced-`ConversionEvidence`
#: producer slice lands. The fixed 40% threshold does NOT move — the measured
#: result changes, never the goalpost.
LADDER = [
    (_facts(has_identity=False, has_memory=True, has_artifact=True,
            selected_rung_authoritative=True),
     "no canonical identity"),
    (_facts(has_quantity=False, has_memory=True, has_artifact=True,
            selected_rung_authoritative=True),
     "no stated quantity"),
    (_facts(selected_rung_authoritative=False, has_memory=True,
            has_artifact=True),
     "scales only heuristically"),
    (_facts(has_memory=True, has_artifact=True, selected_rung="memory",
            selected_rung_authoritative=True), "memory"),
    (_facts(has_memory=False, has_artifact=True, selected_rung="artifact",
            selected_rung_authoritative=True), "artifact"),
    (_facts(selected_rung_authoritative=True), "no local evidence"),
]


@pytest.mark.parametrize("facts,marker", LADDER,
                         ids=[m for _, m in LADDER])
def test_the_coverage_ladder_keeps_its_order(facts, marker):
    verdict = decide(facts)
    if marker in ("memory", "artifact"):
        assert isinstance(verdict, Supported), \
            f"expected Supported({marker}), got {verdict}"
        assert verdict.expected_source == marker
    else:
        assert isinstance(verdict, Unsupported), \
            f"expected Unsupported({marker}), got {verdict}"
        assert marker in verdict.reason, \
            f"the decline reason changed: {verdict.reason!r}"


def test_memory_outranks_a_present_artifact_and_the_top_rung_is_named():
    """The one ordering that decides a PRICE rather than a route: with both
    present, MEMORY answers. `LOCALLY_EVIDENCED` states the ladder; this proves
    `decide` walks it in that order."""
    verdict = decide(_facts(has_memory=True, has_artifact=True,
                            selected_rung="memory",
                            selected_rung_authoritative=True))
    assert verdict.expected_source == LOCALLY_EVIDENCED[0] == "memory"


# ══ the frozen gates — deleting one must fail ═══════════════════════════════

#: Every invariant this backend is frozen at, and the test that enforces it.
#:
#: ⚠ THE CHEAPEST WAY TO DEFEAT AN INVARIANT IS TO DELETE ITS TEST, and until
#: now nothing watched for that. A rename is fine — rename it here in the same
#: commit, which is the point: the edit becomes visible.
FROZEN_GATES = {
    "A1  one owner, and legacy unreachable when supported":
        ("tests.test_the_general_settlement_owner",
         "test_a1_the_owner_is_the_only_settlement_the_stage_invokes_when_supported"),
    "A2  the owner imports nothing from the legacy executor":
        ("tests.test_the_general_settlement_owner",
         "test_a2_the_owner_imports_nothing_from_the_legacy_executor"),
    "A2  pricing is synchronous, so nothing can retrieve":
        ("tests.test_the_general_settlement_owner",
         "test_a2_pricing_is_synchronous_so_nothing_can_retrieve"),
    "A6  provenance names the rung that actually decided":
        ("tests.test_the_general_settlement_owner",
         "test_a6_memory_decides_and_says_memory"),
    "A8  the owner does not catch PricingRefused":
        ("tests.test_the_general_settlement_owner",
         "test_a8_the_owner_does_not_catch_pricing_refused"),
    "A8  settlement is never wrapped in an except at the seam":
        ("tests.test_the_general_settlement_owner",
         "test_a8_the_native_stage_does_not_catch_around_settlement"),
    "A11 one unsupported item declines the whole meal":
        ("tests.test_the_general_settlement_owner",
         "test_a11_one_unsupported_item_declines_the_whole_meal"),
    "A11 a count-only quantity is unsupported even with evidence":
        ("tests.test_the_general_settlement_owner",
         "test_a11_a_count_only_quantity_is_unsupported_even_with_evidence"),
    "A11 the cohort fails closed when unset":
        ("tests.test_the_general_settlement_owner",
         "test_the_cohort_fails_closed"),
    "A12 a retyped identical message settles once":
        ("tests.test_canonical_owns_what_a_duplicate_is",
         "test_the_same_message_retyped_settles_once"),
    "A12 the same meal after the window is a new occurrence":
        ("tests.test_canonical_owns_what_a_duplicate_is",
         "test_the_same_meal_after_the_window_is_a_new_occurrence"),
    "A12 both owners answer a duplicate identically":
        ("tests.test_canonical_owns_what_a_duplicate_is",
         "test_the_user_cannot_tell_which_owner_refused_the_duplicate"),
    "the duplicate never wears the coordinator's failure floor":
        ("tests.test_the_duplicate_reply_is_not_the_failure_floor",
         "test_a_duplicate_is_never_answered_with_a_recovery_bubble"),
}


@pytest.mark.parametrize("invariant", sorted(FROZEN_GATES))
def test_every_frozen_invariant_still_has_a_live_gate(invariant):
    module_name, test_name = FROZEN_GATES[invariant]
    module = importlib.import_module(module_name)
    gate = getattr(module, test_name, None)
    assert callable(gate), (
        f"the gate for {invariant!r} is gone: "
        f"{module_name}.{test_name} is not importable. Either restore it or, if "
        f"it was deliberately renamed, update FROZEN_GATES in the same commit.")


def test_the_manifest_is_not_empty_and_covers_every_criterion():
    """⭐ ANTI-VACUITY. A manifest that lost its entries would pass every
    assertion above by having nothing to check — the same shape as the fixture
    that skipped silently for three runs."""
    assert len(FROZEN_GATES) >= 13
    for tag in ("A1", "A2", "A6", "A8", "A11", "A12"):
        assert any(k.startswith(tag) for k in FROZEN_GATES), \
            f"{tag} lost its entry in the freeze manifest"
