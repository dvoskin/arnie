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
    #: AN AUTHORITATIVE RESULT WAS RETURNED, AND NOTHING NEW WAS WRITTEN.
    #:
    #: A settled operation answering the same tap again is not a failure and
    #: not a new application — it is the original commit, handed back. Carried
    #: as `APPLIED` with `reason="replay"`, it was indistinguishable from a
    #: fresh mutation in every count that mattered: a client could not tell
    #: whether to animate a new row, and "successful applications" silently
    #: included repeats.
    REPLAY = "replay"
    #: The answer was understood as an explicit stop. The operation closes
    #: without a write; the user said so.
    CANCELLED = "cancelled"
    #: Not understood. Ask the SAME field again, narrower — never the whole
    #: meal again, and never through the interpreter.
    REPAIR = "repair"
    #: The answer names a field or revision this interaction does not have.
    #: Fails closed: a stale tap must not patch whatever looks closest.
    REFUSED = "refused"
    #: UNDERSTOOD, RECORDED, AND THE QUESTION IS STILL OPEN (B-1.5).
    #:
    #: One item can carry several independent material fields — amount and
    #: preparation — and a user may answer them one at a time. This is not
    #: `APPLIED`, which every counter and every client reads as "the meal
    #: landed", and it is not `REPAIR`, which says we failed to understand.
    #: The answer was perfect; there is simply another field open.
    #:
    #: NOTHING TERMINAL HAPPENS HERE. The operation stays `awaiting_answer` at
    #: the SAME revision, because the chips for the unanswered fields are
    #: still on the user's screen and bumping the revision would invalidate
    #: the very taps we are waiting for.
    PARTIAL = "partial"


class RepairReason(str, Enum):
    """WHY we are asking again. Closed, and only what the turn can justify.

    THE ANSWER TURN RUNS BEFORE THE INTERPRETER and sees the raw message and
    nothing else — that ordering is deliberate, and it is how "6 oz" stopped
    becoming a second meal. So it CANNOT know whether a message that failed to
    answer also reported another food: distinguishing "I had some salmon too"
    from "it was pretty good" requires the interpreter, and reaching for it
    here would reintroduce exactly the coupling C10 removes.

    `unrelated_report_while_awaiting` is therefore NOT a member. Stamping it
    would record knowledge the turn does not have, and a reason field that
    guesses is worth less than one that admits its limit. The user-facing copy
    covers the case without the claim: it names the food still open and states
    that anything else mentioned is not logged.
    """
    #: The message carried no amount we could apply. The common case, and the
    #: one an unrelated food report lands in.
    NO_AMOUNT_IN_ANSWER = "no_amount_in_answer"
    #: "Not sure", with nothing about this person that could support a guess.
    ESTIMATE_UNSUPPORTED = "estimate_unsupported"
    #: The durable candidate universe could not be read, so we do not know
    #: what was offered. DISTINCT FROM `ESTIMATE_UNSUPPORTED` on purpose: one
    #: is a fact about the evidence, the other is a fact about our storage,
    #: and reporting them together would let an outage read as a population of
    #: users whose history we lack.
    UNIVERSE_UNAVAILABLE = "universe_unavailable"


class UniverseDisposition(str, Enum):
    """WHETHER THE DURABLE CANDIDATE UNIVERSE COULD BE READ. Declared by the
    loader, never inferred from the shape of what came back.

    Reconstructing storage health from `not candidates` conflates three
    different states: a legitimately empty result, an operation that predates
    the universe, and a read that failed. A future legitimate empty would then
    be recorded as an outage, and a different loading failure as a fact about
    a user's history — which is exactly the pooling this reason exists to
    undo.
    """
    #: The record was read; `candidates` is what it holds.
    LOADED = "loaded"
    #: The read failed, or the record named by the operation is missing.
    UNAVAILABLE = "unavailable"
    #: No universe was expected — an operation opened before 3b, or a caller
    #: that does not resolve candidates at all.
    NOT_APPLICABLE = "not_applicable"


