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


async def open_food_pending(db, user_id: int) -> tuple:
    """The user's live food clarification, or `(None, None)`.

    The ROUTER needs to know a question is open BEFORE the turn is routed, and
    until now only `core/conversation.py` ever looked — deep inside the legacy
    path, long after the coordinator had already decided. So `RouteStage`'s
    `pending_clarification` branch could never fire on the live path, and every
    answer turn was routed from `food_relevance(text)` alone.

    "half of it", "the big bag", "yes" do not read as food to any gate. Legacy
    routes them structured because it holds the pending question; the
    coordinator predicted GENERAL. So the agreement rate that gates the whole
    rollout was biased against precisely the turns the native lane is least
    ready for — it looked like disagreement about food detection when it was
    the coordinator being handed less information (audit A4 → B1).

    READ-ONLY, deliberately. `conversation.py` resolves an expired pending by
    stamping `answered_at` and committing. Doing that here too would put two
    writers on one row, from a path whose whole contract is deciding without
    side effects. An expired pending is simply reported absent — the same
    answer the caller reaches — and legacy still does the resolving.

    Never raises: a router that cannot read the pending should route the turn
    as cold, not lose it.
    """
    if db is None or not user_id:
        return None, None
    try:
        import json

        from core.food_ledger import pending_expired
        from core.food_turn import ASK_KIND
        from db.queries import get_open_pending_question

        pending = await get_open_pending_question(db, user_id, ASK_KIND)
        if pending is None:
            return None, None
        prior = json.loads(pending.payload_json or "{}")
        if pending_expired(pending, (prior or {}).get("kind")):
            return None, None
        return pending, prior
    except Exception as e:
        logger.debug(f"open food pending unavailable: {e}")
        return None, None


