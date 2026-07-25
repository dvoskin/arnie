"""The one way into a turn (architecture review item 1).

`run_chat_turn()` called `core.conversation.run_turn()` directly and never
built a coordinator. The coordinator existed, had legal phase transitions, and
structurally prevented render-before-commit and double execution — and none of
that reached production, because the only thing with side effects was the
2,000-line procedural path it was supposed to front. The coordinator was a
shadow observer predicting what it would have done, alongside the thing
actually doing it.

This is the seam that ends that. Every inbound turn is built into a
`TurnRequest` and handed to `build_coordinator`, which decides — in ONE
expression — whether the lane runs natively or delegates. The delegating path
still calls `run_turn()`; that is the point of the adapter and it is unchanged.
What changes is that the caller no longer has a choice, so there is no longer a
state where both the coordinator and the legacy pipeline are independently
invoked for the same message.

Promoting a lane is now what it always claimed to be: a configuration change,
with nothing at the call site to edit.

The return type is `TurnResult` either way. Native lanes have no legacy
TurnResult to hand back, so one is assembled from the coordinator's own state —
the response it rendered and the snapshot it committed. Callers cannot tell
which path ran, which is what makes the promotion safe to make gradually.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_request(*, turn_id: str, user, platform: str, source_type: str,
                  text: str, db=None, today_log=None,
                  in_onboarding: bool = False,
                  client_message_id: Optional[str] = None):
    """The inbound message as the coordinator's own type.

    `metadata` carries the handles the route stage needs — the session, the
    user, today's board. They are metadata rather than fields because the
    request is transport-independent by design and a db handle is not part of
    what a message IS; the stages that need one reach for it explicitly.
    """
    from core.turns.models import TurnRequest
    return TurnRequest(
        turn_id=turn_id or "-",
        user_id=getattr(user, "id", 0),
        platform=platform,
        source_type=source_type,
        text=text or "",
        client_message_id=client_message_id,
        metadata={
            "db": db,
            "user": user,
            "today_log": today_log,
            "in_onboarding": bool(in_onboarding),
            "has_board": bool(getattr(today_log, "food_entries", None)),
        },
    )


async def run_turn(*, request, **legacy_kwargs) -> Any:
    """Run one turn through the coordinator and return its `TurnResult`.

    The coordinator owns the phase machine, so a stage that crashes lands in
    its recovery rather than propagating a half-executed turn to the caller.
    `state.error` is re-raised for the delegating path, because `run_turn()`
    already has its own recovery and swallowing an exception here would hide a
    failure the legacy path was prepared to report honestly.
    """
    from core.turns.factory import build_coordinator
    from core.turns.observe import CURRENT_ROUTE

    coordinator = await build_coordinator(request, **legacy_kwargs)
    # The route this turn took, published for anything downstream that would
    # otherwise compute its own. Set unconditionally — including back to None
    # on the way out — so a prior turn's route cannot leak into this one on a
    # reused task, and so nothing can mistake a stale decision for a fresh one.
    _token = CURRENT_ROUTE.set(getattr(coordinator.route_stage, "decision", None))
    try:
        state = await coordinator.run(request)
    finally:
        CURRENT_ROUTE.reset(_token)

    # DELEGATED: `state.execution` IS the legacy TurnResult, unchanged.
    execution = state.execution
    if execution is not None and hasattr(execution, "response"):
        return execution

    if state.error is not None:
        raise state.error

    return _result_from_state(state, legacy_kwargs)


def _result_from_state(state, legacy_kwargs) -> Any:
    """A `TurnResult` for a turn the coordinator ran natively.

    Assembled from what the coordinator itself holds rather than from anything
    the legacy pipeline produced — there is nothing to read there, which is the
    whole point of a native lane. A turn that reached here without a response
    (a hold, a validation that declined to execute) still returns a result, so
    the caller's persistence and delivery run exactly once either way.
    """
    from core.platform import Response
    from core.conversation import TurnResult

    response = state.response
    if response is None or not hasattr(response, "bubbles"):
        response = Response.from_text("") if response is None else response

    return TurnResult(
        response=response,
        tool_calls=list(getattr(state.validation, "approved_operations", ())
                        or ()),
        just_completed=False,
        in_onboarding=bool((state.request.metadata or {}).get("in_onboarding")),
        onboarding_field_saved=None,
        today_log=(state.request.metadata or {}).get("today_log"),
        user=(state.request.metadata or {}).get("user")
        or legacy_kwargs.get("user"),
        health_flags=set(state.health_flags or ()),
        skills_fired=(),
        streamed_bubble_count=0,
        streamed_card_ids=(),
        needs_location_share=False,
    )
