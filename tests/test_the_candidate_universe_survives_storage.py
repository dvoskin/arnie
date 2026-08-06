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
    """SQLite WITH FOREIGN KEYS ON.

    SQLite ignores foreign keys unless the pragma is set per connection, so
    without this every database-integrity gate in this file would pass against
    an engine that enforces nothing — green, and proving the opposite of what
    it claims. Production is Postgres, which enforces them always; this makes
    the local run agree with it.
    """
    from sqlalchemy import event, text

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'universe.db'}")

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        assert (await conn.execute(
            text("PRAGMA foreign_keys"))).scalar() == 1, (
            "foreign keys are off; every integrity gate here would be a lie")
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


# ── 3b.2 — a decision is idempotent SEPARATELY from its set ─────────────────

def _ctx(**kw):
    base = dict(surface=SelectionSurface.LABEL_TEXT, locale="en",
                maximum_options=3, renderer_contract_version="labels_v1")
    base.update(kw)
    return CandidateSelectionContext(**base)


def _decision_over(universe, *, context=None, policy="sel_v1",
                   selected=("c2", "c1")):
    decision = CandidateSelectionDecision(
        candidate_set_id=universe.candidate_set_id,
        selection_policy_version=policy, context=context or _ctx(),
        selected_candidate_ids=tuple(selected),
        exclusions=(CandidateExclusion(candidate_id="c3",
                                       reason=ExclusionReason.SELECTION_CAP),))
    return CandidateDecisionRecord(
        candidate_set=universe, decision=decision,
        presented=tuple(PresentedCandidateOption(
            option_id=f"opt_{c}_{policy}", candidate_id=c,
            candidate_set_id=universe.candidate_set_id,
            interaction_revision=0, selected_position=i,
            rendered_label=f"label {i}",
            renderer_contract_version=context.renderer_contract_version
            if context else "labels_v1")
            for i, c in enumerate(selected)))


@pytest.mark.parametrize("label,kw", [
    ("a new selector version", {"policy": "sel_v2"}),
    ("a different surface",
     {"context": _ctx(surface=SelectionSurface.ID_ADDRESSED)}),
    ("a different slot count", {"context": _ctx(maximum_options=5)}),
    ("a different renderer",
     {"context": _ctx(renderer_contract_version="labels_v2")}),
    ("a different locale", {"context": _ctx(locale="ru")}),
])
@pytest.mark.asyncio
async def test_a_new_decision_over_an_existing_universe_is_written(
        sessions, user, label, kw):
    """P0. `save()` RETURNED THE MOMENT THE SET EXISTED.

    So a second decision over the same immutable universe could never be
    persisted — and that is the normal case, not an edge one: the same
    universe rendered for Telegram and for iOS, or reduced again after the
    selector is versioned up, is a new decision over an old set. The set is
    write-once; the decision is not.
    """
    universe = _universe()
    async with sessions() as s:
        await repo.save(s, _decision_over(universe))
        await s.commit()
    async with sessions() as s:
        await repo.save(s, _decision_over(universe, **kw))
        await s.commit()

    async with sessions() as s:
        sets = (await s.execute(select(func.count()).select_from(
            CandidateSetRow))).scalar()
        decisions = (await s.execute(select(func.count()).select_from(
            CandidateSelectionDecisionRow))).scalar()
    assert sets == 1, "the universe was rewritten"
    assert decisions == 2, f"{label} did not produce its own decision"


@pytest.mark.asyncio
async def test_maximum_options_is_part_of_the_decisions_identity(sessions,
                                                                 user):
    """Three text options and five structured ones are different rows, and
    were colliding under one durable identity."""
    universe = _universe()
    three = _decision_over(universe)
    five = _decision_over(universe, context=_ctx(maximum_options=5))
    assert (repo._decision_id(universe.candidate_set_id, three.decision)
            != repo._decision_id(universe.candidate_set_id, five.decision))

    async with sessions() as s:
        await repo.save(s, three)
        await repo.save(s, five)
        await s.commit()
    async with sessions() as s:
        rows = (await s.execute(select(
            CandidateSelectionDecisionRow.maximum_options))).scalars().all()
    assert sorted(rows) == [3, 5]


@pytest.mark.asyncio
async def test_the_same_conditions_replay_rather_than_duplicate(sessions,
                                                                user):
    universe = _universe()
    async with sessions() as s:
        await repo.save(s, _decision_over(universe))
        await repo.save(s, _decision_over(universe))
        await s.commit()
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(
            CandidateSelectionDecisionRow))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(
            CandidateExclusionRow))).scalar() == 1


