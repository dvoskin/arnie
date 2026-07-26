"""The one food-resolution path (review 2026-07-25, P0).

The staged-item architecture — StagedFoodItem, candidate sets, the
multi-dimensional ambiguity engine, the clarification policy, MealResolution —
was built, tested, and never put in the way of a real turn. Meanwhile the live
path kept using the interpreter's JSON and the calorie-only
`food_ledger.material_ambiguities()`. Two architectures, one of them
unreachable.

This is the seam that ends that. It takes what the interpreter produced and
runs it through the real machinery:

    interpreter output
      → StagedFoodItem[]            identity and quantity separated
      → ambiguities                 calorie/protein/carb/fat/identity/basis
      → learned preferences         applied as assumptions, never silently
      → ClarificationDecision       per-item ready/held, per-meal policy
      → approved commands           the only things that may execute

and, after execution, assembles the MealResolution that owns committed state.

Deliberately NOT a third path. It is called from inside `core.food_turn.run()`,
which is what the live turn already uses and what the coordinator's food stage
delegates to — so both callers get the same decisions, and promoting the
coordinator changes orchestration without changing food intelligence.

The pipeline never writes. It decides what may be written.
"""
from __future__ import annotations

import logging
import re
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "food_pipeline_v1"


def pipeline_enabled() -> bool:
    """The staged-item pipeline owns the ask decision.

    Default ON: the modules are heavily tested and the fallback is total — any
    failure returns None and the caller keeps the legacy policy. Set
    FOOD_PIPELINE=false to pin the old calorie-only thresholds.
    """
    raw = (os.getenv("FOOD_PIPELINE", "true") or "").strip().lower()
    return raw not in ("false", "0", "no", "off")


@dataclass(frozen=True)
class FoodTurnDecision:
    """What the pipeline decided, before anything executes."""
    staged_items: Tuple[Any, ...] = ()
    clarification: Any = None
    approved_operations: Tuple[Mapping, ...] = ()
    meal_group_id: str = ""
    traces: Tuple[Any, ...] = ()
    pipeline_version: str = PIPELINE_VERSION

    @property
    def asks(self) -> bool:
        return bool(getattr(self.clarification, "questions", ()))

    @property
    def question(self):
        qs = getattr(self.clarification, "questions", ()) or ()
        return qs[0] if qs else None

    @property
    def holds_everything(self) -> bool:
        return bool(self.staged_items) and not self.approved_operations


