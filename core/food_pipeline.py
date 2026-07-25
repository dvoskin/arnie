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
        quantity = QuantityIntent(
            stated_amount=(float(amount) if _is_number(amount) else None),
            stated_unit=(str(raw.get("unit") or "").strip() or None),
            descriptor=(None if stated else str(raw.get("unit") or "") or None))
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
    try:
        from skills.nutrition.clarify_policy import decide
        from skills.nutrition.clarify_ui import build_traces

        items, meal_group_id = stage_items(data, turn_id=turn_id,
                                           message=message, mode=mode)
        if not items:
            return None
        items = attach_ambiguities(items, data, mode=mode)
        items = apply_preferences(items, preferences, now=now, mode=mode)

        decision = decide(list(items), mode=mode, round_number=round_number)
        approved = _approved_operations(data, items, decision)
        traces = build_traces(items, decision=decision, mode=mode,
                              turn_id=turn_id)
        for trace in traces:
            logger.info(trace.log_line())
        return FoodTurnDecision(staged_items=items, clarification=decision,
                                approved_operations=approved,
                                meal_group_id=meal_group_id, traces=traces)
    except Exception as e:
        logger.warning(f"food pipeline skipped, legacy policy: {e}")
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
