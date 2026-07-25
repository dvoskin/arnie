"""UI-ready clarification payloads and per-item traces (directive 26, 27).

Two outputs that are not the conversation.

**The UI model.** A clarification rendered as prose forces the user to type an
answer we already know the shape of. The same question carries structured
options so iOS can render chips, a fraction control and the standing exits
("use label values", "estimate it", "skip this item") — and tapping a chip
returns a candidate id, which is unambiguous in a way free text never is.

Chat stays fully functional. The structured payload is additive: a client that
ignores it still gets the prompt string, and the narrow parsers still handle a
typed answer.

**The trace.** One line per staged item, carrying what was found, what was
chosen, what was ambiguous, and what the system decided. Without it, a wrong
question or a wrong pick is only reproducible by guessing at the conversation
that produced it — which is how nutrition bugs stay anecdotes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from skills.nutrition.clarify_policy import (ClarificationQuestion,
                                             ResponseSchema)
from skills.nutrition.staging import StagedFoodItem

UI_MODEL_VERSION = "clarify_ui_v1"
TRACE_VERSION = "item_trace_v1"


class ExitAction:
    """The standing escapes, offered on every clarification.

    A question the user cannot get out of is an interrogation. These are always
    available, which is also what makes bounded loops honest — the exit exists
    before the rounds run out, not only after.
    """
    LABEL_VALUES = "use_label_values"
    ESTIMATE = "estimate_it"
    SKIP_ITEM = "skip_this_item"


#: Which exits make sense per schema. Reading label values off a package is
#: only an answer when the question is about a packaged product.
_EXITS_BY_SCHEMA = {
    ResponseSchema.PRODUCT_SELECTION: (ExitAction.LABEL_VALUES,
                                       ExitAction.ESTIMATE,
                                       ExitAction.SKIP_ITEM),
    ResponseSchema.PRODUCT_AND_FRACTION: (ExitAction.LABEL_VALUES,
                                          ExitAction.ESTIMATE,
                                          ExitAction.SKIP_ITEM),
    ResponseSchema.QUANTITY: (ExitAction.ESTIMATE, ExitAction.SKIP_ITEM),
    ResponseSchema.SERVING_BASIS: (ExitAction.LABEL_VALUES,
                                   ExitAction.ESTIMATE, ExitAction.SKIP_ITEM),
    ResponseSchema.NUTRIENT_VALUES: (ExitAction.ESTIMATE, ExitAction.SKIP_ITEM),
    ResponseSchema.YES_NO: (ExitAction.SKIP_ITEM,),
}

_EXIT_LABELS = {
    ExitAction.LABEL_VALUES: "Use label values",
    ExitAction.ESTIMATE: "Estimate it",
    ExitAction.SKIP_ITEM: "Skip this item",
}

#: Fraction controls offered when the question is about how much of a container
#: was consumed. Chips beat a text box: "half" typed and "half" tapped should
#: not travel through different code.
FRACTION_CHOICES = ((1.0, "All of it"), (0.75, "Most"), (0.5, "Half"),
                    (0.25, "A quarter"), (0.1, "A sip"))

_FRACTION_FIELDS = frozenset({"consumed_fraction"})


@dataclass(frozen=True)
class UIOption:
    label: str
    value: Any = None
    candidate_id: Optional[str] = None
    field_name: str = ""
    sublabel: str = ""

    def as_dict(self) -> dict:
        out = {"label": self.label, "field": self.field_name}
        if self.candidate_id:
            out["candidate_id"] = self.candidate_id
        if self.value is not None:
            out["value"] = self.value
        if self.sublabel:
            out["sublabel"] = self.sublabel
        return out


@dataclass(frozen=True)
class ClarificationUIModel:
    """Everything a client needs to render one question without parsing prose."""
    question_id: str
    staged_item_id: str
    title: str
    subtitle: str = ""
    schema: str = ""
    options: tuple = ()
    fraction_control: tuple = ()
    exits: tuple = ()
    allows_free_text: bool = True
    requested_fields: tuple = ()
    version: str = UI_MODEL_VERSION

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "question_id": self.question_id,
            "staged_item_id": self.staged_item_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "schema": self.schema,
            "requested_fields": list(self.requested_fields),
            "options": [o.as_dict() for o in self.options],
            "fraction_control": [{"value": v, "label": l}
                                 for v, l in self.fraction_control],
            "exits": [{"action": a, "label": _EXIT_LABELS[a]}
                      for a in self.exits],
            "allows_free_text": self.allows_free_text,
        }


def _subtitle_for(question: ClarificationQuestion) -> str:
    """Why we are asking. A user who understands the stakes answers faster and
    resents it less than one being quizzed for no stated reason."""
    if question.response_schema in (ResponseSchema.PRODUCT_SELECTION,
                                    ResponseSchema.PRODUCT_AND_FRACTION):
        return "These versions have different nutrition."
    if question.response_schema is ResponseSchema.QUANTITY:
        return "The amount changes the numbers."
    if question.response_schema is ResponseSchema.SERVING_BASIS:
        return "The label's serving size decides the totals."
    if question.response_schema is ResponseSchema.NUTRIENT_VALUES:
        return "I'll log exactly what the label says."
    return ""


def build_ui_model(question: ClarificationQuestion,
                   item: Optional[StagedFoodItem] = None
                   ) -> ClarificationUIModel:
    """The structured twin of a question. Never replaces the prompt — a client
    that ignores this still has a working conversation."""
    options = tuple(
        UIOption(label=o.label, value=o.value, candidate_id=o.candidate_id,
                 field_name=getattr(o, "field_name", ""))
        for o in (question.options or ())
        if getattr(o, "field_name", "") not in _FRACTION_FIELDS)

    fraction = (FRACTION_CHOICES
                if any(f in _FRACTION_FIELDS
                       for f in (question.requested_fields or ()))
                else ())

    return ClarificationUIModel(
        question_id=question.question_id,
        staged_item_id=question.staged_item_id,
        title=question.prompt,
        subtitle=_subtitle_for(question),
        schema=question.response_schema.value,
        options=options,
        fraction_control=fraction,
        exits=_EXITS_BY_SCHEMA.get(question.response_schema,
                                   (ExitAction.SKIP_ITEM,)),
        allows_free_text=question.allows_free_text,
        requested_fields=tuple(question.requested_fields or ()))


def build_ui_models(decision) -> tuple:
    """One model per question the decision asks."""
    return tuple(build_ui_model(q) for q in (decision.questions or ()))


# ── per-item traces (directive 27) ────────────────────────────────────────────
@dataclass(frozen=True)
class ItemTrace:
    """What happened to one staged item, in one loggable record."""
    turn_id: str
    staged_item_id: str
    original_text: str
    food_class: str
    candidates_found: int = 0
    candidates_after_collapse: int = 0
    top_candidate: str = ""
    top_score: float = 0.0
    second_score: float = 0.0
    ambiguities: tuple = ()
    materiality_score: float = 0.0
    mode: str = ""
    decision: str = ""
    question_id: str = ""
    assumptions: tuple = ()
    meal_group_id: str = ""
    version: str = TRACE_VERSION

    def as_dict(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "staged_item_id": self.staged_item_id,
            "original_text": self.original_text,
            "food_class": self.food_class,
            "candidates_found": self.candidates_found,
            "candidates_after_collapse": self.candidates_after_collapse,
            "top_candidate": self.top_candidate,
            "top_score": round(self.top_score, 3),
            "second_score": round(self.second_score, 3),
            "ambiguities": list(self.ambiguities),
            "materiality_score": round(self.materiality_score, 3),
            "mode": self.mode,
            "decision": self.decision,
            "question_id": self.question_id,
            "assumptions": list(self.assumptions),
            "meal_group_id": self.meal_group_id,
            "version": self.version,
        }

    def log_line(self) -> str:
        """The greppable one-liner. `decision` and `materiality` are the two
        fields a triage actually starts from."""
        return (f"event=item_trace turn={self.turn_id or '-'} "
                f"item={self.staged_item_id} class={self.food_class} "
                f"text={self.original_text!r} "
                f"candidates={self.candidates_found}"
                f"→{self.candidates_after_collapse} "
                f"top={self.top_candidate!r} score={self.top_score:.2f} "
                f"second={self.second_score:.2f} "
                f"ambiguities={','.join(self.ambiguities) or '-'} "
                f"materiality={self.materiality_score:.2f} "
                f"mode={self.mode or '-'} decision={self.decision} "
                f"question={self.question_id or '-'}")


def build_item_trace(item: StagedFoodItem, *, decision, mode: str,
                     turn_id: str = "", raw_candidate_count: Optional[int] = None
                     ) -> ItemTrace:
    """Assemble one item's trace from the item and the decision that covered it.

    `raw_candidate_count` is passed separately because collapse happens before
    the item is built — and "five results became two real choices" is exactly
    the fact a trace needs to show, rather than looking like three were dropped.
    """
    candidates = tuple(item.candidate_products or ())
    scores = sorted((getattr(c, "overall_score", 0.0) for c in candidates),
                    reverse=True)
    top = candidates[0] if candidates else None

    if item.staged_item_id in (decision.ready_item_ids or ()):
        outcome = "commit"
    elif any(q.staged_item_id == item.staged_item_id
             for q in (decision.questions or ())):
        outcome = "ask"
    elif item.staged_item_id in (decision.held_item_ids or ()):
        outcome = "hold"
    else:
        outcome = "undecided"

    question = next((q.question_id for q in (decision.questions or ())
                     if q.staged_item_id == item.staged_item_id), "")
    worst = max((a.materiality_score for a in item.ambiguities), default=0.0)

    return ItemTrace(
        turn_id=turn_id, staged_item_id=item.staged_item_id,
        original_text=item.original_text,
        food_class=getattr(item.food_class, "value", str(item.food_class)),
        candidates_found=(raw_candidate_count if raw_candidate_count is not None
                          else len(candidates)),
        candidates_after_collapse=len(candidates),
        top_candidate=(top.describe() if top is not None else ""),
        top_score=(scores[0] if scores else 0.0),
        second_score=(scores[1] if len(scores) > 1 else 0.0),
        ambiguities=tuple(a.field_name for a in item.ambiguities),
        materiality_score=worst, mode=mode, decision=outcome,
        question_id=question,
        assumptions=tuple(a.field_name for a in (decision.assumptions or ())
                          if a.staged_item_id == item.staged_item_id),
        meal_group_id=item.meal_group_id)


def build_traces(items, *, decision, mode: str, turn_id: str = "",
                 raw_counts: Mapping[str, int] = None) -> tuple:
    raw_counts = raw_counts or {}
    return tuple(
        build_item_trace(item, decision=decision, mode=mode, turn_id=turn_id,
                         raw_candidate_count=raw_counts.get(item.staged_item_id))
        for item in (items or ()))