# ── interpreter output → staged items ─────────────────────────────────────────
def stage_items(data: Mapping, *, turn_id: str, message: str = "",
                mode: str = "moderate") -> tuple:
    """Turn the interpreter's item list into StagedFoodItems.

    This is where identity stops being a string. `food` becomes a FoodIdentity
    with brand/line/variant where the interpreter supplied them, and the amount
    becomes a QuantityIntent that records whether the USER stated it or we
    inferred it — the distinction the old path collapsed and then could not ask
    about.
    """
    from skills.nutrition.staging import (FoodClass, FoodIdentity,
                                          QuantityIntent, StagedFoodItem,
                                          classify_food, make_meal_group_id,
                                          make_staged_item_id)
    from core.food_turn import _item_is_stated

    meal_group_id = make_meal_group_id(turn_id)
    items = []
    for ordinal, raw in enumerate(data.get("items") or []):
        if not isinstance(raw, Mapping):
            continue
        food = str(raw.get("food") or "").strip()
        if not food:
            continue
        brand = (str(raw.get("brand") or "").strip() or None)
        stated = _item_is_stated(dict(raw), message)
        amount = raw.get("amount")
        value = float(amount) if _is_number(amount) else None
        unit = str(raw.get("unit") or "").strip() or None
        # The amount lands in `stated_*` ONLY when the user gave it. An
        # interpreter-chosen amount goes to `inferred_*`, so everything
        # downstream can tell "they said one tablespoon" from "we picked one
        # tablespoon" — which the single pair of fields could not, and which is
        # why "a scoop" reached the user as an approved fact.
        quantity = QuantityIntent(
            stated_amount=(value if stated else None),
            stated_unit=(unit if stated else None),
            inferred_amount=(None if stated else value),
            inferred_unit=(None if stated else unit),
            descriptor=(None if stated else unit))
        items.append(StagedFoodItem(
            staged_item_id=make_staged_item_id(turn_id, ordinal, food),
            original_text=food, ordinal=ordinal,
            food_class=classify_food(food, brand,
                                     bool(raw.get("is_packaged"))),
            identity=FoodIdentity(canonical_name=food, brand=brand),
            quantity=quantity, meal_group_id=meal_group_id))
    return tuple(items), meal_group_id


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# ── interpreter ambiguities → typed ambiguities ───────────────────────────────
def attach_ambiguities(items, data: Mapping, *, mode: str) -> tuple:
    """Lift the interpreter's reported ambiguities onto the items they concern.

    The old policy read one number — `impact_cal` — against a calorie-only
    threshold. The engine scores calorie, protein, carb, fat, identity risk and
    serving-basis risk, so an item that is calorie-tight and protein-wild is no
    longer waved through.
    """
    from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                            build_ambiguity)

    reported = [a for a in (data.get("ambiguities") or [])
                if isinstance(a, Mapping)]
    if not reported:
        return items

    by_ordinal = {i.ordinal: i for i in items}
    # The item's own size, so the fraction rule can run. A span of 90 calories
    # is most of a granola bar and a rounding error on a platter, and the
    # scorer cannot tell them apart without this.
    # IS THIS REALLY THE ONLY THING WE ARE UNSURE ABOUT? The prompt below said
    # so unconditionally, and it was routinely false: "had a Barebells bar and
    # some chicken and rice" listed "One cup of white rice" — a cup nobody
    # said — and then claimed the chicken was the only open question. A
    # sentence asserting certainty one line under our own guess is the worst
    # kind of wrong, because it tells the user not to look.
    _sole_estimate = sum(
        1 for i in (items or []) if not getattr(
            getattr(i, "quantity", None), "is_stated", False)) <= 1

    raw_by_ordinal = {}
    for ordinal, raw in enumerate(data.get("items") or []):
        if isinstance(raw, Mapping):
            raw_by_ordinal[ordinal] = raw

    grouped = {}
    for amb in reported:
        field_name = str(amb.get("field") or "").strip() or "consumed_quantity"
        target = _match_item(amb, items)
        if target is None:
            continue
        options = tuple(
            AmbiguityOption(str(o), confidence=0.5)
            for o in (amb.get("options") or [])[:4])
        grouped.setdefault(target.ordinal, []).append(build_ambiguity(
            staged_item_id=target.staged_item_id,
            ambiguity_type=_AMBIGUITY_TYPES.get(field_name,
                                                AmbiguityType.CONSUMED_QUANTITY),
            field_name=_FIELD_NAMES.get(field_name, field_name), mode=mode,
            calorie_span=float(amb.get("impact_cal") or 0),
            protein_span=float(amb.get("impact_protein") or 0),
            item_calories=_calories_for(raw_by_ordinal.get(target.ordinal) or {}),
            options=options))

    return tuple(
        item.with_ambiguities(grouped[item.ordinal])
        if item.ordinal in grouped else item
        for item in items)


#: The interpreter's vocabulary for what is uncertain → the typed enum.
_AMBIGUITY_TYPES = {}
_FIELD_NAMES = {}


