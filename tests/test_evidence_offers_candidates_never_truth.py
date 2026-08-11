"""B-1.7a — THE ADDED-FAT IDENTITY CONTRACT.

    ADDED_FAT_PRESENT
      |- IsTrue -> ADDED_FAT_IDENTITY     SIBLINGS, never a chain
      \\- IsTrue -> ADDED_FAT_AMOUNT

⭐ THE LINE THIS FILE EXISTS TO HOLD:

    ALLOWED    food + preparation -> PLAUSIBLE added-fat identities
    FORBIDDEN  food + preparation -> a RESOLVED added-fat identity

Evidence can say grilled chicken is commonly cooked in oil or butter. It
cannot say what THIS user cooked with. The pricing artifact already stores a
qualified candidate SET rather than a winner for exactly this reason —
`best_candidate` ranks at runtime — and identity inherits that discipline
rather than getting a shortcut, because the shortcut is the substitution
problem the artifact was designed to avoid.

⭐⭐ AND AMOUNT MUST NOT DEPEND ON IDENTITY. "About a tablespoon, not sure what
oil" is a truthful, useful answer. A graph that discarded the amount because
the identity is unknown would destroy a fact to satisfy a topology.

⭐⭐⭐ AN ID THE PRICER CANNOT ACT ON IS INERT. Measured 2026-08-11: the
artifact holds 27 entries and none is a fat, so every offered id currently
misses. The field is therefore `Evidence.GENERATED` — not offered when there
is nothing to build an option from — and the gap between OFFERED and
priceable() is a measurement of what the artifact owes, not a silent
degradation.
"""
from __future__ import annotations

import pytest

from core import field_activation as fa
from core import semantic_fields as sf
from core.semantics import (ClarificationAttribute, Provenance,
                            SetAddedFatIdentity, SetAddedFatPresent)
from skills.nutrition import added_fat_ontology as af

PRESENT = ClarificationAttribute.ADDED_FAT_PRESENT.value
IDENTITY = ClarificationAttribute.ADDED_FAT_IDENTITY.value
AMOUNT = ClarificationAttribute.ADDED_FAT_AMOUNT.value


@pytest.fixture(autouse=True)
def _installed():
    sf._ensure_installed()


def _present(value: bool):
    return SetAddedFatPresent(event_id="e", field_id=f"op:e:{PRESENT}:0",
                              present=value)


# ── the graph: siblings, not a chain ───────────────────────────────────────

def test_identity_and_amount_are_siblings_of_presence():
    assert sf.spec_for(IDENTITY).depends_on == (PRESENT,)
    assert sf.spec_for(AMOUNT).depends_on == (PRESENT,)


def test_an_amount_is_valid_without_an_identity():
    """"About a tablespoon, not sure what oil" must stay answerable. If amount
    depended on identity, that fact would be discarded to satisfy a
    topology."""
    assert IDENTITY not in sf.spec_for(AMOUNT).depends_on, (
        "amount depends on identity — a user who knows how much but not what "
        "would have no way to tell us the part they know")
    active = fa.active_attributes(
        fa.ActivationState(item={"food": "Chicken"},
                           resolved={PRESENT: _present(True)}),
        baseline=[PRESENT])
    assert {IDENTITY, AMOUNT} <= active, (
        "both dependants must open together; which one is ASKED is "
        "presentation and policy, not activation truth")


def test_neither_opens_when_presence_is_false_or_unasked():
    for resolved in ({}, {PRESENT: _present(False)}):
        active = fa.active_attributes(
            fa.ActivationState(item={"food": "Chicken"}, resolved=resolved),
            baseline=[PRESENT])
        assert not ({IDENTITY, AMOUNT} & active)


# ── ⭐ CANDIDATES, NEVER TRUTH ─────────────────────────────────────────────

ARTIFACT_PROVENANCE = {Provenance.ONTOLOGY, Provenance.CATALOG,
                       Provenance.MODEL_ESTIMATE, Provenance.MODE_DEFAULT}


