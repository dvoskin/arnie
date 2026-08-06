"""B-1.9 commit 3b — the durable candidate universe under hostile conditions.

NOT SCORED BY WHETHER THE TABLES EXIST. Scored by whether a persisted record
survives restart, retry, race, rollback and replay without changing meaning.
An elegant schema that loses its meaning under a retry is not trustworthy
storage; it is a diagram that happens to compile.

The property every gate here defends: for any candidate a user expected and
did not see, exactly one answer exists, and it comes from stored rows without
rerunning the generator.

    not generated  ·  generated then excluded  ·  shown but not chosen

Never "unknown".
"""
import asyncio
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from core import candidate_repository as repo
from core.semantics import (CandidateDecisionRecord, CandidateExclusion,
                            CandidateGenerationRejection,
                            CandidateSelectionContext,
                            CandidateSelectionDecision, CandidateSet,
                            CandidateSource, EvidenceContext, ExclusionReason,
                            GenerationRejectionReason,
                            PresentedCandidateOption, SelectionSurface,
                            SourceReference)
from db.database import Base, make_engine
from db.models import (CandidateEvidenceRow, CandidateExclusionRow,
                       CandidateRow, CandidateSelectionDecisionRow,
                       CandidateSetRow, PresentedOptionRow, User)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests._typed_candidates import ENTITY, candidate

USER_ID = 26

CTX = CandidateSelectionContext(surface=SelectionSurface.LABEL_TEXT,
                                locale="en", maximum_options=3,
                                renderer_contract_version="labels_v1")


def _universe(*, set_id="cs_test", user_id=USER_ID, fingerprint="fp_1",
              candidates=None, rejections=()):
    return CandidateSet(
        candidate_set_id=set_id, operation_id="op_test", user_id=user_id,
        context=EvidenceContext(user_id=user_id, canonical_entity_id=ENTITY),
        interaction_revision=0, field_id="f_quantity",
        generator_version="gen_v1", generation_input_fingerprint=fingerprint,
        candidates=(candidates if candidates is not None else (
            candidate("c1", 85.0, prior=0.2),
            candidate("c2", 141.7, source=CandidateSource.USER_HISTORY,
                      prior=0.55, confidence=0.9),
            candidate("c3", 226.0, prior=0.3))),
        rejections=rejections)


def _record(universe=None, *, selected=("c2", "c1"),
            excluded=(("c3", ExclusionReason.SELECTION_CAP),), presented=True):
    universe = universe or _universe()
    revision = universe.interaction_revision
    decision = CandidateSelectionDecision(
        candidate_set_id=universe.candidate_set_id,
        selection_policy_version="sel_v1", context=CTX,
        selected_candidate_ids=tuple(selected),
        exclusions=tuple(CandidateExclusion(candidate_id=c, reason=r)
                         for c, r in excluded))
    shown = ()
    if presented:
        shown = tuple(PresentedCandidateOption(
            option_id=f"opt_{c}", candidate_id=c,
            candidate_set_id=universe.candidate_set_id,
            interaction_revision=revision, selected_position=i,
            rendered_label=f"label {i}",
            renderer_contract_version="labels_v1")
            for i, c in enumerate(selected))
    return CandidateDecisionRecord(candidate_set=universe, decision=decision,
                                   presented=shown)


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'universe.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession,
                              expire_on_commit=False)


@pytest_asyncio.fixture
async def user(sessions, monkeypatch):
    async with sessions() as s:
        u = User(id=USER_ID, telegram_id="t26", name="Danny", timezone="UTC")
        s.add(u)
        await s.commit()
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(USER_ID))
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    return u


# ── atomic write, and a full reload with no generator ───────────────────────

@pytest.mark.asyncio
async def test_a_universe_reloads_from_storage_without_regenerating(sessions,
                                                                    user):
    """REPLAY IS EVIDENCE ONLY IF IT DOES NOT RERUN ANYTHING.

    A replay that regenerates is a second opinion from a system that may have
    changed since — which is exactly what cannot be used to explain what
    somebody was shown last week.
    """
    original = _record()
    async with sessions() as s:
        await repo.save(s, original)
        await s.commit()

    async with sessions() as s:
        back = await repo.load(s, "cs_test", user_id=USER_ID)

    assert back is not None
    # Candidate identity, evidence, ordering, labels, reasons — all restored.
    assert back.candidate_set.candidate_ids == {"c1", "c2", "c3"}
    assert back.decision.selected_candidate_ids == ("c2", "c1")
    assert [p.rendered_label for p in back.presented] == ["label 0", "label 1"]
    assert back.decision.exclusions[0].reason is ExclusionReason.SELECTION_CAP
    history = back.candidate_set.candidate("c2").evidence[0]
    assert history.source_type is CandidateSource.USER_HISTORY
    assert history.subject_user_id == USER_ID
    assert back.candidate_set.candidate("c2").quantity.grams == Decimal("141.7")
    # The aggregate's own partition gate held across the round trip.
    assert back == CandidateDecisionRecord.from_payload(back.to_payload())


