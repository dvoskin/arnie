"""Whether one reference may bind to a more specific one, WITH ITS EVIDENCE.

Split from identity after review, 2026-08-04. `same_food` had been answering
both questions, which made `same_food("bread", "banana bread")` return True —
an invalid identity assertion. A meal can contain both.

The adversarial cases did not reproduce a live deletion through `_undeferred`:
its exact-first, injective matching preserved every tested compound/generic
pair. That is evidence about ONE execution path and not architectural
clearance. The surrounding algorithm was compensating for a false predicate,
which is precisely the latent coupling the rebuild exists to remove — so the
predicate is narrowed here and the compensation is made explicit rather than
incidental.

WHY A DECISION OBJECT AND NOT A BOOLEAN. A bare `may_refine(a, b)` invites the
next caller to use it without any of the conditions that make it safe, and
nothing in the type would object. Requiring a `RefinementContext` means a
caller has to state what it knows — that exact matches were resolved first,
that the candidate is unconsumed, that it is the only one — and returning a
`RefinementDecision` means production can be asked WHY a food was bound rather
than only that it was.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RefinementOperation(str, Enum):
    """Which operation is asking. Named so telemetry can separate them and so
    a new caller has to add itself deliberately."""
    UNDEFER_PENDING_ITEM = "undefer_pending_item"
    CORRECTION_BINDING = "correction_binding"
    CLARIFICATION_ANSWER = "clarification_answer"


class RefinementReason(str, Enum):
    ALIAS = "alias"                                   # same entity outright
    UNIQUE_REMAINING_CANDIDATE = "unique_remaining_candidate"
    NOT_RELATED = "not_related"
    AMBIGUOUS = "ambiguous"                           # several candidates
    EXACT_PASS_INCOMPLETE = "exact_pass_incomplete"
    CANDIDATE_CONSUMED = "candidate_consumed"
    UNKNOWN_ENTITY = "unknown_entity"
    CROSSES_BOUNDARY = "crosses_boundary"             # ingredient / distinct


@dataclass(frozen=True)
class RefinementContext:
    """What the CALLER knows. Every field is a condition that must hold for a
    refinement to be safe, and none of them can be inferred from the two names.
    """
    operation: RefinementOperation
    exact_pass_completed: bool = False
    candidate_is_unconsumed: bool = False
    candidate_set_size: int = 0
    quantity_compatible: bool = True


@dataclass(frozen=True)
class RefinementDecision:
    allowed: bool
    reason: RefinementReason
    source_entity_id: Optional[str] = None
    candidate_entity_id: Optional[str] = None
    evidence: tuple = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return self.allowed


def evaluate_refinement(source: str, candidate: str,
                        context: RefinementContext,
                        language: str = "en") -> RefinementDecision:
    """May `candidate` bind `source` in THIS operation?

    Order matters. Identity is checked first and needs no context — an alias is
    an alias. Everything after it is a refinement, and a refinement without the
    caller's conditions is refused no matter how related the two foods are.
    """
    from skills.nutrition.entities import (Relation, may_refine,
                                           relation_between, resolve,
                                           same_food)

    ev = []
    sid, cid = resolve(source, language), resolve(candidate, language)

    def _no(reason):
        return RefinementDecision(False, reason, sid, cid, tuple(ev))

    if sid is None or cid is None:
        ev.append(f"unresolved: source={sid!r} candidate={cid!r}")
        return _no(RefinementReason.UNKNOWN_ENTITY)

    if same_food(source, candidate, language):
        ev.append("same canonical entity or alias of it")
        return RefinementDecision(True, RefinementReason.ALIAS, sid, cid,
                                  tuple(ev))

    rel = relation_between(source, candidate) or relation_between(
        candidate, source)
    if rel in (Relation.INGREDIENT_OF, Relation.DISTINCT):
        ev.append(f"declared {rel.value} — a recorded refusal, not a gap")
        return _no(RefinementReason.CROSSES_BOUNDARY)

    # Refinement is directional; the caller may not know which reading is
    # narrower, so both orders are offered and either may carry it.
    if not (may_refine(source, candidate, language)
            or may_refine(candidate, source, language)):
        ev.append("no refining relation in either direction")
        return _no(RefinementReason.NOT_RELATED)

    # THE CONTEXT GATES, and they are the whole reason this is not a boolean.
    if not context.exact_pass_completed:
        ev.append("exact matches were not resolved first")
        return _no(RefinementReason.EXACT_PASS_INCOMPLETE)
    if not context.candidate_is_unconsumed:
        ev.append("candidate already claimed by another item")
        return _no(RefinementReason.CANDIDATE_CONSUMED)
    if context.candidate_set_size != 1:
        ev.append(f"{context.candidate_set_size} candidates — ambiguous")
        return _no(RefinementReason.AMBIGUOUS)
    if not context.quantity_compatible:
        ev.append("quantities incompatible")
        return _no(RefinementReason.NOT_RELATED)

    ev.append(f"{rel.value if rel else 'refining'} relation, sole candidate, "
              f"after the exact pass")
    return RefinementDecision(True, RefinementReason.UNIQUE_REMAINING_CANDIDATE,
                              sid, cid, tuple(ev))
