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
from tests.test_a_conversation_across_turns import _structured  # noqa: F401
from tests.test_b1b1_system_matrix import _ask, density  # noqa: F401
from tests.test_b1b1_real_enrichment import real_lookups  # noqa: F401


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


async def _payload(user_id):
    """The interaction as STORED — the only evidence of what was offered."""
    ops = await operations(user_id)
    assert ops, "no operation to read"
    return json.loads(ops[-1].canonical_payload)


def _field_id_of(payload) -> str:
    """`field_id` lives on the OPTION, not the field: the field computes it as
    a property, so only options carry it across storage."""
    return payload["interaction"]["groups"][0]["fields"][0]["options"][0][
        "field_id"]


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

    # THE STRUCTURED BOUNDARY, not prose. `say(label)` exercises LABEL
    # SELECTION — a different route with a different modality — so answering
    # that way while the docstring claimed "tap by id" tested the one path
    # the iOS client will never use. Four ids, and the meaning comes from
    # storage.
    before = len(await commits(user))
    turn = await _structured(user,
                             field_id=_field_id_of(
                                 json.loads(owned.row.canonical_payload)),
                             option_id=tapped.option_id, revision=0,
                             message="")
    assert turn is not None and turn.applied, turn
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

    # ── the card the user is shown, off the committed result ────────────────
    from core import b1_answer_turn
    facts = b1_answer_turn.facts_for(turn)
    card = b1_answer_turn.card_for(facts)
    assert card is not None, "the committing turn rendered no card"
    shown = card["payload"]
    assert shown["entry_id"] == entry.id, (
        "the card names a different row than the one that was written")
    assert abs(float(shown["calories"]) - float(entry.calories)) < 1.0, (
        f"the card says {shown['calories']} cal and the row says "
        f"{entry.calories} — the user is shown a number nobody wrote")
    assert abs(float(shown["protein_g"]) - float(entry.protein)) < 1.0
    assert shown["estimated"] is False, (
        "a tapped option is the user's choice, not our guess")
    # THE SENTENCE BESIDE THE CARD is the same facts, said. Both come from one
    # `facts_for()` result, so "the card and the copy agree" is a shape rather
    # than a check — but the shape is only worth anything if the numbers in it
    # are the row's.
    copy = b1_answer_turn.copy_for(facts)
    assert str(int(round(float(entry.calories)))) in copy, (
        f"the reply {copy!r} does not state the {entry.calories} cal it wrote")
    assert str(int(round(float(entry.protein)))) in copy

    # ── and the day agrees with the row ─────────────────────────────────────
    board = await rows(user)
    assert sum(float(e.calories or 0) for e in board) == pytest.approx(
        float(entry.calories), abs=1.0), (
        "the day's total does not equal the single row that produced it")
    assert sum(float(e.protein or 0) for e in board) == pytest.approx(
        float(entry.protein), abs=0.5)

    # ── telemetry names the route that did it ───────────────────────────────
    from tests.test_b1b1_system_matrix import _observation
    seen = await _observation(user)
    assert seen is not None and seen.outcome == "applied"
    # THE ROUTE SAYS WHAT IT IS. `option_id` is the structured tap; anything
    # else here would mean the turn came in by a different door than the one
    # this test believes it used, and the "Other" rate is computed from this
    # field.
    assert seen.modality == "option_id", (
        f"a structured tap recorded modality {seen.modality!r}")
    assert seen.operation_id == owned.operation_id
    assert seen.user_id == user

    # ── FULL PROVENANCE ATTRIBUTION ─────────────────────────────────────────
    #
    # A tap is a SELECTION, not a statement: the user accepted a figure we
    # produced, and recording it as their own is the measured 2026-08-04
    # disclosure defect. Provenance is the only thing that keeps the
    # distinction once the answer applies.
    from core.semantics import Provenance
    assert turn.patch.provenance is Provenance.USER_SELECTED, (
        f"a tapped option recorded {turn.patch.provenance} — the user chose "
        f"from what we offered; they did not state it")
    assert turn.patch.quantity.grams == offered_grams, (
        "the patch carries a quantity the candidate did not name")

    # THE ROUTE THAT DECIDED, and the source it came from — both persisted,
    # neither inferred from prose.
    assert seen.selected_source in {"ontology", "user_history",
                                    "free_text", "none", "unknown_option"}, (
        seen.selected_source)
    evidence_sources = {e.source_type for e in tables["evidence"]}
    assert seen.selected_source in evidence_sources or not evidence_sources, (
        f"telemetry names source {seen.selected_source!r}, which no persisted "
        f"evidence record carries: {sorted(evidence_sources)}")
    # A PLAIN TAP NAMES NO POLICY. Stamping every row would make the field
    # mean "some policy ran" rather than "this policy decided".
    assert not seen.policy_version, (
        f"a structured tap attributed itself to policy "
        f"{seen.policy_version!r}, but nothing versioned decided it")


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

    # A MESSAGE THAT IS NOT AN ANSWER, while the question is open.
    await say(user, "I had some salmon too")

    second = await _universe_rows()
    assert len(second["decisions"]) == len(first["decisions"]), (
        "an unrelated meal produced a selection decision")
    assert len(second["presented"]) == len(first["presented"])

    # NOTHING COMMITTED UNDER THE OPEN QUESTION'S FOOD. This is the half that
    # actually cost users: a question in flight consumed the next meal AS ITS
    # ANSWER, committing chicken at its default and losing the oatmeal, with
    # "Logged" said out loud. An unrelated message is HELD — it repairs rather
    # than answering — so the board must still be empty here.
    board = await rows(user)
    assert not board, (
        f"a message that answered nothing committed a meal: "
        f"{[(r.parsed_food_name, r.quantity) for r in board]}")
    still = await operations(user)
    assert len(still) == 1 and still[-1].status == "awaiting_answer", (
        "the question was closed by a message that did not answer it")

    # THE LANE IS NOT STUCK EITHER. Answering releases it, and the meal that
    # arrived meanwhile can then be logged — "held" means deferred, not lost,
    # and a test that stopped at the refusal could not tell those apart.
    owned, record = await _replay(user)
    assert record is not None
    await say(user, record.presented[0].rendered_label)
    assert len(await rows(user)) == 1, "the answer did not commit its meal"

    # The next food reaches the lane on its own terms — a new operation of its
    # own, answered and committed — so nothing is stranded behind the settled
    # question.
    await _ask(edges, user, food="Oatmeal", cal=150)
    ops = await operations(user)
    assert len(ops) == 2, (
        f"the second food never got its own operation: "
        f"{[(o.operation_id, o.status) for o in ops]}")
    _owned2, record2 = await _replay(user)
    assert record2 is not None
    await say(user, record2.presented[0].rendered_label)
    after = await rows(user)
    assert len(after) == 2, (
        f"the lane never freed — {[e.parsed_food_name for e in after]}")
    assert {str(e.parsed_food_name) for e in after} == {"Chicken breast",
                                                        "Oatmeal"}


