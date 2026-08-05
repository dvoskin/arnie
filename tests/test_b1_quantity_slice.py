"""B-1: one item, one mass-quantity field — the first authoritative slice.

What is measured here, and why each one is load-bearing:

  * THE PREDICATE DECLINES BY DEFAULT. Every clause is a thing B-1 has not
    built. A decline costs nothing (the turn stays legacy, exactly as today);
    a wrong claim strands a meal mid-clarification.
  * OPTIONS COME FROM EVIDENCE, not from tiers. The bracket offered is the one
    the ontology already computed to decide the question was worth asking.
  * NO NEAR-DUPLICATES. `4.8 / 5.0 / 5.2` was three chips carrying one answer.
  * CHIP AND TYPED CONVERGE on one patch type, differing only in provenance —
    a tap is not the user's own figure (C14, and the 2026-08-04 disclosure
    defect).
  * STALE, FOREIGN AND INVALID ANSWERS FAIL CLOSED. A tap on last turn's chip
    addresses a field this interaction does not have; it is refused, never
    applied to whatever looks closest.
  * TERMINAL OWNERSHIP (C10). Once the operation exists there is no path back
    to legacy — not on a cancelled rollout, not on an unparseable answer.
"""
from decimal import Decimal

import pytest

from core.clarification_answer import Outcome, answer_from_chip, answer_from_text
from core.semantics import (CandidateSource, CandidateValue, Dimension,
                            Provenance, ResponseType, SetQuantity)
from skills.nutrition import quantity_clarification as qc
from skills.nutrition import quantity_rollout as qr
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

OP, REV = "chat:144:t_1", 0


def _ambiguity(field_name="estimated_mass_g", kind=AmbiguityType.CONSUMED_QUANTITY,
               score=2.0, item_id="si_1"):
    return FoodAmbiguity(ambiguity_id=f"amb_{field_name}", staged_item_id=item_id,
                         ambiguity_type=kind, field_name=field_name,
                         materiality_score=score, calorie_span=180.0)


def _item(*, name="chicken breast", stated=False, ambiguities=None,
          vague="some", fraction_of_container=False):
    if stated:
        intent = QuantityIntent(stated_amount=5.0, stated_unit="oz")
    elif fraction_of_container:
        intent = QuantityIntent(descriptor=vague, consumed_fraction=0.5,
                                container_count=1.0)
    else:
        intent = QuantityIntent(descriptor=vague)
    return StagedFoodItem(
        staged_item_id="si_1", original_text=f"{vague} {name}",
        identity=FoodIdentity(canonical_name=name),
        quantity=intent,
        vague_measure=vague,
        ambiguities=tuple(ambiguities if ambiguities is not None
                          else (_ambiguity(),)))


class _Decision:
    def __init__(self, items):
        self.staged_items = tuple(items)


def _eligible_decision(**kw):
    return _Decision([_item(**kw)])


def _candidates(*grams_and_sources):
    out = []
    for cid, grams, source, prob, conf in grams_and_sources:
        prov = (Provenance.USER_HISTORY if source is CandidateSource.USER_HISTORY
                else Provenance.ONTOLOGY)
        out.append(CandidateValue(
            candidate_id=cid,
            # `basis` is set here because the real producer sets it, and a
            # fixture that omits it would let traceability rot untested.
            semantic_value=qc._quantity(grams, provenance=prov,
                                        confidence=conf,
                                        basis=f"{source.value} evidence"),
            source=source, probability=prob, confidence=conf))
    return tuple(out)


REAL = _candidates(
    ("ont_low", 85.0, CandidateSource.ONTOLOGY, 0.2, 0.6),
    ("hist_last", 141.7, CandidateSource.USER_HISTORY, 0.55, 0.9),
    ("ont_high", 226.0, CandidateSource.ONTOLOGY, 0.3, 0.6),
)


def _interaction(candidates=REAL, food="chicken breast"):
    item = _item(name=food)
    field = qc.quantity_field(operation_id=OP, revision=REV, item=item)
    options = qc.select(candidates, field=field, food_name=food)
    return qc.build_interaction(operation_id=OP, revision=REV, item=item,
                                options=options,
                                introduction="How much chicken breast?")


def _field_id(ix):
    return ix.groups[0].fields[0].field_id


