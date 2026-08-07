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

import asyncio
import logging
import time as _time

from skills.nutrition import evidence_semantics as food

logger = logging.getLogger(__name__)

#: How far apart two preparations must price before asking is worth the
#: interruption. 25% of the lower density — same order as the quantity
#: slice's spread floor, and for the same reason: a question that cannot move
#: the number by more than rounding is an interruption, not a clarification.
MATERIAL_SPREAD = 1.25

#: Bounded web results for the materiality claim. Small deliberately: this is
#: evidence that a preparation EXISTS and is material, not a survey.
_WEB_RESULTS = 5

#: HOW LONG THE INTERACTION MAY WAIT for materiality that is still in flight.
#:
#: Measured 2026-08-07: starting the supplemental lookup inside
#: `derive_unresolved` cost a production turn 6.8 seconds and still opened
#: nothing. Speculation moves the work earlier; this bounds what the user pays
#: when it is nevertheless unfinished.
#:
#: THE RULE ON EXPIRY IS "DO NOT ASK", never "guess" and never "wait longer".
#: A small grace period to collapse two turns into one is worth paying; making
#: someone watch a spinner while Arnie researches a second question is not.
MATERIALITY_BUDGET_S = 1.5


def supplemental_key(food_name: str) -> str:
    return f"web-materiality:{str(food_name or '').strip().lower()}:{food.VERSION}"


def start_supplemental(food_name: str, context=None) -> None:
    """Begin the relevance-only materiality lookup NOW, at identity time.

    SPECULATION, NOT DEFERRAL. For a generic food the corpus says structured
    evidence usually cannot establish grilled/roasted/fried at all, so the web
    lookup is the PRIMARY source for preparation materiality — and starting it
    when `derive_unresolved` runs is structurally too late: it lands squarely
    on the critical path of the ask.

    Fire-and-forget by design. The context owns the future; whoever needs it
    awaits it, and if nobody does it is simply dropped with the turn.
    """
    import asyncio

    from core.evidence_context import ensure

    shared = ensure(context)
    key = supplemental_key(food_name)
    if shared.reused(key):
        return
    shared._inflight[key] = asyncio.ensure_future(
        _web_space(food_name, exclude=frozenset()))
    logger.info("event=materiality_speculated food=%s", food_name)


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
    if len(space) < 2:
        return False

    densities = [kcal for kcal in space.values() if kcal]
    if len(densities) < 2:
        # Two preparations exist and we cannot price the difference, so we
        # cannot show the question is worth asking. Silence beats a guess.
        logger.info("event=preparation_space food=%s preparations=%s "
                    "material=unknown_no_densities", name, sorted(space))
        return False

    low, high = min(densities), max(densities)
    material = low > 0 and (high / low) >= MATERIAL_SPREAD
    logger.info("event=preparation_space food=%s preparations=%s low=%.0f "
                "high=%.0f ratio=%.2f material=%s",
                name, sorted(space), low, high,
                (high / low) if low else 0.0, material)
    return material


