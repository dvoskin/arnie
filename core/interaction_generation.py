"""B-1.6b — REBUILDING THE ANSWER SURFACE WHEN ITS SHAPE CHANGES.

    reconciliation  ->  next_generation()  ->  a NEW ClarificationInteraction
                                               at revision + 1

THE PRODUCER CONSUMES ACTIVATION; IT DOES NOT COMPUTE IT. Everything here
takes a `Reconciliation` as input and never calls `active_attributes` itself.
If it recomputed, `active_when` would be advisory and there would be two
owners of when a field is asked — the exact defect B-1.6a exists to remove,
reintroduced one layer up.

ONE SHAPE CHANGE, ONE REVISION BUMP, ALL FIELDS REBUILT. `field_id` is
`operation:event:attribute:revision`, so a surviving field carried forward at
its old revision would produce a MIXED-GENERATION interaction — half the chips
on screen addressing a generation that no longer exists.
`ClarificationInteraction.__post_init__` refuses to construct one, which is
why this rebuilds every rendered field rather than patching the list.

A VALUE CHANGE IS NOT A SHAPE CHANGE. Answering an already-active field with a
different value must NOT bump the revision: `revision` means "answer-surface
generation", and letting any mutation move it would turn every stale-tap
rejection into a race with the user's own typing.

ACTIVE-BUT-RESOLVED FIELDS DO NOT RENDER. `present=yes` arriving with the
amount already known reconciles straight to active-and-resolved, so no amount
question is ever produced — not produced-then-withdrawn. A transient question
is a visible flicker and, worse, a chip a fast user can tap.
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional

logger = logging.getLogger(__name__)


def renderable(*, active, resolved_attributes) -> tuple:
    """Active AND unresolved, in deterministic topological order.

    THE ORDER IS NOT `sorted(active)` AND NOT SET ITERATION. Field order
    reaches the iOS payload, so an order that depends on registry insertion is
    a rendering difference with no semantic cause — which gets diagnosed as a
    client bug.
    """
    from core.field_activation import activation_order

    answered = {str(a) for a in (resolved_attributes or ())}
    live = {str(a) for a in (active or ())}
    return tuple(a for a in activation_order()
                 if a in live and a not in answered)


def _field_for(attribute: str, *, operation_id: str, revision: int,
               event_id: str):
    """Build ONE unresolved field FROM ITS SPEC.

    GENERIC, NOT A PER-ATTRIBUTE BRANCH. `if attribute == "added_fat_present":
    build_yes_no()` would make the producer a second place that knows what a
    field is, and the next field would add the next branch. The spec already
    declares its value space, its vocabulary and its patch type; this turns
    those into a field and knows nothing about fat, chicken or grams.
    """
    from core.semantic_fields import ValueSpace, spec_for
    from core.semantics import (ClarificationAttribute, ClarificationOption,
                                Provenance, ResponseType, UnresolvedField,
                                patch_from_payload)

    spec = spec_for(attribute)
    identity = dict(operation_id=operation_id, revision=revision,
                    event_id=event_id,
                    attribute=ClarificationAttribute(attribute))
    # Derived from semantics, so the id is the same one the options must name.
    field_id = UnresolvedField(**identity).field_id

    if spec.value_space is not ValueSpace.ENUMERATED or not spec.vocabulary:
        # MEASURED, or enumerated with nothing to offer: free text with the
        # fallback said out loud. C15 exists because a blank select is what a
        # client "repairs" by parsing prose.
        return UnresolvedField(**identity,
                               response_type=ResponseType.FREE_TEXT_FALLBACK)

    options = []
    for value in spec.vocabulary:
        payload = {"patch_type": spec.patch_type, "schema_version": 1,
                   "event_id": event_id, "field_id": field_id,
                   "provenance": Provenance.USER_SELECTED.value}
        payload.update(_value_payload(spec, value))
        options.append(ClarificationOption(
            label=str(value).capitalize(), option_id=f"{attribute}_{value}",
            field_id=field_id, patch=patch_from_payload(payload)))
    return UnresolvedField(**identity, response_type=ResponseType.SINGLE_SELECT,
                           options=tuple(options))


def _value_payload(spec, value) -> dict:
    """The vocabulary term as the patch's own value field.

    Kept narrow deliberately. A domain whose enumerated patch needs more than
    one key registers a builder rather than growing a branch here — and the
    day that happens, this raises instead of storing a patch missing its
    value, because a silently valueless answer is worse than a refused one.
    """
    from core.semantics import PATCH_TYPES

    cls = PATCH_TYPES[spec.patch_type]
    # `patch_type` is a ClassVar the discriminator already carries, and the
    # base's three identity fields are set by the caller. What is left is the
    # value the vocabulary term means.
    names = {f for f in getattr(cls, "__dataclass_fields__", {})} - {
        "event_id", "field_id", "provenance", "patch_type"}
    if len(names) != 1:
        raise ValueError(
            f"{spec.patch_type} carries {sorted(names)}; a generic vocabulary "
            f"option can only fill a single value field. Register a builder "
            f"for this field rather than guessing which key the term means")
    name = names.pop()
    if name == "present":
        return {name: str(value).strip().lower() in ("yes", "true", "y")}
    return {name: value}


def next_generation(*, previous, reconciliation, answered: Mapping,
                    item: Optional[Mapping] = None):
    """The rebuilt interaction, or None when the shape did not change.

    RETURNING NONE IS THE COMMON CASE AND THE IMPORTANT ONE. Most answers
    resolve a field without changing which fields exist; rebuilding then would
    bump the revision, invalidate every chip on screen, and make a user who
    answers two questions quickly race themselves.
    """
    from core.field_activation import attribute_of_field_id
    from core.semantics import ClarificationGroup, ClarificationInteraction

    if not reconciliation.changed:
        return None

    revision = int(previous.revision) + 1        # ONE bump per shape change
    resolved = {attribute_of_field_id(f, p) for f, p in (answered or {}).items()}
    show = renderable(active=reconciliation.active, resolved_attributes=resolved)

    groups = []
    for group in previous.groups:
        fields = tuple(_field_for(a, operation_id=previous.operation_id,
                                  revision=revision, event_id=group.event_id)
                       for a in show)
        if fields:
            groups.append(ClarificationGroup(event_id=group.event_id,
                                             label=group.label, fields=fields))

    logger.info("event=interaction_regenerated operation=%s revision=%d->%d "
                "rendered=%s newly_active=%s newly_inactive=%s",
                previous.operation_id, previous.revision, revision,
                ",".join(show) or "-",
                ",".join(reconciliation.newly_active) or "-",
                ",".join(reconciliation.newly_inactive) or "-")

    return ClarificationInteraction(
        interaction_id=previous.interaction_id,
        operation_id=previous.operation_id, revision=revision,
        introduction=previous.introduction, groups=tuple(groups))