def test_a_resolved_identity_may_not_come_from_the_artifact():
    """THE ENFORCING GATE. Evidence proposes; only a person disposes.

    A resolved identity carrying artifact/ontology provenance would mean the
    system decided what the user cooked with — the exact substitution the
    pricing artifact's candidate-set design exists to prevent, arriving by a
    different door.
    """
    from core import canonical_pricing  # noqa: F401  (import graph sanity)

    truthful = {Provenance.USER_STATED, Provenance.USER_SELECTED,
                Provenance.USER_CONFIRMED}
    for source in truthful:
        SetAddedFatIdentity(event_id="e", field_id=f"op:e:{IDENTITY}:0",
                            entity_id="olive_oil", provenance=source)

    # And the rule, as a checkable statement about what settlement may accept.
    assert not (truthful & ARTIFACT_PROVENANCE), (
        "a provenance counts as both user truth and evidence, so the "
        "distinction this gate rests on has collapsed")


def test_no_default_identity_exists_anywhere():
    """`resolve()` returning something for an unknown id would mean an
    identity we do not hold gets priced as one we do."""
    assert af.resolve("olive_oil").entity == "olive oil"
    for unknown in ("", "   ", "oil", "schmaltz", "unknown", "default"):
        assert af.resolve(unknown) is None, (
            f"{unknown!r} resolved to a fat — a default identity is the "
            f"legacy phrase table under a typed interface")


def test_the_ontology_has_no_unknown_member_that_could_be_priced():
    """Preparation has an UNKNOWN member because an unknown preparation
    legitimately leaves the food's name alone. There is no equivalent here: an
    unknown FAT cannot be priced as anything, and a member meaning "some fat,
    unspecified" would immediately need a calorie value."""
    ids = {f.entity_id for f in af.OFFERED}
    assert not (ids & {"unknown", "other", "some", "default", "generic"})


def test_a_blank_identity_cannot_be_stored():
    with pytest.raises(ValueError):
        SetAddedFatIdentity(event_id="e", field_id="f", entity_id="")


# ── ⭐⭐⭐ inert-question guard ─────────────────────────────────────────────

def test_the_field_is_not_offered_from_a_vocabulary_it_cannot_price():
    """AN ID THE PRICER CANNOT ACT ON IS INERT — the constraint
    `preparation_ontology` paid for. A chip that changes nothing is worse than
    no chip, because its usage rate looks like engagement.

    So the field is GENERATED, not ONTOLOGY: it is not offered where there is
    no evidence to build an option from. Measured 2026-08-11, `priceable()` is
    EMPTY — the artifact holds 27 entries and none is a fat — and that is a
    recorded gap rather than a silent one.
    """
    spec = sf.spec_for(IDENTITY)
    assert spec.evidence is sf.Evidence.GENERATED, (
        "an ONTOLOGY identity field would ship a chip bar of unpriceable "
        "choices the day the artifact does not cover fats — which is today")
    assert set(af.priceable()) <= set(af.OFFERED)


def test_every_offered_fat_is_a_food_not_a_label():
    """The fat is a FOOD, and that is the whole design: pricing becomes
    composition through the canonical pricer rather than a constant."""
    for fat in af.OFFERED:
        assert fat.entity == fat.entity_id.replace("_", " ")
        assert " " not in fat.entity_id and fat.entity_id.islower()


def test_dressings_and_sauces_are_deliberately_not_fats():
    """`_ADDED_FAT_CAL` fused fats and sauces into one lookup, which is how it
    became a phrase table. Ranch is a composite food with its own amount, not
    a fat — folding it in would make one field mean two things."""
    ids = {f.entity_id for f in af.OFFERED}
    assert not (ids & {"ranch", "caesar", "alfredo", "vinaigrette", "gravy",
                       "marinade", "teriyaki", "bbq_sauce"})


# ── the contract is registered, not merely written down ────────────────────

def test_the_identity_field_is_admitted_by_the_registry():
    spec = sf.spec_for(IDENTITY)
    assert spec.activation is sf.Activation.CONDITIONAL
    assert spec.patch_type == "set_added_fat_identity"
    assert spec.pricing is sf.Pricing.NONE, (
        "a fat identity does not multiply the meal's calories; it names a "
        "SECOND FOOD that B-1.7c prices as its own component")
    assert isinstance(spec.active_when, fa.Rule)


def test_the_graph_is_still_acyclic_with_three_added_fat_fields():
    fa.assert_declares_its_dependencies()
    fa.assert_acyclic()
    order = fa.activation_order()
    assert order.index(PRESENT) < order.index(IDENTITY)
    assert order.index(PRESENT) < order.index(AMOUNT)
