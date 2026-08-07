"""B-1.9 commit 7 — the integration proof, joined end to end.

The three corpora that came before this each prove one half of the slice, and
all three PREDATE the durable candidate universe:

    test_a_conversation_across_turns   routing, ownership, replay, expiry
    test_b1b2_sequence_corpus          restart, failure, unrelated meals
    test_b1b1_system_matrix            answer routes, repricing, telemetry

Not one of them joins a COMMITTED MEAL back to the CANDIDATE ROW that
justified it. That join is what step 7 exists to close, because every link is
individually proven and the chain has never been walked in one piece:

    raw message
      -> operation          which question was asked, and stored
      -> candidate set      every candidate generated, with its evidence
      -> decision           which were offered, and why not the rest
      -> presented option   the exact chip, its label, its position
      -> the tap            resolved by id, never by label
      -> patch              the typed quantity
      -> nutrition          repriced from the ANSWER, not the ask
      -> card + totals      what the user is shown and what the day says
      -> telemetry          route, modality, policy

REAL POSTGRES AND REAL ENRICHMENT where the environment supplies them; the
shared harness otherwise. A link asserted against a stub is a link asserted
against our own imagination of it.
"""
import json

import pytest
from sqlalchemy import func, select

from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say, operations, commits, vague, B1_ELIGIBLE,
)
from tests.test_b1b1_system_matrix import _ask, density  # noqa: F401


async def _universe_rows():
    """Everything the durable universe holds, read straight from the tables."""
    import db.database as D
    from db.models import (CandidateEvidenceRow, CandidateExclusionRow,
                           CandidateRow, CandidateSelectionDecisionRow,
                           CandidateSetRow, PresentedOptionRow)

    async with D.AsyncSessionLocal() as s:
        out = {}
        for name, model in (("sets", CandidateSetRow),
                            ("candidates", CandidateRow),
                            ("evidence", CandidateEvidenceRow),
                            ("decisions", CandidateSelectionDecisionRow),
                            ("exclusions", CandidateExclusionRow),
                            ("presented", PresentedOptionRow)):
            out[name] = list(
                (await s.execute(select(model).order_by(model.id))).scalars())
        return out


async def _replay(user_id):
    """The record as the ANSWER TURN would load it: by decision id."""
    import db.database as D
    from core import b1_quantity_operation as b1
    from core import candidate_repository as repo
    from db.models import User

    async with D.AsyncSessionLocal() as s:
        owned = await b1.owning(s, await s.get(User, user_id))
        if owned is None or not owned.decision_id:
            return None, None
        return owned, await repo.load_for_replay(
            s, decision_id=owned.decision_id, user_id=user_id)


