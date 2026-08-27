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
        # `adapter_built=True` is the C10 enforcement key: patch=None is
        # permitted ONLY on inventoried legacy measurement paths, and this is
        # one. Every canonical B-1 option must carry a patch.
        return ClarificationOption(label=text, field_id=field_id,
                                   adapter_built=True) if text else None
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
        option_id=str(getattr(raw, "candidate_id", "") or ""),
        adapter_built=True)


def field_from_dict(raw: dict, index: int = 0,
                    pending_id: str = "") -> Optional[ClarificationField]:
    """The interpreter branch's `{item, text, options}` dict.

    ⚠ THE GENERATED ID IS MEASUREMENT-ONLY AND MUST NOT BECOME THE CONTRACT.
    It is derived from list position and display text, so it changes when the
    interpreter reorders its questions or renames the item — which makes it
    unusable for binding an answer across turns, the one job an id has.

    A durable id has to come from stable semantics:

        f"{pending_meal_id}:{meal_item_id}:{attribute}:{revision}"

    `pending_id` is threaded through so the shape exists; the item id and
    revision arrive with the PendingOperation migration (step 4). DELETION
    MILESTONE: this fallback goes when that lands, and the shadow must not be
    promoted to a write path before it.
    """
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    item = str(raw.get("item") or "").strip()
    fid = f"{pending_id}:q{index}:{item.lower() or 'turn'}" if pending_id \
        else f"q{index}:{item.lower() or 'turn'}"
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
    """Which attribute the question is about.

    ⚠ MIGRATION-ONLY, AND BACKWARDS. This reads the RENDERED QUESTION to guess
    the attribute, which is the direction the architecture is supposed to
    reverse:

        wanted:  unresolved attribute -> clarification field -> rendered question
        current: rendered question    -> guessed attribute

    It is here so the adapter can normalise producers that never recorded an
    attribute at all. DELETION MILESTONE: it goes when the producers emit
    `ClarificationField` directly, and until then this type WRAPS the
    prose-parsing architecture rather than replacing it. Uses the food lane's
    own `_render_facet` rather than a second classifier, so at least there is one
    guess and not two.
    """
    try:
        # ⛔ RENAMED 2026-08-27 (`_facet_kind` -> `_render_facet`) when the
        # canonical ask-type vocabulary landed. THIS IMPORT SITS INSIDE A BARE
        # EXCEPT: the rename broke it silently and every field fell back to
        # "detail". Only `test_the_live_ask_produces_two_answerable_fields`
        # noticed. A cross-module import behind `except Exception` is a
        # rename away from being permanently dead.
        from core.food_turn import _render_facet
        return _render_facet(text)
    except Exception:
        return "detail"


def fields_from_turn(sft: dict, pending_id: str = "") -> tuple:
    """Every clarification a structured-food turn is asking, as typed fields.

    Reads whichever shape this turn happened to produce. Returns () for a turn
    that is not asking — which is a real answer and not a gap.
    """
    if not isinstance(sft, dict) or sft.get("action") != "ask":
        return ()
    out = []
    for i, raw in enumerate(sft.get("questions") or ()):
        field = (field_from_dict(raw, i, pending_id) if isinstance(raw, dict)
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


#: Response types that PROMISE a choice. Only these are defective without
#: options.
_SELECT_TYPES = frozenset({"single_select", "multi_select"})


def free_text_required(fields) -> tuple:
    """Fields with no options — NOT NECESSARILY A DEFECT.

    Renamed from `unanswerable`, which was wrong and would have overstated
    breakage in production. "What restaurant was it from?" and "what was in the
    homemade sauce?" correctly require typing; a metric calling those broken
    pushes toward generating chips for questions that should stay free text.
    """
    return tuple(f for f in fields if not f.options)


def missing_expected_options(fields) -> tuple:
    """THE ACTUAL DEFECT: a field that PROMISES a choice and offers none.

    `response_type` already records the promise, so the metric reads it rather
    than assuming every optionless question is broken. This is the number that
    would have shown 39 of 40 prod asks losing their options — those were
    select-type questions whose choices were computed and dropped, not free-text
    ones.
    """
    return tuple(f for f in fields
                 if f.response_type in _SELECT_TYPES and not f.options)