class RefusalReason(str, Enum):
    """WHY a structured answer was refused. Typed, because a client has to
    branch on it and prose is not a branch condition.

    Every member is OUR failure or a stale screen, never a user who was
    unclear — that distinction is why these are REFUSED rather than REPAIR.
    """
    #: The id names no option this interaction offered.
    UNKNOWN_OPTION = "unknown_option"
    #: The field belongs to another operation.
    FOREIGN_FIELD = "foreign_field"
    #: The screen has moved on since this answer was rendered.
    REVISION_MISMATCH = "revision_mismatch"
    #: The option exists and carries no patch — a producer defect.
    OPTION_WITHOUT_PATCH = "option_without_patch"


class AnswerModality(str, Enum):
    """HOW the answer reached us — stamped where it is known, never inferred.

    This was derived from the diagnostic `reason` string, and that dependency
    broke twice: once when an improved error message reclassified a refusal as
    free-text usage, and once when policy attribution was read out of the same
    prose. `reason` is written for a human reading a trace. Rewording it must
    never change what the system recorded about its own behaviour, and the
    only way to guarantee that is for the route to say what it is at the point
    where it alone knows.

    "Other usage" — the single number the observation window exists to read —
    is computed from this field. A wrong value here is not a mislabelled log
    line; it is a wrong answer to the question the whole slice is asking.
    """
    OPTION_ID = "option_id"            # a structured tap: ids, not words
    LABEL_SELECTION = "label_selection"  # they typed back exactly what we offered
    USER_TEXT = "user_text"            # a quantity of their own  <- "Other"
    COMMAND = "command"                # not sure / cancel / skip
    REPAIR = "repair"                  # we could not read it; ask again
    #: Never assigned by a route. Present so a MISSING modality is visible as
    #: itself rather than defaulting into one of the real ones — a silent
    #: default would land in USER_TEXT and inflate exactly the metric that
    #: decides whether the option pipeline is working.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AnswerResult:
    """An outcome and, when it applied, THE patch that applied.

    The pairing is validated rather than assumed. `patch` was `Any = None` and
    nothing checked it, so a REFUSED result carrying `patch=None` reached a
    caller that read `.patch` unconditionally and died on `NoneType.quantity`
    — the failure surfaced in a test, but nothing in the type stopped it from
    reaching production instead.
    """
    outcome: Outcome
    patch: Optional["SemanticPatchT"] = None
    reason: str = ""
    #: WHICH VERSIONED POLICY DECIDED THIS, when one did.
    #:
    #: A FIELD, never inferred from `reason`. Attribution was briefly derived
    #: with `reason.startswith("estimate")`, which is the same dependency that
    #: had already broken modality classification one layer over: an improved
    #: error message silently reclassified a refusal as free text. `reason` is
    #: prose for a human reading a trace; rewording it must never change what
    #: the system recorded about its own decision.
    #:
    #: None when no versioned policy governed the route — a stated quantity
    #: decides itself, and stamping every result would make the field mean
    #: "some policy ran" rather than "this policy decided".
    decision_policy_version: Optional[str] = None
    #: HOW the answer arrived. Set by the route that owns it; never derived.
    modality: Optional["AnswerModality"] = None
    #: WHY we are re-asking, typed. Only on REPAIR; None elsewhere, so the
    #: field means "this is why" rather than "something happened".
    repair_reason: Optional["RepairReason"] = None
    #: WHY a structured answer was refused, typed. Only on REFUSED.
    refusal_reason: Optional["RefusalReason"] = None

    def __post_init__(self):
        from core.semantics import SemanticPatch

        if self.outcome is Outcome.APPLIED:
            if not isinstance(self.patch, SemanticPatch):
                raise TypeError(
                    f"an APPLIED answer IS its patch, got "
                    f"{type(self.patch).__name__} — a caller reading .patch "
                    f"on this result has nothing to apply")
        elif self.patch is not None:
            raise TypeError(
                f"a {self.outcome.value} answer must carry no patch; this one "
                f"carries {type(self.patch).__name__}, which a caller could "
                f"apply while believing the answer was refused")

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.APPLIED


