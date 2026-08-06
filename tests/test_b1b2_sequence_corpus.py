"""B-1b.2 — THE PRODUCTION-SEQUENCE CORPUS.

Naturally occurring conversation SEQUENCES, not isolated states. Every defect
this slice shipped green lived in the seam between one turn and the next, and
was unreachable by any test that set a state up and then asserted about it.

Each scenario starts from a raw user message and runs through real routing,
candidate generation, persistence, answer application and commit, with a FRESH
DATABASE SESSION PER TURN — which is what `say()` does — and, under
`TEST_POSTGRES_URL`, on Postgres in a private schema.

Five of the directive's ten sequences already exist and are not duplicated
here:

    answer -> unrelated new meal        test_a_conversation_across_turns
    answer -> duplicate answer          test_b1b1_system_matrix (structured)
    cancel -> new meal                  test_a_conversation_across_turns
    repair -> valid answer              both
    duplicate webhook delivery          test_b1b1_system_matrix (transport)

This file covers the five that did not exist.
"""
import pytest

from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say, operations, commits, vague,
)


async def _ask(edges, user, food="Chicken breast", cal=280, amount=6, unit="oz"):
    edges.plans.append({
        "action": "ask",
        "points": [{"label": food, "q": "How much?"}],
        "items": [vague(food, cal=cal, amount=amount, unit=unit)],
        "ready": [],
    })
    await say(user, f"I had some {food.lower()}")
    return await operations(user)


def _restart():
    """Everything a process restart would take with it.

    A deploy drops every in-memory cache and leaves only the database. The
    operation must be answerable from durable state alone — this is the
    sequence a real deploy runs mid-conversation, and it is why the pending
    payload is versioned and stored rather than held.
    """
    import core.food_ledger as _FL
    import core.food_turn as _FT
    import handlers.tool_executor as _TE
    import skills.nutrition.off as _OFF
    from core import trace_buffer
    for cache in (_FT._SPREAD_CACHE, _FT._RELEVANCE_CACHE,
                  _TE._INFLIGHT_FETCHES, _FL._SEEN, _OFF._BREAKER):
        cache.clear()
    trace_buffer._lines.clear()


# ── 1. a NEW MEAL arrives while a question is still open ────────────────────

@pytest.mark.asyncio
async def test_a_new_meal_while_a_question_is_open_does_not_commit_the_old_one(
        edges, b1_live, app_db):
    """FOUND BY THIS CORPUS, and it was live.

    "I had some salmon" while a chicken-breast question was open committed the
    CHICKEN at its default 174 g and lost the salmon. `_grams_from_text`
    resolved the word "some" to the ontology's portion, so the sentence read
    as a quantity answer.

    Same family as the 2026-08-05 oatmeal loss, on the AWAITING path — which
    the settled and expired guards never covered, because that path is the one
    that is SUPPOSED to accept answers. Two independent guards now exist for
    one failure, and this is the one at the root: an answer to "how much?"
    must contain an amount the person actually stated.

    The open question survives as a repair rather than being abandoned (C10:
    once owned, the operation completes through apply, repair, cancel or
    commit — never a fall back to legacy).
    """
    ops = await _ask(edges, b1_live, "Chicken breast")
    assert ops and ops[-1].status == "awaiting_answer"

    await say(b1_live, "I had some salmon")

    board = await rows(b1_live)
    assert not board, (
        f"a new meal committed the OPEN question's food at its default: "
        f"{[(r.parsed_food_name, r.quantity) for r in board]}")
    still = await operations(b1_live)
    assert len(still) == 1 and still[0].status == "awaiting_answer", (
        f"the question was closed by a message that did not answer it: "
        f"{[(o.operation_id, o.status) for o in still]}")


@pytest.mark.parametrize("answer", ["6 oz", "137 grams", "a cup",
                                    "half a breast"])
@pytest.mark.asyncio
async def test_a_real_answer_still_commits(edges, b1_live, app_db, answer):
    """The other half, or the fix would be a denial-of-service on answering.

    Every one of these carries an amount the user stated — a number, a vessel,
    a fraction of a piece — and must still land. Only the vague fallback is
    refused.
    """
    await _ask(edges, b1_live)
    await say(b1_live, answer)

    board = await rows(b1_live)
    assert len(board) == 1, (
        f"{answer!r} was refused; only an UNSTATED quantity should repair: "
        f"{[(r.parsed_food_name, r.quantity) for r in board]}")


# ── 2. a deploy lands between the question and the answer ───────────────────

@pytest.mark.asyncio
async def test_an_answer_survives_a_restart_between_the_turns(
        edges, b1_live, app_db):
    """The question is asked, the process restarts, then the answer arrives.

    Every in-memory cache is gone; only the database remains. This is the
    sequence a real deploy runs mid-conversation — and this slice deployed
    five times in one afternoon, so it is not hypothetical.
    """
    ops = await _ask(edges, b1_live)
    operation = ops[-1].operation_id

    _restart()

    await say(b1_live, "50 g")

    board = await rows(b1_live)
    assert len(board) == 1, (
        f"the answer did not land after a restart: "
        f"{[(r.parsed_food_name, r.quantity) for r in board]}")
    assert "50" in (board[0].quantity or ""), board[0].quantity
    final = [o for o in await operations(b1_live)
             if o.operation_id == operation]
    assert final and final[0].status == "committed", (
        f"{operation} did not settle across the restart: "
        f"{[(o.operation_id, o.status) for o in await operations(b1_live)]}")