# ── eligibility ──────────────────────────────────────────────────────────────

def test_the_canonical_shape_is_eligible():
    e = qc.is_eligible(_eligible_decision(), message="I had some chicken breast",
                       client_capable=True)
    assert e.ok, e.reason
    assert e.item.identity.canonical_name == "chicken breast"


@pytest.mark.parametrize("kw,message,expected", [
    ({}, "actually make that 8oz", qc.Ineligible.CORRECTION_TURN),
    ({"stated": True}, "I had 5oz of chicken", qc.Ineligible.QUANTITY_ALREADY_STATED),
    ({"ambiguities": ()}, "I had some chicken", qc.Ineligible.NO_QUANTITY_QUESTION),
    ({"ambiguities": (_ambiguity("variant", AmbiguityType.PRODUCT_VARIANT),)},
     "I had a Core Power", qc.Ineligible.IDENTITY_AMBIGUOUS),
    ({"ambiguities": (_ambiguity("preparation", AmbiguityType.PREPARATION),)},
     "I had some chicken", qc.Ineligible.PREPARATION_DEPENDENCY),
    # A CONTAINER FRACTION, expressed where the distinction actually lives:
    # the quantity INTENT. Both cases carry field_name="consumed_fraction",
    # so the ambiguity alone cannot tell "half a bottle" (B-2.5) from "some
    # chicken" (B-1).
    ({"fraction_of_container": True}, "I had half of it",
     qc.Ineligible.NOT_MASS),
])
def test_every_out_of_scope_shape_declines_with_its_reason(kw, message, expected):
    """A typed reason, not a bool: 'how often, and for what' is the
    measurement that sizes B-1.5 and B-2."""
    e = qc.is_eligible(_eligible_decision(**kw), message=message,
                       client_capable=True)
    assert not e.ok
    assert e.reason is expected


def test_a_multi_item_meal_is_not_b1():
    d = _Decision([_item(name="chicken breast"), _item(name="white rice")])
    assert qc.is_eligible(d, message="chicken and rice",
                          client_capable=True).reason is \
        qc.Ineligible.MULTIPLE_ITEMS


def test_an_incapable_client_is_excluded_not_downgraded():
    """Rendering canonical options as prose for a client that cannot read the
    payload would keep the sentence parser alive INSIDE the replacement."""
    assert qc.is_eligible(_eligible_decision(), message="I had some chicken",
                          client_capable=False).reason is \
        qc.Ineligible.CLIENT_INCAPABLE


def test_an_unresolved_identity_is_not_b1():
    d = _Decision([StagedFoodItem(staged_item_id="si_1", original_text="something",
                                  identity=FoodIdentity(),
                                  ambiguities=(_ambiguity(),))])
    assert qc.is_eligible(d, message="I ate something",
                          client_capable=True).reason is \
        qc.Ineligible.IDENTITY_UNRESOLVED


# ── options are a projection of evidence ─────────────────────────────────────

def test_options_are_the_bracket_the_ontology_already_computed():
    ix = _interaction()
    options = ix.groups[0].fields[0].options
    assert [str(o.patch.quantity.grams) for o in options] == \
        ["85.0", "141.7", "226.0"], "the offered masses must be the evidence"
    assert [o.source for o in options] == [
        CandidateSource.ONTOLOGY, CandidateSource.USER_HISTORY,
        CandidateSource.ONTOLOGY]


def test_every_canonical_option_carries_a_typed_patch():
    for o in _interaction().groups[0].fields[0].options:
        assert isinstance(o.patch, SetQuantity)
        assert o.patch.quantity.dimension is Dimension.MASS
        assert o.adapter_built is False
        assert o.option_id, "a tap submits ids; an unidentified option is unanswerable"


def test_near_duplicates_are_suppressed():
    """`4.8 / 5.0 / 5.2` — three chips, one answer, no information gained."""
    crowded = _candidates(
        ("a", 136.0, CandidateSource.ONTOLOGY, 0.4, 0.6),
        ("b", 141.7, CandidateSource.USER_HISTORY, 0.55, 0.9),
        ("c", 147.0, CandidateSource.ONTOLOGY, 0.3, 0.6),
    )
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    assert len(qc.select(crowded, field=field, food_name="chicken breast")) == 1


