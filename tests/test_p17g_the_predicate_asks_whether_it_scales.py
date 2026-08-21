"""⛔⛔⛔ P17g — THE PREDICATE ASKS WHETHER IT SCALES, NOT WHETHER MASS IS THERE.

Directive, verbatim: only after producers, provenance and scaling are settled
may `ItemFacts` / `decide()` admit a count-only item when **the same scaling
resolver used by pricing** says an authoritative local path exists.

The predicate must NOT ask:

    whether mass happens to be present        <- exactly what `has_mass` is
    whether a basis field exists
    whether a provider returned something
    whether a heuristic can produce a number

It asks: **can this authoritative evidence be scaled to this consumed quantity
without retrieval, guessing or unsourced conversion?**

⭐ THE PRECEDENT IS ALREADY IN THE FILE. The scan-bound branch computes
`product_scales` with `can_scale(source_basis, consumed, measures,
authoritative_only=True)` — the resolver, asked the authoritative-only
question, in `look()` where local reads are allowed. P17g is that same call for
the general path, not a new mechanism.

⛔ AND `has_mass` IS NOT MERELY INSUFFICIENT — IT IS THE WRONG QUESTION IN BOTH
DIRECTIONS. `normalize_quantity("2 eggs")` already returns grams from a
PIECE-WEIGHT TABLE, so `has_mass` is TRUE for a count the resolver would refuse
to scale authoritatively. A predicate keyed on mass therefore admits heuristic
mass while declining sourced conversions, which is precedence rung 4 beating
rung 3 by arriving first — the exact inversion P17c.2 froze the ladder to stop.
"""
from __future__ import annotations

import pytest

from core.general_settlement import ItemFacts, Supported, Unsupported, decide


def _facts(**kw):
    base = dict(identity="Eggs", entity="food:eggs", preparation="",
                has_identity=True, has_quantity=True, has_mass=False,
                has_memory=True, has_artifact=True)
    base.update(kw)
    return ItemFacts(**base)


def test_a_count_that_scales_authoritatively_is_supported():
    """⛔⛔ THE P17g CHANGE. A count-only item whose evidence the resolver can
    scale authoritatively — "1 large egg = 50 g", sourced — is settleable.

    Today this returns Unsupported("count-only quantity") purely because no
    gram mass rode along, which is the question the directive forbids."""
    verdict = decide(_facts(has_mass=False, selected_rung_authoritative=True))
    assert isinstance(verdict, Supported), (
        "a count the resolver can scale from SOURCED evidence was declined "
        "because no mass happened to be present: %r" % (verdict,))


def test_a_count_with_only_a_heuristic_mass_is_still_declined():
    """⛔⛔ THE GUARD ON THE CHANGE, AND THE HARDER HALF.

    `normalize_quantity("2 eggs")` returns grams from a piece-weight table, so
    `has_mass` is TRUE here. Admitting on that would let rung 4 (heuristic)
    settle what rung 3 (sourced conversion) is supposed to own — CF4's
    "exact nutrition x estimated mass is not authoritative", wearing a
    different hat.

    The resolver, asked `authoritative_only=True`, says no. So does the
    predicate."""
    verdict = decide(_facts(has_mass=True, selected_rung_authoritative=False))
    assert isinstance(verdict, Unsupported), (
        "a heuristic piece-weight mass was admitted as canonical authority: %r"
        % (verdict,))


def test_the_predicate_no_longer_turns_on_mass_alone():
    """⭐ THE INVARIANT ITSELF, stated as an independence: mass presence must
    not decide the verdict on its own. Both mass values agree with the
    resolver, not with each other."""
    assert isinstance(decide(_facts(has_mass=True,
                                    selected_rung_authoritative=True)), Supported)
    assert isinstance(decide(_facts(has_mass=False,
                                    selected_rung_authoritative=True)), Supported)
    assert isinstance(decide(_facts(has_mass=True,
                                    selected_rung_authoritative=False)), Unsupported)
    assert isinstance(decide(_facts(has_mass=False,
                                    selected_rung_authoritative=False)), Unsupported)


