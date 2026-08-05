"""The ONE place a clarification answer becomes a change.

A chip tap and a typed sentence are two ways of saying the same thing, and
until now they were two subsystems: the tap round-tripped a LABEL that the
server re-parsed, and the sentence went through the broad food interpreter,
which read it as a new meal. Both converge here, on one typed patch crossing
one boundary (C14).

    chip:   (operation_id, revision, field_id, option_id)
              -> the STORED patch, loaded from the interaction
    typed:  narrow parser -> the SAME patch type, USER_STATED instead of
              USER_SELECTED

TERMINAL OWNERSHIP — the rule this module exists to enforce.

Once a canonical operation exists, it finishes canonically: repair,
cancellation, or commit. There is no fourth outcome and deliberately no
function here that returns one. The rollout gate is asked ONCE, before the
operation is created (`skills.nutrition.quantity_rollout`), and is never
consulted again — because every available "fall back now" is a way to lose a
meal the user is halfway through:

  * hand the message to the broad interpreter -> the answer becomes a SECOND
    meal, which is the measured defect the canonical path replaces;
  * drop the pending operation -> the food silently vanishes;
  * re-ask from scratch -> the user answers the same question twice and the
    first answer is lost.

So an answer this module cannot apply produces a REPAIR (ask the same field
again, narrower) or an explicit CANCEL. Both keep the operation canonical and
both are visible to the user. Neither is a fallback.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Outcome(str, Enum):
    """The only ways a canonical answer turn can end. There is no `LEGACY`
    member, and adding one is the thing C10 forbids."""
    APPLIED = "applied"
    #: The answer was understood as an explicit stop. The operation closes
    #: without a write; the user said so.
    CANCELLED = "cancelled"
    #: Not understood. Ask the SAME field again, narrower — never the whole
    #: meal again, and never through the interpreter.
    REPAIR = "repair"
    #: The answer names a field or revision this interaction does not have.
    #: Fails closed: a stale tap must not patch whatever looks closest.
    REFUSED = "refused"


@dataclass(frozen=True)
class AnswerResult:
    outcome: Outcome
    patch: Any = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.APPLIED


#: Words that END an operation rather than answering it. Deliberately small
#: and literal: this is the one branch that closes a pending meal without a
#: write, so a miss costs a repair question (recoverable) and a false positive
#: costs the user their meal (not).
_CANCEL = ("cancel", "never mind", "nevermind", "forget it", "skip it",
           "don't log", "dont log", "drop it")


def answer_from_chip(interaction, *, field_id: str, option_id: str,
                     revision: int) -> AnswerResult:
    """A tap: four ids, and the meaning comes from storage.

    The label never travels back as semantics (C11). Every failure here is
    REFUSED rather than repaired, because a tap that does not resolve is not a
    user who was unclear — it is a stale screen or a client bug, and asking
    them to rephrase would be asking them to fix ours.
    """
    if revision != interaction.revision:
        return AnswerResult(
            Outcome.REFUSED,
            reason=f"stale revision {revision} != {interaction.revision}")
    try:
        patch = interaction.patch_for(field_id, option_id)
    except KeyError as exc:
        return AnswerResult(Outcome.REFUSED, reason=str(exc))
    except ValueError as exc:          # an option with no patch
        return AnswerResult(Outcome.REFUSED, reason=str(exc))
    return AnswerResult(Outcome.APPLIED, patch=patch)


def answer_from_text(interaction, *, field_id: str, text: str,
                     food_name: str = "") -> AnswerResult:
    """A typed answer, through the NARROW parser only.

    The broad interpreter is not reachable from here, by construction. That is
    the whole point: sending "about six ounces" through the full food
    interpreter is how an answer became a new meal, and the parser that can
    read it correctly was sitting unwired behind a missing `response_schema`.

    A quantity the chips did not offer is a first-class answer — the typed
    path is not a fallback for people the options failed, it is the same
    answer expressed differently, and it produces the same patch type with
    `USER_STATED` provenance instead of `USER_SELECTED`.
    """
    from core.semantics import Provenance, SetQuantity

    said = (text or "").strip()
    if not said:
        return AnswerResult(Outcome.REPAIR, reason="empty answer")
    low = said.lower()
    if any(c in low for c in _CANCEL):
        return AnswerResult(Outcome.CANCELLED, reason="user cancelled")

    try:
        field = interaction.field(field_id)
    except KeyError as exc:
        return AnswerResult(Outcome.REFUSED, reason=str(exc))

    grams = _grams_from_text(said, food_name)
    if grams is None:
        return AnswerResult(Outcome.REPAIR,
                            reason=f"no quantity in {said!r}")

    from skills.nutrition.quantity_clarification import _quantity

    quantity = _quantity(grams, provenance=Provenance.USER_STATED,
                         confidence=1.0, basis="the user said so")
    return AnswerResult(
        Outcome.APPLIED,
        patch=SetQuantity(event_id=field.event_id, field_id=field.field_id,
                          quantity=quantity,
                          provenance=Provenance.USER_STATED))


def _grams_from_text(text: str, food_name: str = "") -> Optional[float]:
    """The user's own words as a mass, or None.

    `normalize_quantity` already owns every hard case here — fractions,
    ranges, ordinals, spelled numbers, unit aliases. Reaching for a second
    parser would be the same duplication the migration is removing, one layer
    down.
    """
    try:
        from skills.nutrition.normalize import normalize_quantity
        nq = normalize_quantity(text, food_name or "")
    except Exception:
        logger.debug("quantity answer unparsed", exc_info=True)
        return None
    grams = getattr(nq, "grams", None) if nq is not None else None
    return float(grams) if grams else None


def apply_answer(payload, patches) -> Any:
    """Apply typed patches to a domain payload and return the revised one.

    THE DOMAIN APPLIES THE CHANGE, not this function. A dict merge here would
    make this module a second owner of what a food is — the exact
    responsibility split the directive's ownership map forbids — so it
    dispatches on patch type and asks the payload to revise itself.
    """
    from core.semantics import SemanticPatch

    revised = payload
    for patch in (patches or ()):
        if not isinstance(patch, SemanticPatch):
            raise TypeError(
                f"apply_answer takes typed patches, got "
                f"{type(patch).__name__} — an untyped answer is the shape "
                f"being removed")
        revise = getattr(revised, "revised_with", None)
        if revise is None:
            raise TypeError(
                f"{type(revised).__name__} cannot apply a patch — the domain "
                f"owns the change, and a merge here would make this module a "
                f"second owner of what a food is")
        revised = revise(patch)
    return revised