def _init_maps():
    from skills.nutrition.ambiguity import AmbiguityType
    _AMBIGUITY_TYPES.update({
        "consumed": AmbiguityType.CONSUMED_QUANTITY,
        "consumed_quantity": AmbiguityType.CONSUMED_QUANTITY,
        "amount": AmbiguityType.CONSUMED_QUANTITY,
        "portion": AmbiguityType.CONSUMED_QUANTITY,
        "size": AmbiguityType.PACKAGE_SIZE,
        "package": AmbiguityType.PACKAGE_SIZE,
        "product": AmbiguityType.PRODUCT_IDENTITY,
        "identity": AmbiguityType.PRODUCT_IDENTITY,
        "brand": AmbiguityType.PRODUCT_LINE,
        "variant": AmbiguityType.PRODUCT_VARIANT,
        "flavor": AmbiguityType.PRODUCT_VARIANT,
        "preparation": AmbiguityType.PREPARATION,
        "serving": AmbiguityType.SERVING_BASIS,
    })
    _FIELD_NAMES.update({
        "consumed": "consumed_fraction", "amount": "stated_amount",
        "portion": "estimated_mass_g", "size": "package_size",
        "package": "package_size", "product": "canonical_name",
        "identity": "canonical_name", "brand": "product_line",
        "variant": "variant", "flavor": "variant",
        "preparation": "preparation", "serving": "serving_basis",
    })


_init_maps()


def _match_item(amb: Mapping, items):
    """Which staged item an ambiguity is about.

    The interpreter names the food; matching on that is how the answer later
    binds to one row. An unmatched ambiguity is DROPPED rather than applied to
    the first item — a question about the wrong food is worse than no question.
    """
    named = str(amb.get("item") or amb.get("food") or "").strip().lower()
    if named:
        for item in items:
            if named in item.original_text.lower() \
                    or item.original_text.lower() in named:
                return item
        return None
    return items[0] if len(items) == 1 else None


# ── the decision ──────────────────────────────────────────────────────────────
def plan_turn(data: Mapping, *, turn_id: str, message: str = "",
              mode: str = "moderate", round_number: int = 0,
              preferences=None, now: Optional[datetime] = None
              ) -> Optional[FoodTurnDecision]:
    """The whole pre-execution decision. Returns None on any failure, so the
    caller keeps its existing behaviour rather than losing the turn."""
    from core import food_trace
    from core.food_trace import Outcome, Stage

    try:
        from skills.nutrition.clarify_policy import decide
        from skills.nutrition.clarify_ui import build_traces

        with food_trace.stage(Stage.STAGE) as staging:
            items, meal_group_id = stage_items(data, turn_id=turn_id,
                                               message=message, mode=mode)
            staging.counts["items"] = len(items)
            if not items:
                staging.outcome = Outcome.SKIPPED
        if not items:
            return None
        with food_trace.stage(Stage.CLARIFY) as clarifying:
            items = attach_ambiguities(items, data, mode=mode)
            # The interpreter reports what IT noticed uncertain. It does not
            # notice having invented precision — "a scoop" arriving as "1 tbsp"
            # looks like an answer from where it stands. Derived from the user's
            # own words, so the review turn can disclose it as ours.
            #
            # Inside the CLARIFY stage because deriving an ambiguity IS
            # clarification work, and its cost belongs in that stage's timing.
            items = derive_vague_quantities(items, data, message=message,
                                            mode=mode)
            items = apply_preferences(items, preferences, now=now, mode=mode)
            decision = decide(list(items), mode=mode,
                              round_number=round_number)
            approved = _approved_operations(data, items, decision)
            clarifying.counts.update(
                ready=len(decision.ready_item_ids or ()),
                held=len(decision.held_item_ids or ()),
                questions=len(decision.questions or ()),
                assumptions=len(decision.assumptions or ()))
            # Where the turn stopped, from the clarifier's own point of view.
            # ASKED and HELD are different outcomes and the funnel needs both:
            # a question is a turn the user can finish, a hold is one they
            # cannot see a way to.
            if decision.questions:
                clarifying.outcome = Outcome.ASKED
            elif not approved and items:
                clarifying.outcome = Outcome.HELD

        traces = build_traces(items, decision=decision, mode=mode,
                              turn_id=turn_id)
        for trace in traces:
            logger.info(trace.log_line())

        # `items_ready`, not `items_committed`: this is the clarifier's approval
        # to write, recorded before the executor has written anything. A blocked
        # or failed write used to surface here as a commit. The executor sets the
        # committed and failed counts once it knows them (core/conversation.py).
        food_trace.note(
            meal_group_id=meal_group_id, mode=mode,
            items_staged=len(items),
            items_ready=len(decision.ready_item_ids or ()),
            items_held=len(decision.held_item_ids or ()),
            questions_asked=len(decision.questions or ()),
            assumptions_made=len(decision.assumptions or ()))

        return FoodTurnDecision(staged_items=items, clarification=decision,
                                approved_operations=approved,
                                meal_group_id=meal_group_id, traces=traces)
    except Exception as e:
        logger.warning(f"food pipeline skipped, legacy policy: {e}")
        food_trace.note(error=f"pipeline:{type(e).__name__}")
        return None


