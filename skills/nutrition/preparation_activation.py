"""IS PREPARATION MATERIALLY UNRESOLVED? Asked of QUALIFIED semantic evidence.

Replaces `preparation_materiality.py`, which is deleted rather than refined:
that predicate matched registered preparation tokens against raw provider
descriptions, which is the regex identity B-1.5E prohibits. It survived only
because it was fail-closed — measured in production, it opened nothing.

    qualified assessments (reused, free)   what preparations does the
      + one bounded web materiality query  evidence say EXIST for this food?
              ↓
    PreparationEvidence[]                  registered ids + densities
              ↓
    deterministic materiality              two or more, far enough apart?

SPACE, NEVER VALUE. Everything here decides whether to ASK. Nothing here
resolves what the user ate — no `SetPreparation` is constructible from this
module, and `test_evidence_opens_preparation_but_cannot_answer_it` holds that.

CLAIMS STAY TYPED ACROSS PROVIDERS. Web evidence is admissible for
`preparation_materiality` and inadmissible for `nutrition_pricing`, so this
module may open a field on a web answer while pricing still comes only from
structured evidence. That separation is the thing that stops "web says fried
matters" from becoming "web calories are authoritative".

WHY WEB AT ALL: measured on the captured corpus, USDA's top rows for generic
foods carry almost no REGISTERED preparations (its own words are raw ·
smoked · baked · "cooked, dry heat"). Structured evidence alone establishes
the space for very few foods, so the materiality claim is where web evidence
earns its place — and only there.
"""
from __future__ import annotations

import logging

from skills.nutrition import evidence_semantics as food

logger = logging.getLogger(__name__)

#: How far apart two preparations must price before asking is worth the
#: interruption. 25% of the lower density — same order as the quantity
#: slice's spread floor, and for the same reason: a question that cannot move
#: the number by more than rounding is an interruption, not a clarification.
MATERIAL_SPREAD = 1.25


def space_is_material(space: dict) -> bool:
    """Does this SPACE justify interrupting someone? THE ONE DEFINITION.

    Named for its input, not for its question, because
    `skills.nutrition.materiality.is_material` already answers a DIFFERENT
    question — whether a given uncertainty's macro spans are worth a question,
    given the day's targets. Two functions called `is_material` taking
    unrelated arguments is how a caller reaches for the wrong rule and gets a
    plausible answer; the collision is removed rather than documented.

    Two consumers need this answer — the predicate that opens the field, and
    §4's early exit, which stops the turn waiting on supplemental evidence
    that cannot change a decision already made. Two copies of the rule would
    drift, and the drift would be invisible: the early exit would fire on a
    space the predicate then declined, and preparation would silently stop
    opening for exactly the foods structured evidence handles best.
    """
    densities = [kcal for kcal in space.values() if kcal]
    if len(space) < 2 or len(densities) < 2:
        return False
    low, high = min(densities), max(densities)
    return low > 0 and (high / low) >= MATERIAL_SPREAD






async def preparation_is_materially_unresolved(item, context=None) -> bool:
    """The `unresolved_when` predicate for the preparation field.

    Order is the directive's, and each step is a reason NOT to ask:

        stated or already resolved   -> no field; do not ask twice
        name already encodes it      -> no field; "grilled chicken" answers
                                        itself
        fewer than two preparations  -> no field; nothing to choose between
        densities agree              -> no field; the answer changes nothing
        anything raised              -> no field; evidence we could not gather
                                        is not evidence of ambiguity
    """
    from skills.nutrition.ambiguity import AmbiguityType

    prep = getattr(item, "preparation", None)
    if getattr(prep, "stated", False) and getattr(prep, "method", None):
        return False

    # The interpreter raised it itself — believe it, and spend nothing.
    for amb in tuple(getattr(item, "material_ambiguities", lambda: ())()):
        if getattr(amb, "ambiguity_type", None) is AmbiguityType.PREPARATION:
            return True

    name = str(getattr(getattr(item, "identity", None), "canonical_name", "")
               or "").strip()
    if not name:
        return False

    space = await preparation_space(name, context)
    material = space_is_material(space)

    densities = [kcal for kcal in space.values() if kcal]
    if len(densities) < 2:
        # Two preparations may exist and we still cannot price the difference,
        # so we cannot show the question is worth asking. Silence beats a guess.
        logger.info("event=preparation_space food=%s preparations=%s "
                    "material=unknown_no_densities", name, sorted(space))
        return material

    low, high = min(densities), max(densities)
    logger.info("event=preparation_space food=%s preparations=%s low=%.0f "
                "high=%.0f ratio=%.2f material=%s",
                name, sorted(space), low, high,
                (high / low) if low else 0.0, material)
    return material


async def preparation_space(food_name: str, context=None) -> dict:
    """`{preparation_id: kcal_per_100g}` the evidence supports — READ, never
    computed.

    ZERO provider retrieval. ZERO semantic model call. ZERO web lookup. The
    answer was derived at build time by the same resolver and the same
    projection, and lives in a fingerprinted artifact
    (`skills.nutrition.preparation_artifact`). This function looks it up.

    WHY, MEASURED 2026-08-07. This used to gather evidence inline: bare
    `chicken` returned 8 USDA rows, qualification correctly kept ONE — refusing
    chicken spread, chicken FAT at 900 kcal and a frankfurter — and the
    semantic classification cost 8,992 ms for 8 records, 15,813 ms for 12. It
    then opened nothing, because the one survivor carried no preparation. The
    computed answer is a UNIVERSAL FACT: which preparations exist for chicken
    and how they price does not vary by user, by turn, or by day. Nine to
    sixteen seconds of an interactive request to re-derive a constant was the
    defect, not the evidence boundary — which was working exactly as designed.

    FAILS CLOSED. A food with no entry, a stale artifact, an unreadable one:
    every case returns `{}`, and `{}` means the field does not open. Nothing
    here can block, and nothing here can raise.

    `context` is accepted and unused. It stays in the signature because
    `unresolved_when` is called with it by `derive_unresolved` for every field,
    and a field that needs no turn-scoped evidence should not need a different
    shape from one that does.
    """
    from skills.nutrition import preparation_artifact as artifact

    space = artifact.space_for(food_name)
    logger.info("event=preparation_space_read food=%s preparations=%s",
                food_name, sorted(space))
    return space


