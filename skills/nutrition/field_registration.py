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


def _preparation_speculate(item, context=None) -> None:
    """Start the supplemental materiality lookup for this item's food.

    C2.1a §3 moved the start here from generic enrichment. Late import for the
    same reason as the predicate: registration must not drag the resolver or
    the search lane in at import time.
    """
    from skills.nutrition.preparation_activation import start_supplemental

    name = str(getattr(getattr(item, "identity", None), "canonical_name", "")
               or "").strip()
    if name:
        start_supplemental(name, context)


def register_all() -> None:
    from core.semantics import ClarificationAttribute
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
        # THE ONLY FIELD THAT SPECULATES TODAY. Its evidence is mostly web —
        # measured: USDA's top rows for bare "chicken" carry no registered
        # preparations — so a lookup started when the predicate runs lands
        # squarely on the ask's critical path.
        speculate=_preparation_speculate,
        caption="Preparation", order=20))