def apply_preferences(items, preferences, *, now=None, mode="moderate") -> tuple:
    """Fill identity gaps from what this user has confirmed before.

    A learned default is applied as an ASSUMPTION, never silently: the item
    records what was assumed and what the alternatives were, so a correction
    has something to contradict.
    """
    if not preferences:
        return items
    try:
        from skills.nutrition.preferences import (normalize_term,
                                                  resolve_from_preference)
        from skills.nutrition.staging import FoodAssumption
    except Exception:
        return items

    now = now or datetime.utcnow()
    by_term = {}
    for pref in preferences:
        by_term[normalize_term(getattr(pref, "trigger_term", ""))] = pref

    out = []
    for item in items:
        pref = by_term.get(normalize_term(item.original_text))
        fields = resolve_from_preference(pref, now=now, mode=mode) if pref else {}
        if not fields:
            out.append(item)
            continue
        resolved = item.resolving(**fields)
        out.append(resolved.with_assumption(FoodAssumption(
            staged_item_id=item.staged_item_id,
            field_name=next(iter(fields)), assumed_value=next(iter(fields.values())),
            confidence=getattr(pref, "confidence", 0.5),
            user_visible_text=(f"Went with your usual "
                               f"{pref.describe()} for the "
                               f"{item.original_text}."))))
    return tuple(out)


def _approved_operations(data: Mapping, items, decision) -> tuple:
    """The interpreter's calls, filtered to items the policy cleared.

    Filtered, not rebuilt: the call construction (units, ids, provenance,
    board binding) is already correct and re-deriving it here would be a second
    implementation to keep in step. What this adds is the veto.

    **This is not where the veto is enforced.** `data["_calls"]` is populated by
    the transcript fixtures and by the coordinator's food stage; the live turn
    reaches here with the interpreter's raw JSON, which has no `_calls` at all,
    so this returns empty and reports nothing about what was allowed. That gap
    is why the enforcement lives in `core.food_turn._apply_clarification_veto`,
    against the calls as actually constructed. What this function is for is the
    callers that DO hold their calls at decision time — for them it is the
    filter, and for everyone else it is a report.
    """
    ready = set(decision.ready_item_ids or ())
    if not ready:
        return ()
    ready_texts = {i.original_text.lower() for i in items
                   if i.staged_item_id in ready}
    approved = []
    for call in (data.get("_calls") or ()):
        name = str(((call or {}).get("input") or {}).get("food_name")
                   or "").strip().lower()
        if not name or name in ready_texts \
                or any(name in t or t in name for t in ready_texts):
            approved.append(call)
    return tuple(approved)


# ── after execution ───────────────────────────────────────────────────────────
def build_meal_resolution(decision: FoodTurnDecision, execution, *,
                          turn_id: str = ""):
    """Assemble the committed/pending/failed view from the typed execution.

    MealResolution becomes the sole authority for what landed — nothing
    downstream re-derives it from the interpreter's original words.
    """
    from skills.nutrition.meal_resolution import build_resolution

    by_item = {}
    calls = list(getattr(execution, "calls", ()) or ())
    for item in decision.staged_items:
        match = next((c for c in calls
                      if _call_names(c).strip().lower()
                      in (item.original_text.lower(),)), None)
        if match is None:
            continue
        by_item[item.staged_item_id] = {
            "entry_id": getattr(match, "entry_id", None),
            "event_id": getattr(match, "event_id", None),
            "name": _call_names(match) or item.original_text,
            "quantity_text": item.quantity.describe(),
            "source": getattr(match, "result_text", "")[:0] or "",
            "reason": ("" if getattr(match, "committed", False)
                       else getattr(match, "status", "failed")),
        }
    return build_resolution(meal_group_id=decision.meal_group_id,
                            items=list(decision.staged_items),
                            decision=decision.clarification,
                            execution_by_item=by_item, turn_id=turn_id)


