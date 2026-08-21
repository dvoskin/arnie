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


#: The two P17h product twins, as the user would NAME them (no scan, no
#: `product_evidence_id`). Both are declines today and positives the day a
#: sourced PRODUCT producer lands — which is the claim the test below has to
#: prove rather than assert.
PRODUCT_TWINS = [
    ("Barebells Salty Peanut Protein Bar", "1 bar", "bar",
     {"calories": 200.0, "protein": 20.0, "carbs": 16.0, "fat": 8.0}, 55.0),
    ("Fairlife Core Power Elite", "1 bottle", "bottle",
     {"calories": 230.0, "protein": 42.0, "carbs": 8.0, "fat": 3.5}, 414.0),
]


@pytest.mark.parametrize("identity,quantity,unit,per_serving,serving_g",
                         PRODUCT_TWINS)
def test_the_product_twins_decline_because_NO_PRODUCER_EXISTS(
        identity, quantity, unit, per_serving, serving_g):
    """⛔ EXPLICIT NEGATIVE TWINS, AND THE REASON PROVEN RATHER THAN ASSERTED
    *(Danny, review of `61eaf4e`)*.

    ⛔⛔⛔ THE FIRST VERSION OF THIS TEST PASSED FOR THE WRONG REASON, and its
    shape is worth keeping as the warning. It forced `entity=""`/
    `has_identity=False`, so `decide()` returned at the IDENTITY rung — "no
    canonical identity" — and never reached the producer question at all. Its
    one assertion (`"mass" not in reason`) then held trivially, because the
    identity reason does not mention mass. It covered ONE twin, and it was
    written that way BECAUSE the honest reason contains the word "mass" ("a
    user-stated exact mass") — the assertion had been fitted to a verdict that
    answered a different question. A twin that declines at a rung above the one
    under test proves nothing about the rung under test.

    So the claim is made positively, in three steps, against the REAL selector:

        1  with the rungs `look()` actually builds, PRODUCT's evidence is
           `None` — the rung does not exist, so nothing wins and nothing is
           authoritative;
        2  the SAME identity and the SAME quantity, given a real per-serving
           PRODUCT producer, scale AUTHORITATIVELY through `direct_basis`;
        3  therefore the decline is the producer's absence, and it lifts the
           day the producer lands — not the day someone states a mass.

    Step 2 is what step 1 alone cannot say: an absence is only attributable
    when you can show the presence changing the answer."""
    from core.canonical_pricing import (ProductEvidence, _from_memory,
                                        _from_product)
    from skills.nutrition.pricing_artifact import split_identity

    entity, preparation = split_identity(identity)
    consumed = normalize_quantity(quantity, identity)

    # 1 — the rung set `look()` builds for an item the user merely NAMED.
    # `assemble()` hard-codes PRODUCT to None for anything not scan-bound.
    no_producer = select_priced_rung(
        entity=entity, preparation=preparation, consumed=consumed,
        rungs=((None, _from_memory), (None, _from_product)), bound=False)
    assert no_producer.rung is None and no_producer.priced is None, (
        "a PRODUCT rung priced this without a producer: %r" % (no_producer,))
    assert no_producer.authoritative is False

    # 2 — the same item, with the producer this slice does not yet have.
    ev = ProductEvidence(identifier=identity, per_serving=dict(per_serving),
                         serving_grams=serving_g, serving_unit=unit)
    with_producer = select_priced_rung(
        entity=entity, preparation=preparation, consumed=consumed,
        rungs=((ev, _from_product),), bound=False)
    assert with_producer.rung is Rung.PRODUCT, (
        "the per-serving producer did not win its own rung: %r"
        % (with_producer,))
    assert with_producer.authoritative is True, (
        "a count of the LABEL'S OWN unit is a direct compatible basis "
        "(precedence rung 2), not a heuristic: %r" % (with_producer,))

    # 3 — so today's verdict is a decline, and it is the SELECTED-RUNG verdict,
    # reached with identity and quantity both present. Not the identity rung.
    verdict = decide(_facts(identity=identity, entity=entity,
                            preparation=preparation, has_mass=False,
                            selected_rung="", selected_rung_authoritative=False))
    assert isinstance(verdict, Unsupported)
    assert "identity" not in verdict.reason and "quantity" not in verdict.reason, (
        "the twin declined ABOVE the rung under test — this is the vacuity the "
        "first version of this test shipped with: %r" % (verdict.reason,))
    assert "heuristically" in verdict.reason, (
        "the decline did not come from the selected-rung branch: %r"
        % (verdict.reason,))


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