#: Only for the annotation above — `core.semantics` is imported lazily
#: everywhere in this module to keep the import graph acyclic.
SemanticPatchT = Any


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
            Outcome.REFUSED, modality=AnswerModality.OPTION_ID,
            refusal_reason=RefusalReason.REVISION_MISMATCH,
            reason=f"stale revision {revision} != {interaction.revision}")
    try:
        patch = interaction.patch_for(field_id, option_id)
    except KeyError as exc:
        # WHICH ID WAS WRONG. A client showing "that option is gone" and one
        # showing "that screen is stale" are different repairs for the user,
        # so the distinction is typed rather than left in prose.
        known = any(f.field_id == field_id
                    for g in interaction.groups for f in g.fields)
        return AnswerResult(
            Outcome.REFUSED, reason=str(exc),
            refusal_reason=(RefusalReason.UNKNOWN_OPTION if known
                            else RefusalReason.FOREIGN_FIELD),
            modality=AnswerModality.OPTION_ID)
    except ValueError as exc:          # an option with no patch
        return AnswerResult(Outcome.REFUSED, reason=str(exc),
                            refusal_reason=RefusalReason.OPTION_WITHOUT_PATCH,
                            modality=AnswerModality.OPTION_ID)
    return AnswerResult(Outcome.APPLIED, patch=patch,
                        modality=AnswerModality.OPTION_ID)


def answer_from_text(interaction, *, field_id: str, text: str,
                     revision: int, food_name: str = "",
                     locale: str = "en", context=None,
                     candidates=None,
                     universe=UniverseDisposition.NOT_APPLICABLE
                     ) -> AnswerResult:
    """A typed answer, through the NARROW parser only.

    The broad interpreter is not reachable from here, by construction. That is
    the whole point: sending "about six ounces" through the full food
    interpreter is how an answer became a new meal, and the parser that can
    read it correctly was sitting unwired behind a missing `response_schema`.

    A quantity the chips did not offer is a first-class answer — the typed
    path is not a fallback for people the options failed, it is the same
    answer expressed differently, and it produces the same patch type with
    `USER_STATED` provenance instead of `USER_SELECTED`.

    `revision` IS REQUIRED, symmetrically with the chip path. A typed answer
    can be as stale as a tapped one — the user types into a screen rendered
    two revisions ago — and a boundary that checks staleness on one path only
    is a boundary that does not check it.
    """
    from core.semantics import Provenance, SetQuantity

    if revision != interaction.revision:
        return AnswerResult(
            Outcome.REFUSED, modality=AnswerModality.USER_TEXT,
            reason=f"stale revision {revision} != {interaction.revision}")

    said = (text or "").strip()
    if not said:
        return AnswerResult(Outcome.REPAIR, reason="empty answer",
                            modality=AnswerModality.REPAIR,
                            repair_reason=RepairReason.NO_AMOUNT_IN_ANSWER)

    try:
        field = interaction.field(field_id)
    except KeyError as exc:
        return AnswerResult(Outcome.REFUSED, reason=str(exc),
                            modality=AnswerModality.USER_TEXT)

    commanded = _command(said, field, locale, context, candidates,
                         universe)
    if commanded is not None:
        return commanded

    grams = _grams_from_text(said, food_name)
    if grams is None:
        return AnswerResult(Outcome.REPAIR, reason=f"no quantity in {said!r}",
                            modality=AnswerModality.REPAIR,
                            repair_reason=RepairReason.NO_AMOUNT_IN_ANSWER)

    from skills.nutrition.quantity_clarification import _quantity

    return AnswerResult(
        Outcome.APPLIED, modality=AnswerModality.USER_TEXT,
        patch=SetQuantity(
            event_id=field.event_id, field_id=field.field_id,
            quantity=_quantity(grams, provenance=Provenance.USER_STATED,
                               confidence=1.0, basis="the user said so"),
            provenance=Provenance.USER_STATED))


