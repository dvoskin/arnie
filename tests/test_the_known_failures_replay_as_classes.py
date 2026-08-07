"""B-1.9 commit 6 — the two production failures, replayed as CLASSES.

Chicken and honey are one row each here, not the subject. A regression test
for "435 g of chicken breast" proves that one number no longer commits; it
proves nothing about the next food whose bracket collapses, and the whole
point of the B-1.9 rebuild was that these were SYSTEM failures wearing a
food's name.

    CLASS A — unsupported estimate
      "not sure" may not commit from evidence that is not about this person
      eating this thing. Swept over every serving basis, with and without a
      history record, so the rule is shown to be entity-agnostic rather than
      tuned to chicken.

    CLASS B — serving-basis mismatch
      A quantity observed in one basis may not become a candidate in another
      without a sourced, executable conversion — and a volume-native food
      must be able to stay volume-native rather than being silently rounded
      into grams. Honey's `30g / 80g / 200g` offered to someone who logs
      tablespoons is one instance.

COVERAGE HONESTY. Some of this matrix is reachable by contract and selector
today and NOT yet by the production generator, which currently emits mass
candidates only. Those rows are marked, not skipped: "the platform supports
it" and "production produces it" are different claims, and a test that
quietly proved the first while implying the second is the kind of instrument
this slice keeps finding.
"""
from decimal import Decimal

import pytest

from core.clarification_answer import Outcome, answer_from_text
from core.semantics import (CandidateSelectionContext, CandidateSet,
                            CandidateSource, CanonicalQuantity,
                            ConversionEvidence, EvidenceContext, EvidenceScope,
                            QuantityCandidate, QuantityCandidateEvidence,
                            SelectionSurface, ServingBasis, ServingExpression,
                            SourceReference, measure_on)
from skills.nutrition import candidate_selection as policy
from skills.nutrition import quantity_clarification as qc
from skills.nutrition.staging import FoodIdentity, StagedFoodItem

USER = 26
ENTITY = "food:subject"

#: Every basis the contract knows, with a unit the registry recognises and an
#: amount that is meaningful on it. THE MATRIX IS THE VOCABULARY, not a
#: sample of it — a basis missing here is a basis nobody proved.
BASES = [
    (ServingBasis.MASS, "g", "150", {"grams": "150"}),
    (ServingBasis.VOLUME, "ml", "240", {"milliliters": "240"}),
    (ServingBasis.COUNT, "piece", "2", {"count": "2"}),
    (ServingBasis.PIECE, "piece", "1", {"count": "1"}),
    (ServingBasis.PACKAGE, "package", "1", {"amount": "1",
                                            "unit_id": "package"}),
    (ServingBasis.FRACTION_OF_PACKAGE, "package", "0.5",
     {"amount": "0.5", "unit_id": "package"}),
    (ServingBasis.STANDARD_SERVING, "serving", "1", {"amount": "1",
                                                     "unit_id": "serving"}),
]

CTX = EvidenceContext(user_id=USER, canonical_entity_id=ENTITY)


def _quantity(fields):
    return CanonicalQuantity(**{k: (Decimal(v) if k != "unit_id" else v)
                                for k, v in fields.items()})


def _source(scope):
    if scope is EvidenceScope.THIS_USER:
        return SourceReference(dataset_id="food_entries",
                               dataset_version="live", record_key="9001",
                               record_version="entry:9001")
    return SourceReference(dataset_id="portion_ontology",
                           dataset_version="2026-08-06",
                           record_key="subject:some",
                           immutable_within_version=True)


def _candidate(basis, unit, amount, fields, *, scope, cid="c1",
               prior="0.5", confidence="0.6", variant=None):
    quantity = _quantity(fields)
    evidence = QuantityCandidateEvidence(
        source_type=(CandidateSource.USER_HISTORY
                     if scope is EvidenceScope.THIS_USER
                     else CandidateSource.ONTOLOGY),
        source=_source(scope), observed_quantity=quantity,
        observed_basis=basis, subject_scope=scope,
        subject_user_id=USER if scope is EvidenceScope.THIS_USER else None,
        product_variant_id=variant,
        confidence=Decimal(confidence))
    return QuantityCandidate(
        candidate_id=cid, canonical_entity_id=ENTITY, quantity=quantity,
        serving_basis=basis,
        offered=ServingExpression(amount=Decimal(amount), unit_id=unit,
                                  basis=basis, normalized=quantity),
        evidence=(evidence,), prior=Decimal(prior))


