"""B-1: the canonical producer for ONE food's unresolved consumed mass.

The first slice where the canonical clarification path owns a real production
turn end to end — for exactly one shape of turn:

    "I had some chicken breast."

Deliberately food-specific and deliberately narrow. The generalized
`ClarificationOptionGenerator` across every field family is milestone 9;
building it here is how a vertical slice becomes a horizontal layer, and the
four legacy producers exist because that happened once already.

THE PIPELINE, and who owns each step (directive §Ownership):

    unresolved field  ->  candidates  ->  selection  ->  typed patches
                                                     ->  rendered labels

`candidates()` produces evidence. `select()` decides which evidence becomes an
offer. `build_interaction()` binds them to a semantic field. Labels are
rendered LAST, from the chosen quantities, and are never read back — a tap
returns `option_id`, and the meaning comes from the stored `SetQuantity`.

WHAT THIS DOES NOT INVENT. Both candidate sources already exist and are
already trusted for other purposes:

  * the user's own logged history for the same food (the resolver already
    treats it as ground truth over USDA);
  * the calibrated portion ontology's distribution — the SAME bracket
    `food_turn._portion_stakes` already computes to RANK this question and
    then discards. Offering the numbers that decided the question is worth
    asking introduces no new judgement.

Web search, LLM-proposed candidates, catalog variants and cross-unit ranking
are excluded from B-1 by the directive, not by accident.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: At most three numeric options. A fourth is not more helpful; it is a longer
#: row to read before answering, and the directive caps it here.
MAX_NUMERIC_OPTIONS = 3

#: Two options within this ratio of each other are the same answer wearing two
#: labels. `4.8 / 5.0 / 5.2` was the measured failure of ranking by
#: probability alone: three chips, one meaning, no information gained.
NEAR_DUPLICATE_RATIO = 1.25

#: Below this spread the question is not worth asking in the first place, so
#: it is not worth offering a bracket for either. Same bar the pipeline uses.
MIN_USEFUL_SPREAD = 1.35


class Ineligible(str, Enum):
    """WHY a turn is not B-1's. A typed reason rather than a bool, because
    "how often, and for what" is the measurement that sizes B-1.5 and B-2 —
    and a bare False cannot answer it."""
    ELIGIBLE = "eligible"
    NO_ITEMS = "no_items"
    MULTIPLE_ITEMS = "multiple_items"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    IDENTITY_AMBIGUOUS = "identity_ambiguous"      # product/variant/package
    QUANTITY_ALREADY_STATED = "quantity_already_stated"
    NO_QUANTITY_QUESTION = "no_quantity_question"
    OTHER_MATERIAL_AMBIGUITY = "other_material_ambiguity"
    PREPARATION_DEPENDENCY = "preparation_dependency"
    NOT_MASS = "not_mass"
    CORRECTION_TURN = "correction_turn"
    CLIENT_INCAPABLE = "client_incapable"
    NO_CANDIDATES = "no_candidates"


@dataclass(frozen=True)
class Eligibility:
    reason: Ineligible
    item: Any = None

    @property
    def ok(self) -> bool:
        return self.reason is Ineligible.ELIGIBLE


# ── eligibility ──────────────────────────────────────────────────────────────

#: Ambiguity fields whose presence means this is NOT a pure quantity turn.
#: Named positively rather than as "anything but quantity" so that a NEW
#: ambiguity type added later defaults to ineligible — B-1 declining a turn it
#: could have handled costs nothing; B-1 claiming one it cannot handle strands
#: a meal.
_QUANTITY_FIELDS = frozenset({"estimated_mass_g", "consumed_fraction"})


def is_eligible(decision, *, message: str = "",
                client_capable: bool = False) -> Eligibility:
    """Does this turn match B-1's predicate exactly?

    Conjunctive and conservative. Every clause is a thing B-1 has NOT built,
    so a decline is the correct outcome and the turn stays legacy, untouched.
    """
    if not client_capable:
        # NOT a fallback — an exclusion. Rendering canonical options as prose
        # for a client that cannot read the payload would keep the sentence
        # parser alive inside the replacement, which is the defect being
        # deleted. Old clients stay wholly legacy until they update.
        return Eligibility(Ineligible.CLIENT_INCAPABLE)

    items = tuple(getattr(decision, "staged_items", ()) or ())
    if not items:
        return Eligibility(Ineligible.NO_ITEMS)
    if len(items) > 1:
        return Eligibility(Ineligible.MULTIPLE_ITEMS)
    item = items[0]

    if _is_correction(message):
        return Eligibility(Ineligible.CORRECTION_TURN)

    identity = getattr(item, "identity", None)
    if not getattr(identity, "canonical_name", None):
        return Eligibility(Ineligible.IDENTITY_UNRESOLVED)

    quantity = getattr(item, "quantity", None)
    if getattr(quantity, "is_stated", False):
        # They told us. There is nothing to ask, and asking anyway is how a
        # clarification becomes an interrogation.
        return Eligibility(Ineligible.QUANTITY_ALREADY_STATED)

    material = tuple(getattr(item, "material_ambiguities", lambda: ())())
    if not material:
        return Eligibility(Ineligible.NO_QUANTITY_QUESTION)

    for amb in material:
        kind = getattr(getattr(amb, "ambiguity_type", None), "value", "")
        if getattr(getattr(amb, "ambiguity_type", None), "is_identity", False):
            return Eligibility(Ineligible.IDENTITY_AMBIGUOUS)
        if kind == "preparation":
            return Eligibility(Ineligible.PREPARATION_DEPENDENCY)
        if getattr(amb, "field_name", "") not in _QUANTITY_FIELDS:
            return Eligibility(Ineligible.OTHER_MATERIAL_AMBIGUITY)

    if not any(getattr(a, "field_name", "") == "estimated_mass_g"
               for a in material):
        # `consumed_fraction` alone is a fraction-of-a-container question —
        # B-2.5's slice, not a mass one.
        return Eligibility(Ineligible.NOT_MASS)

    return Eligibility(Ineligible.ELIGIBLE, item=item)


#: Correction and destructive wording. Kept literal and small: this is a
#: DECLINE gate, so a miss costs a legacy turn (today's behaviour) rather than
#: a wrong canonical one.
_CORRECTION_MARKERS = (
    "actually", "correct", "change", "undo", "delete", "remove", "instead",
    "meant", "not ", "yesterday", "earlier", "wrong", "fix ",
)


def _is_correction(message: str) -> bool:
    low = (message or "").lower()
    return any(m in low for m in _CORRECTION_MARKERS)


# ── candidates ───────────────────────────────────────────────────────────────

#: Masses are held to a tenth of a gram. Not a precision claim — nothing here
#: was weighed — but a STABILITY one: option ids, labels and stored patches all
#: derive from this number, and an unquantized 141.70000000000002 would make
#: two runs of the same evidence produce two different chips.
_GRAM_STEP = Decimal("0.1")


def _quantity(grams, *, provenance, unit_id: str = "g",
              confidence: float = 0.0, basis: str = "") -> Any:
    """A `CanonicalQuantity` in grams, WITHOUT a float round trip.

    `Decimal(str(v))`, never `Decimal(str(round(float(v), 1)))`: the second
    form re-widens an already-imprecise value into a binary float before
    narrowing it again, which is how `Decimal("0.1")` stops equalling itself.
    `CanonicalQuantity` holds `Decimal` precisely so a portion survives the
    round trip into storage that B-0c proved — spending that guarantee at the
    point of construction would make the guarantee decorative.
    """
    from core.semantics import CanonicalQuantity, Confidence, Dimension

    g = (grams if isinstance(grams, Decimal) else Decimal(str(grams)))
    g = g.quantize(_GRAM_STEP)
    return CanonicalQuantity(
        amount=g, unit_id=unit_id, dimension=Dimension.MASS, grams=g,
        provenance=provenance,
        confidence=Confidence(score=float(confidence), basis=basis))


async def candidates(db, *, user_id, item, message: str = "") -> tuple:
    """Everything this quantity could plausibly be, with its evidence.

    Ordered by the directive's authority ladder — the user's own history
    first, the calibrated ontology second — and NOT scored here. Producing
    evidence and choosing what to offer are different jobs with different
    owners (§Ownership); collapsing them is what made the legacy option
    builders unauditable.
    """
    from core.semantics import CandidateSource, CandidateValue, Provenance

    out = []
    name = str(getattr(getattr(item, "identity", None), "canonical_name", "")
               or "").strip()
    if not name:
        return ()

    # 1 — THE USER'S OWN LOG. Ground truth for a repeat item; it beats a
    # generic ontology row for the same reason it beats USDA.
    try:
        grams = await _history_grams(db, user_id, name)
    except Exception:
        logger.debug("b1 history candidate unavailable", exc_info=True)
        grams = None
    if grams:
        out.append(CandidateValue(
            candidate_id="hist_last",
            semantic_value=_quantity(grams, provenance=Provenance.USER_HISTORY,
                                     confidence=0.9,
                                     basis="the user's own last log"),
            source=CandidateSource.USER_HISTORY,
            probability=0.55, confidence=0.9))

    # 2 — THE CALIBRATED ONTOLOGY, via the bracket that already ranked this
    # question. `_portion_stakes` walks exactly this chain and throws the
    # distribution away.
    dist = _distribution_for(item, message, name)
    if dist is not None and dist.lower_g:
        wide = dist.upper_g / max(dist.lower_g, 1e-6) >= MIN_USEFUL_SPREAD
        anchors = ((("ont_low", dist.lower_g, 0.2),
                    ("ont_mid", dist.median_g, 0.5),
                    ("ont_high", dist.upper_g, 0.3)) if wide
                   else (("ont_mid", dist.median_g, 0.6),))
        for cid, g, prob in anchors:
            if not g:
                continue
            out.append(CandidateValue(
                candidate_id=cid,
                semantic_value=_quantity(
                    g, provenance=Provenance.ONTOLOGY,
                    confidence=float(getattr(dist, "confidence", 0.6) or 0.6),
                    basis=f"portion ontology ({getattr(dist, 'specificity', '')})"),
                source=CandidateSource.ONTOLOGY,
                probability=prob,
                confidence=float(getattr(dist, "confidence", 0.6) or 0.6)))

    return tuple(out)


async def _history_grams(db, user_id, food_name: str) -> Optional[float]:
    """The user's most recent NON-ESTIMATED log of this exact food, in grams.

    Reuses `_logged_history_match`'s guards deliberately: >=2 content tokens
    (so a bare "bagel" cannot speak for every bagel), exact content-token-set
    equality (so "grilled chicken breast" never answers for "chicken breast"),
    and `estimated_flag is False` — because a row is not ground truth just
    because we wrote it, and one bad auto-estimate would otherwise launder
    itself into a permanent chip.
    """
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from db.models import DailyLog, FoodEntry
    from handlers.tool_executor import _content_tokens

    tokens = _content_tokens(food_name)
    if len(tokens) < 2:
        return None
    cutoff = date.today() - timedelta(days=90)
    rows = (await db.execute(
        select(FoodEntry, DailyLog.date)
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id, DailyLog.date >= cutoff,
               FoodEntry.estimated_flag.is_(False),
               FoodEntry.quantity.isnot(None))
        .order_by(DailyLog.date.desc(), FoodEntry.id.desc()).limit(50))).all()
    for fe, _d in rows:
        if _content_tokens(fe.parsed_food_name or "") != tokens:
            continue
        from skills.nutrition.normalize import normalize_quantity
        nq = normalize_quantity(fe.quantity or "", fe.parsed_food_name or "")
        if nq is not None and getattr(nq, "grams", None):
            return float(nq.grams)
    return None


def _distribution_for(item, message: str, name: str):
    """The ontology's distribution for the user's own vague word, or for the
    food itself when they used none.

    `vague_measure` is read off the STAGED ITEM first: it was recorded on the
    turn whose message contained the word, and re-deriving it from whatever
    message is current loses it the moment a meal spans two turns.
    """
    try:
        from skills.nutrition.portions import distribution_for
        measure = (str(getattr(item, "vague_measure", "") or "").strip()
                   or _measure_in(message, name))
        if not measure:
            # No hedge of their own — the food's own typical serving is still
            # honest evidence, and "some" is the neutral row for it.
            measure = "some"
        return distribution_for(measure, name)
    except Exception:
        logger.debug("b1 ontology candidate unavailable", exc_info=True)
        return None


def _measure_in(message: str, name: str) -> str:
    try:
        from core.food_pipeline import _vague_measure_in
        return _vague_measure_in(message or "", name or "") or ""
    except Exception:
        return ""


# ── selection ────────────────────────────────────────────────────────────────

def select(candidates_in, *, field, food_name: str = "") -> tuple:
    """Which candidates become offers, and what each one MEANS.

    NOT top-N by probability — that returns near-duplicates, which is how
    `4.8 / 5.0 / 5.2` reached a screen. Rank by `probability x source
    confidence`, then accept a candidate only if it says something the already
    accepted ones do not: information gain, expressed as distance.

    Every returned option carries a typed `SetQuantity`. There is no path here
    that produces a label without a patch, so "a canonical option always has a
    patch" holds by construction rather than by review.
    """
    from dataclasses import replace

    from core.semantics import ClarificationOption, Provenance, SetQuantity

    ranked = sorted(
        (c for c in (candidates_in or ())
         if getattr(c.semantic_value, "grams", None)),
        key=lambda c: (float(c.probability) * float(c.confidence)),
        reverse=True)

    chosen = []
    for cand in ranked:
        if len(chosen) >= MAX_NUMERIC_OPTIONS:
            break
        grams = float(cand.semantic_value.grams)
        if any(_near(grams, float(c.semantic_value.grams)) for c in chosen):
            continue
        chosen.append(cand)
    chosen.sort(key=lambda c: float(c.semantic_value.grams))
    if not chosen:
        return ()

    # DEDUPE AGAIN ON WHAT THE USER ACTUALLY READS.
    #
    # The pass above compares GRAMS; a chip row is compared by eye. Measured
    # on the first wired turn: chicken breast's ontology bracket
    # (130.5 / 174 / 435 g) is well separated numerically — 1.33x between the
    # first two — and renders as "5 oz / 6 oz / 16 oz". Nobody reads 5 and 6
    # ounces as two different answers, so that row offers three chips and two
    # choices, and the third is a pound of chicken.
    #
    # The test is the label's own re-parsed mass, which is the same
    # philosophy `_everyday_labels` already applies to accept a rendering at
    # all: if two labels MEAN nearly the same thing when read back, they are
    # one option. Ranked order breaks the tie, so the better-evidenced
    # candidate keeps its slot.
    chosen, labels = _collapse_by_label(chosen, ranked, food_name)

    options = []
    for cand, label in zip(chosen, labels):
        # A TAP IS A SELECTION, NOT A STATEMENT. The user accepted a figure we
        # produced; recording it as their own is the measured 2026-08-04
        # disclosure defect, and provenance is the only thing that keeps the
        # distinction once the answer applies.
        quantity = replace(cand.semantic_value,
                           provenance=Provenance.USER_SELECTED)
        options.append(ClarificationOption(
            label=label,
            option_id=f"opt_{cand.candidate_id}",
            field_id=field.field_id,
            patch=SetQuantity(event_id=field.event_id,
                              field_id=field.field_id, quantity=quantity,
                              provenance=Provenance.USER_SELECTED),
            source=cand.source))
    return tuple(options)


def _near(a: float, b: float) -> bool:
    lo, hi = min(a, b), max(a, b)
    return lo > 0 and hi / lo < NEAR_DUPLICATE_RATIO


def _collapse_by_label(chosen, ranked, food_name: str):
    """Drop options whose LABELS say the same thing, then re-render.

    Re-rendering after each drop is not wasted work: `_everyday_labels` picks
    a rendering per anchor relative to its neighbours, so removing one anchor
    can legitimately change how the survivors are said.
    """
    rank = {id(c): i for i, c in enumerate(ranked)}
    while True:
        labels = labels_for(tuple(float(c.semantic_value.grams)
                                  for c in chosen), food_name)
        drop = None
        for i in range(len(chosen) - 1):
            a, b = _label_mass(labels[i], food_name), \
                _label_mass(labels[i + 1], food_name)
            if labels[i] == labels[i + 1] or (
                    a and b and _near(a, b)):
                # Keep the better-evidenced one; ranked order decided that.
                drop = (i if rank.get(id(chosen[i]), 99)
                        > rank.get(id(chosen[i + 1]), 99) else i + 1)
                break
        if drop is None:
            return chosen, labels
        chosen = chosen[:drop] + chosen[drop + 1:]
        if len(chosen) <= 1:
            return chosen, labels_for(
                tuple(float(c.semantic_value.grams) for c in chosen),
                food_name)


def _label_mass(label: str, food_name: str) -> Optional[float]:
    """What this label means when READ BACK — the only definition of "these
    two chips say the same thing" that matches how a user compares them."""
    try:
        from skills.nutrition.normalize import normalize_quantity
        grams = normalize_quantity(label, food_name or "").grams
        return float(grams) if grams else None
    except Exception:
        return None


