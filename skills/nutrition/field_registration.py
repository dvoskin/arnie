"""WHERE NUTRITION'S SEMANTIC FIELDS ARE REGISTERED.

The registry mechanism is `core.semantic_fields`; what a preparation IS, and
what this domain's resolver can act on, is knowledge that belongs here. Core
enforces that an identity-pricing field declares how its vocabulary is
validated; this module supplies what that means for food.

Imported by `core.semantic_fields._ensure_installed()` at first use — the one
place core names a domain. Nothing else should import this module for its side
effect.
"""
from __future__ import annotations

from core.field_activation import IsTrue
from core.semantic_fields import (Activation, Evidence, FieldSpec, Pricing,
                                  Settlement, ValueSpace, register)


async def _preparation_unresolved(item, context=None) -> bool:
    """Late import: the activation probe reaches the resolver and the web, and
    registration must not drag either in at import time.

    B-1.5E C2 pointed this at `preparation_activation`, and DELETED
    `preparation_materiality` rather than refining it — the old predicate
    matched preparation tokens against raw provider descriptions, which is the
    regex identity the evidence boundary exists to remove. The hook survived;
    the predicate behind it did not.
    """
    from skills.nutrition.preparation_activation import (
        preparation_is_materially_unresolved)

    return await preparation_is_materially_unresolved(item, context)