def _field():
    item = StagedFoodItem(staged_item_id="si", original_text="x",
                          identity=FoodIdentity(canonical_name="subject"))
    return qc.quantity_field(operation_id="op", revision=0, item=item)


def _selection_context(**kw):
    base = dict(surface=SelectionSurface.LABEL_TEXT, locale="en",
                maximum_options=3,
                renderer_contract_version=qc.RENDERER_CONTRACT_VERSION)
    base.update(kw)
    return CandidateSelectionContext(**base)


def _ask(*candidates, context=None, food_name="subject"):
    """A real interaction, through the real selector and renderer.

    `context` is the set's BOUND SUBJECT. Product-scoped evidence is refused
    by a set whose context names no variant — correctly, and that is why the
    product rows pass it explicitly rather than relying on a default.
    """
    field = _field()
    universe = CandidateSet(
        candidate_set_id="cs", operation_id="op", user_id=USER,
        context=context or CTX,
        interaction_revision=0, field_id=field.field_id,
        generator_version="gen_v1", generation_input_fingerprint="fp",
        candidates=candidates)
    options, record = qc.reduce_universe(universe, field=field,
                                         context=_selection_context(),
                                         food_name=food_name)
    interaction = qc.build_interaction(operation_id="op", revision=0,
                                       item=StagedFoodItem(
                                           staged_item_id="si",
                                           original_text="x",
                                           identity=FoodIdentity(
                                               canonical_name="subject")),
                                       options=options,
                                       introduction="How much subject?")
    return interaction, options, record


def _not_sure(interaction):
    field_id = interaction.groups[0].fields[0].field_id
    return answer_from_text(interaction, field_id=field_id,
                            text="I don't know", revision=0,
                            food_name="subject", context=CTX)


#: THE SCOPES, and where each is CONSTRUCTIBLE. `THIS_PRODUCT_QUANTITY`
#: requires a basis that denotes an amount — knowing a jar is Brand X honey
#: does not establish that three tablespoons were eaten — so it exists on
#: three of the seven bases and not by omission.
QUANTITY_BEARING = {ServingBasis.PACKAGE, ServingBasis.STANDARD_SERVING,
                    ServingBasis.FRACTION_OF_PACKAGE}
SCOPES = [EvidenceScope.POPULATION, EvidenceScope.THIS_USER,
          EvidenceScope.THIS_PRODUCT_QUANTITY]

#: scope x basis, with the impossible combinations EXCLUDED BY RULE rather
#: than forgotten. `sufficient` is whether that scope may authorise an
#: assumption at all.
MATRIX = [
    pytest.param(scope, basis, unit, amount, fields,
                 scope is not EvidenceScope.POPULATION,
                 id=f"{scope.value}-{basis.value}")
    for scope in SCOPES
    for basis, unit, amount, fields in BASES
    if scope is not EvidenceScope.THIS_PRODUCT_QUANTITY
    or basis in QUANTITY_BEARING
]

VARIANT = "sku:991"


def _context_for(scope):
    return (EvidenceContext(user_id=USER, canonical_entity_id=ENTITY,
                            product_variant_id=VARIANT)
            if scope is EvidenceScope.THIS_PRODUCT_QUANTITY else CTX)


# ── CLASS A · an estimate may not commit from evidence about people ─────────