@pytest.mark.asyncio
async def test_the_same_conditions_selecting_differently_fails_loudly(
        sessions, user):
    """The selector is meant to be reproducible from set + policy + context.
    If it is not, the stored record no longer explains the screen."""
    universe = _universe()
    async with sessions() as s:
        await repo.save(s, _decision_over(universe))
        await s.commit()
    async with sessions() as s:
        other = CandidateDecisionRecord(
            candidate_set=universe,
            decision=CandidateSelectionDecision(
                candidate_set_id=universe.candidate_set_id,
                selection_policy_version="sel_v1", context=_ctx(),
                selected_candidate_ids=("c1",),
                exclusions=(CandidateExclusion(
                    candidate_id="c2",
                    reason=ExclusionReason.SEMANTIC_DUPLICATE),
                    CandidateExclusion(
                        candidate_id="c3",
                        reason=ExclusionReason.SELECTION_CAP))))
        with pytest.raises(repo.DeterminismViolation, match="now decides"):
            await repo.save(s, other)


# ── 3b.2 — membership enforced by the DATABASE, not only the aggregate ──────

@pytest.mark.asyncio
async def test_a_foreign_candidate_cannot_be_excluded_or_presented(sessions,
                                                                   user):
    """THE AGGREGATE IS NOT THE ONLY WRITER.

    A migration, a script, or a future write path does not go through the
    dataclass. An exclusion or an option naming a candidate from another set —
    or from no set — makes the partition arithmetic wrong wherever it is read,
    so the database refuses it too.
    """
    from sqlalchemy.exc import IntegrityError

    async with sessions() as s:
        await repo.save(s, _decision_over(_universe()))
        await s.commit()

    async with sessions() as s:
        decision_id = (await s.execute(
            select(CandidateSelectionDecisionRow.decision_id))).scalars().first()
        s.add(CandidateExclusionRow(decision_id=decision_id,
                                    candidate_set_id="cs_somewhere_else",
                                    candidate_id="c1", reason="selection_cap"))
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()

    async with sessions() as s:
        decision_id = (await s.execute(
            select(CandidateSelectionDecisionRow.decision_id))).scalars().first()
        s.add(PresentedOptionRow(
            decision_id=decision_id, candidate_set_id="cs_test",
            option_id="opt_ghost", candidate_id="c_nonexistent",
            interaction_revision=0, selected_position=9,
            rendered_label="ghost", renderer_contract_version="labels_v1"))
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()


# ── 3b.2 — one durable authority for evidence ──────────────────────────────

@pytest.mark.asyncio
async def test_replay_and_analytics_read_the_same_evidence(sessions, user):
    """P1. TWO COPIES MEANT TWO TRUTHS.

    The candidate payload embedded its evidence AND every record was written
    to `candidate_evidence_records`; replay read the first and the funnel
    grouped the second. They could disagree — the system would behave
    correctly while reporting the wrong provenance, which is worse than
    reporting nothing.

    The evidence rows are now the sole authority, and the payload carries no
    copy to drift from.
    """
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()

    async with sessions() as s:
        payloads = (await s.execute(select(CandidateRow.payload))).scalars().all()
        assert all("evidence" not in p for p in payloads), (
            "the candidate payload still carries a second copy of evidence")

        record = await repo.load(s, "cs_test", user_id=USER_ID)
        replayed = sorted(e.source_type.value
                          for c in record.candidate_set.candidates
                          for e in c.evidence)
        counted = (await s.execute(
            select(CandidateEvidenceRow.source_type))).scalars().all()
    assert replayed == sorted(counted), (
        "replay and the funnel disagree about where candidates came from")


@pytest.mark.asyncio
async def test_evidence_survives_the_round_trip_intact(sessions, user):
    """Rebuilt from rows, the candidates must still satisfy every contract
    gate — including that the evidence produces the offered quantity."""
    async with sessions() as s:
        await repo.save(s, _record())
        await s.commit()
    async with sessions() as s:
        back = await repo.load(s, "cs_test", user_id=USER_ID)

    history = back.candidate_set.candidate("c2")
    assert history.evidence[0].source.record_version
    assert history.evidence[0].observed_quantity.grams == history.quantity.grams
    assert history.authorizes_assumption(back.candidate_set.context)
    ontology = back.candidate_set.candidate("c1")
    assert not ontology.authorizes_assumption(back.candidate_set.context)