def register_all() -> None:
    from core.semantics import ClarificationAttribute
    from skills.nutrition import added_fat_ontology as added_fat
    from skills.nutrition import preparation_ontology as prep

    register(FieldSpec(
        attribute=ClarificationAttribute.QUANTITY,
        value_space=ValueSpace.MEASURED,
        patch_type="set_quantity",
        pricing=Pricing.AMOUNT,
        # GENERATED, not ontology: the offer depends on this user's history
        # and this product's servings, and the field is not asked when there
        # is no evidence to build one from.
        evidence=Evidence.GENERATED,
        caption="Amount", order=10))

    register(FieldSpec(
        attribute=ClarificationAttribute.PREPARATION,
        value_space=ValueSpace.ENUMERATED,
        patch_type="set_preparation",
        # IDENTITY, never a multiplier: the answer changes which food we ask
        # the resolver about, and the resolver prices from its own evidence.
        pricing=Pricing.IDENTITY,
        evidence=Evidence.ONTOLOGY,
        vocabulary=tuple(p.preparation_id for p in prep.OFFERED if p.known),
        # THE NUTRITION REGISTRATION LAYER SUPPLIES THIS, not core. Late-bound
        # so importing this module does not drag the resolver in.
        supported_vocabulary=lambda: __import__(
            "skills.nutrition.validators", fromlist=["_PREPARATIONS"]
        )._PREPARATIONS,
        # THE FIELD DECIDES ITS OWN NECESSITY, from USDA's own rows for this
        # food. Without this the field was reachable only when the interpreter
        # volunteered a preparation ambiguity — which it does not do for
        # "I had some chicken", so B-1.5 could not fire in production at all.
        unresolved_when=_preparation_unresolved,
        caption="Preparation", order=20))

    # ── B-1.8c2.1: PRODUCT_VARIANT — registered, and GENERATED ─────────
    #
    # ⭐ IT WAS NEVER MISSING A PARSER; IT WAS MISSING A PERSISTED EXACT
    # CANDIDATE UNIVERSE (c2.0 recon). The field exists in the enum and the
    # typed patch (SelectProductVariant) has been serializable for weeks;
    # nothing REGISTERED it, so no producer could be asked for it and no
    # tapped option could carry it. IDENTITY pricing: the answer changes WHICH
    # PRODUCT we price, and — unlike every other identity field — it BINDS
    # the evidence universe to one persisted snapshot rather than merely
    # renaming the food (see canonical_pricing bound pricing).
    #
    # GENERATED, and the generation rule is the strictest in this registry:
    # the producer REOPENS an already-persisted exact universe. It never
    # assembles one from "similar / same brand / looks related / search
    # again" — a barcode proves a product, not its siblings — and a
    # correction with no persisted universe REFUSES rather than synthesizes.
    #
    # THE VALUE SPACE, HONESTLY *(Danny)*: ENUMERATED + GENERATED. Its answers
    # are NOT a static list — they are the persisted exact CandidateSet for
    # THIS operation, and membership is checked at answer time against that
    # set. No `vocabulary` is declared, on purpose: a grammar like `off:<gtin>`
    # would be syntactic validity, not the set of valid answers, and would make
    # the registry claim off:999... exists though it was never offered.
    register(FieldSpec(
        attribute=ClarificationAttribute.PRODUCT_VARIANT,
        value_space=ValueSpace.ENUMERATED,
        patch_type="select_product_variant",
        pricing=Pricing.IDENTITY,
        evidence=Evidence.GENERATED,
        # No static vocabulary. THIS names how membership is checked: the
        # persisted exact universe's members, per operation.
        supported_vocabulary=lambda: __import__(
            "skills.nutrition.product_variant_clarification",
            fromlist=["exact_universe_members"]).exact_universe_members,
        caption="Which product", order=15))

    # ── B-1.6: the first CONDITIONAL pair ────────────────────────────────
    #
    # THE DEPENDENCY IS DATA ON THE SPEC. The alternative — the one this
    # replaces everywhere it still exists — is `if present: ask_amount()`
    # written inside a producer, which makes the producer a second owner of
    # when to ask and leaves no way to ask the question generically.
    register(FieldSpec(
        attribute=ClarificationAttribute.ADDED_FAT_PRESENT,
        value_space=ValueSpace.ENUMERATED,
        patch_type="set_added_fat_present",
        # PRICES NOTHING. Presence gates a question; it does not move a
        # number, and a field that "adds 120 kcal for oil" would be the
        # MULTIPLIER member this enum deliberately does not have.
        pricing=Pricing.NONE,
        evidence=Evidence.ONTOLOGY,
        vocabulary=("yes", "no"),
        caption="Added fat", order=30))

    # ⭐ IDENTITY AND AMOUNT ARE SIBLINGS, NEVER A CHAIN. Both hang off
    # PRESENT. "About a tablespoon, not sure what oil" is a truthful, useful
    # answer, and a graph that discarded the amount because the identity is
    # unknown would destroy a fact to satisfy a topology.
    register(FieldSpec(
        attribute=ClarificationAttribute.ADDED_FAT_IDENTITY,
        value_space=ValueSpace.ENUMERATED,
        patch_type="set_added_fat_identity",
        # NONE — like presence. A fat identity does not multiply the meal's
        # calories; it names a SECOND FOOD, which B-1.7c prices as its own
        # component through the canonical pricer. `IDENTITY` here would mean
        # "changes which food we are asking about", and it does not: the
        # chicken is still chicken.
        pricing=Pricing.NONE,
        # GENERATED, NOT ONTOLOGY, and measured rather than assumed: the
        # artifact holds 27 entries and none is a fat, so every offered id
        # currently MISSES. An ONTOLOGY field would ship a chip bar of
        # unpriceable choices — a question whose answer moves no number, whose
        # usage rate then looks like engagement. Extending the artifact's seed
        # set is the unblocking step, and it is BUILD time, not turn time.
        evidence=Evidence.GENERATED,
        vocabulary=tuple(f.entity_id for f in added_fat.OFFERED),
        activation=Activation.CONDITIONAL,
        active_when=IsTrue(ClarificationAttribute.ADDED_FAT_PRESENT.value),
        caption="Which fat", order=32))

    register(FieldSpec(
        attribute=ClarificationAttribute.ADDED_FAT_AMOUNT,
        value_space=ValueSpace.MEASURED,
        patch_type="set_added_fat_amount",
        pricing=Pricing.NONE,
        evidence=Evidence.ONTOLOGY,
        activation=Activation.CONDITIONAL,
        # A RULE, NOT A LAMBDA. The engine evaluates it and derives the
        # dependency edge from its structure, so `depends_on` cannot disagree
        # with what activation actually reads — and there is nowhere in a rule
        # to reach a provider, the raw message, or the interpreter's prose.
        active_when=IsTrue(ClarificationAttribute.ADDED_FAT_PRESENT.value),
        caption="How much fat", order=31))