@pytest.mark.asyncio
async def test_the_whole_universe_lands_or_none_of_it_does(sessions, user):
    """A partial universe is worse than none: it looks authoritative and
    describes an ask that never happened."""
    async with sessions() as s:
        await repo.save(s, _record())
        # The transaction is the caller's, and it is abandoned here exactly as
        # a failing turn would abandon it.
        await s.rollback()

    async with sessions() as s:
        for table in (CandidateSetRow, CandidateRow, CandidateEvidenceRow,
                      CandidateSelectionDecisionRow, CandidateExclusionRow,
                      PresentedOptionRow):
            count = (await s.execute(
                select(func.count()).select_from(table))).scalar()
            assert count == 0, f"{table.__tablename__} survived a rollback"


@pytest.mark.asyncio
async def test_every_row_is_written_not_only_the_shown_ones(sessions, user):
    """THE POINT OF THE WHOLE COMMIT. Three candidates generated, two shown —
    and the third is on disk with a typed reason, not missing."""
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(
            CandidateRow))).scalar() == 3
        assert (await s.execute(select(func.count()).select_from(
            PresentedOptionRow))).scalar() == 2
        assert (await s.execute(select(func.count()).select_from(
            CandidateExclusionRow))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(
            CandidateEvidenceRow))).scalar() == 3


# ── idempotency and determinism ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_same_ask_retried_finds_its_universe(sessions, user):
    """A transport retry must not mint a second universe for one question."""
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()
    async with sessions() as s:
        assert await repo.save(s, _record()) == "cs_test"
        await s.commit()

    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(
            CandidateSetRow))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(
            CandidateRow))).scalar() == 3


@pytest.mark.asyncio
async def test_the_same_key_from_different_inputs_fails_loudly(sessions, user):
    """SILENCE HERE WOULD BE THE WORST OUTCOME.

    Returning the stored universe for a regeneration from different inputs
    means the options on screen are justified by a record describing something
    else — a record that looks authoritative and is about another question.
    """
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    async with sessions() as s:
        with pytest.raises(repo.DeterminismViolation, match="different"):
            await repo.save(s, _record(_universe(fingerprint="fp_2")))


@pytest.mark.asyncio
async def test_a_universe_cannot_be_claimed_by_another_user(sessions, user):
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    foreign = _universe(
        user_id=99,
        candidates=(candidate("c1", 85.0, user_id=99),
                    candidate("c2", 141.7, user_id=99),
                    candidate("c3", 226.0, user_id=99)))
    async with sessions() as s:
        with pytest.raises(repo.DeterminismViolation, match="belongs to user"):
            await repo.save(s, _record(foreign))


@pytest.mark.asyncio
async def test_two_concurrent_asks_produce_one_universe(sessions, user):
    """The process doing the remembering is the one most likely to be racing
    itself. Deduped by the DATABASE, because an application-level check loses
    every race it is asked to arbitrate."""
    async def _attempt():
        async with sessions() as s:
            try:
                await repo.save(s, _record())
                await s.commit()
                return "wrote"
            except Exception:
                await s.rollback()
                return "lost"

    outcomes = await asyncio.gather(_attempt(), _attempt(),
                                    return_exceptions=True)
    assert any(o == "wrote" for o in outcomes), outcomes

    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(
            CandidateSetRow))).scalar() == 1
        # And whichever attempt lost left nothing half-written behind it.
        assert (await s.execute(select(func.count()).select_from(
            CandidateRow))).scalar() == 3


# ── ownership at the durable boundary ───────────────────────────────────────

@pytest.mark.asyncio
async def test_a_universe_is_not_readable_by_supplying_its_id(sessions, user):
    """Evidence here can quote one person's logging history. A set must never
    become readable merely because someone knows its identifier."""
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    async with sessions() as s:
        assert await repo.load(s, "cs_test", user_id=USER_ID) is not None
        assert await repo.load(s, "cs_test", user_id=99) is None
        assert await repo.load_for_operation(
            s, "op_test", user_id=99) is None


# ── append-only ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_new_revision_adds_a_universe_and_changes_nothing(sessions,
                                                                  user):
    """These rows are evidence. "What did we offer that person, that day" has
    one true answer and it is not the current one."""
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    later = CandidateSet(
        candidate_set_id="cs_test_r1", operation_id="op_test",
        user_id=USER_ID,
        context=EvidenceContext(user_id=USER_ID, canonical_entity_id=ENTITY),
        interaction_revision=1, field_id="f_quantity",
        generator_version="gen_v1", generation_input_fingerprint="fp_2",
        candidates=(candidate("c9", 200.0),))
    async with sessions() as s:
        await repo.save(s, _record(later, selected=("c9",), excluded=()))
        await s.commit()

    async with sessions() as s:
        first = await repo.load(s, "cs_test", user_id=USER_ID)
        second = await repo.load(s, "cs_test_r1", user_id=USER_ID)
    assert first.decision.selected_candidate_ids == ("c2", "c1")
    assert second.decision.selected_candidate_ids == ("c9",)
    assert first.revision == 0 and second.revision == 1