def test_near_duplicates_are_suppressed_by_LABEL_not_only_by_grams():
    """MEASURED ON THE FIRST WIRED TURN. Chicken breast's real ontology
    bracket (130.5 / 174 / 435 g) is well separated numerically — 1.33x
    between the first two, comfortably past the gram threshold — and renders
    as `5 oz / 6 oz / 16 oz`.

    Nobody reads 5 and 6 ounces as two different answers. A row that offers
    three chips and two choices is the "% choosing Other" failure the
    directive names, arriving through the one gap a grams-only check leaves:
    the user compares LABELS.
    """
    real = _candidates(
        ("ont_low", 130.5, CandidateSource.ONTOLOGY, 0.2, 0.6),
        ("ont_mid", 174.0, CandidateSource.ONTOLOGY, 0.5, 0.6),
        ("ont_high", 435.0, CandidateSource.ONTOLOGY, 0.3, 0.6),
    )
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    labels = [o.label for o in qc.select(real, field=field,
                                         food_name="chicken breast")]
    assert labels == ["6 oz", "16 oz"], labels
    assert "5 oz" not in labels, \
        "the better-evidenced candidate keeps the slot; ranked order breaks " \
        "the tie"


def test_label_dedupe_does_not_eat_a_genuinely_spread_row():
    """The guard must not collapse rows that were always fine."""
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    assert [o.label for o in qc.select(REAL, field=field,
                                       food_name="chicken breast")] == \
        ["3 oz", "5 oz", "8 oz"]


def test_at_most_three_numeric_options():
    many = _candidates(*[(f"c{i}", 50.0 * (i + 1), CandidateSource.ONTOLOGY,
                          0.3, 0.6) for i in range(6)])
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    assert len(qc.select(many, field=field,
                         food_name="chicken breast")) <= qc.MAX_NUMERIC_OPTIONS


def test_no_candidates_becomes_an_explicit_free_text_fallback():
    """C15: never a blank select the client 'repairs' by parsing prose."""
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item(),
                              options=())
    assert field.response_type is ResponseType.FREE_TEXT_FALLBACK
    assert field.options == ()


def test_labels_are_rendered_last_and_never_carry_meaning():
    ix = _interaction()
    options = ix.groups[0].fields[0].options
    assert [o.label for o in options] == ["3 oz", "5 oz", "8 oz"], \
        "meat is answered in ounces, not grams — a question, not a chore"
    # The label is presentation: the meaning is the patch, and they differ.
    assert options[0].label == "3 oz"
    assert options[0].patch.quantity.grams == Decimal("85.0")


# ── the ten answer variants ──────────────────────────────────────────────────

def test_a_chip_tap_resolves_to_the_stored_patch():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_hist_last",
                         revision=REV)
    assert r.outcome is Outcome.APPLIED
    assert r.patch.quantity.grams == Decimal("141.7")
    assert r.patch.provenance is Provenance.USER_SELECTED


def test_a_typed_quantity_that_was_offered_produces_the_same_patch_type():
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="5 oz",
                         revision=REV, food_name="chicken breast")
    assert r.outcome is Outcome.APPLIED
    assert isinstance(r.patch, SetQuantity)
    assert r.patch.provenance is Provenance.USER_STATED, \
        "typing it is a statement; tapping it is a selection (C14)"


def test_a_typed_quantity_that_was_never_offered_is_a_first_class_answer():
    """The typed path is not a fallback for people the chips failed."""
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="about 6 ounces",
                         revision=REV, food_name="chicken breast")
    assert r.outcome is Outcome.APPLIED
    assert 160 < float(r.patch.quantity.grams) < 185
    assert r.patch.provenance is Provenance.USER_STATED


def test_a_stale_revision_is_refused_not_retargeted():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_hist_last",
                         revision=REV + 1)
    assert r.outcome is Outcome.REFUSED
    assert "revision" in r.reason


def test_a_foreign_field_is_refused():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=f"{OP}:food_other:quantity:{REV}",
                         option_id="opt_hist_last", revision=REV)
    assert r.outcome is Outcome.REFUSED
    r2 = answer_from_text(ix, field_id="op_2:food_si_1:quantity:0", text="5 oz",
                          revision=REV)
    assert r2.outcome is Outcome.REFUSED