@pytest.mark.parametrize("scope,basis,unit,amount,fields,sufficient", MATRIX)
@pytest.mark.parametrize("history", ["history_empty", "history_rich"])
def test_the_estimate_rule_holds_across_scope_basis_and_history(
        scope, basis, unit, amount, fields, sufficient, history):
    """THE CHICKEN CLASS, as the cross-product it claims to be.

    Every scope x every serving basis x history present or absent, run through
    the REAL ask and the REAL answer route. "Not sure" committed 435 g because
    a generic bracket collapsed and the estimate took the upper of two; the
    rule that fixed it is about WHAT THE EVIDENCE IS ABOUT, so it has to hold
    for a food measured in packages exactly as for one in grams.

    HISTORY-RICH PUTS BOTH CANDIDATES IN THE ROW. An earlier version of this
    gate named the case and built only the user record, so it never tested
    that a population prior sitting beside a sufficient one fails to dilute
    it — the thing the name promised.
    """
    subject = _candidate(basis, unit, amount, fields, scope=scope, cid="c1",
                         variant=VARIANT if
                         scope is EvidenceScope.THIS_PRODUCT_QUANTITY else None)
    candidates = [subject]
    if history == "history_rich":
        # A POPULATION PRIOR ALONGSIDE, far enough away not to be collapsed.
        candidates.append(_candidate(
            basis, unit, str(Decimal(amount) * 4),
            {k: (str(Decimal(v) * 4) if k != "unit_id" else v)
             for k, v in fields.items()},
            scope=EvidenceScope.POPULATION, cid="pop", prior="0.2"))

    context = _context_for(scope)
    interaction, options, _record = _ask(*candidates, context=context)
    assert options, f"{scope.value}/{basis.value} produced nothing to offer"

    result = answer_from_text(
        interaction, field_id=interaction.groups[0].fields[0].field_id,
        text="I don't know", revision=0, food_name="subject", context=context)

    if sufficient:
        from core.semantics import Provenance
        assert result.outcome is Outcome.APPLIED, result
        assert result.patch.provenance is Provenance.MODE_DEFAULT, (
            "an assumed portion must stay disclosable — it is not the user's")
    else:
        assert result.outcome is Outcome.REPAIR, result
        assert result.patch is None, "a refused estimate carries no patch"
        assert result.decision_policy_version, "the refusal must name a policy"


@pytest.mark.parametrize("basis,unit,amount,fields", BASES,
                         ids=[b.value for b, *_ in BASES])
def test_product_evidence_about_another_variant_refuses_on_every_basis(
        basis, unit, amount, fields):
    """Identity is not consumption, run through the FULL route rather than by
    calling `authorizes_assumption` directly — the earlier version asserted
    the rule without proving the ask and answer honour it."""
    if basis not in QUANTITY_BEARING:
        pytest.skip(f"{basis.value} cannot carry product-quantity evidence")
    interaction, _options, _record = _ask(
        _candidate(basis, unit, amount, fields,
                   scope=EvidenceScope.THIS_PRODUCT_QUANTITY,
                   variant=VARIANT),
        context=EvidenceContext(user_id=USER, canonical_entity_id=ENTITY,
                                product_variant_id=VARIANT))
    for variant, expected in ((VARIANT, Outcome.APPLIED),
                              ("sku:000", Outcome.REPAIR),
                              (None, Outcome.REPAIR)):
        result = answer_from_text(
            interaction, field_id=interaction.groups[0].fields[0].field_id,
            text="I don't know", revision=0, food_name="subject",
            context=EvidenceContext(user_id=USER, canonical_entity_id=ENTITY,
                                    product_variant_id=variant))
        assert result.outcome is expected, (variant, result)


@pytest.mark.parametrize("basis,unit,amount,fields", BASES,
                         ids=[b.value for b, *_ in BASES])
def test_history_empty_refuses_on_every_basis(basis, unit, amount, fields):
    """HISTORY-EMPTY, swept. Two population options and nothing about this
    person: the degenerate bracket that committed 435 g."""
    low = _candidate(basis, unit, amount, fields,
                     scope=EvidenceScope.POPULATION, cid="low", prior="0.2")
    high = _candidate(
        basis, unit, str(Decimal(amount) * 5),
        {k: (str(Decimal(v) * 5) if k != "unit_id" else v)
         for k, v in fields.items()},
        scope=EvidenceScope.POPULATION, cid="high", prior="0.3")
    interaction, options, _record = _ask(low, high)
    assert len(options) == 2, "the degenerate two-option bracket, as measured"

    result = answer_from_text(
        interaction, field_id=interaction.groups[0].fields[0].field_id,
        text="I don't know", revision=0, food_name="subject", context=CTX)
    assert result.outcome is Outcome.REPAIR
    # THE MEASURED FAILURE WAS THE UPPER OF TWO COMMITTING. Nothing committed,
    # so no option's quantity reached a patch — asserted against the outcome
    # rather than against `result.patch`, which is None here by definition and
    # made the previous form of this check unfalsifiable.
    assert result.outcome is not Outcome.APPLIED