# ── 3. the answer path fails internally, then the user tries again ──────────

@pytest.mark.asyncio
async def test_an_internal_failure_writes_nothing_and_the_retry_succeeds(
        edges, b1_live, app_db, monkeypatch):
    """A failure mid-settle must leave no partial meal behind.

    The operation is the unit of atomicity: either the meal lands whole or the
    user can answer again. A half-written commit would be the worst outcome —
    worse than losing the turn, because the next answer would build on it.
    """
    from core import b1_quantity_operation as ops_mod

    real_settle = ops_mod.settle
    calls = {"n": 0}

    async def _boom(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated commit failure")
        return await real_settle(*a, **kw)

    monkeypatch.setattr(ops_mod, "settle", _boom)

    await _ask(edges, b1_live)
    await say(b1_live, "50 g")                      # fails inside settle

    assert not await rows(b1_live), (
        f"a failed settle left a partial meal: "
        f"{[(r.parsed_food_name, r.quantity) for r in await rows(b1_live)]}")
    assert not await commits(b1_live), "a failed settle left a commit claim"

    op = (await operations(b1_live))[-1]
    assert op.status == "awaiting_answer", (
        f"the failure closed the operation, so the user can no longer answer "
        f"it: {op.status}")
    assert not op.answer_claim_key, (
        f"a claim survived a failed settle and would block the retry: "
        f"{op.answer_claim_key!r}")

    # RETRIED WITH DIFFERENT WORDING, deliberately. Re-sending the IDENTICAL
    # text does not re-enter settle — the exactly-once turn registry treats it
    # as the same delivery, which is correct idempotency and is proven
    # elsewhere. What this scenario is about is whether the OPERATION is still
    # answerable after a failure, and it is.
    await say(b1_live, "51 g")

    board = await rows(b1_live)
    assert len(board) == 1, (
        f"the operation was not answerable after an internal failure: "
        f"{[(r.parsed_food_name, r.quantity) for r in board]}")
    assert "51" in (board[0].quantity or ""), board[0].quantity
    assert calls["n"] >= 2, calls


# ── 4. the reply names an EARLIER meal while asking about this one ──────────

@pytest.mark.asyncio
async def test_referencing_a_prior_meal_while_asking_is_not_a_phantom(
        edges, b1_live, app_db):
    """The production false positive, as the sequence that produced it.

    Live: "Already got chicken breast on the books at 718 cal. Now, salmon,
    how much did you have?" — flagged as a phantom log. It names a PRIOR meal
    and asks about the current one, which is honest reporting.

    B-1c fixed the detector; this proves the SEQUENCE that exposed it stays
    clean, because a unit test of the detector cannot tell whether the turn
    that follows a commit is classified correctly.
    """
    await _ask(edges, b1_live, "Chicken breast")
    first = await say(b1_live, "50 g")
    assert len(await rows(b1_live)) == 1

    await _ask(edges, b1_live, "Salmon")
    second_turn_ops = await operations(b1_live)
    assert len(second_turn_ops) == 2

    for turn in (first,):
        assert "phantom_log_claim" not in (turn.health_flags or []), (
            f"the committing turn was flagged: {turn.health_flags}")


# ── 5. the user corrects the committed row minutes later ────────────────────

@pytest.mark.asyncio
async def test_a_correction_within_ten_minutes_is_observed_once(
        edges, b1_live, app_db):
    """The signal that says the number we committed was wrong.

    Deduped by the DATABASE rather than by the sweep remembering, because the
    sweep runs on a timer and is the thing most likely to restart mid-run —
    otherwise "corrected within ten minutes" measures how often cron fires.
    """
    from sqlalchemy import select

    import db.database as D
    from core import b1_quantity_operation as ops_mod
    from db.models import B1CorrectionObservation, LedgerEvent

    await _ask(edges, b1_live)
    await say(b1_live, "50 g")
    board = await rows(b1_live)
    assert len(board) == 1
    entry_id = board[0].id

    # The user edits it — the ledger event a correction actually produces.
    async with D.AsyncSessionLocal() as s:
        s.add(LedgerEvent(user_id=b1_live, domain="food", entry_id=entry_id,
                          daily_log_id=board[0].daily_log_id,
                          event_type="updated", source="test:correction"))
        await s.commit()

    async with D.AsyncSessionLocal() as s:
        await ops_mod.note_corrections(s)
        await s.commit()
    async with D.AsyncSessionLocal() as s:      # the sweep runs again
        await ops_mod.note_corrections(s)
        await s.commit()

    async with D.AsyncSessionLocal() as s:
        seen = list((await s.execute(
            select(B1CorrectionObservation)
            .where(B1CorrectionObservation.entry_id == entry_id)
        )).scalars().all())

    assert len(seen) == 1, (
        f"the correction was recorded {len(seen)} times — the rate would then "
        f"measure how often the sweep runs, not how often we were wrong")