@pytest.mark.asyncio
async def test_the_chain_from_a_raw_message_to_a_committed_meal_is_unbroken(
        edges, seeded, b1_live, density):
    """EVERY LINK, IN ONE PIECE.

    Each of these is proven somewhere already. None of them is proven to
    connect: the option the user tapped has never been shown to be the option
    a persisted candidate produced, nor the committed grams shown to be that
    candidate's own quantity.
    """
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)

    owned, record = await _replay(user)
    assert owned is not None, "no operation owned the turn"
    assert record is not None, "the operation named no persisted decision"

    # ── the universe exists, in full ────────────────────────────────────────
    tables = await _universe_rows()
    assert len(tables["sets"]) == 1
    assert tables["candidates"], "no candidate rows"
    assert tables["evidence"], "candidates were stored without their evidence"
    assert len(tables["decisions"]) == 1
    assert tables["presented"], "nothing was recorded as shown"

    stored_set = tables["sets"][0]
    assert stored_set.user_id == user
    assert stored_set.operation_id == owned.operation_id
    assert stored_set.domain == "food"
    assert stored_set.generation_input_fingerprint

    # ── the row shown IS the row recorded ───────────────────────────────────
    payload = json.loads(owned.row.canonical_payload)
    shown = payload["interaction"]["groups"][0]["fields"][0]["options"]
    assert [o["option_id"] for o in shown] == [
        p.option_id for p in sorted(tables["presented"],
                                    key=lambda p: p.selected_position)]
    assert [o["label"] for o in shown] == [
        p.rendered_label for p in sorted(tables["presented"],
                                         key=lambda p: p.selected_position)]

    # ── nothing generated was lost ──────────────────────────────────────────
    generated = {c.candidate_id for c in tables["candidates"]}
    decided = set(tables["decisions"][0].selected_candidate_ids or ())
    decided |= {x.candidate_id for x in tables["exclusions"]}
    assert generated == decided, (
        f"a candidate vanished between generation and observation: "
        f"{sorted(generated ^ decided)}")

    # ── the tap, resolved by id ─────────────────────────────────────────────
    tapped = sorted(tables["presented"],
                    key=lambda p: p.selected_position)[0]
    candidate = record.option_for(tapped.option_id)
    assert candidate is not None, "the shown option resolved to no candidate"
    assert candidate.evidence, "the candidate behind a chip carries no reason"
    offered_grams = candidate.quantity.grams

    before = len(await commits(user))
    await say(user, tapped.rendered_label)
    after = await commits(user)
    assert len(after) == before + 1, "the tap did not commit exactly one meal"

    # ── the committed meal IS that candidate's quantity, repriced ───────────
    import db.database as D
    from db.models import FoodEntry
    async with D.AsyncSessionLocal() as s:
        entry = (await s.execute(
            select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    assert entry is not None
    # THE ANSWER PRICED THE MEAL, not the ask. With the fixed 2 cal/g density,
    # a stale ask-time figure cannot survive this equality.
    assert abs(float(entry.calories)
               - float(offered_grams) * density["cal_per_g"]) < 1.0, (
        f"{entry.calories} cal for {offered_grams} g is not the answered "
        f"quantity repriced")
    assert abs(float(entry.protein)
               - float(offered_grams) * density["protein_per_g"]) < 0.5

    # ── telemetry names the route that did it ───────────────────────────────
    from tests.test_b1b1_system_matrix import _observation
    seen = await _observation(user)
    assert seen is not None and seen.outcome == "applied"
    assert seen.modality, "the answer route declared no modality"
    assert seen.operation_id == owned.operation_id


@pytest.mark.asyncio
async def test_the_universe_survives_a_restart_between_the_turns(
        app_db, edges, seeded, b1_live, density):
    """The ask and the answer are different processes in production. Nothing
    that explains the question may live only in memory.

    THE POOL IS DROPPED ONLY WHERE DROPPING IT MEANS SOMETHING. On Postgres,
    `dispose()` closes every connection exactly as a deploy does. On the
    in-memory SQLite harness it would destroy the database itself, so there
    the restart is simulated by discarding every session and re-materialising
    from rows — which is the property under test either way.

    An earlier version disposed `D.engine`, the module-level engine the
    harness does not bind to. It passed while simulating nothing.
    """
    import db.database as D

    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    owned, _record = await _replay(user)
    decision_id = owned.decision_id
    assert decision_id

    if app_db.dialect.name == "postgresql":
        await app_db.dispose()

    from core import candidate_repository as repo
    async with D.AsyncSessionLocal() as s:
        s.expunge_all()
        reloaded = await repo.load_for_replay(s, decision_id=decision_id,
                                              user_id=user)
    assert reloaded is not None
    assert reloaded.candidate_set.candidates
    assert reloaded.presented, "the row shown did not survive the restart"

    before = len(await commits(user))
    await say(user, reloaded.presented[0].rendered_label)
    assert len(await commits(user)) == before + 1


@pytest.mark.asyncio
async def test_an_unrelated_meal_while_awaiting_does_not_touch_the_universe(
        edges, seeded, b1_live, density):
    """The measured data loss: a question in flight consumed the next meal as
    its answer. The universe must not gain a decision it never made, and the
    open question must still be answerable."""
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    first = await _universe_rows()

    edges.plans.append({"action": "log", "points": [],
                        "items": [], "ready": [
                            {"food": "Black coffee", "quantity": "1 cup",
                             "calories": 5}]})
    await say(user, "also a black coffee")

    second = await _universe_rows()
    assert len(second["decisions"]) == len(first["decisions"]), (
        "an unrelated meal produced a selection decision")
    assert len(second["presented"]) == len(first["presented"])

    # And the original question is still answerable.
    owned, record = await _replay(user)
    assert record is not None
    before = len(await commits(user))
    await say(user, record.presented[0].rendered_label)
    assert len(await commits(user)) == before + 1


@pytest.mark.asyncio
async def test_a_duplicate_tap_replays_without_a_second_universe(
        edges, seeded, b1_live, density):
    """Transport retries and double taps are ordinary. Neither may mint a
    second decision over the same question, nor a second meal."""
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    _owned, record = await _replay(user)
    label = record.presented[0].rendered_label

    before = len(await commits(user))
    await say(user, label)
    await say(user, label)

    assert len(await commits(user)) == before + 1, "a replay wrote twice"
    tables = await _universe_rows()
    assert len(tables["sets"]) == 1
    assert len(tables["decisions"]) == 1


@pytest.mark.asyncio
async def test_a_foreign_or_stale_answer_leaves_the_universe_alone(
        edges, seeded, b1_live, density):
    """A tap from a stale screen is our bug, not the user's — it must not
    patch whatever looks closest, and must not alter the record of what was
    offered."""
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    before = await _universe_rows()

    import db.database as D
    from core import b1_answer_turn
    from db.models import User
    async with D.AsyncSessionLocal() as s:
        out = await b1_answer_turn.handle(
            s, user=await s.get(User, user), message="",
            option_id="opt_not_a_candidate",
            field_id=before["presented"][0].option_id, revision=0,
            source_turn_id="t_foreign")
    assert out is None or not out.applied

    after = await _universe_rows()
    assert {k: len(v) for k, v in after.items()} == {
        k: len(v) for k, v in before.items()}
    assert len(await commits(user)) == 0


@pytest.mark.asyncio
async def test_the_analysis_can_answer_why_each_candidate_was_not_shown(
        edges, seeded, b1_live, density):
    """THE POINT OF THE WHOLE UNIVERSE, asked of a real production turn.

    For every candidate generated on this ask, exactly one answer exists, and
    it comes from stored rows without rerunning anything.
    """
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    owned, _record = await _replay(user)

    import db.database as D
    from core import candidate_repository as repo
    tables = await _universe_rows()
    async with D.AsyncSessionLocal() as s:
        answers = {}
        for row in tables["candidates"]:
            answers[row.candidate_id] = await repo.why_not(
                s, decision_id=owned.decision_id, user_id=user,
                candidate_id=row.candidate_id)
        assert await repo.why_not(
            s, decision_id=owned.decision_id, user_id=user,
            candidate_id="cand_never_generated") == "not_generated"

    assert answers, "no candidates to explain"
    assert all(v == "shown" or v.startswith("excluded:")
               for v in answers.values()), answers
    assert "unknown" not in set(answers.values())


@pytest.mark.asyncio
async def test_the_slice_reports_which_engine_it_proved_itself_on(app_db):
    """POSTGRES OR SQLITE, said out loud, READ OFF THE BOUND ENGINE.

    An integration claim is only as strong as the engine behind it, and a
    suite that silently ran on SQLite while the report said "production
    shaped" is the same instrument problem this slice keeps finding.

    IT CAUGHT ITSELF ON ITS FIRST RUN. The first version read
    `db.database.engine` — the module-level engine, which the harness does not
    bind to — and reported `sqlite` with `TEST_POSTGRES_URL` set. The claim
    "this ran on Postgres" would have been false while the reporter agreed
    with it.
    """
    import os

    import db.database as D

    dialect = app_db.dialect.name
    assert dialect in {"postgresql", "sqlite"}
    if os.getenv("TEST_POSTGRES_URL"):
        assert dialect == "postgresql", (
            "TEST_POSTGRES_URL is set but the harness bound SQLite — the "
            "Postgres claim would be false")
    bound = D.AsyncSessionLocal.kw.get("bind")
    assert bound is app_db, "sessions are not bound to the engine under test"
    print(f"\n  B-1.9 step 7 integration proof ran on: {dialect}")