# ── 3b.3 — replay is bound to the exact decision, not to the universe ───────

@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.asyncio
async def test_each_decision_reloads_itself_whatever_the_insertion_order(
        sessions, user, reverse):
    """P0. ALLOWING SEVERAL DECISIONS BROKE THE READ PATH.

    `load(candidate_set_id)` ran `.first()` over an unordered query, so once a
    universe held a Telegram decision and an iOS one, replay returned whichever
    row the database produced. That is the same failure as regenerating: a
    true statement about the system and a false one about this turn.

    Parameterised on insertion order because the defect was invisible in one
    direction — the first write happened to be the one wanted.
    """
    universe = _universe()
    telegram = _decision_over(universe)
    ios = _decision_over(universe,
                         context=_ctx(surface=SelectionSurface.ID_ADDRESSED))
    writes = [ios, telegram] if reverse else [telegram, ios]
    async with sessions() as s:
        for record in writes:
            await repo.save(s, record)
        await s.commit()

    async with sessions() as s:
        for record, want in ((telegram, SelectionSurface.LABEL_TEXT),
                             (ios, SelectionSurface.ID_ADDRESSED)):
            back = await repo.load_by_decision_id(
                s, repo.decision_id_for(record), user_id=USER_ID)
            assert back is not None
            assert back.decision.context.surface is want
            assert back.candidate_set.candidate_ids == {"c1", "c2", "c3"}


@pytest.mark.asyncio
async def test_the_operation_records_which_question_it_asked(sessions, user):
    """END TO END. The answer turn must be able to name the question it is
    answering rather than infer it from the universe."""
    from core import b1_quantity_operation as b1
    from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
    from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                          StagedFoodItem)

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
            turn_id="t_decision", client_capable=True)
        await s.commit()
    assert ask is not None

    async with sessions() as s:
        owned = await b1.owning(s, await s.get(User, USER_ID))
        assert owned is not None
        assert owned.decision_id, "the operation did not record its decision"
        replayed = await repo.load_by_decision_id(
            s, owned.decision_id, user_id=USER_ID)
    assert replayed is not None
    assert {p.option_id for p in replayed.presented} == {
        o.option_id for o in ask.interaction.groups[0].fields[0].options}


# ── 3b.3 — the WHOLE decision, and the WHOLE row, must match on replay ──────

@pytest.mark.asyncio
async def test_a_changed_exclusion_reason_fails_loudly(sessions, user):
    """P0. COMPARING THE WINNERS WAS NOT COMPARING THE DECISION.

    Same options, different explanation of why the rest were dropped: the
    write was silently ignored, so the caller believed one reason and the
    record held another. A decision whose explanation can drift is not
    evidence of anything.
    """
    universe = _universe()
    async with sessions() as s:
        await repo.save(s, _decision_over(universe))
        await s.commit()

    changed = CandidateDecisionRecord(
        candidate_set=universe,
        decision=CandidateSelectionDecision(
            candidate_set_id=universe.candidate_set_id,
            selection_policy_version="sel_v1", context=_ctx(),
            selected_candidate_ids=("c2", "c1"),
            exclusions=(CandidateExclusion(
                candidate_id="c3",
                reason=ExclusionReason.SEMANTIC_DUPLICATE),)))
    async with sessions() as s:
        with pytest.raises(repo.DeterminismViolation, match="now decides"):
            await repo.save(s, changed)


