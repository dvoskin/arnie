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
                     revision: int, food_name: str = "",
                     locale: str = "en") -> AnswerResult:
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
            Outcome.REFUSED,
            reason=f"stale revision {revision} != {interaction.revision}")

    said = (text or "").strip()
    if not said:
        return AnswerResult(Outcome.REPAIR, reason="empty answer")

    try:
        field = interaction.field(field_id)
    except KeyError as exc:
        return AnswerResult(Outcome.REFUSED, reason=str(exc))

    commanded = _command(said, field, locale)
    if commanded is not None:
        return commanded

    grams = _grams_from_text(said, food_name)
    if grams is None:
        return AnswerResult(Outcome.REPAIR, reason=f"no quantity in {said!r}")

    from skills.nutrition.quantity_clarification import _quantity

    return AnswerResult(
        Outcome.APPLIED,
        patch=SetQuantity(
            event_id=field.event_id, field_id=field.field_id,
            quantity=_quantity(grams, provenance=Provenance.USER_STATED,
                               confidence=1.0, basis="the user said so"),
            provenance=Provenance.USER_STATED))


def _command(said: str, field, locale: str = "en") -> Optional[AnswerResult]:
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
        return AnswerResult(Outcome.CANCELLED, reason=command.value)
    if command in (ClarificationCommand.ESTIMATE,
                   ClarificationCommand.KEEP_AS_READ,
                   ClarificationCommand.COMMIT_READY):
        return _estimate(field, command.value)
    return None


#: The estimate policy this decision was made under. Versioned because the
#: sufficiency rule is a POLICY, not a constant — a later ranker will change
#: what counts as support, and observations already collected must remain
#: attributable to the rule that produced them.
ESTIMATE_POLICY_VERSION = "estimate_evidence_v1"

#: Sources that say something about THIS user or THIS product. Everything else
#: is a population prior.
_SUPPORTS_AN_ESTIMATE = frozenset({"user_history", "catalog"})


def _estimate_is_supported(field):
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
    supported = [o for o in getattr(field, "options", ()) or ()
                 if o.patch is not None
                 and getattr(o.patch, "quantity", None) is not None
                 and str(getattr(getattr(o, "source", None), "value", "") or "")
                 in _SUPPORTS_AN_ESTIMATE]
    return supported


def _estimate(field, reason: str) -> AnswerResult:
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

    priced = _estimate_is_supported(field)
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
        return AnswerResult(
            Outcome.REPAIR,
            reason=f"{reason}: no evidence supports an estimate here",
            decision_policy_version=ESTIMATE_POLICY_VERSION)
    priced.sort(key=lambda o: o.patch.quantity.grams)
    middle = priced[len(priced) // 2].patch
    return AnswerResult(
        Outcome.APPLIED, reason=reason,
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