def _command(said: str, field, locale: str = "en",
             context=None, candidates=None,
             universe=UniverseDisposition.NOT_APPLICABLE) -> Optional[AnswerResult]:
    """Deterministic commands, through the parser that already owns them.

    A local word list was the first version, matched by substring, and it was
    wrong in the direction that costs the most: `"cancel" in text` fires on
    "I didn't cancel my order", and the docstring's own rule is that a false
    positive here costs the user their meal. `parse_command` matches anchored
    patterns, already covers skip/cancel/estimate/restart/keep-as-read, and is
    the single owner of what those phrases mean — a second one drifts.

    `locale` is passed EXPLICITLY, never defaulted here. The parser's Tier-1
    lexicon is English; a caller that knows better and stays silent is how an
    EN-only detector ends up judging a Russian sentence.
    """
    from skills.nutrition.answer_parsers import (ClarificationCommand,
                                                 parse_command)

    command = parse_command(said, locale=locale)
    if command is None:
        return None
    if command in (ClarificationCommand.CANCEL_MEAL,
                   ClarificationCommand.SKIP_ITEM,
                   ClarificationCommand.RESTART):
        return AnswerResult(Outcome.CANCELLED, reason=command.value,
                            modality=AnswerModality.COMMAND)
    if command in (ClarificationCommand.ESTIMATE,
                   ClarificationCommand.KEEP_AS_READ,
                   ClarificationCommand.COMMIT_READY):
        return _estimate(field, command.value, context, candidates,
                         universe)
    return None


#: The estimate policy this decision was made under. Versioned because the
#: sufficiency rule is a POLICY, not a constant — a later ranker will change
#: what counts as support, and observations already collected must remain
#: attributable to the rule that produced them.
ESTIMATE_POLICY_VERSION = "estimate_evidence_v1"

#: CF-1 CLOSED. This was `frozenset({"user_history", "catalog"})` — source
#: NAMES, matched as strings. It worked only because those two lanes happen to
#: be entity-specific today, and it would have drifted silently the moment a
#: lane was added whose name says nothing about what its evidence is about.
#:
#: Applicability is now read from `EvidenceScope` on the candidate's evidence:
#: the contract states what the evidence is ABOUT, and a lane added tomorrow
#: is judged on that rather than on what it is called.
#:
def _estimate_is_supported(field, context=None, candidates=None):
    """May "not sure" commit, or must it stay unresolved?

    THE MEASURED CASE. "Not sure" committed 435 g of chicken breast — 718 cal,
    nearly a pound — because the ontology's generic bracket collapsed to
    `6 oz / 16 oz` and the estimate took the upper of two. The user asked us
    not to guess and we guessed extravagantly.

    NO THRESHOLD IS DEFENSIBLE HERE, and that was measured before choosing.
    Confidence does not separate the failures from the successes — it runs
    the wrong way:

        Chicken breast   piece      conf 0.75   3.3x   <- the failure
        White rice       category   conf 0.32   3.2x   <- fine
        Banana           piece      conf 0.83   2.8x   <- degenerate

    Nor does spread: everything sits between 2.8x and 6.7x. A cut-off on
    either number would be exactly the arbitrary threshold the standing rules
    forbid, and would have been tuned to two anecdotes.

    THE RULE IS ABOUT WHAT THE EVIDENCE IS ABOUT. A portion ontology is a
    statement about people in general; it is the right basis for OFFERING
    choices and it is not evidence about what this person ate. `USER_HISTORY`
    is — they logged this exact food at this exact amount. Catalog/package
    data is, for a product with a defined serving.

    So: an estimate may only commit from a candidate carrying user-specific or
    product-specific evidence. With none, the canonical state stays
    unresolved and we repair. That is entity-agnostic, needs no food name, no
    tier and no cut-off, and it gets all four production cases right —
    chicken and honey refuse, white rice and ground turkey commit the user's
    own logged portion.
    """
    return [o for o in getattr(field, "options", ()) or ()
            if o.patch is not None
            and getattr(o.patch, "quantity", None) is not None
            and _authorizes_assumption(o, context, candidates)]


