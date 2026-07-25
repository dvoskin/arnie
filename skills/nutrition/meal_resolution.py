"""Mixed commit states and meal grouping (build order 10, 11, 12).

One meal can legitimately contain, at the same moment:

    resolved exact       200 g of chicken — the user weighed it
    resolved estimated   a handful of blueberries — we estimated 45 g ± 15
    held                 "a Fairlife" — which bottle materially matters
    failed               a write the executor refused

Every earlier version of this collapsed to one state per turn, and both
collapses are wrong. "All committed" describes the held item as logged. "All
held" makes the certain chicken wait on the uncertain bottle.

The second half of the module is the thing that makes partial commit
survivable: a shared meal_group_id. When moderate mode commits two items and
holds one, the held item's later resolution must join the SAME meal — not
appear as an unrelated entry an hour later with its own card, its own timeline
position, and its own totals that do not add up to anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Optional

from skills.nutrition.staging import (FoodAssumption, ResolutionStatus,
                                      StagedFoodItem)


class ItemOutcome(str, Enum):
    """What actually happened to one item this turn. Deliberately distinct from
    ResolutionStatus: an item can be RESOLVED_EXACT and still fail to write."""
    COMMITTED_EXACT = "committed_exact"
    COMMITTED_ESTIMATED = "committed_estimated"
    HELD = "held"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_committed(self) -> bool:
        return self in (ItemOutcome.COMMITTED_EXACT,
                        ItemOutcome.COMMITTED_ESTIMATED)


@dataclass(frozen=True)
class ResolvedItem:
    """A committed item, with the entry it became."""
    staged_item_id: str
    outcome: ItemOutcome
    entry_id: Optional[int] = None
    event_id: Optional[int] = None
    name: str = ""
    quantity_text: str = ""
    nutrients: Optional[Mapping[str, float]] = None
    source: str = ""
    confidence: float = 0.0
    assumptions: tuple = ()
    meal_group_id: str = ""


@dataclass(frozen=True)
class PendingItem:
    """A held item, and why. `question_id` is what an incoming answer binds
    to — never the meal, never the most recent food."""
    staged_item_id: str
    name: str = ""
    original_text: str = ""
    question_id: str = ""
    requested_fields: tuple = ()
    reason: str = ""
    meal_group_id: str = ""
    outcome: ItemOutcome = ItemOutcome.HELD


@dataclass(frozen=True)
class FailedItem:
    staged_item_id: str
    name: str = ""
    reason: str = ""
    detail: str = ""
    meal_group_id: str = ""
    outcome: ItemOutcome = ItemOutcome.FAILED


@dataclass(frozen=True)
class MealResolution:
    """The whole turn's outcome, with every item in its own real state.

    Renderers read `committed` for what to narrate as logged and `pending` for
    what to describe as waiting. Nothing in `pending` may be narrated as
    logged — that is enforced by them being different collections rather than
    one list with a flag someone forgets to check.
    """
    meal_group_id: str
    committed: tuple = ()
    pending: tuple = ()
    failed: tuple = ()
    skipped: tuple = ()
    assumptions: tuple = ()
    turn_id: str = ""

    @property
    def is_complete(self) -> bool:
        return not self.pending

    @property
    def is_partial(self) -> bool:
        return bool(self.committed) and bool(self.pending)

    @property
    def committed_nothing(self) -> bool:
        return not self.committed

    def item_ids(self) -> tuple:
        return tuple(i.staged_item_id for i in
                     (*self.committed, *self.pending, *self.failed,
                      *self.skipped))

    def pending_for(self, staged_item_id: str) -> Optional[PendingItem]:
        return next((p for p in self.pending
                     if p.staged_item_id == staged_item_id), None)

    def totals(self) -> dict:
        """Macro totals over COMMITTED items only.

        A held item contributes nothing, because it is not in the day. Adding
        its estimate here is how a card shows three items and a total that
        matches two of them.
        """
        out = {}
        for item in self.committed:
            for key, value in (item.nutrients or {}).items():
                if value is None:
                    continue
                out[key] = round(out.get(key, 0.0) + float(value), 1)
        return out

    def describe_state(self) -> str:
        """A one-line summary for the trace. Deliberately explicit about the
        mixed case, since that is the state most likely to be mis-narrated."""
        parts = []
        if self.committed:
            exact = sum(1 for c in self.committed
                        if c.outcome is ItemOutcome.COMMITTED_EXACT)
            est = len(self.committed) - exact
            parts.append(f"{exact} exact, {est} estimated")
        if self.pending:
            parts.append(f"{len(self.pending)} held")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        return "; ".join(parts) or "nothing"


# ── assembly ──────────────────────────────────────────────────────────────────
def build_resolution(*, meal_group_id: str, items, decision,
                     execution_by_item: Mapping[str, Mapping] = None,
                     turn_id: str = "") -> MealResolution:
    """Assemble the turn's outcome from the staged items and the policy's
    decision.

    An item is committed only if the decision made it ready AND the executor
    actually wrote it. Ready-but-unwritten is FAILED, not committed: the
    distinction is the whole reason narration can be trusted.
    """
    execution_by_item = execution_by_item or {}
    ready = set(decision.ready_item_ids or ())
    held = set(decision.held_item_ids or ())
    questions_by_item = {}
    for q in (decision.questions or ()):
        questions_by_item.setdefault(q.staged_item_id, q)

    committed, pending, failed, skipped = [], [], [], []

    for item in items or []:
        name = item.identity.describe() or item.original_text
        if item.resolution_status is ResolutionStatus.REJECTED:
            skipped.append(FailedItem(
                staged_item_id=item.staged_item_id, name=name,
                reason="rejected", meal_group_id=meal_group_id,
                outcome=ItemOutcome.SKIPPED))
            continue

        if item.staged_item_id in ready:
            wrote = execution_by_item.get(item.staged_item_id)
            if not wrote or wrote.get("entry_id") is None:
                failed.append(FailedItem(
                    staged_item_id=item.staged_item_id, name=name,
                    reason=(wrote or {}).get("reason", "not_written"),
                    detail=(wrote or {}).get("detail", ""),
                    meal_group_id=meal_group_id))
                continue
            item_assumptions = tuple(
                a for a in (decision.assumptions or ())
                if a.staged_item_id == item.staged_item_id)
            outcome = (ItemOutcome.COMMITTED_ESTIMATED if item_assumptions
                       or item.resolution_status is
                       ResolutionStatus.RESOLVED_ESTIMATED
                       else ItemOutcome.COMMITTED_EXACT)
            committed.append(ResolvedItem(
                staged_item_id=item.staged_item_id, outcome=outcome,
                entry_id=wrote.get("entry_id"), event_id=wrote.get("event_id"),
                name=wrote.get("name") or name,
                quantity_text=wrote.get("quantity_text")
                or item.quantity.describe(),
                nutrients=wrote.get("nutrients"),
                source=wrote.get("source", ""),
                confidence=float(wrote.get("confidence") or 0.0),
                assumptions=item_assumptions, meal_group_id=meal_group_id))
            continue

        if item.staged_item_id in held:
            q = questions_by_item.get(item.staged_item_id)
            pending.append(PendingItem(
                staged_item_id=item.staged_item_id, name=name,
                original_text=item.original_text,
                question_id=(q.question_id if q else ""),
                requested_fields=(tuple(q.requested_fields) if q else ()),
                reason=_hold_reason(item),
                meal_group_id=meal_group_id))
            continue

        # Neither ready nor held: the decision did not cover it. Held is the
        # safe default — an uncovered item must never be assumed written.
        pending.append(PendingItem(
            staged_item_id=item.staged_item_id, name=name,
            original_text=item.original_text, reason="undecided",
            meal_group_id=meal_group_id))

    return MealResolution(
        meal_group_id=meal_group_id, committed=tuple(committed),
        pending=tuple(pending), failed=tuple(failed), skipped=tuple(skipped),
        assumptions=tuple(decision.assumptions or ()), turn_id=turn_id)


def _hold_reason(item: StagedFoodItem) -> str:
    material = [a for a in item.ambiguities if a.is_material]
    if material:
        worst = max(material, key=lambda a: a.materiality_score)
        return worst.ambiguity_type.value
    return "atomic_hold"


# ── joining a later answer to the same meal (build order 12) ──────────────────
def attach_to_meal(resolution: MealResolution, *, staged_item_id: str,
                   entry_id: int, event_id: Optional[int] = None,
                   name: str = "", quantity_text: str = "",
                   nutrients: Mapping[str, float] = None, source: str = "",
                   confidence: float = 0.0,
                   assumptions: tuple = ()) -> MealResolution:
    """Move a held item into committed, keeping the meal group.

    This is what stops a resolved clarification from appearing as an unrelated
    entry with its own card and a total that adds up to nothing.
    """
    held = resolution.pending_for(staged_item_id)
    if held is None:
        return resolution
    item = ResolvedItem(
        staged_item_id=staged_item_id,
        outcome=(ItemOutcome.COMMITTED_ESTIMATED if assumptions
                 else ItemOutcome.COMMITTED_EXACT),
        entry_id=entry_id, event_id=event_id, name=name or held.name,
        quantity_text=quantity_text, nutrients=nutrients, source=source,
        confidence=confidence, assumptions=tuple(assumptions),
        meal_group_id=resolution.meal_group_id)
    return replace(
        resolution,
        committed=resolution.committed + (item,),
        pending=tuple(p for p in resolution.pending
                      if p.staged_item_id != staged_item_id),
        assumptions=resolution.assumptions + tuple(assumptions))


def drop_from_meal(resolution: MealResolution,
                   staged_item_id: str) -> MealResolution:
    """"skip it" / "don't log the yogurt" — the held item leaves without
    becoming an entry, and without cancelling what already committed."""
    held = resolution.pending_for(staged_item_id)
    if held is None:
        return resolution
    return replace(
        resolution,
        pending=tuple(p for p in resolution.pending
                      if p.staged_item_id != staged_item_id),
        skipped=resolution.skipped + (FailedItem(
            staged_item_id=staged_item_id, name=held.name, reason="user_skipped",
            meal_group_id=resolution.meal_group_id,
            outcome=ItemOutcome.SKIPPED),))