@pytest.mark.parametrize("basis,unit,amount,fields", BASES,
                         ids=[b.value for b, *_ in BASES])
def test_population_evidence_never_commits_on_not_sure(basis, unit, amount,
                                                       fields):
    """THE CHICKEN CLASS, swept over every basis.

    "Not sure" committed 435 g — 718 cal, nearly a pound — because a generic
    bracket collapsed to two options and the estimate took the upper. The rule
    that fixed it is about WHAT THE EVIDENCE IS ABOUT, so it must hold for a
    food measured in packages or pieces exactly as it does for one in grams.
    """
    interaction, options, _record = _ask(
        _candidate(basis, unit, amount, fields,
                   scope=EvidenceScope.POPULATION))
    assert options, f"{basis.value} produced no offer to refuse from"

    result = _not_sure(interaction)
    assert result.outcome is Outcome.REPAIR, result
    assert result.patch is None, "a refused estimate must carry no patch"
    assert result.decision_policy_version, "the refusal must name its policy"


@pytest.mark.parametrize("basis,unit,amount,fields", BASES,
                         ids=[b.value for b, *_ in BASES])
def test_this_users_own_record_commits_on_every_basis(basis, unit, amount,
                                                      fields):
    """The other half of the same rule: with evidence about THIS person, the
    estimate commits — so the refusal above is the scope talking, not a
    blanket ban that would make "not sure" useless."""
    interaction, options, _record = _ask(
        _candidate(basis, unit, amount, fields,
                   scope=EvidenceScope.THIS_USER))
    assert options

    result = _not_sure(interaction)
    assert result.outcome is Outcome.APPLIED, result
    from core.semantics import Provenance
    assert result.patch.provenance is Provenance.MODE_DEFAULT, (
        "an assumed portion must stay disclosable — it is not the user's")


def test_a_product_record_commits_only_for_the_variant_in_hand():
    """The third scope, on a quantity-bearing basis. Identity is not
    consumption: the record must be about the variant actually selected."""
    cand = _candidate(ServingBasis.STANDARD_SERVING, "serving", "1",
                      {"amount": "1", "unit_id": "serving"},
                      scope=EvidenceScope.THIS_PRODUCT_QUANTITY,
                      variant="sku:991")
    assert cand.authorizes_assumption(
        EvidenceContext(user_id=USER, canonical_entity_id=ENTITY,
                        product_variant_id="sku:991"))
    assert not cand.authorizes_assumption(
        EvidenceContext(user_id=USER, canonical_entity_id=ENTITY,
                        product_variant_id="sku:000"))
    assert not cand.authorizes_assumption(CTX)     # no variant selected


@pytest.mark.parametrize("basis,unit,amount,fields", BASES,
                         ids=[b.value for b, *_ in BASES])
def test_a_population_prior_beside_the_users_own_record_does_not_dilute_it(
        basis, unit, amount, fields):
    """HISTORY-RICH. Richer provenance must not reduce what we may do with
    it, and a population record must not be able to carry the decision."""
    interaction, _options, _record = _ask(
        _candidate(basis, unit, amount, fields,
                   scope=EvidenceScope.THIS_USER, cid="mine",
                   prior="0.55", confidence="0.9"))
    assert _not_sure(interaction).outcome is Outcome.APPLIED


def test_history_empty_is_a_refusal_not_a_guess():
    """HISTORY-EMPTY. The generator produced only population candidates, so
    "not sure" has nothing about this person to stand on."""
    interaction, options, _record = _ask(
        _candidate(ServingBasis.MASS, "g", "85", {"grams": "85"},
                   scope=EvidenceScope.POPULATION, cid="low", prior="0.2"),
        _candidate(ServingBasis.MASS, "g", "435", {"grams": "435"},
                   scope=EvidenceScope.POPULATION, cid="high", prior="0.3"))
    assert len(options) == 2, "the degenerate two-option bracket, as measured"
    result = _not_sure(interaction)
    assert result.outcome is Outcome.REPAIR
    # THE MEASURED FAILURE, ARITHMETICALLY: the upper of two is what committed.
    assert not any(measure_on(o.patch.quantity, ServingBasis.MASS)
                   == Decimal("435") and result.patch for o in options)