def _call_names(call) -> str:
    return str((getattr(call, "raw_input", None) or {}).get("food_name") or "")


# ── derived ambiguity: the user was vague and we were precise ────────────────
#: Measures a user says when they do not know the amount. Each maps to the
#: portion ontology's measure name, so the plausible range comes from the
#: ontology rather than from a second table here.
VAGUE_MEASURES = {
    "scoop": "scoop", "scoops": "scoop", "spoonful": "spoonful",
    "spoonfuls": "spoonful", "spoon": "spoonful", "handful": "handful",
    "handfuls": "handful", "drizzle": "drizzle", "splash": "drizzle",
    "dollop": "spoonful", "glug": "drizzle", "bit": "little",
    "little": "little", "some": "some", "few": "some", "couple": "some",
    "bowl": "bowl", "plate": "plate", "bite": "bite", "bites": "bite",
    "chunk": "some", "piece": "some", "smear": "spoonful",
}

#: The plausible range has to span at least this ratio before the vagueness is
#: worth a turn. A measure whose upper bound is under 1.6x its lower bound is
#: vague in wording and precise enough in fact.
VAGUE_SPREAD_RATIO = 1.6


_CLAUSE_SPLIT_RE = re.compile(r"\s*(?:,|\band\b|\bwith\b|\bplus\b|\+)\s*",
                              re.I)
_CLAUSE_STOPWORDS = frozenset({
    "a", "an", "the", "of", "some", "like", "had", "i", "my", "was", "were",
    "also", "just", "about", "and", "with", "for", "on", "in", "it", "that",
})


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9&]+", (text or "").lower())
            if w not in _CLAUSE_STOPWORDS}


def _vague_measure_in(message: str, food: str) -> Optional[str]:
    """The vague measure the user used for THIS food, if any.

    Matched inside the CLAUSE that names the food, not anywhere in the message.
    "a scoop of peanut butter and 200g of chicken" contains "scoop", and
    attaching it to the chicken would ask about a portion the user stated
    exactly.

    Clause selection is by token overlap rather than by position, because
    position gets "peanut butter" wrong the moment the message also mentions
    "peanut M&Ms" — the first "peanut" belongs to the other food.
    """
    if not message or not food:
        return None
    food_tokens = _tokens(food)
    if not food_tokens:
        return None

    best, best_score = None, 0.0
    for clause in _CLAUSE_SPLIT_RE.split(message):
        clause_tokens = _tokens(clause)
        if not clause_tokens:
            continue
        overlap = food_tokens & clause_tokens
        if not overlap:
            continue
        score = len(overlap) / len(food_tokens | clause_tokens)
        if score > best_score:
            best, best_score = clause, score

    if best is None:
        return None
    for word, measure in VAGUE_MEASURES.items():
        if re.search(rf"\b{re.escape(word)}\b", best.lower()):
            return measure
    return None