def labels_for(grams: tuple, food_name: str = "") -> tuple:
    """Ascending grams, said in the unit the user serves this food in.

    Rendered LAST and never read back. `_everyday_labels` already owns this
    judgement — ounces for meat, cups for rice — and its acceptance test is
    entirely derived: a label survives only if its re-parsed mass is closer to
    its OWN anchor than to a neighbour's, so a chip can never silently stand
    in for a portion the user did not mean. That check is relative to the
    whole row, which is why the row is rendered in one call rather than a
    label at a time. Grams remain the fallback and remain what all of this is
    measured in.
    """
    try:
        from core.food_pipeline import _everyday_labels
        rendered = _everyday_labels(tuple(grams), food_name or "")
        if rendered and len(rendered) == len(grams):
            return tuple(str(r) for r in rendered)
    except Exception:
        logger.debug("everyday labels unavailable", exc_info=True)
    return tuple(f"{int(round(g))}g" for g in grams)


# ── the interaction ──────────────────────────────────────────────────────────

def event_id_for(item) -> str:
    """The event a patch targets. The staged item's id, which is stable across
    the ask and the answer turn — unlike list position or display text, which
    is what the adapter's ids were made of and why an answer could land on the
    wrong row."""
    return f"food_{getattr(item, 'staged_item_id', '') or 'unknown'}"