def _indefensible_rung():
    """A rung that SCALES but cannot PRICE: a non-evidence zero.

    `is_defensible()` is `calories > 0 or evidence_backed`, so a zero-calorie
    profile that is not evidence-backed is exactly the case `price()` skips —
    "the estimate was zero" becomes "try the next thing", not "refuse".
    """
    zero = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}

    def build(_ev):
        return (_profile(zero, source="estimate", source_id="",
                         confidence=0.0, estimated=True),
                Rung.ESTIMATE, "", dict(zero), Per100g(), ())
    return (object(), build)


def _exact_mass_rung():
    """An authoritative rung: real calories, and an exact mass will scale it."""
    def build(_ev):
        return (_profile(_PER100G, source="artifact", source_id="a:1",
                         confidence=1.0, estimated=False),
                Rung.ARTIFACT, "a:1", dict(_PER100G), Per100g(), ())
    return (object(), build)


def test_the_selector_skips_a_rung_that_scales_but_cannot_price():
    """⛔⛔⛔ THE REQUIRED REGRESSION, AT THE SELECTOR — an earlier candidate
    that scales but produces no DEFENSIBLE price, and a later authoritative
    rung that does.

    This is the only shape that separates "first rung whose `resolve_scaling`
    succeeds" from "first rung `price()` would return". The zero rung scales
    perfectly well — an exact mass meets a Per100g basis — so a
    resolver-only selector stops there and reports ITS verdict. `price()`
    does not stop there: an indefensible price is a failed rung and the ladder
    continues.

    Found by mutation: making `is_defensible()` unconditional changed
    behaviour and NOTHING failed, because the earlier version of this
    regression asserted over hand-built `ItemFacts` instead of driving the
    real selector. A regression that recreates the rule cannot detect the rule
    changing."""
    consumed = normalize_quantity("100 g eggs", "Eggs")
    sel = select_priced_rung(
        entity="Eggs", preparation="", consumed=consumed,
        rungs=(_indefensible_rung(), _exact_mass_rung()), bound=False)

    assert sel.rung is Rung.ARTIFACT, (
        "the selector stopped at a rung that scales but cannot price — "
        "price() would have continued to the artifact: got %r" % (sel.rung,))
    assert sel.authoritative is True, (
        "the winning rung's resolution was not reported as authoritative")


@pytest.mark.asyncio
@pytest.mark.parametrize("rung,authoritative", [
    (Rung.ARTIFACT, True),
    (Rung.MEMORY, False),
    (None, False),
])
async def test_the_selectors_result_REACHES_the_facts(monkeypatch, rung,
                                                      authoritative):
    """⛔⛔⛔ THE DATA FLOW, DRIVEN — not an AST that accepts any `.authoritative`
    anywhere in the function *(Danny, review of `61eaf4e`)*.

    Two earlier versions of this proof were both too weak, in the same
    direction, and the second one is the interesting failure:

        v1  asserted `select_priced_rung` appears in the source. Mutation P7
            replaced the assignment with `= True` and left the call standing:
            green while routing had stopped consuming the pricer entirely.
        v2  asserted that SOME `<name>.authoritative` is read somewhere in
            `look()`. That still passes for `_ = _sel.authoritative` followed
            by a hard-coded constant — it proves a READ happened, never that
            the value reaches the `ItemFacts` `decide()` will read.

    A structural test can say the wire exists. Only a driven one can say the
    current arrives. So the selector is replaced by a SENTINEL and the returned
    facts are read: both fields, over three selections, including a `None` rung
    (which is what a selector that found no winner returns, and the case a
    hard-coded `""`/`False` would pass by accident on its own).

    ⭐ THE THREE CASES ARE NOT REDUNDANT. A constant `True` fails case 2, a
    constant `False` fails case 1, a hard-coded `"memory"` fails cases 1 and 3
    — no single frozen value survives the set."""
    import core.canonical_pricing as CP
    import core.general_settlement as GS
    from core.canonical_pricing import RungSelection

    sentinel = RungSelection(priced=object(), rung=rung,
                             authoritative=authoritative)
    calls = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(CP, "select_priced_rung", _spy)

    facts = await GS.look(None, user_id=1,
                          item={"food_name": "Eggs", "quantity": "2 eggs"})

    assert calls, "look() never called the shared selector"
    assert facts.selected_rung == (rung.value if rung is not None else ""), (
        "the selector chose %r but the facts say %r — the verdict would name a "
        "rung the pricer is not going to commit"
        % (rung, facts.selected_rung))
    assert facts.selected_rung_authoritative is authoritative, (
        "the selector said authoritative=%r but the facts say %r — `decide()` "
        "is reading a number routing invented"
        % (authoritative, facts.selected_rung_authoritative))