async def preparation_space(food_name: str, context=None) -> dict:
    """`{preparation_id: kcal_per_100g or None}` the evidence supports.

    THE SPACE, not the answer. Structured evidence first — shared with the
    pricing path through the turn's `EvidenceContext`, so whichever consumer
    arrives first starts the work and the other AWAITS THE SAME FUTURE — then
    one bounded web query for the materiality claim, which is the only claim
    web may support.
    """
    from core.evidence_context import ensure
    from skills.nutrition.evidence_qualification import assessment_key

    shared = ensure(context)
    space: dict = {}
    key = assessment_key(food_name, food.VERSION)
    reused = shared.reused(key)

    structured = await _structured_assessments(shared, key, food_name)
    if structured:
        records, assessments = structured
        for evidence in food.preparation_evidence(
                assessments, records,
                minimum_confidence=food.MINIMUM_IDENTITY_CONFIDENCE):
            if evidence.kcal_per_100g is not None or \
                    evidence.preparation_id not in space:
                space.setdefault(evidence.preparation_id,
                                 evidence.kcal_per_100g)

    from_structured = len(space)

    # THE DEADLINE. Supplemental evidence is awaited only for the remaining
    # budget: already resolved costs nothing, in flight costs at most the
    # grace period, and an expired wait means UNKNOWN — omit preparation.
    # NO NEW LOOKUP IS LAUNCHED HERE; if speculation never started one, this
    # turn simply has no supplemental evidence.
    web, waited_ms, timed_out = {}, 0, False
    web_key = supplemental_key(food_name)
    if shared.reused(web_key):
        started = _time.monotonic()
        try:
            web = await asyncio.wait_for(
                shared.shared(web_key, _never), timeout=MATERIALITY_BUDGET_S)
        except asyncio.TimeoutError:
            timed_out = True
            logger.info("event=materiality_deadline food=%s budget_s=%.1f — "
                        "UNKNOWN, not asking", food_name,
                        MATERIALITY_BUDGET_S)
        except Exception:
            logger.warning("event=materiality_supplemental_failed food=%s",
                           food_name, exc_info=True)
        waited_ms = int((_time.monotonic() - started) * 1000)
    space.update(web)

    shared.note(preparation={
        "assessments_reused": reused,
        "from_structured": from_structured,
        "from_supplemental": len(web),
        "supplemental_speculated": shared.reused(web_key),
        "grace_ms": waited_ms,
        "deadline_expired": timed_out,
    })
    return space


async def _structured_assessments(shared, key: str, food_name: str):
    """The turn's structured classification, AWAITED not duplicated.

    If the pricing path already started it, this awaits that future. If it has
    not run at all — the food never reached enrichment this turn — preparation
    does NOT start its own retrieval: acquisition belongs to the pricing path,
    and a second retrieval path is exactly what §4 forbids.
    """
    if not shared.reused(key):
        return None
    try:
        return await shared.shared(key, _never)
    except Exception:
        logger.warning("event=preparation_structured_unavailable food=%s",
                       food_name, exc_info=True)
        return None


async def _never():                                  # pragma: no cover
    raise RuntimeError("acquisition belongs to the pricing path")


async def _web_space(food_name: str, exclude=frozenset()) -> dict:
    """Preparations the web says exist for this food, with densities.

    ACQUISITION, called only through `EvidenceContext.shared` — never
    directly by a field. Fields project and request; the context owns whether
    the work is already running.

    ASKED, NOT FILTERED. Source quality is a function of query construction
    (measured: the same claim asked loose returns Instagram; asked at a
    government domain returns USDA four times), so this names the authority
    rather than grading whatever comes back.
    """
    from core import search
    from core.semantic_evidence import resolve
    from skills.nutrition.evidence_qualification import _default_complete

    wanted = [p for p in _registered_preparations() if p not in exclude]
    if not wanted:
        return {}

    query = (f"site:fdc.nal.usda.gov OR site:nal.usda.gov {food_name} "
             f"{' '.join(wanted)} calories per 100 g")
    try:
        result = await search.search(query)
    except Exception:
        logger.warning("event=preparation_web_lookup_failed food=%s",
                       food_name, exc_info=True)
        return {}

    records = food.from_web(result)[:_WEB_RESULTS]
    if not records:
        return {}
    try:
        assessments = await resolve(
            food.DOMAIN, food.FoodIntent(base_identity=food_name), records,
            _default_complete)
    except Exception:
        logger.warning("event=preparation_web_assessment_failed food=%s",
                       food_name, exc_info=True)
        return {}

    out: dict = {}
    for evidence in food.preparation_evidence(
            assessments, records,
            minimum_confidence=food.MINIMUM_IDENTITY_CONFIDENCE):
        out.setdefault(evidence.preparation_id, evidence.kcal_per_100g)
    return out


def _registered_preparations() -> tuple:
    from core.semantic_fields import spec_for

    return tuple(spec_for("preparation").vocabulary)