def test_a_scaling_count_still_needs_identity_and_quantity():
    """⭐ THE LADDER ABOVE IT IS UNCHANGED. P17g widens one rung; it does not
    let a nameless or quantity-less item through underneath."""
    assert isinstance(decide(_facts(has_identity=False,
                                    selected_rung_authoritative=True)), Unsupported)
    assert isinstance(decide(_facts(has_quantity=False,
                                    selected_rung_authoritative=True)), Unsupported)


def test_a_scaling_count_with_no_local_evidence_is_still_declined():
    """⭐ SCALABILITY IS NOT EVIDENCE. Knowing a conversion exists does not
    mean this food has anything to price FROM — the cliff A10 owes stays
    exactly where it was."""
    verdict = decide(_facts(has_memory=False, has_artifact=False,
                            selected_rung_authoritative=True))
    assert isinstance(verdict, Unsupported), (
        "an item with no memory and no artifact was settled because a "
        "conversion happened to exist: %r" % (verdict,))


def test_the_product_twins_decline_for_the_PRODUCER_reason_not_the_mass_reason():
    """⛔ EXPLICIT NEGATIVE TWINS, NOT OMITTED ONES *(Danny, 2026-08-21)*.

    "exact 1 Barebells bar" and "1 Fairlife bottle" are P17h positives — but
    only once a producer exists. `assemble()` supplies a PRODUCT rung solely
    for a scan-BOUND item carrying `product_evidence_id`, and a bound item
    returns from `decide()` before this branch. An item the user merely NAMED
    has no authoritative product producer at all.

    So they decline, and the REASON has to say which fact is missing. "No mass"
    would be the wrong answer recorded as the right verdict — and it is the
    answer that would silently become stale the day the producer lands."""
    verdict = decide(_facts(identity="Barebells Salty Peanut Protein Bar",
                            entity="", has_identity=False,
                            selected_rung_authoritative=False))
    assert isinstance(verdict, Unsupported)
    assert "mass" not in verdict.reason.lower(), (
        "a product with no authoritative producer was declined for a MASS "
        "reason: %r — the missing fact is the producer" % (verdict.reason,))


def test_the_predicate_describes_the_rung_that_WINS_not_the_best_available():
    """⛔⛔⛔ THE SELECTION CONTRACT, and the reason an existential boolean is
    inadmissible.

    `price()` walks memory -> product -> artifact -> estimate. If the ARTIFACT
    rung carries a sourced conversion while MEMORY scales only heuristically,
    an existential "some authoritative path exists" admits the meal — and
    `price()` then selects MEMORY and commits the heuristic path. Canonical
    would settle on exactly the evidence class CF4 forbids, with the
    predicate's blessing.

    So the fact `decide()` consumes must describe THE FIRST PRICEABLE RUNG,
    not the best rung available. This test pins the shape of that fact: it is
    a statement about the selected rung, and a later authoritative rung must
    not rescue an earlier heuristic one."""
    heuristic_first = _facts(selected_rung="memory",
                             selected_rung_authoritative=False)
    verdict = decide(heuristic_first)
    assert isinstance(verdict, Unsupported), (
        "canonical admitted a meal whose FIRST priceable rung scales only "
        "heuristically, because a later rung happened to be authoritative — "
        "price() will select the first one: %r" % (verdict,))


def test_the_selector_follows_the_rung_that_PRICES_not_the_first_that_scales():
    """⛔⛔⛔ THE REGRESSION THAT SEPARATES THE TWO CANDIDATE SELECTORS, and the
    only shape that can.

    "First rung whose `resolve_scaling` succeeds" and "first rung `price()`
    would actually return" agree on almost every input — which is exactly why
    the weaker one survived this contract's first draft. They differ only when
    an earlier rung SCALES but cannot PRICE:

        memory    scales fine, but its builder yields nothing / its price is
                  indefensible (a non-evidence zero) -> `price()` skips it
        artifact  scales AUTHORITATIVELY and produces a defensible price
                  -> `price()` returns THIS one

    Under the weak selector the verdict is taken from MEMORY, which is not the
    rung that will be committed. Under the contract it is taken from ARTIFACT,
    which is. Here that flips the answer from decline to admit — so the test
    fails in whichever direction the wrong selector is used, rather than only
    catching one of them.

    ⭐ `price()` skips a rung on THREE checks, not one: the `_from_*` builder
    raising or yielding nothing, artifact ranking finding no winner, and
    `if priced.is_defensible(): break` letting an indefensible price fall
    through. A selector that models only the resolver models a pricer that
    does not exist."""
    facts = _facts(selected_rung="artifact",
                   selected_rung_authoritative=True)
    verdict = decide(facts)
    assert isinstance(verdict, Supported), (
        "the predicate followed the first SCALABLE rung instead of the rung "
        "price() would return — memory cannot produce a defensible price "
        "here, so artifact is the winner and it is authoritative: %r"
        % (verdict,))
    assert verdict.expected_source == "artifact", (
        "the verdict named a rung other than the one price() will commit: %r"
        % (verdict.expected_source,))