def derive_vague_quantities(items, data: Mapping, *, message: str,
                            mode: str) -> tuple:
    """Add an ambiguity where the USER was vague and the interpreter was not.

    The failure this exists for, from a shipped transcript: the user said "a
    scoop of peanut butter" and the review turn said "1 tbsp Peanut Butter",
    then asked "Does that look right?". A scoop of peanut butter is plausibly
    one tablespoon or three, a span of roughly 190 calories, and the user was
    invited to approve it without ever being shown that a number had been
    chosen for them.

    The interpreter reports ambiguities it noticed. It did not notice this one,
    because from its point of view it produced an answer. So the ambiguity is
    DERIVED here from two facts we already have: the user's own words, and the
    portion ontology's plausible range for the measure they used.
    """
    from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                            build_ambiguity)
    from skills.nutrition.portions import distribution_for

    # IS THIS REALLY THE ONLY THING WE ARE UNSURE ABOUT? The prompt below said
    # so unconditionally, and it was routinely false: "had a Barebells bar and
    # some chicken and rice" listed "One cup of white rice" — a cup nobody
    # said — and then claimed the chicken was the only open question. A
    # sentence asserting certainty one line under our own guess is the worst
    # kind of wrong, because it tells the user not to look.
    _sole_estimate = sum(
        1 for i in (items or []) if not getattr(
            getattr(i, "quantity", None), "is_stated", False)) <= 1

    raw_by_ordinal = {}
    for ordinal, raw in enumerate(data.get("items") or []):
        if isinstance(raw, Mapping):
            raw_by_ordinal[ordinal] = raw

    out = []
    for item in items or ():
        measure = _vague_measure_in(message, item.original_text)
        # A stated amount is the user's own number and is never second-guessed.
        if measure is None or item.quantity.is_stated:
            out.append(item)
            continue
        # An ambiguity the interpreter already reported for this field wins —
        # it has the better options and the real impact numbers.
        if any(a.ambiguity_type is AmbiguityType.CONSUMED_QUANTITY
               for a in item.ambiguities):
            out.append(item)
            continue

        # Only when our unit DIFFERS from the user's word. "a plate of turkey"
        # arriving as 1 plate is vague but not CONVERTED — the vagueness is
        # inherent to the measure and the portion ontology discloses it. "a
        # scoop" arriving as 1 tbsp is a different measure than the one they
        # used, which is the silent conversion this exists to surface.
        our_unit = (item.quantity.inferred_unit or "").strip().lower()
        if our_unit and VAGUE_MEASURES.get(our_unit.rstrip("s")) == measure:
            out.append(item)
            continue

        distribution = distribution_for(measure, item.original_text)
        if distribution is None or not distribution.lower_g:
            out.append(item)
            continue
        if distribution.upper_g / max(distribution.lower_g, 1e-6) < \
                VAGUE_SPREAD_RATIO:
            out.append(item)
            continue

        calories = _calories_for(raw_by_ordinal.get(item.ordinal) or {})
        span = _span_from(distribution, calories)
        # Descending confidence, deliberately. Equal confidences read as a coin
        # toss to the clarification policy, which makes QUICK mode ask — and
        # quick exists precisely to accept this risk and commit with a stated
        # assumption instead.
        labels = _measure_options(measure, distribution)
        options = tuple(
            AmbiguityOption(label, confidence=confidence)
            for label, confidence in zip(labels, (0.6, 0.35, 0.2)))

        out.append(item.with_ambiguities(list(item.ambiguities) + [
            build_ambiguity(
                staged_item_id=item.staged_item_id,
                ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
                field_name="consumed_fraction", mode=mode,
                calorie_span=span, item_calories=calories, options=options,
                prompt=_vague_prompt(item.original_text, measure,
                                     _measure_options(measure, distribution),
                                     sole_estimate=_sole_estimate))]))
    return tuple(out)


def _vague_prompt(food: str, measure: str, options,
                  sole_estimate: bool = True) -> str:
    """Name what is uncertain, then ask about it.

    Two sentences rather than one long one. The lead says which food the
    question is about, so the ask itself can stay short and can use the user's
    own measure — "was the scoop closer to one or two tablespoons" reads like a
    person asking, where "was the peanut butter scoop closer to one tablespoon
    or two tablespoons" reads like a form validating a field.

    The lead is also the part that keeps the question bindable in a three-food
    meal: without it, "the scoop" could be any of them.
    """
    low, high = options[0], options[-1]
    food = (food or "").strip()
    # A HEDGE IS NOT A MEASURE. "Was the some closer to 30g or 200g?" is the
    # same defect as "One some of mustard" one layer over: the interpreter
    # hands back a hedge in the unit slot and every rule downstream treats a
    # unit as a noun to put an article in front of.
    lead = ("How much" if measure in _HEDGE_MEASURES
            else f"Was the {measure} closer")
    tail = (f" — closer to {_shared_unit(low, high)}?"
            if measure in _HEDGE_MEASURES
            else f" to {_shared_unit(low, high)}?")
    if not food:
        return f"{lead}{tail}"
    ask = (f"{lead} of the {food.lower()}{tail}"
           if measure in _HEDGE_MEASURES else f"{lead}{tail}")
    if sole_estimate:
        return f"The {food.lower()} is the only part I'm unsure about. {ask}"
    # Other amounts on this meal are ours too. Naming that is what earns the
    # question — the user is being asked about the one that moves the most,
    # not told the rest are settled.
    return f"I picked the other amounts myself. {ask}"