@pytest.mark.parametrize("label,mutate", [
    ("a different label", {"rendered_label": "8 oz"}),
    ("a different candidate binding", {"candidate_id": "c3"}),
    ("a different position", {"selected_position": 7}),
    ("a different revision", {"interaction_revision": 4}),
])
@pytest.mark.asyncio
async def test_a_changed_presented_row_fails_loudly(sessions, user, label,
                                                    mutate):
    """P0. COMPARING OPTION IDS WAS NOT COMPARING THE ROW.

    `6 oz` becoming `8 oz` under the same option id was accepted and dropped,
    so the stored row and the row the caller believed it wrote diverged with
    no error — exactly the replay contradiction this table exists to detect.
    """
    universe = _universe()
    async with sessions() as s:
        await repo.save(s, _decision_over(universe))
        await s.commit()

    base = _decision_over(universe)
    first = base.presented[0]
    fields = dict(option_id=first.option_id, candidate_id=first.candidate_id,
                  candidate_set_id=first.candidate_set_id,
                  interaction_revision=first.interaction_revision,
                  selected_position=first.selected_position,
                  rendered_label=first.rendered_label,
                  renderer_contract_version=first.renderer_contract_version)
    fields.update(mutate)

    # BYPASSING THE AGGREGATE ON PURPOSE. Three of these four mutations are
    # refused by `CandidateDecisionRecord` itself, which is correct — but the
    # aggregate is not the only writer, and the directive requires the check
    # at BOTH boundaries. This hands the repository a row the aggregate would
    # never have built, exactly as a migration or a future write path could.
    class _Bypass:
        candidate_set = universe
        decision = base.decision
        presented = (PresentedCandidateOption(**fields), base.presented[1])

    async with sessions() as s:
        with pytest.raises(repo.DeterminismViolation,
                           match="now presenting"):
            await repo.ensure_presented_options(
                s, _Bypass(), decision_id=repo.decision_id_for(base))


@pytest.mark.asyncio
async def test_the_complete_unchanged_decision_replays_idempotently(sessions,
                                                                    user):
    universe = _universe()
    async with sessions() as s:
        for _ in range(3):
            await repo.save(s, _decision_over(universe))
        await s.commit()
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(
            CandidateSelectionDecisionRow))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(
            PresentedOptionRow))).scalar() == 2
        assert (await s.execute(select(func.count()).select_from(
            CandidateExclusionRow))).scalar() == 1


# ── 3b.3 — concurrency at all three boundaries ─────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_identical_decisions_create_exactly_one(sessions,
                                                                 user):
    """Now that idempotency is split three ways, each boundary races
    separately. The database arbitrates; the repository must lose cleanly
    rather than leaving a half-written record behind."""
    universe = _universe()

    async def _attempt():
        async with sessions() as s:
            try:
                await repo.save(s, _decision_over(universe))
                await s.commit()
                return "wrote"
            except Exception:
                await s.rollback()
                return "lost"

    outcomes = await asyncio.gather(*(_attempt() for _ in range(3)),
                                    return_exceptions=True)
    assert any(o == "wrote" for o in outcomes), outcomes
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(
            CandidateSetRow))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(
            CandidateSelectionDecisionRow))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(
            PresentedOptionRow))).scalar() == 2


@pytest.mark.asyncio
async def test_concurrent_distinct_decisions_over_one_set_both_persist(
        sessions, user):
    """The set is write-once and the decisions are not, so a race between two
    LEGITIMATELY different decisions must end with both stored."""
    universe = _universe()
    records = [_decision_over(universe),
               _decision_over(universe,
                              context=_ctx(surface=SelectionSurface.ID_ADDRESSED))]

    async def _attempt(record):
        last = None
        for attempt in range(6):
            async with sessions() as s:
                try:
                    await repo.save(s, record)
                    await s.commit()
                    return "wrote"
                except Exception as exc:      # noqa: BLE001
                    last = exc
                    await s.rollback()
            # SQLite serialises writers with a file lock, so a loser must back
            # off rather than spin straight into the same lock. Postgres does
            # not need this; the retry shape is the same either way.
            await asyncio.sleep(0.05 * (attempt + 1))
        return f"lost: {type(last).__name__}: {last}"

    outcomes = await asyncio.gather(*(_attempt(r) for r in records))
    assert outcomes == ["wrote", "wrote"], outcomes
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(
            CandidateSetRow))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(
            CandidateSelectionDecisionRow))).scalar() == 2


@pytest.mark.asyncio
async def test_replay_never_runs_the_generator_or_the_selector(sessions, user,
                                                               monkeypatch):
    """If either runs during replay, replay is a second opinion from a system
    that may have changed — not a record of what happened."""
    from skills.nutrition import quantity_clarification as qc

    async with sessions() as s:
        await repo.save(s, _decision_over(_universe()))
        await s.commit()

    async def _boom(*a, **k):
        raise AssertionError("the generator ran during replay")

    def _boom_sync(*a, **k):
        raise AssertionError("the selector ran during replay")

    monkeypatch.setattr(qc, "generate", _boom)
    monkeypatch.setattr(qc, "reduce_universe", _boom_sync)
    async with sessions() as s:
        back = await repo.load(s, "cs_test", user_id=USER_ID)
    assert back is not None and back.candidate_set.candidates
