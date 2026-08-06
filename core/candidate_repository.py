"""Write and read the durable candidate universe. APPEND-ONLY.

There is no update path in this module, deliberately. These rows are evidence:
"what did we offer that person, that day" has one true answer and it is not
the current one. A new revision or policy writes a NEW set and a NEW decision.

WHAT THIS BUYS. After a write, exactly one of these is true for any candidate
the user expected and did not see, and the answer comes from stored rows
without rerunning anything:

    not generated        absent from the set (see its `rejections` for
                         inputs the generator saw and could not use)
    generated, excluded  present, with a typed exclusion reason
    shown, not chosen    present in the decision's selected ids, and in
                         `presented_candidate_options`

DOMAIN-NEUTRAL. Nothing here knows about food. `domain`, `subject_entity_id`
and typed payloads are the whole vocabulary, so the same functions will store
exercise identity and set/rep ambiguity unchanged.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

#: Raised when a universe is regenerated for the same key from DIFFERENT
#: semantic inputs. Loud on purpose: silently returning the old universe would
#: mean the options shown were justified by a record describing other inputs.
class DeterminismViolation(RuntimeError):
    pass


def _decision_id(candidate_set_id: str, decision) -> str:
    """Deterministic, so the same decision under the same conditions is the
    same row on replay rather than a second one.

    EVERY FIELD THE CONTEXT CLAIMS TO DETERMINE THE OUTCOME BY, including
    `maximum_options`. Omitting it collided two legitimately different
    decisions — three text options and five structured ones, same surface and
    renderer — under one durable identity, so the second could never be
    written and the first would be replayed in its place.
    """
    import hashlib

    ctx = decision.context
    raw = "|".join((candidate_set_id, decision.selection_policy_version,
                    ctx.surface.value, ctx.locale,
                    str(ctx.maximum_options),
                    ctx.renderer_contract_version))
    return "dec_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def decision_id_for(record) -> str:
    """The durable identity of the question a record represents."""
    return _decision_id(record.candidate_set.candidate_set_id, record.decision)


async def save(db, record, *, domain: str = "food") -> str:
    """Persist a universe, its decision and the options shown. ATOMICALLY.

    Flushes rather than commits: the caller's transaction owns the boundary,
    so the universe and the pending operation that references it either both
    exist or neither does. A universe without its operation would describe an
    ask nobody was ever shown; an operation without its universe is an ask we
    cannot explain.

    THREE INDEPENDENT IDEMPOTENCIES, not one. The set, the decision and the
    presented row are separate append-only records with separate identities,
    and short-circuiting on the set alone meant a second decision over the
    SAME immutable universe could never be written — which is the normal case,
    not an edge one: the same universe rendered for Telegram and for iOS, or
    reduced again after the selector is versioned up, is a new decision over
    an old set.
    """
    set_id = await ensure_candidate_set(db, record.candidate_set, domain=domain)
    decision_id = await ensure_selection_decision(db, record.decision)
    await ensure_presented_options(db, record, decision_id=decision_id)
    return set_id


async def ensure_candidate_set(db, universe, *, domain: str = "food") -> str:
    """The generated universe. Written once; never rewritten.

    Same key and same fingerprint is a replay and returns the stored set. Same
    key and a DIFFERENT fingerprint is a determinism violation: returning the
    stored universe would justify the options on screen with a record
    describing other inputs.
    """
    from sqlalchemy import select

    from db.models import (CandidateEvidenceRow, CandidateRow, CandidateSetRow)

    set_id = universe.candidate_set_id
    existing = await _existing_set(db, set_id)
    if existing is not None:
        _assert_same_universe(existing, universe)
        return set_id

    # A CONCURRENT WRITER MAY WIN BETWEEN THE READ ABOVE AND THIS INSERT.
    # The database arbitrates — that is what the unique constraint is for —
    # and losing the race is a REPLAY, not an error: the winner wrote the same
    # universe, and the loser must recover to it rather than surface an
    # IntegrityError to a turn that did nothing wrong.
    savepoint = await db.begin_nested()
    db.add(CandidateSetRow(
        candidate_set_id=set_id, domain=domain,
        operation_id=universe.operation_id, user_id=universe.user_id,
        interaction_revision=universe.interaction_revision,
        field_id=universe.field_id,
        subject_entity_id=universe.context.canonical_entity_id or "",
        subject_variant_id=universe.context.product_variant_id,
        generator_version=universe.generator_version,
        generation_input_fingerprint=universe.generation_input_fingerprint,
        rejections=[r.to_payload() for r in universe.rejections]))
    try:
        await db.flush()
    except IntegrityError:
        await savepoint.rollback()
        lost = await _existing_set(db, set_id)
        if lost is None:
            raise
        _assert_same_universe(lost, universe)
        return set_id

    for position, cand in enumerate(universe.candidates):
        db.add(CandidateRow(
            candidate_set_id=set_id, candidate_id=cand.candidate_id,
            candidate_kind="quantity", position=position,
            semantic_hash=cand.semantic_hash,
            # THE PAYLOAD CARRIES NO EVIDENCE. `candidate_evidence_records` is
            # the sole durable authority for it — two copies meant replay
            # could trust one while the funnel counted the other, and the
            # system would behave correctly while reporting the wrong
            # provenance. Nothing is more dangerous than a metric that is
            # confidently wrong.
            payload=_candidate_payload_without_evidence(cand)))
    await db.flush()

    for cand in universe.candidates:
        for index, ev in enumerate(cand.evidence):
            db.add(CandidateEvidenceRow(
                candidate_set_id=set_id, candidate_id=cand.candidate_id,
                evidence_index=index, source_type=ev.source_type.value,
                source_dataset_id=ev.source.dataset_id,
                source_dataset_version=ev.source.dataset_version,
                source_record_key=ev.source.record_key,
                source_record_version=ev.source.record_version,
                subject_scope=ev.subject_scope.value,
                subject_user_id=ev.subject_user_id,
                subject_variant_id=ev.product_variant_id,
                payload=ev.to_payload()))
    await db.flush()
    return set_id


async def _existing_set(db, set_id: str):
    from sqlalchemy import select

    from db.models import CandidateSetRow

    return (await db.execute(select(CandidateSetRow).where(
        CandidateSetRow.candidate_set_id == set_id))).scalar_one_or_none()


def _assert_same_universe(existing, universe) -> None:
    if (existing.generation_input_fingerprint
            != universe.generation_input_fingerprint):
        raise DeterminismViolation(
            f"{universe.candidate_set_id} already exists with fingerprint "
            f"{existing.generation_input_fingerprint!r} but was regenerated "
            f"as {universe.generation_input_fingerprint!r} — the same "
            f"question produced a different universe, and returning the "
            f"stored one would justify the options with a record of other "
            f"inputs")
    if existing.user_id != universe.user_id:
        raise DeterminismViolation(
            f"{universe.candidate_set_id} belongs to user "
            f"{existing.user_id}, not {universe.user_id}")


def _candidate_payload_without_evidence(cand) -> dict:
    payload = cand.to_payload()
    payload.pop("evidence", None)
    return payload


def _canonical_decision(*, selected, exclusions, policy, set_id, surface,
                        locale, maximum_options, renderer) -> tuple:
    """Everything a decision asserts, in one comparable value.

    Order matters for the selection (it decides prominence); exclusions are
    sorted because their storage order is not a fact about the decision.
    """
    return (set_id, policy, surface, locale, int(maximum_options), renderer,
            tuple(selected), tuple(sorted(exclusions)))


async def ensure_selection_decision(db, decision) -> str:
    """The reduction. A NEW decision over an existing set is legitimate.

    A retry of the same conditions must find the stored decision and prove it
    identical; a genuinely different one — new policy, new surface, new slot
    count, new renderer — is a new append-only record over the same immutable
    universe.
    """
    from sqlalchemy import select

    from db.models import (CandidateExclusionRow,
                           CandidateSelectionDecisionRow)  # noqa: F401

    set_id = decision.candidate_set_id
    decision_id = _decision_id(set_id, decision)
    ctx = decision.context
    existing = (await db.execute(
        select(CandidateSelectionDecisionRow).where(
            CandidateSelectionDecisionRow.decision_id
            == decision_id))).scalar_one_or_none()
    if existing is not None:
        # THE WHOLE DECISION, NOT ITS WINNERS.
        #
        # Comparing `selected_candidate_ids` alone accepted a retry that kept
        # the same options and changed WHY the others were dropped —
        # `SEMANTIC_DUPLICATE` becoming `SELECTION_CAP` under one identity.
        # The write was silently ignored, so the caller believed one
        # explanation and the record held another. A decision record whose
        # explanation can drift is not evidence.
        stored_exclusions = (await db.execute(
            select(CandidateExclusionRow).where(
                CandidateExclusionRow.decision_id == decision_id))).scalars().all()
        stored = _canonical_decision(
            selected=tuple(existing.selected_candidate_ids or ()),
            exclusions=tuple((x.candidate_id, x.reason)
                             for x in stored_exclusions),
            policy=existing.selection_policy_version,
            set_id=existing.candidate_set_id,
            surface=existing.surface, locale=existing.locale,
            maximum_options=existing.maximum_options,
            renderer=existing.renderer_contract_version)
        incoming = _canonical_decision(
            selected=tuple(decision.selected_candidate_ids),
            exclusions=tuple((x.candidate_id, x.reason.value)
                             for x in decision.exclusions),
            policy=decision.selection_policy_version, set_id=set_id,
            surface=ctx.surface.value, locale=ctx.locale,
            maximum_options=ctx.maximum_options,
            renderer=ctx.renderer_contract_version)
        if stored != incoming:
            raise DeterminismViolation(
                f"{decision_id} is already stored as {stored} but the same "
                f"set under the same policy and context now decides "
                f"{incoming} — the selector is meant to be reproducible from "
                f"set + policy + context, and if it is not, the stored record "
                f"no longer explains the screen")
        return decision_id

    db.add(CandidateSelectionDecisionRow(
        decision_id=decision_id, candidate_set_id=set_id,
        selection_policy_version=decision.selection_policy_version,
        surface=ctx.surface.value, locale=ctx.locale,
        maximum_options=ctx.maximum_options,
        renderer_contract_version=ctx.renderer_contract_version,
        selected_candidate_ids=list(decision.selected_candidate_ids)))
    await db.flush()

    for exclusion in decision.exclusions:
        db.add(CandidateExclusionRow(
            decision_id=decision_id, candidate_set_id=set_id,
            candidate_id=exclusion.candidate_id,
            reason=exclusion.reason.value))
    await db.flush()
    return decision_id


def _shown_tuple(shown) -> tuple:
    """Every field that decides what the user actually read."""
    return (shown.option_id, shown.candidate_id, shown.candidate_set_id,
            int(shown.interaction_revision), int(shown.selected_position),
            shown.rendered_label, shown.renderer_contract_version)


async def ensure_presented_options(db, record, *, decision_id: str) -> None:
    """The row as shown. Written once per decision."""
    from sqlalchemy import select

    from db.models import PresentedOptionRow

    if not record.presented:
        return
    already = (await db.execute(
        select(PresentedOptionRow)
        .where(PresentedOptionRow.decision_id == decision_id)
        .order_by(PresentedOptionRow.selected_position))).scalars().all()
    if already:
        # THE WHOLE ROW, IN ORDER.
        #
        # Comparing option ids alone accepted a retry that kept the ids and
        # changed the LABEL — `6 oz` becoming `8 oz` — or the candidate each
        # id pointed at, or the position it occupied. The write was silently
        # dropped, so the stored row and the row the caller believed it wrote
        # diverged with no error. That is exactly the replay contradiction
        # this table exists to detect.
        stored = tuple(_shown_tuple(p) for p in already)
        incoming = tuple(sorted((_shown_tuple(p) for p in record.presented),
                                key=lambda t: t[4]))
        if stored != incoming:
            raise DeterminismViolation(
                f"{decision_id} already presented {stored} but is now "
                f"presenting {incoming}")
        return
    for shown in record.presented:
        db.add(PresentedOptionRow(
            decision_id=decision_id,
            candidate_set_id=record.candidate_set.candidate_set_id,
            option_id=shown.option_id, candidate_id=shown.candidate_id,
            interaction_revision=shown.interaction_revision,
            selected_position=shown.selected_position,
            rendered_label=shown.rendered_label,
            renderer_contract_version=shown.renderer_contract_version))
    await db.flush()


async def load_by_decision_id(db, decision_id: str, *,
                              user_id: int) -> Optional[Any]:
    """THE AUTHORITATIVE READ. The exact question this person was shown.

    One universe may now hold several decisions — Telegram and iOS, a new
    selector version, a different slot count — all legitimate and all over the
    same immutable set. `decision_id` is therefore the durable identity of the
    question that was ASKED; the set id only identifies what could have been
    asked.

    Answer handling and replay must come through here. Anything that resolves
    by set alone can return a different valid decision over the same universe,
    which is the same failure as regenerating: a true statement about the
    system that is not a true statement about this turn.
    """
    from sqlalchemy import select

    from db.models import CandidateSelectionDecisionRow

    row = (await db.execute(select(CandidateSelectionDecisionRow).where(
        CandidateSelectionDecisionRow.decision_id
        == decision_id))).scalar_one_or_none()
    if row is None:
        return None
    return await load(db, row.candidate_set_id, user_id=user_id,
                      decision_id=decision_id)


async def load(db, candidate_set_id: str, *, user_id: int,
               decision_id: Optional[str] = None) -> Optional[Any]:
    """Rebuild a `CandidateDecisionRecord` FROM STORAGE. No regeneration.

    WITHOUT `decision_id` THIS IS AN ADMINISTRATIVE READ. It returns the
    OLDEST decision over the set, deterministically, so a listing is stable —
    but a set may hold several decisions and only the caller knows which one
    was shown. For answer handling and replay use `load_by_decision_id`.

    If replay regenerates, replay is not evidence — it is a second opinion
    from a system that may have changed. Everything returned here was written
    at ask time: the candidates, their evidence, the exclusions and their
    reasons, the ordering, and the labels as they were rendered.

    `user_id` IS REQUIRED AND CHECKED. Evidence here can quote one person's
    logging history, so a set must never become readable merely because
    someone supplied its id.
    """
    from sqlalchemy import select

    from core.semantics import (CandidateDecisionRecord, CandidateExclusion,
                                CandidateGenerationRejection,
                                CandidateSelectionContext,
                                CandidateSelectionDecision, CandidateSet,
                                EvidenceContext, ExclusionReason,
                                PresentedCandidateOption, QuantityCandidate,
                                SelectionSurface)
    from db.models import (CandidateEvidenceRow, CandidateExclusionRow,
                           CandidateRow, CandidateSelectionDecisionRow,
                           CandidateSetRow, PresentedOptionRow)

    row = (await db.execute(select(CandidateSetRow).where(
        CandidateSetRow.candidate_set_id == candidate_set_id,
        CandidateSetRow.user_id == user_id))).scalar_one_or_none()
    if row is None:
        return None

    candidate_rows = (await db.execute(
        select(CandidateRow)
        .where(CandidateRow.candidate_set_id == candidate_set_id)
        .order_by(CandidateRow.position))).scalars().all()
    # EVIDENCE COMES FROM THE EVIDENCE ROWS. One authority: replay and the
    # funnel must read the same records, or the system can behave correctly
    # while reporting the wrong provenance — a metric that is confidently
    # wrong, which is worse than a missing one.
    evidence_rows = (await db.execute(
        select(CandidateEvidenceRow)
        .where(CandidateEvidenceRow.candidate_set_id == candidate_set_id)
        .order_by(CandidateEvidenceRow.evidence_index))).scalars().all()
    by_candidate = {}
    for evidence in evidence_rows:
        by_candidate.setdefault(evidence.candidate_id, []).append(
            evidence.payload)
    universe = CandidateSet(
        candidate_set_id=row.candidate_set_id, operation_id=row.operation_id,
        user_id=row.user_id,
        context=EvidenceContext(
            user_id=row.user_id,
            canonical_entity_id=row.subject_entity_id or "",
            product_variant_id=row.subject_variant_id),
        interaction_revision=row.interaction_revision, field_id=row.field_id,
        generator_version=row.generator_version,
        generation_input_fingerprint=row.generation_input_fingerprint,
        candidates=tuple(
            QuantityCandidate.from_payload(
                {**c.payload, "evidence": by_candidate.get(c.candidate_id,
                                                           [])})
            for c in candidate_rows),
        rejections=tuple(CandidateGenerationRejection.from_payload(r)
                         for r in (row.rejections or ())))

    decisions = select(CandidateSelectionDecisionRow).where(
        CandidateSelectionDecisionRow.candidate_set_id == candidate_set_id)
    if decision_id:
        decisions = decisions.where(
            CandidateSelectionDecisionRow.decision_id == decision_id)
    # ORDERED, ALWAYS. `.first()` over an unordered query returned whichever
    # row the database happened to produce, so replay could hand back a
    # different valid decision over the same universe depending on insertion
    # order. Deterministic by id, which is stable across backends.
    decision_row = (await db.execute(decisions.order_by(
        CandidateSelectionDecisionRow.id))).scalars().first()
    if decision_row is None:
        return None

    exclusions = (await db.execute(
        select(CandidateExclusionRow).where(
            CandidateExclusionRow.decision_id
            == decision_row.decision_id))).scalars().all()
    decision = CandidateSelectionDecision(
        candidate_set_id=candidate_set_id,
        selection_policy_version=decision_row.selection_policy_version,
        context=CandidateSelectionContext(
            surface=SelectionSurface(decision_row.surface),
            locale=decision_row.locale,
            maximum_options=decision_row.maximum_options,
            renderer_contract_version=decision_row.renderer_contract_version),
        selected_candidate_ids=tuple(decision_row.selected_candidate_ids or ()),
        exclusions=tuple(CandidateExclusion(candidate_id=x.candidate_id,
                                            reason=ExclusionReason(x.reason))
                         for x in exclusions))

    shown = (await db.execute(
        select(PresentedOptionRow)
        .where(PresentedOptionRow.decision_id == decision_row.decision_id)
        .order_by(PresentedOptionRow.selected_position))).scalars().all()
    return CandidateDecisionRecord(
        candidate_set=universe, decision=decision,
        presented=tuple(PresentedCandidateOption(
            option_id=p.option_id, candidate_id=p.candidate_id,
            candidate_set_id=p.candidate_set_id,
            interaction_revision=p.interaction_revision,
            selected_position=p.selected_position,
            rendered_label=p.rendered_label,
            renderer_contract_version=p.renderer_contract_version)
            for p in shown))


async def load_for_operation(db, operation_id: str, *, user_id: int,
                             revision: int = 0,
                             decision_id: Optional[str] = None):
    """The universe behind one operation revision.

    `decision_id` SHOULD BE PASSED by anything replaying a real turn — the
    operation stores it precisely so the answer turn can name the question it
    is answering rather than infer it.
    """
    from sqlalchemy import select

    from db.models import CandidateSetRow

    set_id = (await db.execute(select(CandidateSetRow.candidate_set_id).where(
        CandidateSetRow.operation_id == operation_id,
        CandidateSetRow.interaction_revision == revision,
        CandidateSetRow.user_id == user_id))).scalars().first()
    return None if set_id is None else await load(
        db, set_id, user_id=user_id, decision_id=decision_id)


async def why_not(db, candidate_set_id: str, *, user_id: int,
                  candidate_id: str) -> str:
    """Exactly one answer, never "unknown".

    The question analysis actually has to answer is why the quantity someone
    expected was not on their screen, and before this record existed the three
    causes were one undifferentiated "bad options" problem.
    """
    record = await load(db, candidate_set_id, user_id=user_id)
    if record is None:
        return "no_such_universe"
    if candidate_id in record.decision.selected_candidate_ids:
        return "shown"
    for exclusion in record.decision.exclusions:
        if exclusion.candidate_id == candidate_id:
            return f"excluded:{exclusion.reason.value}"
    return "not_generated"