@pytest.mark.asyncio
async def test_the_same_transport_delivery_twice_writes_one_meal(
        edges, seeded, b1_live, density):
    """THE SAME MESSAGE ID, REDELIVERED. A transport retry, which is ordinary
    and must be caught before the answer turn ever runs."""
    import db.database as D
    from core import b1_answer_turn
    from db.queries import reload_user

    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    shown = sorted((await _universe_rows())["presented"],
                   key=lambda p: p.selected_position)[0]
    field_id = _field_id_of(await _payload(user))

    for _delivery in range(2):
        async with D.AsyncSessionLocal() as s:
            await b1_answer_turn.handle(
                s, user=await reload_user(s, user), field_id=field_id,
                option_id=shown.option_id, revision=0, message="",
                source_turn_id="telegram:the-same-message")
            await s.commit()

    assert len(await commits(user)) == 1, "a redelivery wrote a second meal"
    tables = await _universe_rows()
    assert len(tables["sets"]) == 1 and len(tables["decisions"]) == 1


@pytest.mark.asyncio
async def test_the_same_tap_under_two_transport_ids_writes_one_meal(
        edges, seeded, b1_live, density):
    """A DOUBLE TAP. Two genuinely different deliveries carrying the same
    option — transport dedup cannot catch this one, so the operation's own
    settled state has to."""
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    shown = sorted((await _universe_rows())["presented"],
                   key=lambda p: p.selected_position)[0]
    field_id = _field_id_of(await _payload(user))

    first = await _structured(user, field_id=field_id,
                              option_id=shown.option_id, revision=0,
                              message="")
    second = await _structured(user, field_id=field_id,
                               option_id=shown.option_id, revision=0,
                               message="")
    assert first.applied
    assert second is not None and second.reason == "replay", second
    assert len(await commits(user)) == 1, "a second tap wrote a second meal"

    tables = await _universe_rows()
    assert len(tables["sets"]) == 1 and len(tables["decisions"]) == 1


@pytest.mark.asyncio
async def test_a_repeated_label_after_settlement_replays(
        edges, seeded, b1_live, density):
    """The LABEL route, separately — a different modality with a different
    resolution path, and it must reach the same one-meal outcome."""
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    _owned, record = await _replay(user)
    label = record.presented[0].rendered_label

    await say(user, label)
    await say(user, label)
    assert len(await commits(user)) == 1


@pytest.mark.asyncio
async def test_a_valid_option_from_a_stale_revision_is_refused(
        edges, seeded, b1_live, density):
    """A REAL OPTION, AT THE WRONG REVISION. Distinct from a foreign id: this
    one exists, is ours, and would resolve — the only thing wrong with it is
    that the screen it came from has moved on. A stale tap is our bug, not the
    user's, so it must not patch whatever looks closest.

    The previous form of this gate sent a nonsense option id AND a field id in
    the wrong parameter AND the current revision, which proves only that an
    obviously malformed answer is rejected.
    """
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    before = await _universe_rows()
    shown = sorted(before["presented"], key=lambda p: p.selected_position)[0]
    field_id = _field_id_of(await _payload(user))

    out = await _structured(user, field_id=field_id,
                            option_id=shown.option_id, revision=99,
                            message="")
    assert out is None or not out.applied, out
    assert len(await commits(user)) == 0
    assert {k: len(v) for k, v in (await _universe_rows()).items()} == {
        k: len(v) for k, v in before.items()}

    # The SAME option at the RIGHT revision still works — so the refusal above
    # is the revision talking, not a broken option.
    good = await _structured(user, field_id=field_id,
                             option_id=shown.option_id, revision=0,
                             message="")
    assert good is not None and good.applied
    assert len(await commits(user)) == 1