# ══════════════════════════════════════════════════════════════════════════
# THE OTHER HALF OF "ONE SELECTION RULE, CONSUMED TWICE" — the PRICER
#
# ⛔⛔⛔ `decide()` consuming the rule is not the contract; BOTH consuming it
# is. `price()` held a `RungSelection` carrying `.authoritative` and returned
# `.priced` without ever looking at it, so a promise made at routing had no
# enforcement at the only place that writes.
# ══════════════════════════════════════════════════════════════════════════


def _memory_evidence():
    from core.canonical_pricing import MemoryEvidence
    return MemoryEvidence(per100g=dict(_PER100G), source_id="memory:1",
                          confidence=1.0)


def test_the_pricer_refuses_a_rung_the_predicate_would_never_have_blessed():
    """⛔⛔⛔ `price()` MUST ENFORCE WHAT `decide()` PROMISED *(Danny, review of
    `61eaf4e`)*.

    The two run the SAME selector but not over the same rungs: `look()` builds
    `(memory, None, artifact)` while `assemble()` supplies
    `(memory, product, artifact, ESTIMATE)`. So routing can admit on an
    authoritative artifact and the pricer — artifact ranking having found no
    winner on its own query — can fall through to the ESTIMATE rung and commit
    a heuristic price under an admission that promised authority. Nothing
    checked. `selection.authoritative` existed and was discarded one line
    before the return.

    ⭐ THE REQUIREMENT IS THE CALLER'S, NOT A GLOBAL RULE. Refusing every
    non-authoritative price everywhere would refuse most ordinary meals — a
    heuristic estimate is a legitimate price, it is simply not a canonical
    SETTLEMENT. So `price()` takes the requirement from whoever is calling,
    exactly as it already takes `bound`, and general settlement — the one
    caller that has published an authoritative promise — passes it.

    ⚠ AND IT REFUSES BEFORE ANY WRITE. `PricingRefused` propagates by design
    (A8); a divergence therefore costs a refused turn, never a wrong row."""
    from core.canonical_pricing import PricingRefused, price

    consumed = normalize_quantity("2 eggs", "Eggs")

    # UNCHANGED for every other caller: a heuristic piece weight still prices.
    lenient = price(entity="Eggs", consumed=consumed, memory=_memory_evidence())
    assert lenient.calories > 0, (
        "the ordinary pricing path changed — this requirement is the caller's, "
        "not a new global rule")

    with pytest.raises(PricingRefused) as caught:
        price(entity="Eggs", consumed=consumed, memory=_memory_evidence(),
              require_authoritative=True)
    assert "authoritativ" in str(caught.value).lower(), (
        "the refusal did not name the requirement it enforced: %r"
        % (str(caught.value),))


def test_the_pricer_still_returns_an_authoritative_rung_under_the_requirement():
    """⛔ THE NEGATIVE INVARIANT'S TWIN. A requirement that refused everything
    would satisfy the test above and delete canonical settlement — so the
    exact-mass positive has to keep pricing with the requirement ON."""
    from core.canonical_pricing import price

    priced = price(entity="Eggs", consumed=normalize_quantity("100 g eggs",
                                                              "Eggs"),
                   memory=_memory_evidence(), require_authoritative=True)
    assert priced.calories > 0
    assert priced.rung is Rung.MEMORY


@pytest.mark.asyncio
async def test_general_settlement_asks_the_pricer_to_enforce_the_promise(
        monkeypatch):
    """⛔⛔ THE CALLER SIDE, DRIVEN. `price()` gaining the ability to enforce is
    worth nothing if the one caller that made the promise never asks for it —
    the "a function that is called is not a function whose result is used"
    trap, one layer out.

    So this drives the real `_price` and reads the keyword it passed."""
    from types import SimpleNamespace

    import core.canonical_pricing as CP
    import core.canonical_pricing_inputs as CPI
    from core.general_settlement import GeneralSettlementOwner

    seen = {}

    async def _assemble(*_a, **_k):
        return {"memory": None, "product": None, "artifact": None,
                "estimate": None}

    def _price(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(calories=1.0, rung=Rung.MEMORY)

    monkeypatch.setattr(CPI, "assemble", _assemble)
    monkeypatch.setattr(CP, "price", _price)

    await GeneralSettlementOwner()._price(
        None, user=SimpleNamespace(id=1),
        item={"food_name": "Eggs", "quantity": "100 g"})

    assert seen.get("require_authoritative") is True, (
        "general settlement priced without asking the pricer to enforce the "
        "authority its own predicate promised: %r" % (sorted(seen),))
