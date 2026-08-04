"""Food's four clarification shapes, normalised into one typed field.

Measured 2026-08-04. Four sites in `food_turn` produce the wire's `questions`
list, in three different shapes:

  * `_questions_from_points` — plain dicts {item, text, options}
  * the staged pipeline      — AmbiguityOption -> ClarificationOption ->
                               ClarificationQuestion
  * a literal dict at food_turn.py:5600
  * the calorie-only fallback

and the typed one does not survive the trip. `ClarificationQuestion` is
FLATTENED into loose payload keys (`question_id`, `staged_item_id`,
`response_schema`, `requested_fields`, `options`) and RECONSTRUCTED on the
answer turn — and `parse_prior_answer` returns None the moment `response_schema`
is absent, which is how every deterministic answer parser became unreachable in
production.

This adapter reads all of them and produces `core.semantics.ClarificationField`,
where the question and its options are ONE object. That is the property the
whole step exists for: a question whose options are derived separately can lose
them, and did — the server shipped `options: []` on 39 of 40 asks, so iOS
re-derived chips by parsing Arnie's rendered sentence.

SHADOW ONLY. Nothing here is on a write path. It runs beside the live
producers so the disagreement is measurable before anything depends on it.
"""
from __future__ import annotations

from typing import Any, Optional

from core.semantics import ClarificationField, ClarificationOption


def _option_of(raw: Any, field_id: str) -> Optional[ClarificationOption]:
    """One option, from whichever of the three shapes produced it.

    A bare string is the interpreter branch; `AmbiguityOption` and
    `ClarificationOption` both carry a label plus something else, and the
    something else differs — which is exactly why a single type is needed.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        return ClarificationOption(label=text, field_id=field_id) if text \
            else None
    label = str(getattr(raw, "label", "") or "").strip()
    if not label:
        return None
    # `ClarificationOption.value` and `AmbiguityOption.payload` are the same
    # idea under two names; neither is guaranteed present.
    value = getattr(raw, "value", None)
    if value is None:
        value = getattr(raw, "payload", None)
    return ClarificationOption(
        label=label, value=value, field_id=field_id,
        option_id=str(getattr(raw, "candidate_id", "") or ""))


def field_from_dict(raw: dict, index: int = 0) -> Optional[ClarificationField]:
    """The interpreter branch's `{item, text, options}` dict."""
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    item = str(raw.get("item") or "").strip()
    fid = f"q{index}:{item.lower() or 'turn'}"
    opts = tuple(o for o in (_option_of(x, fid)
                             for x in (raw.get("options") or ())) if o)
    return ClarificationField(
        id=fid, event_id=item, attribute=_attribute_of(text),
        question=text, options=opts,
        response_type="single_select" if opts else "free_text")


def field_from_question(q: Any, index: int = 0
                        ) -> Optional[ClarificationField]:
    """The staged pipeline's `ClarificationQuestion`."""
    prompt = str(getattr(q, "prompt", "") or "").strip()
    if not prompt:
        return None
    fid = str(getattr(q, "question_id", "") or "") or f"q{index}"
    opts = tuple(o for o in (_option_of(x, fid)
                             for x in (getattr(q, "options", ()) or ())) if o)
    return ClarificationField(
        id=fid,
        event_id=str(getattr(q, "staged_item_id", "") or ""),
        attribute=_attribute_of(prompt),
        question=prompt, options=opts,
        response_type=str(getattr(q, "response_schema", "") or "")
        or ("single_select" if opts else "free_text"),
        materiality=getattr(q, "resolved_materiality", None))


def _attribute_of(text: str) -> str:
    """Which attribute the question is about, using the food lane's own
    classifier rather than a second one."""
    try:
        from core.food_turn import _facet_kind
        return _facet_kind(text)
    except Exception:
        return "detail"


def fields_from_turn(sft: dict) -> tuple:
    """Every clarification a structured-food turn is asking, as typed fields.

    Reads whichever shape this turn happened to produce. Returns () for a turn
    that is not asking — which is a real answer and not a gap.
    """
    if not isinstance(sft, dict) or sft.get("action") != "ask":
        return ()
    out = []
    for i, raw in enumerate(sft.get("questions") or ()):
        field = (field_from_dict(raw, i) if isinstance(raw, dict)
                 else field_from_question(raw, i))
        if field is not None:
            out.append(field)
    if not out:
        # The turn asks something the structured list did not carry. The
        # question text still exists; its options do not, and saying so is the
        # measurement this adapter is for.
        text = str(sft.get("text") or "").strip()
        if text:
            out.append(ClarificationField(
                id="q0:turn", event_id="", attribute=_attribute_of(text),
                question=text, options=(), response_type="free_text"))
    return tuple(out)


def unanswerable(fields) -> tuple:
    """Fields a client cannot answer by tapping — the defect being counted.

    A question with no options is one the user must type at, and on Telegram
    and iMessage it shipped with nothing at all.
    """
    return tuple(f for f in fields if not f.options)