#: Words the interpreter puts in the unit slot that measure nothing. They can
#: never take "the ... closer to", which is a frame for a real measure.
_HEDGE_MEASURES = frozenset({"some", "a little", "little", "a bit", "bit",
                             "lots", "plenty", "a few", "few"})


def _shared_unit(low: str, high: str) -> str:
    """"one tablespoon" + "two tablespoons" → "one or two tablespoons".

    Saying the unit twice is the tell of generated text. Only collapses when
    the two options really do share a unit — "one tablespoon or half a cup"
    must keep both.
    """
    lo, hi = (low or "").split(), (high or "").split()
    # Exactly "<amount> <unit>" on the low side. Anything longer carries an
    # article or a qualifier that does not survive having its noun removed:
    # "half a cup" would collapse to "half a or one cup".
    # An article is not an amount: "a scoop" would collapse to "a or two
    # scoops", which reads as a typo rather than a choice.
    if len(lo) == 2 and len(hi) >= 2 and lo[0].lower() not in ("a", "an"):
        lo_unit, hi_unit = lo[-1], hi[-1]
        # Same unit, differing only by plural — the common case (tablespoon /
        # tablespoons), and the only one where dropping the first is lossless.
        if hi_unit in (lo_unit, f"{lo_unit}s") or lo_unit == f"{hi_unit}s":
            return f"{lo[0]} or {high}"
    return f"{low} or {high}"


def _calories_for(raw: Mapping) -> Optional[float]:
    for key in ("calories", "cal", "kcal"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _span_from(distribution, calories: Optional[float]) -> float:
    """What being wrong about this measure would cost, in calories.

    With the item's own calories we can scale the mass range directly. Without
    them the span is reported as the mass spread, which is the right ORDER of
    magnitude for a food at roughly 4 cal/g and is honest about being an
    estimate — a zero here would rank the vaguest portions as the least worth
    asking about.
    """
    spread = max(0.0, distribution.upper_g - distribution.lower_g)
    if calories and distribution.median_g:
        per_gram = calories / distribution.median_g
        return round(spread * per_gram, 1)
    return round(spread * 4.0, 1)


#: Grams per tablespoon, for the measures people answer in spoons.
_G_PER_TBSP = 15.0

_SPOKEN = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def _measure_options(measure: str, distribution) -> tuple:
    """The two ends of the plausible range, in the words the measure invites.

    Spoons get spoons; everything else gets grams. "Was the scoop closer to one
    or two tablespoons?" is a question someone can answer from memory, and "was
    it closer to 16g or 34g?" is one they have to convert first — which is the
    difference between a clarification and a chore.
    """
    if measure in ("spoonful", "scoop", "drizzle") and \
            distribution.upper_g <= 80:
        low = max(1, int(round(distribution.lower_g / _G_PER_TBSP)))
        high = max(low + 1, int(round(distribution.upper_g / _G_PER_TBSP)))
        return (f"{_SPOKEN.get(low, low)} tablespoon"
                + ("" if low == 1 else "s"),
                f"{_SPOKEN.get(high, high)} tablespoons")
    return (f"{_g(distribution.lower_g)}", f"{_g(distribution.upper_g)}")


def _g(grams: float) -> str:
    return f"{int(round(grams))}g"