def test_a_wrong_event_cannot_be_smuggled_through_an_option():
    """An option that patches another field is unconstructable (B-0c)."""
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    from core.semantics import ClarificationOption
    foreign = ClarificationOption(
        label="5 oz", option_id="opt_x", field_id="op_1:food_rice:quantity:0",
        patch=SetQuantity(event_id="food_rice",
                          field_id="op_1:food_rice:quantity:0",
                          quantity=qc._quantity(141.7,
                                                provenance=Provenance.ONTOLOGY)))
    with pytest.raises(ValueError, match="mixed chip row, one level down"):
        qc.quantity_field(operation_id=OP, revision=REV, item=_item(),
                          options=(foreign,))


def test_an_invalid_option_id_is_refused():
    ix = _interaction()
    r = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_nope",
                         revision=REV)
    assert r.outcome is Outcome.REFUSED


def test_a_duplicate_tap_is_deterministic():
    """Same ids in, same patch out — idempotency starts by the answer being a
    pure function of the stored interaction."""
    ix = _interaction()
    a = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_ont_low",
                         revision=REV)
    b = answer_from_chip(ix, field_id=_field_id(ix), option_id="opt_ont_low",
                         revision=REV)
    assert a.patch == b.patch


def test_an_unparseable_answer_repairs_and_never_reaches_the_interpreter():
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="it was fine thanks",
                         revision=REV, food_name="chicken breast")
    assert r.outcome is Outcome.REPAIR, \
        "an unparsed answer must ask again, not become a second meal"


def test_an_explicit_cancel_closes_the_operation():
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="never mind",
                         revision=REV, food_name="chicken breast")
    assert r.outcome is Outcome.CANCELLED


def test_the_answer_outcomes_have_no_legacy_member():
    """C10, at the type level: there is no way to SAY 'fall back' here."""
    assert {o.value for o in Outcome} == {
        "applied", "cancelled", "repair", "refused"}


def test_a_typed_answer_is_checked_for_staleness_too():
    """A boundary that checks staleness on the tap path only is a boundary
    that does not check it — people type into stale screens as readily as
    they tap them."""
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="6 oz",
                         revision=REV + 1, food_name="chicken breast")
    assert r.outcome is Outcome.REFUSED
    assert "revision" in r.reason


# ── the result type ──────────────────────────────────────────────────────────

def test_an_applied_answer_must_carry_its_patch():
    """`patch: Any = None` with nothing checking it let a REFUSED result reach
    a caller that read `.patch` unconditionally — which is how settle() died
    on NoneType.quantity."""
    from core.clarification_answer import AnswerResult

    with pytest.raises(TypeError, match="APPLIED answer IS its patch"):
        AnswerResult(Outcome.APPLIED)
    with pytest.raises(TypeError, match="must carry no patch"):
        AnswerResult(Outcome.REFUSED,
                     patch=SetQuantity(event_id="e", field_id="f",
                                       quantity=qc._quantity(
                                           100, provenance=Provenance.ONTOLOGY)))


# ── commands ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("cancel", Outcome.CANCELLED),
    ("just cancel", Outcome.CANCELLED),
    ("never mind", Outcome.CANCELLED),
    ("skip it", Outcome.CANCELLED),
    ("start over", Outcome.CANCELLED),
    # NOT cancels. A bare "cancel" mid-sentence used to throw the meal away,
    # and cancelling is the one command that destroys work already done.
    ("I didn't cancel my order", Outcome.REPAIR),
    ("cancel my gym membership", Outcome.REPAIR),
])
def test_cancellation_matches_the_command_not_the_substring(text, expected):
    ix = _interaction()
    assert answer_from_text(ix, field_id=_field_id(ix), text=text,
                            revision=REV).outcome is expected


def test_i_dont_know_is_answered_not_re_asked():
    """Repairing here would ask the same question again to someone who just
    said they cannot answer it. The value is an option already on their
    screen, re-provenanced because WE chose it."""
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="I don't know",
                         revision=REV, food_name="chicken breast")
    assert r.outcome is Outcome.APPLIED
    assert r.patch.provenance is Provenance.MODE_DEFAULT, \
        "an assumed portion must stay disclosable — it is not the user's"
    assert r.patch.quantity.grams == Decimal("141.7"), "the middle option"