def build_request(*, turn_id: str, user, platform: str, source_type: str,
                  text: str, db=None, today_log=None,
                  in_onboarding: bool = False,
                  client_message_id: Optional[str] = None,
                  food_prior=None, food_pending: bool = False,
                  messages=None):
    """The inbound message as the coordinator's own type.

    `metadata` carries the handles the route stage needs — the session, the
    user, today's board. They are metadata rather than fields because the
    request is transport-independent by design and a db handle is not part of
    what a message IS; the stages that need one reach for it explicitly.

    `food_prior` / `food_pending` are the open clarification, from
    `open_food_pending` above. They were declared by `RouteStage` and
    `ConfirmReplayPlanStage` and set by nobody, so both branches were dead on
    the live path — the only caller that passed them was the shadow-observation
    hook, whose request was then discarded in favour of the ambient route
    computed without them.
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
            "food_prior": food_prior,
            "food_pending": bool(food_pending),
            # the thread, so the native planner can derive `last_assistant`
            # the way legacy does (B-1.8 canary: the planner was blind)
            "messages": tuple(messages or ()),
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
    from core.request_trace import RequestTrace, active as _trace_active
    from core.request_trace import current_trace
    from core.turn_identity import CURRENT_TURN_ID
    from core.turns.factory import build_coordinator
    from core.turns.observe import CURRENT_ROUTE

    # ⛔⛔ A NATIVE TURN WAS UNMEASURED. The RequestTrace lifecycle lives ONLY in
    # `core/conversation.py` (~731-751), so a turn the coordinator DELEGATES
    # reaches it and is recorded, while a turn the coordinator EXECUTES
    # NATIVELY produced no `turn_metrics` row at all — and every `timed()` leaf
    # on that path was a silent no-op. Measured 2026-08-16: neither iOS canary
    # replay left a metric row, while Telegram turns did.
    #
    # ⭐ THAT IS THE SAME OMISSION CLASS AS `CURRENT_TURN_ID`, bound three lines
    # below for the same reason: the native path was built without the ambient
    # bindings the legacy wrapper provides. And it is the one that hurts most —
    # `stages_json` is what diagnosed the first corn failure, so the canary path
    # cannot be the blind one.
    #
    # ⚠ ONLY WHEN THERE IS NO TRACE ALREADY. If a caller (Telegram, or any
    # future wrapper) has one active, this must not start a second — two traces
    # for one turn means two rows, and a duplicated turn reads as extra traffic
    # rather than as double counting.
    _outer = current_trace()
    _rt = _outer or RequestTrace(
        turn_id=getattr(request, "turn_id", "") or "",
        channel=getattr(request, "platform", "") or "",
        command="turn", user_id=getattr(request, "user_id", None))

    coordinator = await build_coordinator(request, **legacy_kwargs)
    # The route this turn took, published for anything downstream that would
    # otherwise compute its own. Set unconditionally — including back to None
    # on the way out — so a prior turn's route cannot leak into this one on a
    # reused task, and so nothing can mistake a stale decision for a fresh one.
    # ⛔⛔ AND THE TURN ID, WHICH THIS PATH NEVER BOUND. `record_ledger_event`
    # stamps `current_turn_id()`, and `core/conversation.py` sets it for the
    # LEGACY path only — so every canonical write made through the coordinator
    # landed with `turn_id = NULL`. Measured in production 2026-08-16: the
    # general settlement owner's rows carry no turn id at all, which loses the
    # correlation key the corpus attribution repair and the coverage instrument
    # are both built on, and leaves canonical rows unlinkable to their turn.
    #
    # Set unconditionally and reset in `finally`, exactly as CURRENT_ROUTE above
    # and `mutation_contract` do: the endpoint runs on a shared worker task, and
    # a leaked contextvar stamps the NEXT turn's writes with this one's id.
    _token = CURRENT_ROUTE.set(getattr(coordinator.route_stage, "decision", None))
    _tid_token = CURRENT_TURN_ID.set(getattr(request, "turn_id", None))
    _outcome = "ok"
    try:
        # Ambient, so `timed()` leaves record themselves — the mechanism that
        # makes `stages_json` mean anything.
        with _trace_active(_rt):
            state = await coordinator.run(request)
        # ⛔ THE COORDINATOR CATCHES A STAGE FAILURE INTO state.error AND
        # RETURNS. Measured 2026-08-18 (canary #2, ios:0EE4B6BD): the
        # correction COMMITTED, a later stage raised, the user got the
        # recovery bubble — and turn_metrics said outcome=ok, because only an
        # exception that ESCAPED run() was ever recorded. The instrument said
        # "ok" on every failed-after-commit turn. Read the state, not the
        # exception path.
        if getattr(state, "error", None) is not None:
            _outcome = f"error:{type(state.error).__name__}"
    except Exception as exc:
        _outcome = f"error:{type(exc).__name__}"
        raise
    finally:
        CURRENT_TURN_ID.reset(_tid_token)
        CURRENT_ROUTE.reset(_token)
        # OURS TO CLOSE ONLY IF OURS TO OPEN. An outer trace belongs to its
        # own owner, which will mark and persist it.
        if _outer is None:
            try:
                _rt.done(outcome=_outcome)
                await _rt.persist_isolated()
            except Exception:            # noqa: BLE001
                # Telemetry describing a turn must never break the turn, the
                # same rule `record_ledger_event` and `persist` already follow.
                logger.warning("native turn metric not persisted turn=%s",
                               getattr(request, "turn_id", "-"), exc_info=True)

    # DELEGATED: `state.execution` IS the legacy TurnResult, unchanged.
    execution = state.execution
    if execution is not None and hasattr(execution, "response"):
        return execution

    # ⛔⛔ A DUPLICATE IS NOT A FAILURE, AND IT REACHED THE USER AS AN OUTAGE.
    #
    # `ExactlyOnceRefusal` is raised when `claim_processed_turn` finds the same
    # (user, lowercased text, plan) inside its 60-minute window. Nothing caught
    # it, so it propagated here, out of `run_chat_turn`, and the client rendered
    # the 500 as "Arnie's temporarily unavailable · Retry". Reproduced through
    # the real turn 2026-08-16 by sending one message twice.
    #
    # ⭐ THE GESTURE THAT HITS IT IS ORDINARY: clear the day, re-log the same
    # food in the same words. Exactly-once exists to DEDUPLICATE; erroring is
    # the one thing it must not do, because the refusal is indistinguishable
    # from the outage it imitates.
    #
    # ⛔⛔ AND IT MUST RETURN HERE, NEVER FALL THROUGH. On a refusal
    # `state.execution` is None, so the `native_no_plan` delegation below would
    # hand an ALREADY-LOGGED meal to the legacy executor and write it a second
    # time — the exact double-log the claim exists to prevent, caused by its own
    # repair. The refusal is raised BEFORE the executor runs, so nothing of this
    # turn was written and there is nothing to undo; the prior turn's row stands.
    #
    # ⭐⭐ THE TWO LINES BELOW ARE ORDER-DEPENDENT, AND MUTATION TESTING IS HOW
    # THAT WAS LEARNED. Deleting the `return` alone leaves the tests GREEN: the
    # delegation is guarded by `not _bubbles`, so giving the duplicate a REPLY
    # already closes that path, and the return is defence-in-depth behind it.
    # Making the reply conditional, or moving it after the return, re-opens the
    # double write with nothing left to catch it.
    #
    # ⛔⛔ AND THE REPLY WAS ALREADY WRITTEN BEFORE THIS RAN — WHICH IS WHY THE
    # SYMPTOM SURVIVED THE FIRST REPAIR. `TurnCoordinator.run` catches EVERY
    # exception and sets `state.response = await finalizer.recover(state)`, the
    # coordinator's failure floor: `recovery_message("llm_error", ...)`. So by
    # the time the refusal reaches here the bubbles are already full, and a
    # replacement guarded only by `not bubbles` is unreachable on the live path.
    # Production kept answering "Something went sideways on my end. Resend that
    # and I'll catch it." — an instruction to retry the one thing that cannot
    # succeed — while every test was green (`conversation_logs` #9223/#9224,
    # user 26, 2026-08-17 02:40 UTC, `build_sha` 8f5501d).
    #
    # ⭐ SO THE CONDITION IS "NO REPLY THIS TURN CAN OWN", NOT "NO REPLY".
    # A recovery bubble is by definition not this turn's answer: it is the
    # product's word for "this failed, send it again", and `is_recovery_text`
    # exists precisely so a stored one is never replayed onto. A duplicate did
    # not fail — the meal is on the board — so the floor is discarded here.
    #
    # ⚠ NARROW ON PURPOSE. Only the refusal branch does this. Every other error
    # still raises below, keeps the floor, and reaches the caller as a failure.
    # ⭐ TWO OWNERS, TWO SIGNALS, ONE ANSWER (A12). The legacy branch of the
    # native stage refuses through `claim_processed_turn`; canonical refuses
    # through its own occurrence check and raises `DuplicateMeal`. Both mean
    # "this meal is already on the board", both are raised before any write, and
    # the user must not be able to tell which owner settled the turn — so the
    # absorption is stated once, over both types.
    #
    # ⚠ THE RENAME LIVES HERE AND NOT IN THE STAGE. A8's AST gate forbids ANY
    # except handler in `NativeExecutionStage.run`, because a handler around
    # settlement is how a canonical refusal reaches the legacy executor. That
    # gate refused the first version of this slice, and it was right.
    from core.general_settlement import DuplicateMeal
    from core.platform import Response
    from core.recovery import is_recovery_text
    from core.turns.stages.execute_native import ExactlyOnceRefusal
    if isinstance(state.error, (ExactlyOnceRefusal, DuplicateMeal)):
        logger.info(
            "event=duplicate_turn_absorbed turn=%s — same (user, text, plan) "
            "inside the claim window; answering from the prior turn rather "
            "than raising, and NOT delegating to legacy",
            getattr(request, "turn_id", "-"))
        state.error = None
        _said = [b for b in (getattr(state.response, "bubbles", None) or ())
                 if (b or "").strip()]
        if not _said or any(is_recovery_text(b) for b in _said):
            state.response = Response.from_text("Already logged that one.")
        return _result_from_state(state, legacy_kwargs)

    # ⭐ A CANONICAL REFUSAL IS AN ANSWER, NOT AN OUTAGE *(P17 live canary #2,
    # 2026-08-18; CF2)*. "Salty peanut" — an answer to legacy's still-open
    # flavor question — became update_food_entry on a row the user had already
    # deleted; correct_identity refused (correctly: nothing to correct, no
    # evidence to rebind to); the refusal PROPAGATED (A8, correctly, never
    # legacy) — and the client rendered it as "Arnie's temporarily unavailable
    # · Retry", six times across WS + REST retries (turn_metrics outcome
    # error:CorrectionRefused). Non-mutating by construction, so it is
    # answered here in words, the same way a duplicate is absorbed above: no
    # write, no legacy, no raise. The exception's own text is developer copy;
    # the sentence is chosen by refusal KIND.
    from core.canonical_correction import CorrectionRefused
    from skills.nutrition.correction_application import ScanBoundCorrectionRefused
    from core.scan_authority import ScanAuthorityRefusal
    from core.product_bound_ask import BoundAskNotSingular
    from core.turns.stages.execute_native import (ScanBindingDecisionUnavailable,
                                                  ScanBoundIdentityUnavailable,
                                                  ScanBoundNotLegacy)
    # ⚠ `ScanBoundCorrectionRefused` is here as DEFENCE IN DEPTH, not as a
    # route: the CF5 backstop should stop a bound turn long before correction
    # application sees it. But an invariant that prevents a bad write and then
    # surfaces as "Arnie's temporarily unavailable" has traded a wrong number
    # for an outage — CF2's lesson, and the reason every canonical refusal
    # gets user-grade copy.
    if isinstance(state.error, (CorrectionRefused, ScanBoundNotLegacy,
                                ScanBoundIdentityUnavailable,
                                ScanBindingDecisionUnavailable,
                                ScanBoundCorrectionRefused,
                                ScanAuthorityRefusal, BoundAskNotSingular)):
        # CF5b: `ScanBoundNotLegacy` is answered here beside the correction
        # refusals — same contract: no write, no legacy, no raise, words.
        logger.info("event=canonical_refusal_answered turn=%s kind=%s reason=%s",
                    getattr(request, "turn_id", "-"),
                    type(state.error).__name__, state.error)
        state.response = Response.from_text(_refusal_copy(state.error))
        state.error = None
        return _result_from_state(state, legacy_kwargs)

    if state.error is not None:
        raise state.error

    # ⛔⛔ A TURN THE NATIVE LANE CANNOT EXECUTE MUST NOT BE SWALLOWED.
    #
    # Measured in production 2026-08-16: "I had a corn on the cob" reached the
    # native lane, the interpreter produced NO log operation,
    # `NativeExecutionStage` returned None, the renderer had nothing committed
    # to narrate, and `_result_from_state` built `Response.from_text("")` — an
    # EMPTY reply. Delivery substituted the recovery bubble and the user was
    # told "Lost the thread there. Try one more time and I'll catch it." NO ROW
    # WAS WRITTEN. Legacy had logged the identical message hours earlier.
    #
    # ⭐ AND THIS IS NOT THE A8 FALLBACK, WHICH IS FORBIDDEN. A8 forbids
    # reaching legacy AFTER canonical settlement has begun, because that is two
    # settlement owners for one meal. Here `state.execution is None` means the
    # execution stage returned before taking any claim and before any canonical
    # write — NOTHING WAS SETTLED and no ownership was transferred. Handing
    # such a turn to the legacy pipeline is the correct behaviour, and the
    # distinction is the line A8 actually draws:
    #
    #     no plan, nothing settled        -> legacy runs the turn      ALLOWED
    #     canonical settled then refused  -> propagate, never legacy   FORBIDDEN
    #
    # ⚠ AND AN ASK IS NOT AN EMPTY TURN. A clarification legitimately produces
    # a response with no execution, so the response is checked too — delegating
    # one would ask the question twice.
    _bubbles = getattr(state.response, "bubbles", None)
    if state.execution is None and not _bubbles:
        logger.info(
            "event=native_no_plan turn=%s — the native lane produced nothing "
            "executable and nothing to say; delegating to legacy BEFORE any "
            "settlement rather than returning an empty reply",
            getattr(request, "turn_id", "-"))
        from core.turns.stages.execute import LegacyExecutionStage
        delegated = await LegacyExecutionStage(**legacy_kwargs).run(request)
        if delegated is not None:
            return delegated

    return _result_from_state(state, legacy_kwargs)


def _refusal_copy(exc) -> str:
    """User-grade copy for a canonical correction refusal, by KIND. Honest and
    bounded: says what did not happen and what would make it happen. Never
    the exception text (developer copy), never a claim of success."""
    from core.canonical_correction import (ProductSelectionRefused,
                                           StaleUndo)
    from skills.nutrition.correction_application import ScanBoundCorrectionRefused
    from core.scan_authority import ScanAuthorityRefusal
    from core.product_bound_ask import BoundAskNotSingular
    from core.turns.stages.execute_native import (ScanBindingDecisionUnavailable,
                                                  ScanBoundIdentityUnavailable,
                                                  ScanBoundNotLegacy)
    if isinstance(exc, BoundAskNotSingular):
        return ("I have the scanned product but couldn't set up the question "
                "about it cleanly, so I left everything as it was. Send it "
                "once more, or tell me the amount.")
    if isinstance(exc, ScanAuthorityRefusal):
        # CF5c, by REASON — each says what actually happened, because "I
        # couldn't read the scan" and "tell me how much" are different
        # problems for the person holding the phone.
        if exc.reason == "no_consumption":
            return ("Got the scanned product. I haven't logged it — tell me "
                    "if you had it and how much, and I'll log it from the "
                    "label.")
        if exc.reason == "no_quantity_ask":
            return ("I have the scanned product, but I couldn't tell what you "
                    "had of it, so I didn't log anything. Tell me the amount "
                    "and I'll log it from the label.")
        if exc.reason == "impossible_shape":
            return ("I have the scanned product, but I couldn't tell how it "
                    "fits what you asked for, so I left everything as it was. "
                    "Tell me the food and the amount and I'll log it.")
        return ("Something went wrong reading that scan, so I didn't change "
                "anything. Scan it again, or tell me the food and the amount.")
    if isinstance(exc, ScanBindingDecisionUnavailable):
        return ("Something went wrong reading that scan, so I didn't change "
                "anything. Scan it again, or tell me the food and the amount "
                "and I'll log it.")
    if isinstance(exc, ScanBoundCorrectionRefused):
        return ("I have the scanned product, so I didn't apply that as a "
                "change to an existing entry. Tell me how much of it you had "
                "and I'll log it from the label.")
    if isinstance(exc, ScanBoundIdentityUnavailable):
        return ("I couldn't read the scanned product's details just now, so I "
                "didn't log anything. Scan it again, or tell me the food and "
                "the amount.")
    if isinstance(exc, ScanBoundNotLegacy):
        return ("I have the scanned product, but I read that as a change to "
                "another entry, so I didn't touch anything. Tell me how much "
                "of it you had and I'll log it from the label.")
    if isinstance(exc, StaleUndo):
        return ("That undo is out of date — something changed on that entry "
                "since. Undo the newer change first, or tell me what it "
                "should say and I'll set it.")
    if isinstance(exc, ProductSelectionRefused):
        return ("I couldn't match that to the scanned product, so I left the "
                "entry alone. Scan it again and tell me the amount.")
    text = str(exc or "").lower()
    if "does not exist" in text or "not this user's" in text:
        return ("That entry isn't on the board any more, so there was nothing "
                "to update. If you ate it, tell me the food and amount and "
                "I'll log it fresh.")
    return ("I couldn't apply that correction from what I know, so I left the "
            "entry as it was. Tell me the food and the amount and I'll log it "
            "fresh.")


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