def build_interaction(*, operation_id: str, revision: int, item,
                      options, introduction: str = "") -> Any:
    """One group, one field, ID-addressed.

    Structural validity is not re-checked here: `UnresolvedField`,
    `ClarificationGroup` and `ClarificationInteraction` refuse a mixed row, a
    foreign-field option, an operation mismatch and a blank select at
    construction (B-0c). Re-implementing those checks in the producer is how
    two owners of one invariant appear.
    """
    from core.semantics import ClarificationGroup, ClarificationInteraction

    event_id = event_id_for(item)
    field = quantity_field(operation_id=operation_id, revision=revision,
                           item=item, options=options)
    label = str(getattr(getattr(item, "identity", None), "canonical_name", "")
                or getattr(item, "original_text", "") or "").strip()
    return ClarificationInteraction(
        interaction_id=f"ix_{operation_id}:{revision}",
        operation_id=operation_id, revision=revision,
        introduction=introduction,
        groups=(ClarificationGroup(event_id=event_id, label=label,
                                   fields=(field,)),))


def quantity_field(*, operation_id: str, revision: int, item, options=(),
                   uncertainty=None) -> Any:
    """The one unresolved field B-1 owns.

    `FREE_TEXT_FALLBACK` when nothing could be offered, never an empty select:
    C15 exists because a blank options row is what the client "repaired" by
    parsing prose. Saying the fallback out loud is the whole difference.
    """
    from core.semantics import (ClarificationAttribute, ResponseType,
                                UncertaintyEvidence, UnresolvedField)

    return UnresolvedField(
        operation_id=operation_id, revision=revision,
        event_id=event_id_for(item),
        attribute=ClarificationAttribute.QUANTITY,
        allowed_dimensions=("mass",), allowed_units=("g", "oz"),
        uncertainty=uncertainty or UncertaintyEvidence(),
        response_type=(ResponseType.SINGLE_SELECT if options
                       else ResponseType.FREE_TEXT_FALLBACK),
        options=tuple(options or ()))