def test_an_estimate_synthesizes_nothing_and_stays_traceable():
    """Every fact the committed row needs in order to disclose honestly."""
    ix = _interaction()
    field = ix.groups[0].fields[0]
    offered = {o.patch.quantity.grams: o for o in field.options}

    r = answer_from_text(ix, field_id=_field_id(ix), text="just estimate it",
                         revision=REV, food_name="chicken breast")

    assert r.outcome is Outcome.APPLIED
    assert r.patch.quantity.grams in offered, \
        "the assumed value must be an option that was ON SCREEN, not a new one"
    assert r.patch.provenance is Provenance.MODE_DEFAULT
    assert r.patch.quantity.provenance is Provenance.MODE_DEFAULT, \
        "the QUANTITY's own provenance drives is_estimated, so it has to " \
        "change too — the patch alone is not what pricing reads"
    assert r.patch.quantity.is_estimated, \
        "the '(my estimate)' marker, the card range and the disclosure all " \
        "key on this"
    # WHERE THE NUMBER CAME FROM survives the re-provenancing: the candidate's
    # basis rides the quantity's confidence, so a receipt can still say the
    # ontology (or the user's own history) supplied it.
    assert r.patch.quantity.confidence.basis, "the evidence must stay nameable"
    assert offered[r.patch.quantity.grams].source is CandidateSource.USER_HISTORY
    # Same target as any other answer — an estimate is not a different lane.
    assert r.patch.field_id == _field_id(ix)
    assert r.patch.event_id == field.event_id


def test_an_estimate_is_deterministic_and_therefore_idempotent():
    """Two deliveries of "I don't know" must produce the SAME patch, or the
    idempotency the commit boundary provides has nothing to match on."""
    ix = _interaction()
    kw = dict(field_id=_field_id(ix), revision=REV, food_name="chicken breast")
    first = answer_from_text(ix, text="I don't know", **kw)
    second = answer_from_text(ix, text="no idea", **kw)
    assert first.patch == second.patch


def _options_of(field, *grams):
    """Options built directly, bypassing `select`'s three-option cap.

    The cap is a PRODUCT rule about how many chips a row may carry; the median
    rule is arithmetic over whatever a field holds. Testing the second through
    the first would silently make the four-option case untestable — `select`
    would drop one and the assertion would measure the cap instead.
    """
    from core.semantics import ClarificationOption, SetQuantity

    return tuple(
        ClarificationOption(
            label=f"{g:g}g", option_id=f"opt_{i}", field_id=field.field_id,
            source=CandidateSource.ONTOLOGY,
            patch=SetQuantity(
                event_id=field.event_id, field_id=field.field_id,
                quantity=qc._quantity(g, provenance=Provenance.ONTOLOGY,
                                      basis="portion ontology"),
                provenance=Provenance.USER_SELECTED))
        for i, g in enumerate(sorted(grams)))


@pytest.mark.parametrize("grams,expected", [
    ((141.7,), "141.7"),                          # one
    ((85.0, 226.0), "226.0"),                     # two  -> the UPPER middle
    ((85.0, 141.7, 226.0), "141.7"),              # three
    ((85.0, 141.7, 226.0, 340.0), "226.0"),       # four -> the upper middle
])
def test_the_assumed_value_is_the_median_by_semantic_value(grams, expected):
    """Median by GRAMS, never by rendered order — a row's display order is a
    presentation decision and must not become an arithmetic one.

    On an even count the UPPER middle wins. That is not a coin toss: an
    assumed portion is a low-confidence estimate, and this codebase's standing
    rule for those is to bias high, because under-counting a meal is the error
    a user does not notice.
    """
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    options = _options_of(field, *grams)
    ix = qc.build_interaction(operation_id=OP, revision=REV, item=_item(),
                              options=options)
    r = answer_from_text(ix, field_id=_field_id(ix), text="I don't know",
                         revision=REV)
    assert str(r.patch.quantity.grams) == expected


def test_the_median_ignores_the_rendered_order():
    """Same options, shuffled on the row: the assumed value must not move."""
    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    a, b, c = _options_of(field, 85.0, 141.7, 226.0)
    for row in ((a, b, c), (c, a, b), (b, c, a)):
        ix = qc.build_interaction(operation_id=OP, revision=REV, item=_item(),
                                  options=row)
        r = answer_from_text(ix, field_id=_field_id(ix), text="I don't know",
                             revision=REV)
        assert str(r.patch.quantity.grams) == "141.7"


