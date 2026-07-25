"""The clarification policy engine (build order 7, 8, 15, 25).

Given every ambiguity across every item in a meal, decide: what can be assumed,
what must be held, what to ask, and in what order.

Three rules shape it.

**Clear foods are never re-questioned because a neighbour is ambiguous.** The
decision is per item; the transaction policy is per meal. Those are different
things, and conflating them is what makes a system ask about the chicken
because the sauce was vague.

**Strictness changes the threshold and the transaction policy, not the truth.**
Quick commits with visible assumptions, moderate commits what is clear and
holds what is not, strict holds the meal and commits atomically. The nutrition
answer is identical in all three.

**One good question beats three narrow ones.** "Which Fairlife bottle, and did
you drink the whole thing?" resolves product line, package size and consumed
fraction in one turn. Questions are ranked by what they resolve divided by
what they cost the user, and bundled when they are naturally answered together.

The decision table (build order 25) is data at the bottom of this module, not
nested conditionals, so every row can be tested.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodAssumption, ResolutionStatus,
                                      StagedFoodItem)


class TransactionPolicy(str, Enum):
    COMMIT_WITH_ASSUMPTIONS = "commit_with_assumptions"
    PARTIAL_COMMIT = "partial_commit"
    ATOMIC_HOLD = "atomic_hold"


class ResponseSchema(str, Enum):
    """What shape of answer a question expects. The point of naming it is that
    the ANSWER can then be parsed narrowly — sending "Elite, about half"
    through the full food interpreter is how it becomes a new meal."""
    PRODUCT_SELECTION = "product_selection"
    PRODUCT_AND_FRACTION = "product_and_fraction"
    QUANTITY = "quantity"
    SERVING_BASIS = "serving_basis"
    NUTRIENT_VALUES = "nutrient_values"
    YES_NO = "yes_no"


MODE_POLICY = {
    "quick": TransactionPolicy.COMMIT_WITH_ASSUMPTIONS,
    "moderate": TransactionPolicy.PARTIAL_COMMIT,
    "strict": TransactionPolicy.ATOMIC_HOLD,
}

#: How many blocking rounds a mode will spend before offering the exits
#: (label entry, pick-closest, conservative estimate). Re-asking a fourth time
#: is interrogation, not clarification.
MAX_ROUNDS = {"quick": 1, "moderate": 2, "strict": 3}

#: Roughly what each answer shape costs the user. Used as the denominator in
#: question ranking — a yes/no is nearly free, typing label values is not.
EFFORT = {
    ResponseSchema.YES_NO: 1.0,
    ResponseSchema.PRODUCT_SELECTION: 1.2,
    ResponseSchema.QUANTITY: 1.5,
    ResponseSchema.SERVING_BASIS: 1.5,
    ResponseSchema.PRODUCT_AND_FRACTION: 1.8,
    ResponseSchema.NUTRIENT_VALUES: 3.0,
}

#: Ambiguities that are naturally answered in one breath, and the schema that
#: parses the combined answer. Order matters: the first matching bundle wins.
BUNDLES = (
    ({AmbiguityType.PRODUCT_LINE, AmbiguityType.PACKAGE_SIZE,
      AmbiguityType.CONSUMED_QUANTITY}, ResponseSchema.PRODUCT_AND_FRACTION),
    # "Which one, and how much of it?" — any identity question pairs naturally
    # with the portion question. PRODUCT_LINE was missing here, which meant the
    # directive's own headline example ("Which Fairlife bottle was it, and did
    # you drink the whole thing?") did not bundle: the brand was known, so the
    # ambiguity was PRODUCT_LINE rather than PRODUCT_IDENTITY.
    ({AmbiguityType.PRODUCT_IDENTITY, AmbiguityType.CONSUMED_QUANTITY},
     ResponseSchema.PRODUCT_AND_FRACTION),
    ({AmbiguityType.PRODUCT_LINE, AmbiguityType.CONSUMED_QUANTITY},
     ResponseSchema.PRODUCT_AND_FRACTION),
    ({AmbiguityType.PRODUCT_VARIANT, AmbiguityType.CONSUMED_QUANTITY},
     ResponseSchema.PRODUCT_AND_FRACTION),
    ({AmbiguityType.PACKAGE_SIZE, AmbiguityType.CONSUMED_QUANTITY},
     ResponseSchema.PRODUCT_AND_FRACTION),
    ({AmbiguityType.PRODUCT_LINE, AmbiguityType.PACKAGE_SIZE},
     ResponseSchema.PRODUCT_SELECTION),
    ({AmbiguityType.PRODUCT_LINE, AmbiguityType.PRODUCT_VARIANT},
     ResponseSchema.PRODUCT_SELECTION),
)

_SCHEMA_BY_TYPE = {
    AmbiguityType.PRODUCT_IDENTITY: ResponseSchema.PRODUCT_SELECTION,
    AmbiguityType.PRODUCT_LINE: ResponseSchema.PRODUCT_SELECTION,
    AmbiguityType.PRODUCT_VARIANT: ResponseSchema.PRODUCT_SELECTION,
    AmbiguityType.PACKAGE_SIZE: ResponseSchema.PRODUCT_SELECTION,
    AmbiguityType.CONSUMED_QUANTITY: ResponseSchema.QUANTITY,
    AmbiguityType.SERVING_BASIS: ResponseSchema.SERVING_BASIS,
    AmbiguityType.PREPARATION: ResponseSchema.PRODUCT_SELECTION,
    AmbiguityType.COMPONENT_BREAKDOWN: ResponseSchema.QUANTITY,
    AmbiguityType.UNIT_INTERPRETATION: ResponseSchema.QUANTITY,
}


@dataclass(frozen=True)
class ClarificationOption:
    """One offered answer.

    `field_name` is what makes bundled questions parseable: a bundle offers
    product options AND portion options together, and without knowing which
    field an option answers, a parser matching "about half" against the whole
    list can assign it to product_line.
    """
    label: str
    value: object = None
    candidate_id: Optional[str] = None
    field_name: str = ""


@dataclass(frozen=True)
class ClarificationQuestion:
    """One question, bound to one staged item and the exact fields it will
    fill. `requested_fields` is what makes the answer applicable without
    re-interpreting the meal."""
    question_id: str
    staged_item_id: str
    requested_fields: tuple
    prompt: str
    response_schema: ResponseSchema
    options: tuple = ()
    ambiguity_ids: tuple = ()
    resolved_materiality: float = 0.0
    value: float = 0.0
    allows_free_text: bool = True


@dataclass(frozen=True)
class ClarificationDecision:
    assumptions: tuple = ()
    questions: tuple = ()
    ready_item_ids: tuple = ()
    held_item_ids: tuple = ()
    transaction_policy: TransactionPolicy = TransactionPolicy.PARTIAL_COMMIT
    exhausted: bool = False          # rounds spent; offer the exits

    @property
    def asks(self) -> bool:
        return bool(self.questions)


# ── question construction ─────────────────────────────────────────────────────
def _question_id(staged_item_id: str, fields: tuple) -> str:
    digest = hashlib.sha1(
        f"{staged_item_id}|{'+'.join(sorted(fields))}".encode("utf-8")
    ).hexdigest()[:10]
    return f"q_{digest}"


def _bundle_for(types: set):
    for members, schema in BUNDLES:
        if members <= types:
            return members, schema
    return None, None


def build_questions_for_item(item: StagedFoodItem,
                             material: tuple) -> tuple:
    """Turn one item's material ambiguities into as few questions as possible.

    Bundling is not cosmetic: three separate turns to establish which bottle,
    what size and how much of it is a worse experience than one sentence, and
    the answer to the sentence is unambiguous because we asked for all three.
    """
    if not material:
        return ()
    by_type = {a.ambiguity_type: a for a in material}
    members, schema = _bundle_for(set(by_type))
    questions = []

    if members:
        bundled = [by_type[t] for t in by_type if t in members]
        fields = tuple(a.field_name for a in bundled)
        prompt = _bundle_prompt(item, bundled, schema)
        resolved = sum(a.materiality_score for a in bundled)
        questions.append(ClarificationQuestion(
            question_id=_question_id(item.staged_item_id, fields),
            staged_item_id=item.staged_item_id, requested_fields=fields,
            prompt=prompt, response_schema=schema,
            options=_options_from(bundled),
            ambiguity_ids=tuple(a.ambiguity_id for a in bundled),
            resolved_materiality=round(resolved, 3),
            value=round(resolved / EFFORT.get(schema, 1.5), 3)))
        remaining = [a for a in material if a.ambiguity_type not in members]
    else:
        remaining = list(material)

    for amb in remaining:
        schema = _SCHEMA_BY_TYPE.get(amb.ambiguity_type,
                                     ResponseSchema.QUANTITY)
        questions.append(ClarificationQuestion(
            question_id=_question_id(item.staged_item_id, (amb.field_name,)),
            staged_item_id=item.staged_item_id,
            requested_fields=(amb.field_name,),
            prompt=amb.clarification_prompt or _default_prompt(item, amb),
            response_schema=schema, options=_options_from([amb]),
            ambiguity_ids=(amb.ambiguity_id,),
            resolved_materiality=round(amb.materiality_score, 3),
            value=round(amb.materiality_score / EFFORT.get(schema, 1.5), 3)))
    return tuple(questions)


def _options_from(ambiguities) -> tuple:
    out = []
    for amb in ambiguities:
        for opt in amb.top_options(4):
            out.append(ClarificationOption(label=opt.label, value=opt.payload,
                                           candidate_id=opt.candidate_id,
                                           field_name=amb.field_name))
    return tuple(out)


def _label(item: StagedFoodItem) -> str:
    return (item.identity.describe() or item.original_text or "that").strip()


def _bundle_prompt(item, bundled, schema) -> str:
    stated = [a.clarification_prompt for a in bundled if a.clarification_prompt]
    if len(stated) == len(bundled) == 1:
        return stated[0]
    if schema is ResponseSchema.PRODUCT_AND_FRACTION:
        return (f"Which {_label(item)} was it, and did you have the whole "
                f"thing?")
    return f"Which {_label(item)} was it?"


def _default_prompt(item, amb: FoodAmbiguity) -> str:
    if amb.ambiguity_type is AmbiguityType.CONSUMED_QUANTITY:
        return f"How much of the {_label(item)}?"
    if amb.ambiguity_type is AmbiguityType.SERVING_BASIS:
        return f"Is that per serving or for the whole {_label(item)}?"
    if amb.ambiguity_type is AmbiguityType.PREPARATION:
        return f"How was the {_label(item)} cooked?"
    return f"Which {_label(item)} was it?"


# ── the decision ──────────────────────────────────────────────────────────────
def decide(items, *, mode: str = "moderate", round_number: int = 0,
           max_questions: int = 2) -> ClarificationDecision:
    """One decision for the whole meal, made per item.

    An item with no material ambiguity is ready regardless of what its
    neighbours are doing. Whether "ready" means committed now depends on the
    transaction policy, which is the only thing mode changes here.
    """
    mode = (mode or "moderate").strip().lower()
    policy = MODE_POLICY.get(mode, TransactionPolicy.PARTIAL_COMMIT)
    exhausted = round_number >= MAX_ROUNDS.get(mode, 2)

    ready, held, questions, assumptions = [], [], [], []

    for item in items or []:
        if item.resolution_status is ResolutionStatus.REJECTED:
            continue
        material = tuple(a for a in item.ambiguities if a.is_material)
        if not material:
            ready.append(item.staged_item_id)
            # An ESTIMATED portion is an assumption whether or not it was worth
            # asking about. Materiality governs asking; disclosure is
            # unconditional, or "some blueberries" commits at 80 g with nothing
            # said and the user has no idea a number was invented.
            assumptions.extend(_estimated_portion_assumptions(item))
            continue
        if exhausted:
            # Out of rounds: stop asking, assume the leading option, and say
            # so. Repeating a question the user has already declined to answer
            # is interrogation.
            held.append(item.staged_item_id)
            assumptions.extend(_assume_leading(item, material))
            continue
        if policy is TransactionPolicy.COMMIT_WITH_ASSUMPTIONS:
            # Quick still asks when the leading option is genuinely weak —
            # committing a coin toss is not "low friction", it is wrong.
            if _is_coin_toss(material):
                held.append(item.staged_item_id)
                questions.extend(build_questions_for_item(item, material))
            else:
                ready.append(item.staged_item_id)
                assumptions.extend(_assume_leading(item, material))
            continue
        held.append(item.staged_item_id)
        questions.extend(build_questions_for_item(item, material))

    # Rank across the WHOLE meal: what a question resolves per unit of effort.
    questions.sort(key=lambda q: -q.value)
    questions = questions[:max_questions]

    if policy is TransactionPolicy.ATOMIC_HOLD and held:
        # Strict commits the meal as one transaction or not at all, so a clear
        # item waits with the rest. It is still not RE-QUESTIONED — it simply
        # is not committed yet.
        held = [i.staged_item_id for i in items
                if i.resolution_status is not ResolutionStatus.REJECTED]
        ready = []

    return ClarificationDecision(
        assumptions=tuple(assumptions), questions=tuple(questions),
        ready_item_ids=tuple(ready), held_item_ids=tuple(held),
        transaction_policy=policy, exhausted=exhausted)


def _is_coin_toss(material, margin: float = 0.15) -> bool:
    """True when the leading option is not meaningfully ahead. A 0.9/0.05
    split is barely ambiguous; 0.35/0.33 is a guess wearing a confidence
    score."""
    for amb in material:
        opts = amb.top_options(2)
        if len(opts) < 2:
            continue
        if (opts[0].confidence - opts[1].confidence) < margin:
            return True
    return False


def _estimated_portion_assumptions(item: StagedFoodItem) -> list:
    """Disclose an inferred portion mass.

    Not gated on materiality: the user said "some blueberries" and we wrote a
    number. Whether that number was worth interrupting them for is a separate
    question from whether they should be told it was ours.
    """
    from skills.nutrition.staging import NutrientDeltaRange
    q = item.quantity
    if q.is_stated or q.estimated_mass_g is None:
        return []
    label = (item.identity.describe() or item.original_text or "that").strip()
    said = (q.descriptor or "that").strip()
    return [FoodAssumption(
        staged_item_id=item.staged_item_id, field_name="estimated_mass_g",
        assumed_value=q.estimated_mass_g,
        alternatives=(tuple(q.mass_range_g) if q.mass_range_g else ()),
        confidence=(q.mass_confidence if q.mass_confidence is not None else 0.5),
        nutrition_impact=NutrientDeltaRange(),
        user_visible_text=(f"Estimated “{said}” of the {label} at about "
                           f"{_round_g(q.estimated_mass_g)}g."))]


def _round_g(grams) -> str:
    try:
        return str(int(round(float(grams))))
    except (TypeError, ValueError):
        return str(grams)


def _assume_leading(item: StagedFoodItem, material) -> list:
    """Take the leading option and record what was assumed, what it could have
    been, and roughly what being wrong costs."""
    from skills.nutrition.staging import NutrientDeltaRange
    out = []
    for amb in material:
        opts = amb.top_options(3)
        if not opts:
            continue
        lead, alts = opts[0], opts[1:]
        out.append(FoodAssumption(
            staged_item_id=item.staged_item_id, field_name=amb.field_name,
            assumed_value=(lead.payload if lead.payload is not None
                           else lead.label),
            alternatives=tuple(o.label for o in alts),
            confidence=lead.confidence,
            nutrition_impact=NutrientDeltaRange(
                calories=amb.calorie_span or 0.0,
                protein=amb.protein_span or 0.0,
                carbs=amb.carb_span or 0.0, fat=amb.fat_span or 0.0),
            user_visible_text=f"Logged the {lead.label} — say the word if it "
                              f"was something else."))
    return out


# ── the decision table (build order 25) ───────────────────────────────────────
#: (mode, identity_exact, quantity_vague, materiality_band) → expected action.
#: Data, so every row is testable; the engine above must agree with it.
ACTIONS = ("estimate_and_commit", "ask", "hold_and_clarify")

DECISION_TABLE = (
    ("quick",    True,  True,  "low",    "estimate_and_commit"),
    ("quick",    True,  True,  "high",   "estimate_and_commit"),
    ("quick",    False, True,  "high",   "ask"),
    ("moderate", True,  True,  "medium", "ask"),
    ("moderate", True,  False, "low",    "estimate_and_commit"),
    ("moderate", False, False, "high",   "ask"),
    ("strict",   True,  True,  "low",    "ask"),
    ("strict",   False, True,  "high",   "hold_and_clarify"),
    ("strict",   False, False, "high",   "hold_and_clarify"),
)