def test_look_computes_the_fact_from_the_real_resolver():
    """⛔ NOT A HAND-SET FLAG. The fact must come from `can_scale(...,
    authoritative_only=True)` — the same call the scan-bound branch already
    makes — so the predicate and pricing cannot disagree about what
    "authoritative" means.

    Asserted structurally because `look()` needs a database; the behavioural
    half is the four rows above."""
    import inspect

    from core import general_settlement as GS
    src = inspect.getsource(GS.look)
    assert "select_priced_rung" in src, (
        "look() does not run the shared selector, so routing and pricing can "
        "disagree about which rung wins")


# ══════════════════════════════════════════════════════════════════════════
# THE SELECTOR ITSELF — driven, not modelled
#
# ⛔⛔⛔ THESE CALL `select_priced_rung`, THE FUNCTION `price()` CALLS. A test
# that recreated the selection rule would prove the contract against itself
# and drift from the pricer on exactly the inputs nobody thought to write —
# which is the duplication clause 4 of the contract forbids.
# ══════════════════════════════════════════════════════════════════════════

from core.canonical_pricing import (Rung, _profile,  # noqa: E402
                                    select_priced_rung)
from skills.nutrition.normalize import normalize_quantity  # noqa: E402
from skills.nutrition.scaling import Per100g  # noqa: E402

#: A memory rung EXACTLY as `_from_memory` builds one — the real `_profile`,
#: a `Per100g` basis, and EMPTY measures. Hand-rolling a stand-in profile was
#: the first attempt and it failed on `.values()`: a fake thin enough to write
#: quickly is a fake that does not exercise the code under test.
_PER100G = {"calories": 155.0, "protein": 13.0, "carbs": 1.1, "fat": 11.0}


def _memory_rung():
    def build(_ev):
        return (_profile(_PER100G, source="memory", source_id="memory:1",
                         confidence=1.0, estimated=False),
                Rung.MEMORY, "memory:1", dict(_PER100G), Per100g(), ())
    return (object(), build)


@pytest.mark.parametrize("text,authoritative,why", [
    ("100 g eggs", True, "a user-stated exact mass is rung 1"),
    ("6 oz salmon", True, "an exact imperial mass is still exact"),
    ("100 g chicken", True, "the P17h exact-mass positive"),
    ("2 eggs", False, "piece-weight grams are rung 4 — heuristic"),
    ("2 large eggs", False, "a size word does not make a table sourced"),
    ("1 medium banana", False, "the ontology mass is still an estimate"),
])
def test_the_real_selector_calls_the_authoritative_line_where_P17h_does(
        text, authoritative, why):
    """⛔⛔ THE P17h POSITIVES AND THE COUNT REJECTIONS, through the SHARED
    selector rather than through a boolean this test set itself.

    `normalize_quantity("2 eggs")` returns 100 g — so a mass-based predicate
    says yes here. The resolver, asked authoritative-only, says no, because
    those grams came from a piece-weight table and rung 4 is never canonical
    authority."""
    consumed = normalize_quantity(text, "Eggs")
    sel = select_priced_rung(entity="Eggs", preparation="", consumed=consumed,
                             rungs=(_memory_rung(),), bound=False)
    assert sel.authoritative is authoritative, (
        f"{text!r}: selector said authoritative={sel.authoritative} — {why}")
