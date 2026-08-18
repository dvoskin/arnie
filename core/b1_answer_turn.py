"""B-1 part 3: an owned answer completes canonically, or not at all.

    owning()  ->  verify  ->  claim  ->  chip | text  ->  APPLIED / REPAIR
                                                        / CANCELLED / REFUSED
                                                     ->  settle | cancel

WHAT IS DELIBERATELY ABSENT FROM THIS MODULE
--------------------------------------------
`skills.nutrition.quantity_rollout`. Not "unused" — ABSENT, and a test reads
this file's source to keep it that way. The gate is asked once, before
ownership exists; asking it again here is the mid-flight fallback the
directive forbids, and a rule enforced only by discipline is one careless
import from breaking.

`core.food_turn.run`. Handing an answer to the broad food interpreter is how
"6 oz" became a second meal. There is no call to it here and no branch that
could reach one: an owned turn returns from this module or from nowhere.

TWO DISTINCTIONS THAT LOOK ALIKE AND ARE NOT
--------------------------------------------
An UNREADABLE USER ANSWER repairs. The user said something we could not parse;
they can say it again, and the field is still answerable.

A CORRUPT STORED OPERATION fails. We cannot apply ANY answer to it, so asking
again invites a second answer into the same void. It terminates visibly
instead. Presenting our own storage failure as a question to the user is both
dishonest and an infinite loop.

An OFFERED LABEL is a selection. On Telegram and iMessage a chip comes back as
its literal text ("6 oz"), not as an option id — but it is still the option we
offered, so its meaning is LOADED from the stored patch and its provenance is
`USER_SELECTED`. Only a quantity we never offered is `USER_STATED`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from core import b1_quantity_operation as ops
from core.clarification_answer import (Outcome, answer_from_chip,
                                       answer_from_text)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnswerTurn:
    """What an owned answer turn did. Rendered by the caller, never by here."""
    outcome: Outcome
    operation_id: str = ""
    field_id: str = ""
    patch: Any = None
    result: Any = None
    reason: str = ""
    #: Set when OUR state, not the user's answer, was the problem.
    internal_failure: bool = False
    #: THE FOOD THE OPEN QUESTION IS ABOUT, carried so a re-ask can name it.
    #: Committed turns get the name from the row they wrote; a REPAIR writes
    #: nothing, so without this the re-ask has no subject and has to say "it".
    subject_name: str = ""
    #: WHY we re-asked, typed. Copied from the answer, never re-derived.
    repair_reason: str = ""
    #: WHY a structured answer was refused, typed. A client branches on this;
    #: prose is not a branch condition.
    refusal_reason: str = ""
    #: WHICH FIELDS ARE STILL OPEN on a PARTIAL turn, as attribute names
    #: (B-1.5). Carried so the re-ask can say WHAT it still needs instead of
    #: repeating the whole question — and so a renderer never has to reach
    #: into the interaction to find out.
    open_attributes: tuple = ()
    #: THE STILL-OPEN FIELDS, in the client's own wire shape (B-1.5).
    #:
    #: Sent back on a PARTIAL so the client re-renders exactly the rows that
    #: remain. Without it the client keeps the interaction it already had and
    #: goes on offering the field it just answered — and the alternative,
    #: letting it work out which rows to drop, is the client deciding what the
    #: operation still needs. Readiness is server-owned; so is this.
    remaining: Optional[dict] = None

    @property
    def applied(self) -> bool:
        """The user has an authoritative result — new OR replayed.

        Deliberately true for both, because every caller that asks "did this
        turn succeed" means this. `mutated` is the narrower question.
        """
        return (self.outcome in (Outcome.APPLIED, Outcome.REPLAY)
                and not self.internal_failure)

    @property
    def mutated(self) -> bool:
        """A NEW meal was written. The count "successful applications" means
        this one, and conflating it with a replay inflates every rate computed
        from it."""
        return self.outcome is Outcome.APPLIED and not self.internal_failure

    @property
    def repair(self) -> bool:
        return self.outcome is Outcome.REPAIR and not self.internal_failure

    @property
    def cancelled(self) -> bool:
        return self.outcome is Outcome.CANCELLED

    @property
    def refused(self) -> bool:
        return self.outcome is Outcome.REFUSED and not self.internal_failure

    @property
    def failed(self) -> bool:
        return self.internal_failure


async def handle(db, *, user, source_turn_id: str, message: str = "",
                 field_id: str = "", option_id: str = "",
                 revision: Optional[int] = None) -> Optional[AnswerTurn]:
    """Answer an owned operation, or return None if none owns this user.

    None means "not ours" and ONLY that — the caller proceeds exactly as it
    does today. Every other return means the canonical path handled the turn
    and the legacy lane must not run.
    """
    try:
        owned = await ops.owning(db, user)
    except Exception as exc:
        # THE THIRD STATE, and caught by OUTCOME rather than by type. We do
        # not know whether a canonical operation owns this meal, so both
        # remaining moves are unsafe: proceeding legacy may duplicate a meal
        # that is already pending, and proceeding canonically has nothing to
        # proceed with. Log nothing, write nothing, and say so.
        #
        # `OwnershipUnknown` is what the lookup raises deliberately; anything
        # else reaching here means the same thing and is more alarming, not
        # less. Narrowing this to one class would let an unforeseen error
        # propagate to the caller's handler, which reads a raise as "not
        # ours" — the exact collapse this whole item exists to prevent.
        logger.error("event=b1_ownership_unknown user=%s",
                     getattr(user, "id", None), exc_info=True)
        return AnswerTurn(Outcome.REFUSED, internal_failure=True,
                          reason=f"ownership unknown: {exc!r}")
    if owned is None:
        return None

    # ONCE OWNERSHIP IS ESTABLISHED, THIS FUNCTION IS TOTAL. Every remaining
    # failure resolves to a canonical outcome, never to a return of None —
    # because None means "not ours" and the caller reads it as permission to
    # run the legacy interpreter. An owned meal handed to the interpreter
    # because settle() threw is the duplicate-meal path arriving through an
    # error handler.
    try:
        return await _handle_owned(
            db, user=user, owned=owned, source_turn_id=source_turn_id,
            message=message, field_id=field_id, option_id=option_id,
            revision=revision)
    except Exception as exc:
        logger.error("event=b1_answer_failed operation=%s user=%s",
                     owned.operation_id, getattr(user, "id", None),
                     exc_info=True)
        return AnswerTurn(Outcome.REFUSED, operation_id=owned.operation_id,
                          internal_failure=True, reason=repr(exc))


async def _handle_owned(db, *, user, owned, source_turn_id: str, message: str,
                        field_id: str, option_id: str,
                        revision: Optional[int]) -> AnswerTurn:
    if not owned.readable:
        # OUR failure, not theirs. Terminate rather than re-ask: no answer to
        # this operation could be applied, so a repair question would collect
        # a second answer into the same void.
        await ops.fail(db, owned=owned, user=user,
                       reason="stored interaction unreadable")
        logger.error("event=b1_operation_corrupt operation=%s user=%s",
                     owned.operation_id, user.id)
        return AnswerTurn(Outcome.REFUSED, operation_id=owned.operation_id,
                          internal_failure=True,
                          reason="stored interaction unreadable")

    interaction = owned.interaction

    # ⭐ THE FIELD AN UNADDRESSED ANSWER APPLIES TO IS THE FIRST *OPEN* ONE.
    #
    # This read `interaction.groups[0].fields[0]` — the first field, forever —
    # which made B-1.5 a single-field system wearing a two-field interaction.
    # MEASURED IN PRODUCTION 2026-08-10: quantity was answered and held, then
    # every subsequent answer was still routed to QUANTITY. "Grilled" matched
    # no quantity label, parsed as no mass, and repaired; the re-ask then said
    # "How much chicken?" about a field that was already answered. The
    # operation never reached readiness, never settled, and wrote nothing
    # across five turns.
    #
    # It survived because the only paths that ever settled a two-field
    # operation carried an EXPLICIT `field_id` — structured iOS taps — which
    # never consults this variable at all. Free text has no such addressing,
    # so it is exactly the modality that exposed it.
    #
    # FIRST-OPEN, not best-match. Trying each open field and taking whichever
    # parses would silently answer a field the user was not addressing; asking
    # in order and reading in the same order is the rule they can predict. An
    # explicit `field_id` still overrides — see `_read`.
    _open = ops.open_fields(interaction, owned.answered or {})
    live_field = _open[0] if _open else interaction.groups[0].fields[0]

    # ALREADY SETTLED. A tap on a chip still on screen after the meal landed
    # is a real delivery; `settle` replays the stored result rather than
    # writing a second meal (the revision would differ, so the coordinator's
    # claim cannot catch it).
    #
    # ⚠ BUT ONLY AN UNAMBIGUOUS ANSWER MAY CLAIM A SETTLED OPERATION.
    #
    # MEASURED IN PRODUCTION 2026-08-05: for 30 minutes after a commit this
    # branch read FREE TEXT as an answer, so "I had some rice" and "Had some
    # oatmeal" — two NEW meals — were both swallowed as replays of the
    # finished rice operation. The user was told "Logged White rice" twice and
    # the oatmeal was never written. That is the phantom-log failure this
    # whole migration exists to delete, reintroduced by my own ownership
    # window.
    #
    # The distinction the window needs and did not have: after settlement,
    # only an answer that can ONLY be an answer counts — a structured
    # `option_id`, or the exact text of an option we offered. Free prose is a
    # new report, and "some oatmeal" parses as a quantity precisely because
    # the quantity parser is good at its job.
    #
    # Returning None here is not the mid-flight fallback C10 forbids: the
    # operation is TERMINAL, so there is nothing in flight to strand.
    # TWO STATES, ONE RULE. An operation stops being entitled to messages that
    # were never addressed to it once it is either SETTLED or EXPIRED, and the
    # discriminator is the same for both: a structured option id, or the exact
    # text of an option we offered. Anything else is a new report.
    #
    # Both states produced the same production failure — the next meal parsed
    # as an answer, the wrong food committed, "Logged" said out loud — so they
    # are deliberately handled by one condition rather than two that can drift.
    # A late answer still lands: replying after expiry is still replying.
    if not owned.awaiting or owned.expired:
        if not option_id and _label_selection(live_field, message) is None:
            # STRICTLY k=v. The prose that used to close this line ("— operation
            # left alone; this message is a new report") is the explanation
            # above, not data: every other line in this stream parses as
            # key=value pairs, and one that trails a sentence makes the whole
            # stream need a special case. What it said is what the comment block
            # above already says, permanently and to the right audience.
            logger.info(
                "event=b1_not_a_replay operation=%s user=%s state=%s "
                "disposition=left_alone",
                owned.operation_id, getattr(user, "id", None),
                "settled" if not owned.awaiting else "expired")
            return None
        answer = _read(owned, interaction, live_field, message=message,
                       field_id=field_id, option_id=option_id,
                       revision=revision,
                       context=_evidence_context(owned, user),
                       **_shown_kwargs(await _candidates_shown(db, owned,
                                                               user)))
        if answer.outcome is not Outcome.APPLIED:
            return _turn(answer, owned, live_field)

        # TWO STATES ARRIVE HERE AND THEY NEED DIFFERENT THINGS. The condition
        # above is deliberately one condition — "no longer entitled to claim a
        # message that was not addressed to it" is the same rule for settled
        # and expired — but what happens NEXT is not the same at all.
        if not owned.awaiting:
            # SETTLED: a replay. `settle` short-circuits on a committed
            # operation and hands back the original result without pricing
            # anything, so the stored state is what goes in — no re-derived
            # answer may reach the write path.
            result = await ops.settle(
                db, user=user, owned=owned,
                resolved=ops.resolved_fields(owned.answered),
                source_turn_id=source_turn_id,
                cohort=str(getattr(owned, "cohort", "") or ""))
            # A REPLAY IS A TURN AND HAS TO LEAVE A LINE. This branch never
            # reaches the commit coordinator — that is what makes it a replay —
            # so nothing recorded a stage, and `finish()` correctly emits
            # nothing for a record with no stages. The result was that a
            # replayed tap was INVISIBLE in the trace stream, which is the same
            # blackout the answer route already had once.
            #
            # SKIPPED with the counts left at zero: this turn wrote nothing.
            # The rows in `result` belong to the delivery that did, and
            # counting them here would multiply every commit by the number of
            # times a flaky network redelivered it.
            try:
                from core import food_trace as _rp_ft
                _rp_ft.record(_rp_ft.Stage.EXECUTE,
                              outcome=_rp_ft.Outcome.SKIPPED,
                              detail="replay")
            except Exception:
                pass
            return AnswerTurn(Outcome.REPLAY, operation_id=owned.operation_id,
                              field_id=live_field.field_id, patch=answer.patch,
                              result=result, reason="replay")

        # EXPIRED BUT STILL AWAITING: this is a FIRST answer arriving late, not
        # a replay of anything — replying after expiry is still replying. It
        # therefore takes the ordinary path: hold the answer, and settle only
        # when every field is answered. Settling it directly (as this branch
        # did while B-1 had one field) would commit a two-field meal on one
        # late tap, which is the exact defect readiness exists to prevent —
        # reachable only through the expiry door.
        held = await ops.hold_answer(db, owned=owned, patch=answer.patch)
        if not ops.ready_to_settle(interaction, held):
            _measure_partial(owned, answer, user=user, field=live_field,
                             held=held, option_id=option_id)
            still_open = ops.open_fields(interaction, held)
            return AnswerTurn(
                Outcome.PARTIAL, operation_id=owned.operation_id,
                field_id=answer.patch.field_id, patch=answer.patch,
                reason="awaiting the fields still open",
                subject_name=str(interaction.groups[0].label or ""),
                open_attributes=tuple(
                    getattr(f.attribute, "value", str(f.attribute))
                    for f in still_open),
                remaining=ops.wire_payload_for(
                    interaction, locale=owned.locale,
                    only={f.field_id for f in still_open}))
        # ⭐ A FOOD WE CANNOT PRICE IS NOT COMMITTED, and this is the only
        # place that decides so.
        #
        # `PricingRefused` is raised inside `settle` BEFORE any write, so a
        # refusal is non-mutating by construction: no food row, no ledger
        # event, and — because this returns REFUSED rather than APPLIED — no
        # operation that claims to have logged something.
        #
        # Caught NARROWLY, by type. A bare `except Exception` here would be
        # the defect being deleted: production entry 2932 committed 80 g of
        # mackerel at 0.0 kcal / 0 g protein precisely because a pricing
        # failure was allowed to become a number instead of an outcome.
        from core.canonical_pricing import PricingRefused

        try:
            result = await ops.settle(db, user=user, owned=owned,
                                      resolved=ops.resolved_fields(held),
                                      source_turn_id=source_turn_id,
                                      cohort=str(getattr(owned, "cohort", "")
                                                 or ""))
        except PricingRefused as exc:
            logger.warning(
                "event=b1_pricing_refused operation=%s field=%s reason=%s",
                owned.operation_id, live_field.field_id, exc)
            return AnswerTurn(
                Outcome.REFUSED, operation_id=owned.operation_id,
                field_id=live_field.field_id, patch=answer.patch,
                reason="unpriceable")
        return AnswerTurn(Outcome.APPLIED, operation_id=owned.operation_id,
                          field_id=live_field.field_id, patch=answer.patch,
                          result=result, reason=answer.reason)

    answer = _read(owned, interaction, live_field, message=message,
                   field_id=field_id, option_id=option_id,
                   revision=revision,
                   context=_evidence_context(owned, user),
                   **_shown_kwargs(await _candidates_shown(db, owned, user)))

    _measure(owned, answer, option_id=option_id, user=user,
             field=live_field, message=message)
    await _observe(db, owned, answer, user=user, source_turn_id=source_turn_id,
                   field=live_field, option_id=option_id, message=message,
                   selected_source=_selected_source(
                       live_field, option_id=option_id, message=message))

    if answer.outcome is Outcome.CANCELLED:
        await ops.cancel(db, owned=owned, user=user, reason=answer.reason)
        return _turn(answer, owned, live_field)

    if answer.outcome is not Outcome.APPLIED:
        # REPAIR and REFUSED change no persisted semantic state, so the
        # revision does NOT move. Bumping it would invalidate the very chips
        # still on the user's screen — a stale-tap storm would walk the
        # operation forward and lock the user out of answering at all.
        return _turn(answer, owned, live_field)

    # THE QUESTION IS ANSWERED WHEN EVERY FIELD IS (B-1.5).
    #
    # While B-1 asked about one field, "an answer applied" and "the question is
    # answered" were the same sentence, and settling here was correct. They
    # come apart the moment one item carries two independent material fields:
    # settling on the first applied answer commits the meal with the other
    # chips still on screen, and the tap that follows finds a settled operation
    # and is discarded as a replay. The user answered; nothing recorded it.
    #
    # Held DURABLY rather than in this turn's memory — the next tap may arrive
    # from a relaunched app or another worker.
    held = await ops.hold_answer(db, owned=owned, patch=answer.patch)
    if not ops.ready_to_settle(interaction, held):
        _measure_partial(owned, answer, user=user, field=live_field,
                         held=held, option_id=option_id)
        still_open = ops.open_fields(interaction, held)
        return AnswerTurn(
            Outcome.PARTIAL, operation_id=owned.operation_id,
            field_id=answer.patch.field_id, patch=answer.patch,
            reason="awaiting the fields still open",
            subject_name=str(interaction.groups[0].label or ""),
            open_attributes=tuple(
                getattr(f.attribute, "value", str(f.attribute))
                for f in still_open),
            remaining=ops.wire_payload_for(
                interaction, locale=owned.locale,
                only={f.field_id for f in still_open}))

    # THE WHOLE RESOLVED STATE, not a patch the coordinator picked out of it.
    # Which field prices the food is a domain question, and answering it here
    # is what would turn B-2 into a pile of field-specific extractors.
    result = await ops.settle(db, user=user, owned=owned,
                              resolved=ops.resolved_fields(held),
                              source_turn_id=source_turn_id,
                              cohort=str(getattr(owned, "cohort", "") or ""))
    turn = AnswerTurn(Outcome.APPLIED, operation_id=owned.operation_id,
                      field_id=live_field.field_id, patch=answer.patch,
                      result=result, reason=answer.reason)
    await _measure_commit(db, owned, turn, user=user, field=live_field,
                          option_id=option_id, message=message)
    await _stamp_entry(db, owned, turn, source_turn_id=source_turn_id)
    return turn


def _evidence_context(owned, user):
    """WHO is answering, about WHAT — assembled once, from the operation.

    The entity comes from the stored interpreter item rather than from this
    message: the operation already decided what food is under discussion, and
    re-deriving it from a two-word reply is the same re-interpretation the
    answer turn exists to avoid.
    """
    from core.semantics import EvidenceContext

    item = getattr(owned, "item", None) or {}
    return EvidenceContext(
        user_id=getattr(user, "id", None),
        canonical_entity_id=str(item.get("entity_id") or ""),
        product_variant_id=(str(item.get("product_variant_id"))
                            if item.get("product_variant_id") else None))


def _shown_kwargs(pair):
    candidates, disposition = pair
    return {"candidates": candidates, "universe": disposition}


async def _candidates_shown(db, owned, user):
    """The typed candidates behind the options this person actually read.

    THE WIRE FORM CARRIES ONLY IDS, deliberately — a client receives
    identifiers and labels, never semantics it could reinterpret — so the
    interaction reconstructed from the stored payload has no candidates on
    its options. They are resolved HERE, from the persisted universe, by the
    `decision_id` the operation recorded.

    Returning nothing is safe and means "no candidate-backed option": an
    estimate then refuses rather than assuming, which is the correct reading
    of not knowing what justified an option.
    """
    from core.clarification_answer import UniverseDisposition

    if not owned.decision_id:
        # An operation opened before the universe existed. NOT an outage.
        return {}, UniverseDisposition.NOT_APPLICABLE
    try:
        from core import candidate_repository as universe_repo

        record = await universe_repo.load_for_replay(
            db, decision_id=owned.decision_id,
            user_id=getattr(user, "id", None))
    except Exception:
        logger.warning("event=b1_universe_unreadable operation=%s",
                       owned.operation_id, exc_info=True)
        return {}, UniverseDisposition.UNAVAILABLE
    if record is None:
        return {}, UniverseDisposition.UNAVAILABLE
    return ({shown.option_id:
             record.candidate_set.candidate(shown.candidate_id)
             for shown in record.presented},
            UniverseDisposition.LOADED)


def _read(owned, interaction, live_field, *, message: str, field_id: str,
          option_id: str, revision: Optional[int], context=None,
          candidates=None, universe=None):
    """The answer, from whichever modality carried it.

    Order is specificity, not preference: an option id is unambiguous, an
    exact offered label is nearly so, and free text is the general case.
    """
    if option_id:
        return answer_from_chip(
            interaction, field_id=field_id or live_field.field_id,
            option_id=option_id,
            revision=revision if revision is not None else interaction.revision)

    selected = _label_selection(live_field, message)
    if selected is not None:
        return selected

    return answer_from_text(
        interaction, field_id=field_id or live_field.field_id,
        text=message,
        revision=revision if revision is not None else interaction.revision,
        food_name=str(interaction.groups[0].label or ""),
        context=context, candidates=candidates, universe=universe,
        # THE OPERATION'S LOCALE, never re-detected from this message. The
        # question was asked in one language; a two-word reply is exactly
        # where detection is least reliable, and a destructive command sits
        # behind that decision.
        locale=owned.locale)


def _label_selection(field, message: str):
    """An exact offered label, answered as the SELECTION it is.

    Telegram and iMessage have no structured tap — the user presses a chip and
    the platform sends its text. Re-parsing "6 oz" through the quantity parser
    would land on the same number by luck and record the WRONG provenance:
    they chose from what we offered, they did not state a figure. The meaning
    comes from the stored patch either way, which is the whole contract.
    """
    from core.clarification_answer import AnswerResult

    option = _option_for_label(field, message)
    if option is None:
        return None
    from core.clarification_answer import AnswerModality
    return AnswerResult(Outcome.APPLIED, patch=option.patch,
                        modality=AnswerModality.LABEL_SELECTION,
                        reason="label_selection")


def _option_for_label(field, message: str):
    """The offered option whose text the user typed back, or None.

    Split out of `_label_selection` so the matching RULE has one owner and two
    readers: the answer path needs the patch, and the funnel needs the option's
    `source`. Re-implementing the match in the metric would be a second owner
    of "did they pick one of ours?" — and the two would drift, quietly, in the
    direction that makes the numbers look better.
    """
    said = (message or "").strip().casefold()
    if not said:
        return None
    for option in getattr(field, "options", ()) or ():
        if option.patch is None:
            continue
        if said in {(option.label or "").strip().casefold(),
                    str(option.send_value or "").strip().casefold()}:
            return option
    return None


def _turn(answer, owned, field) -> AnswerTurn:
    # THE FIELD THIS OUTCOME IS ABOUT, carried so the copy can name it.
    # Without it a REPAIR reached the renderer with nothing to say, and the
    # renderer's only phrasing was "How much …?" — so an unreadable
    # PREPARATION answer asked about quantity.
    return AnswerTurn(answer.outcome, operation_id=owned.operation_id,
                      field_id=field.field_id, reason=answer.reason,
                      subject_name=_subject_of(owned),
                      open_attributes=(
                          getattr(field.attribute, "value",
                                  str(field.attribute)),),
                      repair_reason=str(
                          getattr(getattr(answer, "repair_reason", None),
                                  "value", "") or ""),
                      refusal_reason=str(
                          getattr(getattr(answer, "refusal_reason", None),
                                  "value", "") or ""))


def _subject_of(owned) -> str:
    """The food this operation is holding, off the stored interpreter item."""
    item = getattr(owned, "item", None) or {}
    return str(item.get("food") or item.get("name") or "").strip()


def _selected_source(field, *, option_id: str, message: str) -> str:
    """WHERE the value the user chose came from — the funnel's join key.

    Resolved from the FIELD rather than carried on `AnswerResult`, so the
    validated outcome/patch contract stays untouched and a measurement need
    never widen a type the commit path depends on.

    `free_text` is a first-class answer here, not a missing value. A typed
    quantity we did not offer is the signal that the option list failed this
    user, and lumping it in with "unknown" would hide exactly the number D4
    exists to read.
    """
    if not field:
        return ""
    options = list(getattr(field, "options", ()) or ())
    if option_id:
        for o in options:
            if o.option_id == option_id:
                return getattr(getattr(o, "source", None), "value", "") or "none"
        return "unknown_option"
    chosen = _option_for_label(field, message)
    if chosen is not None:
        return getattr(getattr(chosen, "source", None), "value", "") or "none"
    return "free_text"


async def _observe(db, owned, answer, *, user, source_turn_id: str,
                   field, option_id: str, message: str,
                   selected_source: str) -> None:
    """The durable half of the measurement (D4.1).

    A SAVEPOINT, and never anything else. A telemetry write that can poison the
    caller's transaction would trade a lost datapoint for a lost meal, which is
    exactly backwards — and this runs inside the answer turn's transaction, so
    a constraint violation here without one would abort the commit beside it.
    """
    from sqlalchemy import func, select

    from db.models import B1AnswerObservation

    try:
        prior = (await db.execute(
            select(func.count()).select_from(B1AnswerObservation)
            .where(B1AnswerObservation.operation_id == owned.operation_id)
        )).scalar() or 0
        async with db.begin_nested():
            db.add(B1AnswerObservation(
                operation_id=owned.operation_id,
                user_id=getattr(user, "id", None),
                source_turn_id=source_turn_id or "",
                attribute=getattr(getattr(field, "attribute", None), "value",
                                  "quantity"),
                outcome=answer.outcome.value,
                # COPIED. `_modality` derived this from `reason`, and that
                # dependency broke twice — a reworded message reclassified a
                # refusal as free-text usage, and the same trick lost policy
                # attribution. The route knows what it is; nothing here reads
                # prose.
                modality=_modality_of(answer),
                # TYPED, AND COPIED FROM THE ANSWER. Never parsed out of
                # `reason` — that dependency has broken twice in this slice,
                # once for modality and once for policy attribution.
                repair_reason=str(getattr(
                    getattr(answer, "repair_reason", None), "value", "")
                    or ""),
                refusal_reason=str(getattr(
                    getattr(answer, "refusal_reason", None), "value", "")
                    or ""),
                selected_source=selected_source,
                offered=_offered_mix(field),
                round_index=int(prior) + 1,
                # BOTH STAMPS. The revision is the semantic state answered
                # against; the version is the wording and option selection the
                # user actually read. A repair does not move the revision by
                # design, so it alone can never tell a wording change from a
                # semantic one — and the moment the wording changes without
                # this, every observation already collected loses the ability
                # to say which question it answered.
                interaction_revision=getattr(
                    getattr(owned, "interaction", None), "revision", None),
                question_version=ops.QUESTION_VERSION,
                # COPIED, NEVER RECONSTRUCTED. The decision names its own
                # policy on the result; reading it back out of `reason` made
                # persisted attribution depend on diagnostic wording, which is
                # exactly how a reworded message once reclassified a refusal
                # as free-text usage.
                policy_version=(getattr(answer, "decision_policy_version",
                                        None) or ""),
                latency_ms=_latency_ms(owned),
                cohort=str(getattr(owned, "cohort", "") or "")))
    except Exception:
        logger.debug("b1 observation write failed", exc_info=True)


async def _stamp_entry(db, owned, turn, *, source_turn_id: str) -> None:
    """Close the funnel: put the committed row on the answer that produced it.

    Corrections are keyed on `entry_id`, so without this the ten-minute
    correction rate can be computed per USER and never per SOURCE — and "does
    history reduce corrections relative to ontology" is the question the whole
    window exists to answer.
    """
    from sqlalchemy import update

    from db.models import B1AnswerObservation

    try:
        entry_id = facts_for(turn).entry_id
        if not entry_id:
            return
        async with db.begin_nested():
            await db.execute(
                update(B1AnswerObservation)
                .where(B1AnswerObservation.operation_id == owned.operation_id,
                       B1AnswerObservation.source_turn_id == (source_turn_id or ""))
                .values(entry_id=entry_id))
    except Exception:
        logger.debug("b1 observation entry stamp failed", exc_info=True)


def _offered_mix(field) -> str:
    """`ontology:2,user_history:1` — acceptance needs a denominator."""
    from collections import Counter
    if not field:
        return ""
    counts = Counter(
        (getattr(getattr(o, "source", None), "value", None) or "none")
        for o in (getattr(field, "options", ()) or ()))
    return ",".join(f"{s}:{n}" for s, n in sorted(counts.items()))


def _latency_ms(owned):
    from core.clock import now as _now
    asked = getattr(owned, "asked_at", None)
    if asked is None:
        return None
    try:
        return int((_now() - asked).total_seconds() * 1000)
    except Exception:
        return None


def _modality_of(answer) -> str:
    """The route's own account of itself, or a LOUD unknown.

    FAILS CLOSED, deliberately. A missing modality used to default into the
    free-text bucket, which is the metric that decides whether the option
    pipeline is working — so a route that forgot to say what it was would have
    argued, quietly and forever, that users reject our options. `unknown` is
    visible as itself and shouts on the way past.
    """
    from core.clarification_answer import AnswerModality

    m = getattr(answer, "modality", None)
    if m is None:
        logger.error(
            "event=b1_modality_missing outcome=%s reason=%r — an answer route "
            "did not declare how it arrived; recording UNKNOWN rather than "
            "defaulting into the free-text rate",
            getattr(getattr(answer, "outcome", None), "value", "?"),
            (getattr(answer, "reason", "") or "")[:80])
        return AnswerModality.UNKNOWN.value
    return m.value if hasattr(m, "value") else str(m)


def _measure(owned, answer, *, option_id: str, user,
             field=None, message: str = "") -> None:
    """One emit per answer, wherever it lands. Measurement may never cost the
    turn, so every failure here is swallowed — a missing datapoint is a worse
    outcome than a lost meal only to a dashboard."""
    from core import b1_metrics

    try:
        quantity = getattr(answer.patch, "quantity", None)
        b1_metrics.answered(
            operation_id=owned.operation_id, user_id=getattr(user, "id", None),
            outcome=answer.outcome.value,
            modality=b1_metrics.modality_of(option_id=option_id,
                                            reason=answer.reason),
            selected_source=_selected_source(
                field, option_id=option_id, message=message or ""),
            asked_at=owned.asked_at, reason=answer.reason,
            # READ BACK FROM THE OPERATION, which is the only thing that spans
            # the two turns. Without it this event printed `cohort=-` while the
            # ask it answers printed `cohort=allowlist`, and the funnel broke at
            # the conversion step.
            cohort=str(getattr(owned, "cohort", "") or ""),
            provenance=getattr(getattr(answer.patch, "provenance", None),
                               "value", ""),
            grams=getattr(quantity, "grams", None))
    except Exception:
        logger.debug("b1 answer metric failed", exc_info=True)


def _measure_partial(owned, answer, *, user, field=None, held: dict,
                     option_id: str = "") -> None:
    """A field answered, the question still open (B-1.5).

    MEASURED SEPARATELY FROM A COMMIT, because the number that matters here is
    the one a funnel cannot infer: how many multi-field questions are ABANDONED
    half-answered. Folding these into `answered` would make the completion rate
    read as though every tap finished a meal.
    """
    from core import b1_metrics

    try:
        b1_metrics.partial(
            operation_id=owned.operation_id, user_id=getattr(user, "id", None),
            field_id=str(getattr(answer.patch, "field_id", "")),
            answered_count=len(held),
            open_count=len(ops.open_fields(owned.interaction, held)),
            modality=str(getattr(getattr(answer, "modality", None), "value",
                                 "") or ("option_id" if option_id else "")))
    except Exception:
        logger.debug("b1 partial metric failed", exc_info=True)


async def _measure_commit(db, owned, turn: AnswerTurn, *, user, field=None,
                          option_id: str = "", message: str = "") -> None:
    """The terminal funnel record.

    `selected_source` is repeated here rather than left to a join with
    `b1_answered`, because a correction arriving ten minutes later is keyed on
    `entry_id` — and attributing that correction to the source that produced
    the number is the comparison D4 exists to make. One event carries
    entry_id AND source, so the attribution needs no third hop.

    `repairs` AND `rounds` ARE COUNTED, NOT INFERRED. `repairs` used to read
    `owned.revision` — a field this module documents, forty lines up, as
    deliberately NOT moving on a repair. The revision goes 0→1 exactly once per
    committed operation, so the metric reported `repairs=1` on every clean
    single-tap answer and 0 on everything uncommitted: a restatement of "did
    this commit", wearing the name of the rate B-1.8 is judged by. `rounds` was
    worse — never passed at all, so it reported the signature default of 1
    forever while `round_index` sat durably in the observation rows.

    Both come from `B1AnswerObservation`, which `_observe` has already written
    for this answer by the time we get here. That table is the only thing that
    survives the turn, which is what makes it the honest source.
    """
    from core import b1_metrics

    try:
        facts = facts_for(turn)
        rounds, repairs = await _answer_counts(db, owned.operation_id)
        b1_metrics.committed(
            operation_id=owned.operation_id, user_id=getattr(user, "id", None),
            entry_id=facts.entry_id, calories=facts.calories,
            selected_source=_selected_source(
                field, option_id=option_id, message=message or ""),
            repairs=repairs, rounds=rounds,
            cohort=str(getattr(owned, "cohort", "") or ""),
            asked_at=owned.asked_at)
    except Exception:
        logger.debug("b1 commit metric failed", exc_info=True)


async def _answer_counts(db, operation_id: str) -> tuple:
    """`(rounds, repairs)` for one operation, from the durable observations.

    Returns `(1, 0)` if the count cannot be taken. A commit metric must not be
    lost to a failed aggregate, and "one round, no repairs" is the shape of the
    overwhelming majority of answers — an honest default rather than a guess
    that inflates either number.

    `rounds` IS `max(round_index)`, NOT A ROW COUNT — and the distinction is the
    same one that produced the defect this function replaced. Counting rows is
    only equal to counting rounds while one observation row is exactly one
    round, which is true today and is not a property anything enforces. B-1.8
    adds repair, refusal, replay and cancel observations; the moment any of
    them writes a row without advancing a round, a row count silently becomes
    something other than "how many times did we ask". `round_index` is the
    durable field that means a round, so it is the one read here. Swapping one
    proxy for another would be the original mistake with a better proxy.

    `repairs` stays a count, because there a row genuinely IS the event: one
    observation whose outcome is `repair` is one repair.
    """
    from sqlalchemy import case, func, select

    from db.models import B1AnswerObservation

    try:
        rounds, repairs = (await db.execute(
            select(
                func.max(B1AnswerObservation.round_index),
                # `case`, not `count(...).filter(...)`: the FILTER clause needs
                # SQLite 3.30+, and this aggregate must not depend on the
                # engine when the suite runs on one and production on another.
                func.sum(case(
                    (B1AnswerObservation.outcome == "repair", 1), else_=0)),
            ).where(B1AnswerObservation.operation_id == operation_id))).one()
        return (max(1, int(rounds or 0)), max(0, int(repairs or 0)))
    except Exception:
        logger.debug("b1 answer counts failed", exc_info=True)
        return (1, 0)


@dataclass(frozen=True)
class CanonicalResponseFacts:
    """The committed truth, extracted ONCE and passed to every renderer.

    Renderers receive THIS, never the `AnswerTurn` or the `MealCommitResult`.
    A renderer holding the raw commit can recompute, and a renderer that can
    recompute is a second owner of the number — which is how three owners of
    the day total produced 789 and 788. Passing the same VALUE to copy, card
    and (later) voice makes their agreement structural: there is no second
    extraction that could drift from the first.
    """
    outcome: str
    internal_failure: bool
    operation_id: str
    field_id: str
    name: str
    entry_id: Any
    calories: Optional[float]
    protein: Optional[float]
    day_calories: Optional[float]

    #: WE chose the portion and the user did not — drives "(my estimate)".
    estimated: bool
    #: The FIGURE is ours even if they picked it — drives the row's flag.
    system_supplied_figure: bool
    assumptions: tuple = ()
    #: THE MACROS THE CARD REQUIRES. Absent from the first canonical card, and
    #: the client could not decode it: `MacroCardPayload` makes `quantity`,
    #: `carbsG` and `fatsG` non-optional, so a payload missing them fails
    #: `try? decode` and lands in `.unknown` — the meal logged, and no card
    #: appeared. The legacy `log_food` card has always sent all three.
    quantity: str = ""
    carbs: Optional[float] = None
    fats: Optional[float] = None
    #: WHY, typed, for a client to branch on. Exactly one is non-empty, and
    #: only on the outcome it belongs to — a field stamped on every result
    #: would mean "something happened" rather than "this is why".
    repair_reason: str = ""
    refusal_reason: str = ""
    #: The fields still open on a PARTIAL turn (B-1.5), as attribute names.
    open_attributes: tuple = ()
    #: The same fields in the client's wire shape, for the response envelope.
    remaining: Optional[dict] = None

    @property
    def committed(self) -> bool:
        return self.entry_id is not None or self.calories is not None


def facts_for(turn: AnswerTurn) -> CanonicalResponseFacts:
    """THE CANONICAL RESPONSE FACTS. Read off the committed result, nothing
    derived.

    Voice comes later and renders THESE — it does not get the result object,
    because a renderer holding the raw commit is a renderer that can recompute,
    and a renderer that can recompute is a second owner of the number. This is
    the seam that makes "voice may never override a committed fact" a property
    of the wiring rather than a rule someone remembers.
    """
    result = turn.result
    items = list(getattr(result, "committed_items", ()) or ())
    first = items[0] if items and isinstance(items[0], dict) else {}
    totals = getattr(result, "meal_totals", None) or {}
    quantity = getattr(turn.patch, "quantity", None)
    return CanonicalResponseFacts(
        outcome=turn.outcome.value,
        internal_failure=turn.internal_failure,
        operation_id=turn.operation_id,
        field_id=turn.field_id,
        # THE COMMITTED ROW NAMES ITSELF; a repair has no row, so it falls
        # back to the subject the operation is holding.
        name=(str(first.get("name") or "").strip()
              or str(getattr(turn, "subject_name", "") or "").strip()),
        entry_id=first.get("entry_id"),
        calories=totals.get("calories"),
        protein=totals.get("protein"),
        day_calories=(getattr(result, "day_totals", None) or {}).get(
            "calories"),
        quantity=str(first.get("quantity") or ""),
        carbs=totals.get("carbs"),
        fats=totals.get("fats"),
        repair_reason=str(getattr(turn, "repair_reason", "") or ""),
        refusal_reason=str(getattr(turn, "refusal_reason", "") or ""),
        open_attributes=tuple(getattr(turn, "open_attributes", ()) or ()),
        remaining=getattr(turn, "remaining", None),
        # THREE PROVENANCES, TWO QUESTIONS, AND THEY ARE NOT THE SAME QUESTION.
        #
        #   USER_STATED    they typed a figure       own=True   assumed=False
        #   USER_SELECTED  they picked one we made   own=False  assumed=False
        #   MODE_DEFAULT   we picked, they did not   own=False  assumed=True
        #
        # `is_estimated` (= not is_users_own) answers the ROW's question: did
        # WE produce this number? It is True for a tapped chip, correctly —
        # that is the 2026-08-04 fix, where a tap cleared the estimated flag
        # and took the disclosure with it.
        #
        # `is_assumption` answers the COPY's question: did the user choose at
        # all? Saying "(my estimate)" to someone who just tapped "6 oz" is
        # wrong in the other direction — it tells them we guessed when they
        # decided. Collapsing the two is how one of these disclosures always
        # ends up lying.
        estimated=bool(getattr(
            getattr(quantity, "provenance", None), "is_assumption", False)),
        system_supplied_figure=bool(
            getattr(quantity, "is_estimated", False)),
        assumptions=tuple(getattr(result, "assumptions", ()) or ()))


async def facts_from_committed_row(db, *, entry_id, operation_id: str = "",
                                   field_id: str = ""
                                   ) -> Optional[CanonicalResponseFacts]:
    """Rebuild the answer's facts FROM THE ROW IT WROTE.

    For a redelivery of a request that already succeeded. The claim stores a
    durable identifier rather than a response body, so the authoritative
    result is recovered from the thing that IS authoritative — the committed
    row — and re-rendered through the same `copy_for`/`card_for` the original
    reply used.

    NOT A RECOMPUTATION OF SEMANTICS. Nothing here decides anything: no
    quantity is parsed, no candidate is selected, no pricing runs. It reads
    what was written and says it again. A replay that answered with an empty
    envelope and an id would force the client to reconstruct the confirmation
    itself, which is the client-side inference the frozen boundary exists to
    prevent.
    """
    from sqlalchemy import select

    from db.models import DailyLog, FoodEntry

    if not entry_id:
        return None
    entry = await db.get(FoodEntry, int(entry_id))
    if entry is None:
        return None
    day_calories = None
    if entry.daily_log_id:
        rows = (await db.execute(
            select(FoodEntry.calories).where(
                FoodEntry.daily_log_id == entry.daily_log_id))).scalars().all()
        day_calories = sum(float(c or 0) for c in rows)
    return CanonicalResponseFacts(
        outcome="applied", internal_failure=False,
        operation_id=operation_id, field_id=field_id,
        name=str(entry.parsed_food_name or ""), entry_id=entry.id,
        calories=float(entry.calories or 0),
        protein=float(entry.protein or 0), day_calories=day_calories,
        quantity=str(entry.quantity or ""),
        carbs=float(entry.carbs or 0), fats=float(entry.fats or 0),
        # THE ROW REMEMBERS WHETHER WE GUESSED. Re-deriving it from the answer
        # would need the answer, which is the thing we no longer have.
        estimated=bool(getattr(entry, "estimated_flag", False)),
        system_supplied_figure=bool(getattr(entry, "estimated_flag", False)))


def card_for(facts: CanonicalResponseFacts) -> Optional[dict]:
    """The macro card, built from the SAME facts as the sentence beside it.

    THIS IS WHY IT IS NOT BUILT FROM THE TOOL CALL. The legacy card reads the
    executed call and the prose reads the planner, so the two could disagree —
    and did: three owners of the day total produced 789 and 788, and a card
    once read "Meal removed" on turns where nothing was deleted. Here the
    card and the copy are two renderings of one `facts_for()` result, so
    "card and totals agree" is not a check that can fail, it is a shape that
    cannot express the disagreement.

    Returns None for every non-commit outcome, deliberately: a card that
    survives a repair or a cancel is a stale card on a reply that logged
    nothing, which is exactly the leak `_logged_entry_card`'s `entry_id` gate
    exists to stop.
    """
    if facts.outcome != "applied" or facts.internal_failure:
        return None
    if facts.entry_id is None:
        return None
    payload = {
        "name": facts.name,
        # EVERY FIELD THE CLIENT MAKES NON-OPTIONAL. `quantity`, `carbs_g` and
        # `fats_g` were missing, so `MacroCardPayload` failed to decode and the
        # card silently became `.unknown` — the meal was logged and nothing
        # appeared. Matches what `log_food` has always sent, because a card is
        # a card whichever lane wrote the row.
        "quantity": facts.quantity,
        "entry_id": facts.entry_id,
        "calories": int(round(facts.calories or 0)),
        "protein_g": int(round(facts.protein or 0)),
        "carbs_g": int(round(facts.carbs or 0)),
        "fats_g": int(round(facts.fats or 0)),
        "source": "manual",
        # THE ASSUMPTION, ON THE ROW. "Logged fast" and "logged fast and
        # quietly guessed" are different products, and this is the difference.
        "estimated": facts.estimated,
    }
    if facts.assumptions:
        payload["assumptions"] = list(facts.assumptions)
    return {"type": "macro_card", "payload": payload}


#: WHAT TO ASK FOR, per open attribute (B-1.5).
#:
#: A TABLE, NOT A FORMAT STRING. `f"What {attribute}?"` renders "What
#: consumed_fraction?" — a field name is an internal identifier and reaches
#: the user as one the moment anyone interpolates it. Anything not here falls
#: back to a phrase that is vague but never wrong.
_ASK_FOR = {
    "preparation": "How was it cooked?",
    "quantity": "How much was it?",
    "consumed_fraction": "How much of it did you have?",
    "product_variant": "Which one was it?",
    "package_size": "What size was it?",
    "serving_basis": "Is that per serving or for the whole thing?",
}


def copy_for(facts: CanonicalResponseFacts) -> str:
    """The DETERMINISTIC fallback sentence, rendered from `facts_for`.

    Not a model call, and not because voice is unwelcome — because B-1's job
    is to prove the spine, and a sentence that can drift from the row it
    describes is the defect the migration exists to remove ("logged, 970/98g"
    while nothing was written, 2026-08-03).

    THE ORDER IS LOAD-BEARING: commit → facts → copy → (later) voice. Voice
    lands after committed-truth verification and before broad rollout, and it
    phrases these same facts. It may never reinterpret, recompute or override
    one. When a voice pass fails it degrades to this sentence — never to
    silence, and never to an invented one.

    Every number below comes off `MealCommitResult`. Nothing here adds,
    scales, or rounds anything.
    """
    if facts.internal_failure:
        # HONEST, and not a question. Asking again would invite an answer we
        # still could not apply. Covers both our failures — a stored
        # interaction we cannot read, and an ownership lookup that did not
        # run — because from the user's side they are the same fact: nothing
        # was logged and it was not their doing.
        return ("Something went wrong on my end holding that question — "
                "nothing was logged. Send the food again and I'll redo it.")
    if facts.outcome == "cancelled":
        return "Dropped it, nothing logged."
    if facts.outcome == "refused":
        return ("That answer was for an older question. Tell me the amount "
                "again and I'll log it.")
    if facts.outcome == "partial":
        # NOTHING WAS LOGGED, AND THE COPY MUST SAY SO WITHOUT SAYING
        # "logged" (B-1.5). Falling through to the applied branch below would
        # render "Logged." on a turn that wrote no row — the phantom claim
        # this whole migration exists to delete, arriving through a new
        # outcome rather than through a detector gap.
        #
        # ACKNOWLEDGE, THEN ASK. The user just answered something; a bare
        # question reads as though their tap was ignored.
        remaining = _ASK_FOR.get(
            (facts.open_attributes or ("",))[0], "one more thing")
        got = f"Got it{f' for {facts.name.lower()}' if facts.name else ''}."
        return f"{got} {remaining}"
    if facts.outcome == "repair":
        # NAME THE FOOD. "How much was it?" after someone reported a DIFFERENT
        # meal reads as a question about the meal they just named — so they
        # answer about that one, and the amount lands on the food still open.
        # Measured: "I had some salmon too" while chicken was awaiting drew
        # "How much was it?", and an answer to that would have priced chicken.
        # The pronoun was doing work no pronoun can do.
        #
        # ⭐ AND NAME THE FIELD. Both phrasings below were hardcoded to
        # quantity, so a repair on ANY other field asked the wrong question —
        # measured 2026-08-10, an unreadable preparation answer drew "How much
        # chicken?" about a quantity that was already answered. The attribute
        # comes off the field the answer was read against, and `_ASK_FOR` is
        # the same table the PARTIAL branch uses, so the two cannot drift.
        attribute = (facts.open_attributes or ("quantity",))[0]
        if attribute != "quantity":
            question = _ASK_FOR.get(attribute, "Which was it?")
            if facts.name:
                return (f"{question} (for the {facts.name.lower()}) — and "
                        f"anything else you mentioned isn't logged yet, so "
                        f"send that again after.")
            return question
        if facts.name:
            return (f"How much {facts.name.lower()}? A rough amount is fine "
                    f"— and anything else you mentioned isn't logged yet, so "
                    f"send that again after.")
        return "How much was it? A rough amount is fine."

    if not facts.committed:
        return "Logged."

    said = f"Logged {facts.name}" if facts.name else "Logged"
    if facts.calories is not None:
        said += f" — {facts.calories:.0f} cal"
        if facts.protein is not None:
            said += f", {facts.protein:.0f}g protein"
    if facts.estimated:
        # THE ASSUMPTION IS DISCLOSED, because the user did not supply it.
        said += " (my estimate)"
    return said + "."