def test_a_non_numeric_option_cannot_be_assumed():
    """An estimate needs a quantity. An option carrying a different patch kind
    — or none at all — is not a candidate for one, and picking it by position
    would apply a preparation as if it were a mass."""
    from core.semantics import ClarificationOption, SetPreparation

    field = qc.quantity_field(operation_id=OP, revision=REV, item=_item())
    prep = ClarificationOption(
        label="Grilled", option_id="opt_prep", field_id=field.field_id,
        patch=SetPreparation(event_id=field.event_id,
                             field_id=field.field_id,
                             preparation_id="prep.grilled"))
    mixed = qc.quantity_field(operation_id=OP, revision=REV, item=_item(),
                              options=(prep,))
    ix = qc.build_interaction(operation_id=OP, revision=REV, item=_item(),
                              options=(prep,))
    r = answer_from_text(ix, field_id=mixed.field_id, text="I don't know",
                         revision=REV)
    assert r.outcome is Outcome.REPAIR, \
        "no mass on offer means nothing to assume"


def test_an_estimate_with_nothing_offered_repairs():
    ix = _interaction(candidates=())
    assert ix.groups[0].fields[0].response_type is ResponseType.FREE_TEXT_FALLBACK
    r = answer_from_text(ix, field_id=_field_id(ix), text="no idea",
                         revision=REV)
    assert r.outcome is Outcome.REPAIR


# ── the shared command parser stays conservative ─────────────────────────────

@pytest.mark.parametrize("text,destroys", [
    # Directed at the open clarification — these MAY destroy it.
    ("cancel", True), ("cancel the meal", True), ("forget the whole thing", True),
    ("skip it", True), ("never mind", True), ("start over", True),
    ("don't log it", True),
    # Ordinary language that merely CONTAINS a command word. An open operation
    # is real work the user already did; the parser must not destroy it on a
    # substring.
    ("I didn't cancel my order", False), ("cancel my subscription", False),
    ("not cancel", False), ("my flight was cancelled", False),
    ("don't skip it", False), ("I skipped breakfast", False),
])
def test_only_a_directed_command_may_destroy_an_operation(text, destroys):
    """`parse_command` is shared with the legacy lane, so this pins the
    distinction that matters most: a command AIMED at the open question versus
    a sentence that happens to contain its word."""
    ix = _interaction()
    outcome = answer_from_text(ix, field_id=_field_id(ix), text=text,
                               revision=REV,
                               food_name="chicken breast").outcome
    assert (outcome is Outcome.CANCELLED) is destroys, \
        f"{text!r} -> {outcome.value}"


@pytest.mark.parametrize("text", [
    "I don't know", "no idea", "estimate it", "just use your estimate",
    "not sure", "your best guess",
])
def test_uncertainty_phrasings_all_reach_the_estimate_path(text):
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text=text, revision=REV,
                         food_name="chicken breast")
    assert r.outcome is Outcome.APPLIED
    assert r.patch.provenance is Provenance.MODE_DEFAULT


# ── the command lexicon is TIER 1, and Tier 1 is English ─────────────────────

@pytest.mark.parametrize("locale", ["ru", "es", "fr", "ja", "und", "", None])
def test_english_command_rules_never_run_on_another_locale(locale):
    """The recurrence guard. EN-only rescue detectors in this lane shipped
    unlogged Russian meals on 2026-08-03; the routing gate was fixed and the
    DETECTORS were not, and `parse_command` is one of them.

    Nothing here is granted a language-neutral exemption — none can be proven
    one, and the cost of being wrong is a destroyed meal. A non-English answer
    falls to the field parser and then to repair.
    """
    from skills.nutrition.answer_parsers import parse_command

    for destructive in ("cancel", "cancel the meal", "skip it", "never mind",
                        "start over", "don't log it"):
        assert parse_command(destructive, locale=locale) is None, \
            f"{destructive!r} was obeyed under locale {locale!r}"

    ix = _interaction()
    assert answer_from_text(ix, field_id=_field_id(ix), text="cancel",
                            revision=REV, locale=locale).outcome is \
        Outcome.REPAIR, "an unreadable answer repairs; it never cancels"