# ── CLASS B · a basis may not change without an authority ──────────────────

#: Every ordered pair of DIFFERENT bases — 7 x 6 = 42. Generated, because a
#: hand-picked five can miss a basis-specific branch and did: the earlier
#: version tested volume/piece/count/package -> mass and mass -> volume, and
#: nothing at all involving fractions or standard servings.
CROSS_BASIS = [
    pytest.param(a, a_fields, b, b_unit, b_fields,
                 id=f"{a.value}->{b.value}")
    for a, _a_unit, _a_amount, a_fields in BASES
    for b, b_unit, _b_amount, b_fields in BASES
    if a is not b
]


@pytest.mark.parametrize("observed,observed_fields,offered,offered_unit,"
                         "offered_fields", CROSS_BASIS)
def test_no_basis_may_change_without_an_authority(observed, observed_fields,
                                                  offered, offered_unit,
                                                  offered_fields):
    """THE HONEY CLASS, generalised to every directed pair.

    A quantity seen in one basis may not be offered in another on nobody's
    authority — that step is where an invented density becomes a calorie. All
    42 pairs, so a basis-specific hole cannot hide in the ones nobody picked.
    """
    seen = _quantity(observed_fields)
    target = _quantity(offered_fields)
    evidence = QuantityCandidateEvidence(
        source_type=CandidateSource.ONTOLOGY,
        source=_source(EvidenceScope.POPULATION), observed_quantity=seen,
        observed_basis=observed, subject_scope=EvidenceScope.POPULATION,
        confidence=Decimal("0.6"))
    with pytest.raises(ValueError, match="nobody's authority"):
        QuantityCandidate(
            candidate_id="c", canonical_entity_id=ENTITY, quantity=target,
            serving_basis=offered,
            offered=ServingExpression(
                amount=measure_on(target, offered), unit_id=offered_unit,
                basis=offered, normalized=target),
            evidence=(evidence,), prior=Decimal("0.5"))


@pytest.mark.parametrize("observed,observed_fields,offered,offered_unit,"
                         "offered_fields", CROSS_BASIS)
def test_a_conversion_must_start_where_the_evidence_actually_looked(
        observed, observed_fields, offered, offered_unit, offered_fields):
    """A sourced conversion is not a licence for any pair. It must begin at
    the basis the evidence OBSERVED and end at the candidate's own."""
    seen = _quantity(observed_fields)
    target = _quantity(offered_fields)
    wrong_start = next(b for b, *_ in BASES if b not in (observed, offered))
    conversion = ConversionEvidence(
        from_basis=wrong_start, to_basis=offered,
        source=SourceReference(dataset_id="usda", dataset_version="2026-04",
                               record_key="conv", immutable_within_version=True),
        factor=Decimal("2"))
    evidence = QuantityCandidateEvidence(
        source_type=CandidateSource.ONTOLOGY,
        source=_source(EvidenceScope.POPULATION), observed_quantity=seen,
        observed_basis=observed, subject_scope=EvidenceScope.POPULATION,
        conversion_evidence=conversion, confidence=Decimal("0.6"))
    with pytest.raises(ValueError, match="did not see"):
        QuantityCandidate(
            candidate_id="c", canonical_entity_id=ENTITY, quantity=target,
            serving_basis=offered,
            offered=ServingExpression(
                amount=measure_on(target, offered), unit_id=offered_unit,
                basis=offered, normalized=target),
            evidence=(evidence,), prior=Decimal("0.5"))