@pytest.mark.asyncio
async def test_the_repository_offers_no_way_to_rewrite_a_record(sessions,
                                                                user):
    """Enforced by absence, and asserted so the absence stays deliberate."""
    assert not [n for n in dir(repo)
                if n.startswith(("update", "delete", "overwrite", "amend"))]


# ── analytics: exactly one answer, never "unknown" ──────────────────────────

@pytest.mark.asyncio
async def test_every_missing_candidate_has_exactly_one_explanation(sessions,
                                                                   user):
    """Before this record, "history never appeared" read identically whether
    the matcher found nothing or the selector dropped it. Different
    engineering problems; one number would have hidden which."""
    rejection = CandidateGenerationRejection(
        producer=CandidateSource.USER_HISTORY,
        source=SourceReference(dataset_id="food_entries",
                               dataset_version="live", record_key="9",
                               record_version="entry:9"),
        reason=GenerationRejectionReason.NO_QUANTITY,
        generator_version="gen_v1")
    async with sessions() as s:
        await repo.save(s, _record(_universe(rejections=(rejection,))))
        await s.commit()

    async with sessions() as s:
        assert await repo.why_not(s, "cs_test", user_id=USER_ID,
                                  candidate_id="c2") == "shown"
        assert await repo.why_not(s, "cs_test", user_id=USER_ID,
                                  candidate_id="c3") == "excluded:selection_cap"
        assert await repo.why_not(s, "cs_test", user_id=USER_ID,
                                  candidate_id="c404") == "not_generated"
        # And a retrieval failure the generator SAW is distinguishable from
        # one it never encountered.
        back = await repo.load(s, "cs_test", user_id=USER_ID)
        assert back.candidate_set.rejections[0].reason is (
            GenerationRejectionReason.NO_QUANTITY)


@pytest.mark.asyncio
async def test_exclusion_reasons_aggregate_without_opening_payloads(sessions,
                                                                    user):
    """"Why wasn't my usual portion there" has to be answerable at population
    scale — a GROUP BY, not a record-by-record read."""
    async with sessions() as s:
        await repo.save(s, _record(
            excluded=(("c3", ExclusionReason.RENDER_COLLISION),)))
        await s.commit()

    async with sessions() as s:
        rows = (await s.execute(
            select(CandidateExclusionRow.reason, func.count())
            .group_by(CandidateExclusionRow.reason))).all()
    assert dict(rows) == {"render_collision": 1}


@pytest.mark.asyncio
async def test_evidence_sources_aggregate_without_opening_payloads(sessions,
                                                                   user):
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    async with sessions() as s:
        rows = (await s.execute(
            select(CandidateEvidenceRow.source_type, func.count())
            .group_by(CandidateEvidenceRow.source_type))).all()
    assert dict(rows) == {"ontology": 2, "user_history": 1}


# ── the chain from a tap back to its justification ──────────────────────────

@pytest.mark.asyncio
async def test_a_tap_resolves_to_the_candidate_that_justified_it(sessions,
                                                                 user):
    """option_id -> candidate_id -> candidate_set_id -> the revision shown."""
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    async with sessions() as s:
        back = await repo.load(s, "cs_test", user_id=USER_ID)
    tapped = back.option_for("opt_c2")
    assert tapped.candidate_id == "c2"
    assert tapped.evidence[0].source.record_key
    assert back.presented[0].interaction_revision == 0


@pytest.mark.asyncio
async def test_the_ask_path_persists_its_universe_before_asking(sessions,
                                                               user):
    """END TO END, through the real ownership call — not a hand-built record.

    The universe must exist by the time the question does, because a user
    answering options nothing can explain is the exact state this prevents.
    """
    from core import b1_quantity_operation as b1
    from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
    from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                          StagedFoodItem)

    # THE REAL SHAPE, ambiguity included. A staged item without one raises no
    # quantity question, so B-1 declines and the gate would prove nothing.
    item = StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken breast",
        identity=FoodIdentity(canonical_name="chicken breast"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        ambiguities=(FoodAmbiguity(
            ambiguity_id="a1", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
            field_name="estimated_mass_g", materiality_score=2.0,
            calorie_span=180.0),))
    async with sessions() as s:
        u = await s.get(User, USER_ID)
        ask = await b1.try_take_ownership(
            s, user=u, material={"items": [{"food": "chicken breast",
                                            "calories": 300}],
                                 "staged_items": (item,),
                                 "asked_item_id": "si_1",
                                 "message": "some chicken breast",
                                 "identity_evidence": True},
            turn_id="t_universe", client_capable=True)
        await s.commit()
    # NOT A SKIP. A skip here is an instrument lying by silence: the day the
    # gate starts declining, this test would go green having exercised
    # nothing, and the most important property in the commit would stop being
    # checked without anyone being told.
    assert ask is not None, "ownership was declined; this gate tested nothing"

    async with sessions() as s:
        stored = await repo.load_for_operation(
            s, ask.operation_id, user_id=USER_ID)
    assert stored is not None, "a question was asked with no durable universe"
    shown = {p.option_id for p in stored.presented}
    asked = {o.option_id
             for o in ask.interaction.groups[0].fields[0].options}
    assert shown == asked, "the row persisted is not the row shown"