def _authorizes_assumption(option, context=None, candidates=None) -> bool:
    """Read the evidence IN CONTEXT, fall back to the migration table, never
    guess.

    An option carrying a real `QuantityCandidate` answers for itself, and it
    answers about a specific person and entity — scope alone proves the
    evidence names *a* user, not *this* one. Without a context we cannot make
    that comparison, so candidate-bearing options fail SHUT rather than being
    authorised on scope alone; a caller that knows who is asking must say so.

    THE QUESTION IS ASKED OF THE CANDIDATE, NOT OF ONE EVIDENCE RECORD. A
    candidate may be supported by several sources, and it is authorised if
    ANY ONE of them is sufficient on its own — population records sitting
    alongside neither help nor dilute.

    NO OPTION WITHOUT A CANDIDATE MAY AUTHORISE ANYTHING. A migration-era
    table once mapped a source NAME to a scope; it worked only because the
    lanes it named happened to be entity-specific, and it would have drifted
    the moment a lane was added whose name says nothing about what its evidence
    is ABOUT. Every production producer emits typed candidates now, so that
    table is deleted rather than left as a path that could quietly become
    load-bearing again. An option reaching here without a candidate is a
    producer nobody migrated, and guessing on its behalf is the exact defect
    CF-1 removed.
    """
    # IN MEMORY THE OPTION CARRIES ITS CANDIDATE; ACROSS A TURN IT DOES NOT.
    # The stored wire form holds only ids, so the answer turn resolves them
    # from the persisted universe and passes them here.
    candidate = getattr(option, "candidate", None)
    if candidate is None and candidates:
        candidate = candidates.get(getattr(option, "option_id", ""))
    if candidate is None:
        logger.warning(
            "event=b1_option_without_candidate option=%s — no typed candidate "
            "to reason from, refusing to authorise an assumption",
            getattr(option, "option_id", "?"))
        return False
    if context is None:
        logger.warning(
            "event=b1_evidence_without_context option=%s — a candidate "
            "cannot be matched to a subject, refusing to authorise",
            getattr(option, "option_id", "?"))
        return False
    return bool(candidate.authorizes_assumption(context))