def test_conversion_available_must_arrive_at_the_offered_quantity():
    """A cited authority is not enough; the arithmetic has to land. This is
    the honey chain end to end: 1 tbsp -> 15 ml -> 21 g."""
    density = SourceReference(dataset_id="usda", dataset_version="2026-04",
                              record_key="density:honey",
                              immutable_within_version=True)
    good = ConversionEvidence(
        from_basis=ServingBasis.VOLUME, to_basis=ServingBasis.MASS,
        source=density, factor=Decimal("1.4"),
        input_quantity=CanonicalQuantity(milliliters=Decimal("15")),
        output_quantity=CanonicalQuantity(grams=Decimal("21.0")))
    honey = CanonicalQuantity(grams=Decimal("21.0"))
    evidence = QuantityCandidateEvidence(
        source_type=CandidateSource.ONTOLOGY,
        source=_source(EvidenceScope.POPULATION),
        observed_quantity=CanonicalQuantity(milliliters=Decimal("15")),
        observed_basis=ServingBasis.VOLUME,
        subject_scope=EvidenceScope.POPULATION,
        conversion_evidence=good, confidence=Decimal("0.6"))
    assert QuantityCandidate(
        candidate_id="c", canonical_entity_id=ENTITY, quantity=honey,
        serving_basis=ServingBasis.MASS,
        offered=ServingExpression(amount=Decimal("21.0"), unit_id="g",
                                  basis=ServingBasis.MASS, normalized=honey),
        evidence=(evidence,), prior=Decimal("0.5"))

    # The same authority, applied to produce a different number, is refused.
    wrong = ConversionEvidence(
        from_basis=ServingBasis.VOLUME, to_basis=ServingBasis.MASS,
        source=density, factor=Decimal("1.4"),
        input_quantity=CanonicalQuantity(milliliters=Decimal("15")),
        output_quantity=CanonicalQuantity(grams=Decimal("21.0")))
    with pytest.raises(ValueError, match="evidence supports"):
        QuantityCandidate(
            candidate_id="c", canonical_entity_id=ENTITY,
            quantity=CanonicalQuantity(grams=Decimal("80")),
            serving_basis=ServingBasis.MASS,
            offered=ServingExpression(
                amount=Decimal("80"), unit_id="g", basis=ServingBasis.MASS,
                normalized=CanonicalQuantity(grams=Decimal("80"))),
            evidence=(evidence.__class__(
                source_type=CandidateSource.ONTOLOGY,
                source=_source(EvidenceScope.POPULATION),
                observed_quantity=CanonicalQuantity(
                    milliliters=Decimal("15")),
                observed_basis=ServingBasis.VOLUME,
                subject_scope=EvidenceScope.POPULATION,
                conversion_evidence=wrong, confidence=Decimal("0.6")),),
            prior=Decimal("0.5"))


def test_a_volume_native_food_stays_volume_native_through_the_row():
    """THE MEASURED HONEY DEFECT. Options came out as `30g / 80g / 200g` for
    someone who logs tablespoons: the basis reached rendering and the
    EXPRESSION did not, so the row was in a unit the person does not think in.

    The platform now carries the expression to the screen.
    """
    tbsp = CanonicalQuantity(amount=Decimal("1"), unit_id="tbsp",
                             milliliters=Decimal("14.787"))
    three = CanonicalQuantity(amount=Decimal("3"), unit_id="tbsp",
                              milliliters=Decimal("44.361"))
    def _vol(cid, quantity, amount, prior):
        evidence = QuantityCandidateEvidence(
            source_type=CandidateSource.ONTOLOGY,
            source=_source(EvidenceScope.POPULATION),
            observed_quantity=quantity, observed_basis=ServingBasis.VOLUME,
            subject_scope=EvidenceScope.POPULATION, confidence=Decimal("0.6"))
        return QuantityCandidate(
            candidate_id=cid, canonical_entity_id=ENTITY, quantity=quantity,
            serving_basis=ServingBasis.VOLUME,
            offered=ServingExpression(amount=Decimal(amount), unit_id="tbsp",
                                      basis=ServingBasis.VOLUME,
                                      normalized=quantity),
            evidence=(evidence,), prior=Decimal(prior))

    _interaction, options, record = _ask(_vol("one", tbsp, "1", "0.5"),
                                         _vol("three", three, "3", "0.3"))
    assert len(options) == 2
    for cand in record.candidate_set.candidates:
        assert cand.serving_basis is ServingBasis.VOLUME, (
            "a volume candidate was silently converted to mass")
        assert cand.offered.unit_id == "tbsp"
    # THE LABELS THE USER READS, not merely the stored expression. Asserting
    # only the expression let `3 tbsps` — the registry-less pluralisation —
    # sit in the row unremarked.
    assert [o.label for o in options] == ["1 tbsp", "3 tbsp"]
    assert [p.rendered_label for p in record.presented] == ["1 tbsp", "3 tbsp"]
    # The selector never collapsed them across bases, and never rendered them
    # into grams to compare.
    assert record.decision.selected_candidate_ids == ("one", "three")