def test_a_universal_notation_answer_still_works_in_any_locale():
    """Numbers and unit symbols carry no language. Excluding a locale from the
    COMMAND lexicon must not exclude it from answering the question."""
    ix = _interaction()
    r = answer_from_text(ix, field_id=_field_id(ix), text="150 g",
                         revision=REV, locale="ru", food_name="chicken breast")
    assert r.outcome is Outcome.APPLIED
    assert r.patch.quantity.grams == Decimal("150.0")


def test_the_locale_resolution_order():
    """Stored preference, then the locale established on the operation, then
    script evidence — detection last, because a two-word reply is where it is
    least reliable and a destructive command sits behind it."""
    from core.language import UNKNOWN_LOCALE, command_locale, is_english

    assert command_locale("Russian", "6 oz") == "ru", "the preference wins"
    assert command_locale(None, "6 oz", established="ru") == "ru", \
        "the question's language governs its answer"
    assert command_locale(None, "не знаю") == "ru", "script, as a fallback"
    assert command_locale(None, "6 oz") == "en"
    assert command_locale("Klingon") == UNKNOWN_LOCALE
    assert not is_english(UNKNOWN_LOCALE), \
        "'we could not tell' must never authorise a destructive command"


# ── decimals ─────────────────────────────────────────────────────────────────

def test_quantities_never_round_trip_through_a_float():
    """`Decimal(str(round(float(v), 1)))` re-widens an already-imprecise value
    into a binary float before narrowing it again. B-0c's storage guarantee is
    decorative if construction spends it."""
    q = qc._quantity(Decimal("141.75"), provenance=Provenance.ONTOLOGY)
    assert q.grams == Decimal("141.8") and q.amount == q.grams
    assert isinstance(q.grams, Decimal)

    ix = _interaction()
    typed = answer_from_text(ix, field_id=_field_id(ix), text="6 oz",
                             revision=REV, food_name="chicken breast")
    assert isinstance(typed.patch.quantity.grams, Decimal)
    assert typed.patch.quantity.grams == Decimal("170.1")


# ── the rollout gate ─────────────────────────────────────────────────────────

def test_ownership_is_refused_by_default(monkeypatch):
    for var in ("B1_QUANTITY_HALT", "B1_QUANTITY_ALLOWLIST",
                "B1_QUANTITY_PERCENT"):
        monkeypatch.delenv(var, raising=False)
    assert qr.may_take_ownership(144) is False
    assert qr.cohort_label(144) == "off"


def test_the_halt_outranks_the_allowlist(monkeypatch):
    """An allowlist entry that could override a halt is not a halt."""
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "144")
    monkeypatch.setenv("B1_QUANTITY_HALT", "true")
    assert qr.may_take_ownership(144) is False
    assert qr.cohort_label(144) == "halted"


def test_widening_the_cohort_adds_users_and_never_swaps_them(monkeypatch):
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    monkeypatch.setenv("B1_QUANTITY_PERCENT", "10")
    at_ten = {u for u in range(2000) if qr.in_cohort(u)}
    monkeypatch.setenv("B1_QUANTITY_PERCENT", "25")
    at_twentyfive = {u for u in range(2000) if qr.in_cohort(u)}
    assert at_ten and at_ten < at_twentyfive, \
        "widening must be monotonic, or users flap between two systems"


def test_the_b1_cohort_is_not_the_resolver_cohort(monkeypatch):
    """A shared salt would make B-1's 5% exactly the resolver's 5%, and every
    B-1 measurement would carry resolver-V2 as a hidden covariate."""
    from skills.nutrition.canary import bucket_for
    same = sum(1 for u in range(500)
               if bucket_for(u) == bucket_for(u, salt=qr.SALT))
    assert same < 25, f"{same}/500 buckets collide — the salts are not distinct"


def test_the_rollout_gate_has_no_continue_function():
    """C10 by absence: the gate answers 'may we START'. A `should_continue`
    would be read on the answer turn, and every way of acting on a False
    answer there loses a meal in flight."""
    assert not [n for n in dir(qr)
                if "continue" in n or "still" in n or "keep" in n]