def _estimate(field, reason: str, context=None, candidates=None,
              universe=UniverseDisposition.NOT_APPLICABLE) -> AnswerResult:
    """"I don't know — you decide."

    A real answer, not a failure to answer, and the alternative is worse than
    it looks: repairing here asks the same question again to a user who has
    already said they cannot answer it, which is an interrogation loop and
    would show up as a repair rate nobody could act on.

    The value is the MIDDLE offered option, re-provenanced. Nothing new is
    invented — it is an option already on their screen — and the provenance
    changes to `MODE_DEFAULT` because we chose it, not them. That is what
    keeps the "(my estimate)" marker, the card range and the disclosure alive
    on the committed row.
    """
    from dataclasses import replace

    from core.semantics import Provenance, SetQuantity

    priced = _estimate_is_supported(field, context, candidates)
    if not priced:
        # UNRESOLVED IS THE CORRECT STATE. No write, the operation stays open,
        # and the user is asked again — rather than being handed a number
        # nothing supports. Manufacturing certainty to finish the turn is the
        # failure mode, not the turn staying open.
        logger.info(
            "event=b1_estimate_unsupported policy=%s reason=%s offered=%s — "
            "no user- or product-specific evidence; remaining unresolved "
            "rather than committing a population prior",
            ESTIMATE_POLICY_VERSION, reason,
            ",".join(str(getattr(getattr(o, "source", None), "value", "?"))
                     for o in (getattr(field, "options", ()) or ())))
        # WHICH KIND OF "we cannot estimate" THIS IS — DECLARED BY THE
        # LOADER. A universe we could not read is an outage; evidence that
        # does not support one is a fact about this person's history.
        # Reporting them together would let a storage failure read as a
        # population of users we know nothing about, and INFERRING the
        # difference from an empty list would misfile a legitimate empty
        # result as an outage.
        unreadable = universe is UniverseDisposition.UNAVAILABLE
        return AnswerResult(
            Outcome.REPAIR, modality=AnswerModality.COMMAND,
            reason=f"{reason}: no evidence supports an estimate here",
            repair_reason=(RepairReason.UNIVERSE_UNAVAILABLE if unreadable
                           else RepairReason.ESTIMATE_UNSUPPORTED),
            decision_policy_version=ESTIMATE_POLICY_VERSION)
    priced.sort(key=lambda o: o.patch.quantity.grams)
    middle = priced[len(priced) // 2].patch
    return AnswerResult(
        Outcome.APPLIED, reason=reason, modality=AnswerModality.COMMAND,
        decision_policy_version=ESTIMATE_POLICY_VERSION,
        patch=replace(middle,
                      quantity=replace(middle.quantity,
                                       provenance=Provenance.MODE_DEFAULT),
                      provenance=Provenance.MODE_DEFAULT))


def _grams_from_text(text: str, food_name: str = ""):
    """The user's own words as a mass `Decimal`, or None.

    `normalize_quantity` already owns every hard case here — fractions,
    ranges, ordinals, spelled numbers, unit aliases. Reaching for a second
    parser would be the same duplication the migration is removing, one layer
    down.

    Returned as `Decimal` via `str`, never through `float()`. The value
    arrives as a float and that precision is already spent; re-widening it to
    a binary float on the way out would spend it twice, and `CanonicalQuantity`
    holds `Decimal` precisely so a portion survives the round trip it is about
    to make into storage.
    """
    from decimal import Decimal, InvalidOperation

    try:
        from skills.nutrition.normalize import normalize_quantity
        nq = normalize_quantity(text, food_name or "")
    except Exception:
        logger.debug("quantity answer unparsed", exc_info=True)
        return None
    grams = getattr(nq, "grams", None) if nq is not None else None
    if not grams:
        return None

    # WE ASKED BECAUSE "SOME" WAS NOT ENOUGH. "SOME" IS STILL NOT ENOUGH.
    #
    # `normalize_quantity` maps a bare vague measure onto the ontology's
    # portion for the food — correct in its own context, and exactly how the
    # interpreter turns "some rice" into a number. At THIS boundary it is
    # wrong: it accepts, as the answer to "how much?", the very vagueness that
    # produced the question.
    #
    # Measured: `_grams_from_text("I had some salmon")` returned 174 g while a
    # chicken-breast question was open, so a new meal COMMITTED THE CHICKEN at
    # its default and the salmon was lost. Same shape as the 2026-08-05
    # oatmeal loss, on the AWAITING path the settled and expired guards never
    # covered — because that path is the one that is supposed to accept
    # answers.
    #
    # The parser already draws the distinction; nothing here needs to detect
    # anything. `normalization_source` names WHERE the grams came from, and
    # only one of its values means "the user told us nothing and we filled it
    # in from the food's typical portion":
    #
    #   "6 oz"            -> mass_conversion   an amount was stated
    #   "about 6 ounces"  -> mass_conversion   hedged, still stated
    #   "a cup"           -> vessel            a vessel was stated
    #   "half a breast"   -> piece_weight      a fraction was stated
    #   "some"            -> ontology          <- nothing was stated
    #
    # NOT `user_stated_amount`, which was the obvious choice and is wrong: it
    # is None for "about 6 ounces" too, because the hedge strips the literal
    # amount. Keying on it refused four legitimate answer routes, and the
    # existing suite caught that immediately — which is what it is for.
    #
    # Returning None here means REPAIR: ask the same field again, narrower.
    # Never a commit of a number the user did not give us.
    if str(getattr(nq, "normalization_source", "") or "") == "ontology":
        logger.info(
            "event=b1_answer_not_stated text=%r grams=%s — the quantity came "
            "from the vague fallback, not from the user; repairing rather "
            "than committing", (text or "")[:60], grams)
        return None
    try:
        return Decimal(str(grams))
    except (InvalidOperation, ValueError):
        return None


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