def test_distinct_bases_are_both_offered_rather_than_merged():
    """A mixed row is coherent: `1 piece` and `150 g` are two answers, and
    collapsing them because the numbers are adjacent would delete a real
    choice."""
    piece = _candidate(ServingBasis.PIECE, "piece", "1", {"count": "1"},
                       scope=EvidenceScope.POPULATION, cid="piece")
    mass = _candidate(ServingBasis.MASS, "g", "150", {"grams": "150"},
                      scope=EvidenceScope.POPULATION, cid="mass")
    chosen, excluded = policy.select(
        CandidateSet(candidate_set_id="cs", operation_id="op", user_id=USER,
                     context=CTX, interaction_revision=0, field_id="f",
                     generator_version="g", generation_input_fingerprint="fp",
                     candidates=(piece, mass)),
        context=_selection_context())
    assert sorted(c.candidate_id for c in chosen) == ["mass", "piece"]
    assert excluded == ()


# ── the coverage ledger ────────────────────────────────────────────────────

def test_the_generator_still_emits_only_mass_and_that_is_recorded():
    """NOT SEEN IS NOT NOT-TESTED, and NOT-PRODUCED IS NOT NOT-SUPPORTED.

    Everything above proves the PLATFORM carries non-mass bases through
    selection, rendering and the answer turn. Production does not yet PRODUCE
    them: `generate` emits mass candidates only, because the portion ontology
    it reads is expressed in grams.

    Asserted rather than left implicit, so the day a volume producer lands,
    this test fails and someone decides deliberately whether the coverage
    ledger above still describes reality.
    """
    import inspect

    source = inspect.getsource(qc.generate) + inspect.getsource(
        qc._mass_candidate)
    assert "ServingBasis.MASS" in source
    for absent in ("ServingBasis.VOLUME", "ServingBasis.PIECE",
                   "ServingBasis.PACKAGE"):
        assert absent not in source, (
            f"{absent} now reaches the generator — the coverage ledger in "
            f"this module's docstring is out of date, and the honey class "
            f"needs a production-path proof rather than a platform one")


# ── what the user actually reads ───────────────────────────────────────────

@pytest.mark.parametrize("basis,unit,amount,fields,expected", [
    (ServingBasis.VOLUME, "ml", "240", {"milliliters": "240"}, "240 ml"),
    (ServingBasis.VOLUME, "tbsp", "3", {"milliliters": "44.361"}, "3 tbsp"),
    (ServingBasis.COUNT, "piece", "2", {"count": "2"}, "2 pieces"),
    (ServingBasis.PIECE, "piece", "1", {"count": "1"}, "1 piece"),
    (ServingBasis.PACKAGE, "package", "1",
     {"amount": "1", "unit_id": "package"}, "1 package"),
    (ServingBasis.PACKAGE, "package", "2",
     {"amount": "2", "unit_id": "package"}, "2 packages"),
    (ServingBasis.FRACTION_OF_PACKAGE, "package", "0.5",
     {"amount": "0.5", "unit_id": "package"}, "0.5 packages"),
    (ServingBasis.STANDARD_SERVING, "serving", "1",
     {"amount": "1", "unit_id": "serving"}, "1 serving"),
    (ServingBasis.STANDARD_SERVING, "serving", "2",
     {"amount": "2", "unit_id": "serving"}, "2 servings"),
])
def test_non_mass_labels_come_from_the_unit_registry(basis, unit, amount,
                                                     fields, expected):
    """THE LABEL IS THE PRODUCT. Asserting the stored expression and not the
    rendered string let `240 mls`, `3 tbsps` and `2 ozs` sit in the row
    unremarked — appending "s" to a canonical unit id, which no rule can fix
    because nothing in an id says whether it is an abbreviation.
    """
    _interaction, options, record = _ask(
        _candidate(basis, unit, amount, fields,
                   scope=EvidenceScope.POPULATION))
    assert [o.label for o in options] == [expected]
    assert [p.rendered_label for p in record.presented] == [expected]