@pytest.mark.asyncio
async def test_an_option_that_was_never_offered_is_refused(
        edges, seeded, b1_live, density):
    """FOREIGN, not stale. An id no candidate produced must resolve to
    nothing rather than to the nearest thing."""
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    before = await _universe_rows()
    field_id = _field_id_of(await _payload(user))

    out = await _structured(user, field_id=field_id,
                            option_id="opt_cand_never_generated", revision=0,
                            message="")
    assert out is None or not out.applied, out
    assert len(await commits(user)) == 0
    assert {k: len(v) for k, v in (await _universe_rows()).items()} == {
        k: len(v) for k, v in before.items()}


@pytest.mark.asyncio
async def test_an_answer_to_a_field_we_never_asked_about_is_refused(
        edges, seeded, b1_live, density):
    user = seeded
    await _ask(edges, user, food="Chicken breast", cal=280)
    shown = sorted((await _universe_rows())["presented"],
                   key=lambda p: p.selected_position)[0]

    out = await _structured(user, field_id="fld_from_another_operation",
                            option_id=shown.option_id, revision=0,
                            message="")
    assert out is None or not out.applied, out
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


# ── the same chain, with REAL enrichment ───────────────────────────────────

@pytest.mark.skipif(not __import__("os").getenv("USDA_API_KEY"),
                    reason="needs USDA_API_KEY — real enrichment is gated, "
                           "and a stubbed run reported as a live one is the "
                           "instrument problem this slice keeps finding")
@pytest.mark.asyncio
async def test_the_whole_chain_holds_with_live_enrichment(
        edges, seeded, b1_live, real_lookups):
    """DURABLE UNIVERSE **AND** REAL ENRICHMENT, IN ONE SEQUENCE.

    Both halves were proven — the candidate chain against a deterministic
    density fixture, live USDA against a separate suite that knows nothing
    about candidates. Neither proved that a candidate's own grams, priced by
    the real ladder, produce the row and the card the user sees. That is the
    join, and it is the one step 7 named and did not walk.

    ASSERTIONS ARE RELATIONAL. USDA's top hit moves; the invariants that must
    not are that the meal is priced FROM THE ANSWERED QUANTITY and that every
    downstream surface agrees with the row.
    """
    from tests.test_b1b1_real_enrichment import _ask as _real_ask

    user = seeded
    await _real_ask(edges, user, "Chicken breast")

    owned, record = await _replay(user)
    assert owned is not None and record is not None, (
        "live enrichment did not produce a durable universe")

    tables = await _universe_rows()
    assert tables["candidates"] and tables["evidence"]
    shown = sorted(tables["presented"], key=lambda p: p.selected_position)[0]
    candidate = record.option_for(shown.option_id)
    assert candidate is not None
    grams = float(candidate.quantity.grams)
    assert grams > 0

    turn = await _structured(user,
                             field_id=_field_id_of(await _payload(user)),
                             option_id=shown.option_id, revision=0,
                             message="")
    assert turn is not None and turn.applied, turn

    import db.database as D
    from db.models import FoodEntry
    async with D.AsyncSessionLocal() as s:
        entry = (await s.execute(
            select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()

    # PRICED FROM THE ANSWER. Real density is unknown, but chicken breast sits
    # in a wide, well-established band; a stale ask-time figure or a per-100g
    # number that never scaled would fall outside it.
    per_gram = float(entry.calories) / grams
    assert 0.8 <= per_gram <= 3.0, (
        f"{entry.calories} cal for {grams} g is {per_gram:.2f} cal/g — not a "
        f"plausible density for a real lookup, so the answered quantity did "
        f"not price this meal")
    assert float(entry.protein) > 0, "a real lookup returned no protein"

    from core import b1_answer_turn
    facts = b1_answer_turn.facts_for(turn)
    card = b1_answer_turn.card_for(facts)
    assert card["payload"]["entry_id"] == entry.id
    assert abs(float(card["payload"]["calories"])
               - float(entry.calories)) < 1.0

    board = await rows(user)
    assert sum(float(e.calories or 0) for e in board) == pytest.approx(
        float(entry.calories), abs=1.0)


@pytest.mark.asyncio
async def test_the_enrichment_gate_says_whether_it_ran(app_db):
    """NOT SEEN IS NOT NOT-TESTED — but a skip must be legible.

    The live-enrichment join above is gated on a key the local machine may not
    have. Saying so out loud is the difference between "we proved this" and
    "nothing objected".
    """
    import os

    live = bool(os.getenv("USDA_API_KEY"))
    print(f"\n  B-1.9 step 7 live-enrichment join: "
          f"{'RAN' if live else 'SKIPPED (no USDA_API_KEY)'}")
    assert True
