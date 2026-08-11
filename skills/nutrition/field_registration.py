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