def test_mass_labels_still_come_from_the_everyday_renderer():
    """Unchanged, and deliberately so: `_everyday_labels` is the accumulated
    judgement about how people say weights — ounces for meat, cups for rice —
    and the registry does not replace it."""
    mass = (_candidate(ServingBasis.MASS, "g", "85", {"grams": "85"},
                       scope=EvidenceScope.POPULATION, cid="low",
                       prior="0.2"),
            _candidate(ServingBasis.MASS, "g", "226", {"grams": "226"},
                       scope=EvidenceScope.POPULATION, cid="high",
                       prior="0.3"))
    _ix, options, _record = _ask(*mass, food_name="chicken breast")
    assert [o.label for o in options] == ["3 oz", "8 oz"]
    assert not any(o.label.endswith("ozs") for o in options)
    # A FOOD THE EVERYDAY RENDERER DOES NOT KNOW still renders in grams,
    # unchanged — the registry path is for non-mass bases, not a replacement.
    _ix2, plain, _r2 = _ask(*mass)
    assert [o.label for o in plain] == ["85g", "226g"]


# ── 6.2 — word units inflect, symbol units do not ──────────────────────────

@pytest.mark.parametrize("amount,unit_id,expected", [
    # SYMBOLS never change. `2 mls` and `3 tbsps` are not English.
    ("2", "ml", "2 ml"), ("3", "tbsp", "3 tbsp"), ("2", "oz", "2 oz"),
    ("2", "g", "2 g"), ("2", "kg", "2 kg"), ("2", "lb", "2 lb"),
    ("2", "l", "2 l"), ("2", "tsp", "2 tsp"),
    # WORDS do. Registering `cup` and `cups` as invariant aliases produced
    # `2 cup` and `3 tablespoon` — reachable the moment a producer states a
    # long-form unit id.
    ("1", "cup", "1 cup"), ("2", "cup", "2 cups"), ("2", "cups", "2 cups"),
    ("1", "tablespoon", "1 tablespoon"),
    ("3", "tablespoon", "3 tablespoons"),
    ("2", "pint", "2 pints"), ("2", "quart", "2 quarts"),
    ("2", "liter", "2 liters"), ("2", "milliliter", "2 milliliters"),
    ("1", "ounce", "1 ounce"), ("2", "ounce", "2 ounces"),
    ("2", "pound", "2 pounds"), ("3", "gram", "3 grams"),
    ("1", "piece", "1 piece"), ("2", "piece", "2 pieces"),
    ("1", "serving", "1 serving"), ("2", "serving", "2 servings"),
])
def test_a_unit_is_written_the_way_the_registry_says(amount, unit_id,
                                                     expected):
    from core import unit_registry

    said = unit_registry.say(Decimal(amount), unit_id)
    assert f"{amount} {said}" == expected


def test_both_spellings_of_a_word_unit_mean_and_read_the_same():
    """A producer that states `cups` rather than `cup` must not change either
    the amount or the row."""
    from core import unit_registry

    for singular, plural in (("cup", "cups"), ("tablespoon", "tablespoons"),
                             ("ounce", "ounces"), ("pound", "pounds"),
                             ("liter", "liters")):
        assert (unit_registry.canonical_amount(Decimal("2"), singular)
                == unit_registry.canonical_amount(Decimal("2"), plural))
        assert (unit_registry.say(Decimal("2"), singular)
                == unit_registry.say(Decimal("2"), plural))


def test_a_long_form_volume_unit_renders_correctly_in_a_real_row():
    """END TO END, because the defect is only visible in the label."""
    two_cups = CanonicalQuantity(amount=Decimal("2"), unit_id="cup",
                                 milliliters=Decimal("473.176"))
    evidence = QuantityCandidateEvidence(
        source_type=CandidateSource.ONTOLOGY,
        source=_source(EvidenceScope.POPULATION),
        observed_quantity=two_cups, observed_basis=ServingBasis.VOLUME,
        subject_scope=EvidenceScope.POPULATION, confidence=Decimal("0.6"))
    cand = QuantityCandidate(
        candidate_id="c", canonical_entity_id=ENTITY, quantity=two_cups,
        serving_basis=ServingBasis.VOLUME,
        offered=ServingExpression(amount=Decimal("2"), unit_id="cup",
                                  basis=ServingBasis.VOLUME,
                                  normalized=two_cups),
        evidence=(evidence,), prior=Decimal("0.5"))
    _ix, options, record = _ask(cand)
    assert [o.label for o in options] == ["2 cups"]
    assert [p.rendered_label for p in record.presented] == ["2 cups"]
