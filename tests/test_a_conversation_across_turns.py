"""A CONVERSATION, NOT A TURN — what happens after the question is answered.

WHY THIS EXISTS. On 2026-08-05 B-1 committed its first canonical meal in
production. Four hours later it ate two more:

    23:46  "I had some rice"    -> "Logged White rice, steamed, 64 cal"
    23:49  "Had some oatmeal"   -> "Logged White rice, steamed, 64 cal"

Neither was written. Both were reported as logged. A committed operation keeps
owning the user's food lane for `SETTLED_OWNERSHIP_MINUTES` so a late duplicate
tap REPLAYS instead of forming its own valid claim — correct, and necessary,
because settlement advances the revision. But `owning()` keys on the USER, not
on what the message SAYS, so every food message inside that window went into
`answer_from_text`, which parsed "some oatmeal" as a quantity.

204 B-1 tests were green. Every one of them ANSWERED the open question. Not one
sent an unrelated new meal afterwards. The bug lived in the seam between one
operation ending and the next thing a person says — and nothing in the suite
had ever crossed that seam, so the shape was unreachable by construction.

WHAT THIS FILE IS FOR. Multi-turn conversations on a CAPABLE channel, driven
below the transport, against a real schema. Production's B-1 channels are
Telegram and iMessage; they arrive by webhook, so nothing scriptable reaches
them and every gate below had to be checked by hand-sending messages on a
phone. That is the reason the defect reached a user instead of CI. It needs no
production access — it never did.

THE RULE THIS FILE KEEPS. **Script what the MODEL would say; let the real
pipeline decide everything else.** Eligibility, the ambiguity, the options and
the patches are derived by `derive_semantics` and the real B-1 producer. A
fixture that hands B-1 a pre-built ambiguity is exactly how two of this
slice's defects survived 152 green tests: `_ambiguity(field_name=...)` built
the shape I ASSUMED, so the assertion could not fail. Here, if B-1 declines to
engage, the test fails and that is a finding — not something to force.

Fixtures come from `test_a_full_day_of_food.py`, which already pins the four
outside edges (LLM, Tavily, USDA, Open Food Facts) and rebinds the app's
sessionmaker in place. Everything between is real.
"""
import itertools

import pytest

# Fixtures are reused, not reimplemented — one definition of "the outside
# edges are pinned" for the whole food lane. pytest resolves them from this
# module's namespace.
from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, edges, seeded, rows, turn, item,
)

#: Transport message ids, the way a real channel supplies them.
_MSG_IDS = itertools.count(9000)


async def say(user_id, text, *, platform=None):
    """One inbound message, carrying a DISTINCT transport message id.

    Production's turn id comes from the transport — `telegram:9132`,
    `telegram:9139` — and the operation id is derived from it. Without one,
    `run_chat_turn` falls back to hashing the message CONTENT, so a
    conversation that says the same thing twice collides on
    `pending_operations.operation_id` and raises a UNIQUE violation that
    cannot happen in production.

    That matters more than it looks. The tempting fix is to make the test send
    artificially varied text — which would hide the collision by ensuring the
    harness never exercises a shape production hits constantly (ask the same
    question about the same food twice in a day). Supplying the id instead
    keeps the harness production-shaped, which is the whole requirement.
    """
    import db.database as D
    from core.chat_service import run_chat_turn
    from db.queries import reload_user
    async with D.AsyncSessionLocal() as s:
        user = await reload_user(s, user_id)
        return await run_chat_turn(
            s, user, text, platform=platform or CAPABLE,
            schedule_background=False,
            client_msg_id=str(next(_MSG_IDS)))

#: The channel B-1 actually runs on. iOS is deliberately `client_incapable`
#: until B-1b, so driving this on "ios" would prove nothing — and that is
#: precisely the hole `scripts/b1_operation_probe.py` falls into: it posts to
#: `/api/v1/chat`, which sets PLATFORM="ios", so it cannot exercise B-1 at all.
CAPABLE = "telegram"


@pytest.fixture
def b1_live(monkeypatch, seeded):
    """B-1 enabled for exactly this user, the way production's first cohort was.

    Set AFTER `seeded` so the allowlist names the real generated id rather than
    a guess, and via the same env vars production reads — the gate is not
    stubbed, so a change to how the cohort is resolved fails here too.
    """
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(seeded))
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    monkeypatch.delenv("B1_QUANTITY_PERCENT", raising=False)
    return seeded


# ── Reading the operation, not the reply ──────────────────────────────────────

async def operations(user_id):
    """Every canonical operation for this user, oldest first."""
    import db.database as D
    from sqlalchemy import select
    from db.models import PendingOperation
    async with D.AsyncSessionLocal() as s:
        r = await s.execute(
            select(PendingOperation)
            .where(PendingOperation.user_id == user_id)
            .order_by(PendingOperation.id))
        return list(r.scalars().all())


async def commits(user_id):
    import db.database as D
    from sqlalchemy import select
    from db.models import MealCommit
    async with D.AsyncSessionLocal() as s:
        r = await s.execute(
            select(MealCommit).where(MealCommit.user_id == user_id))
        return list(r.scalars().all())


def vague(food, **kw):
    """One food whose QUANTITY the person did not state.

    The interpreter still proposes an amount — that is what it does, and the
    production payload for the operation that started this file carried
    `amount: 6, unit: "oz"` on a message that said only "some chicken breast".
    The pipeline's job is to notice the number is assumed rather than stated.
    We do not tell it that; we let it derive it.
    """
    return item(food, **kw)


async def ask_for(edges, user_id, message, plan):
    """One turn that should raise a B-1 quantity question. Returns the ops."""
    edges.plans.append(plan)
    await say(user_id, message, platform=CAPABLE)
    return await operations(user_id)


B1_ELIGIBLE = {
    "action": "ask",
    "points": [{"label": "Chicken breast", "q": "How much?"}],
    "items": [vague("Chicken breast", cal=280, amount=6, unit="oz")],
    "ready": [],
}


# ── The gate this file exists for ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b1_engages_at_all_on_a_capable_channel(edges, b1_live):
    """Nothing below this file means anything if B-1 never takes the turn.

    First, because a conversation test that silently runs on the LEGACY lane
    would pass for the wrong reason and report coverage it does not have.
    Second, because "B-1 did not engage" was the actual state of production for
    five deploys while three diagnostics reported nothing at all — so the
    engagement itself is worth an assertion that fails loudly.
    """
    ops = await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    assert ops, (
        "B-1 did not take ownership of an eligible turn on a capable channel. "
        "Either the eligibility predicate no longer matches what "
        "derive_semantics produces, or the rollout gate did not admit the "
        "user. This is the state production was in for five deploys.")
    assert ops[-1].domain == "food"


@pytest.mark.asyncio
async def test_a_new_meal_after_settlement_is_logged_not_replayed(edges, b1_live):
    """THE ONE. Ask, answer, commit — then say something else entirely.

    In production this replied "Logged White rice, steamed, 64 cal" to a message
    about oatmeal and wrote nothing at all. The settled operation must decline a
    message that is not addressed to its closed question, and the new report
    must reach the lane on its own terms.
    """
    ops = await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    assert ops, "no operation to settle — see test_b1_engages_at_all"
    first = ops[-1].operation_id

    await say(b1_live, "6 oz", platform=CAPABLE)
    after_answer = await rows(b1_live)
    assert len(after_answer) == 1, (
        f"the answer should have committed exactly one meal, got "
        f"{[r.parsed_food_name for r in after_answer]}")

    # The next thing a person says. Nothing to do with the closed question.
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Oatmeal", "q": "How much?"}],
        "items": [vague("Oatmeal", cal=150, amount=1, unit="cup cooked")],
        "ready": [],
    })
    await say(b1_live, "Had some oatmeal", platform=CAPABLE)

    board = await rows(b1_live)
    assert len(board) == 1, (
        "a new report was swallowed as a replay of the settled operation — "
        "this is the production data loss: the user is told the meal is "
        f"logged and no row is written. board={[r.parsed_food_name for r in board]}")

    ops2 = await operations(b1_live)
    assert len(ops2) == 2, (
        f"the new meal must open its OWN operation, not reuse the settled "
        f"one. operations={[o.operation_id for o in ops2]}")
    assert ops2[-1].operation_id != first

    await say(b1_live, "45 g", platform=CAPABLE)
    final = await rows(b1_live)
    names = [r.parsed_food_name for r in final]
    assert len(final) == 2, f"both meals must be on the board, got {names}"
    assert any("atmeal" in (n or "") for n in names), (
        f"the oatmeal never landed: {names}")


@pytest.mark.asyncio
async def test_the_second_operation_commits_canonically_too(edges, b1_live):
    """One operation working is not a lane working.

    Until 2026-08-06 exactly ONE canonical operation had ever existed in
    production, so "a second operation opens and commits after a first settles"
    was untested everywhere. Each must own its own commit at its own revision.
    """
    await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    await say(b1_live, "6 oz", platform=CAPABLE)
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Oatmeal", "q": "How much?"}],
        "items": [vague("Oatmeal", cal=150, amount=1, unit="cup cooked")],
        "ready": [],
    })
    await say(b1_live, "Had some oatmeal", platform=CAPABLE)
    await say(b1_live, "45 g", platform=CAPABLE)

    ops = await operations(b1_live)
    assert len(ops) == 2, [o.operation_id for o in ops]
    assert all(str(o.status) .endswith("committed") or o.status == "committed"
               for o in ops), [(o.operation_id, o.status) for o in ops]

    mc = await commits(b1_live)
    by_op = {}
    for c in mc:
        by_op.setdefault(c.operation_id, []).append(c)
    assert len(by_op) == 2, f"expected one commit per operation, got {by_op}"
    for op_id, rows_ in by_op.items():
        assert len(rows_) == 1, (
            f"{op_id} committed {len(rows_)} times — a second valid claim is "
            f"how a duplicate meal is written")


@pytest.mark.asyncio
async def test_the_exact_option_label_after_settlement_still_replays(edges, b1_live):
    """The half of the window that must SURVIVE the fix.

    Narrowing settled ownership is only correct if the case it exists for still
    works: a late duplicate answer must replay the stored result. Settlement
    advances the revision, so without this the second pass forms its own valid
    claim and writes the meal twice. This is the guard's positive branch, and
    it is the reason the fix keys on "is this addressed to the closed
    question?" rather than on time alone.
    """
    await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    await say(b1_live, "6 oz", platform=CAPABLE)
    assert len(await rows(b1_live)) == 1

    await say(b1_live, "6 oz", platform=CAPABLE)     # the same answer again
    board = await rows(b1_live)
    assert len(board) == 1, (
        f"a duplicate answer wrote a second meal: "
        f"{[(r.id, r.parsed_food_name) for r in board]}")

    assert len(await operations(b1_live)) == 1, (
        "a duplicate answer must replay, not open a new operation")


@pytest.mark.asyncio
async def test_the_lane_still_works_with_b1_off(edges, seeded, monkeypatch):
    """The control. An ineligible cohort must be untouched by any of this.

    B-1's whole containment story is that ineligible turns stay legacy, so a
    regression that only shows up with the flag OFF would be invisible to every
    other test in this file.
    """
    monkeypatch.delenv("B1_QUANTITY_ALLOWLIST", raising=False)
    monkeypatch.setenv("B1_QUANTITY_HALT", "1")

    edges.plans.append({
        "action": "log",
        "points": [],
        "items": [item("White rice", 205, amount=100, unit="g")],
        "ready": [item("White rice", 205, amount=100, unit="g")],
    })
    await say(seeded, "100 g of white rice", platform=CAPABLE)

    assert not await operations(seeded), (
        "a halted cohort must not create a canonical operation")
    board = await rows(seeded)
    assert len(board) == 1, (
        f"the legacy lane stopped logging while B-1 was off: "
        f"{[r.parsed_food_name for r in board]}")


# ── The safety negatives, as conversations ────────────────────────────────────
#
# Each of these was previously provable only by unit-testing a seam directly or
# by hand-sending messages on a phone. Both leave the same hole: they assert
# what a FUNCTION does, not what the lane does when a person says the thing.

async def _set(user_id, operation_id, **cols):
    """Reach into the stored operation the way time or a bad deploy would."""
    import db.database as D
    from sqlalchemy import update
    from db.models import PendingOperation
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(PendingOperation)
                        .where(PendingOperation.operation_id == operation_id)
                        .values(**cols))
        await s.commit()


@pytest.mark.asyncio
async def test_cancelling_writes_nothing_and_frees_the_next_meal(edges, b1_live):
    """"Cancel" must close the operation without a row, and not poison what
    comes next.

    Two failures hide here, not one. The obvious one is a meal written despite
    the cancel. The quieter one is a cancelled operation that keeps owning the
    lane — the same defect class as the settled window, which would swallow the
    next meal with no confirmation at all to make it visible.
    """
    ops = await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    assert ops
    await say(b1_live, "cancel")

    assert not await rows(b1_live), (
        "cancel wrote a food row: "
        f"{[(r.parsed_food_name, r.quantity) for r in await rows(b1_live)]}")

    edges.plans.append({
        "action": "ask", "points": [{"label": "Oatmeal", "q": "How much?"}],
        "items": [vague("Oatmeal", cal=150, amount=1, unit="cup cooked")],
        "ready": [],
    })
    await say(b1_live, "Had some oatmeal")
    ops2 = await operations(b1_live)
    assert len(ops2) == 2, (
        "the meal after a cancel did not open its own operation — the "
        f"cancelled one is still owning the lane. {[o.operation_id for o in ops2]}")


@pytest.mark.asyncio
async def test_an_expired_operation_does_not_claim_the_next_meal(edges, b1_live):
    """A question left unanswered overnight must not answer tomorrow's meal.

    Expiry is the one boundary a user crosses by doing nothing, so it is never
    exercised by a scripted happy path and never noticed until someone's
    breakfast is priced as the answer to last night's dinner question.
    """
    from datetime import timedelta
    from core.clock import now

    ops = await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    await _set(b1_live, ops[-1].operation_id,
               expires_at=now() - timedelta(hours=6))

    edges.plans.append({
        "action": "ask", "points": [{"label": "Oatmeal", "q": "How much?"}],
        "items": [vague("Oatmeal", cal=150, amount=1, unit="cup cooked")],
        "ready": [],
    })
    await say(b1_live, "Had some oatmeal")
    await say(b1_live, "45 g")

    board = await rows(b1_live)
    names = [r.parsed_food_name or "" for r in board]
    assert any("atmeal" in n for n in names), (
        f"the meal after an expired question never landed: {names}")
    assert not any("hicken" in n for n in names), (
        f"an expired question priced the NEXT meal as its answer: {names}")


@pytest.mark.asyncio
async def test_a_corrupt_stored_operation_fails_visibly_and_writes_nothing(
        edges, b1_live):
    """An unreadable payload is OUR failure, and must not be dressed as a
    question to the user.

    `owning()` deliberately returns a row it cannot decode with
    `readable=False` rather than pretending nothing is pending — because
    pretending is how a held meal disappears. The requirement here is the other
    half of that: having noticed, the turn must not write, and must not ask the
    user to repair a corruption they cannot see.
    """
    ops = await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    await _set(b1_live, ops[-1].operation_id,
               canonical_payload="{not valid json at all")

    await say(b1_live, "6 oz")

    assert not await rows(b1_live), (
        "a corrupt operation still wrote a meal: "
        f"{[(r.parsed_food_name, r.quantity) for r in await rows(b1_live)]}")


@pytest.mark.asyncio
async def test_a_quantity_we_never_offered_is_accepted_as_stated(edges, b1_live):
    """Free text is the route out of a bad option list, so it has to work for
    a number nobody offered.

    C15 keeps free text always available; this is what makes that promise real
    rather than decorative. If only offered values commit, the option list is
    silently mandatory and "Other" is a dead end.
    """
    await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    await say(b1_live, "137 grams")

    board = await rows(b1_live)
    assert len(board) == 1, [r.parsed_food_name for r in board]
    assert "137" in (board[0].quantity or ""), (
        f"a quantity outside the offered options did not survive to the row: "
        f"{board[0].quantity!r}")


@pytest.mark.asyncio
async def test_a_typed_label_is_answerable_where_there_are_no_chips(edges, b1_live):
    """Telegram and iMessage have no chips, so the label IS the interface.

    This is the LABEL_TEXT capability, and it is deliberately weaker than
    ID_ADDRESSED: matching prose can never be as certain as an option id, which
    is why iOS gets real ids at B-1b instead of this. Until then, typing back
    exactly what we offered must land.
    """
    ops = await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)
    import json
    payload = json.loads(ops[-1].canonical_payload)
    labels = [o["label"]
              for g in payload["interaction"]["groups"]
              for f in g["fields"] for o in f.get("options", [])]
    assert labels, "the ask offered no options to type back"

    await say(b1_live, labels[0])
    board = await rows(b1_live)
    assert len(board) == 1, (
        f"typing back the exact offered label {labels[0]!r} did not commit: "
        f"{[(r.parsed_food_name, r.quantity) for r in board]}")


@pytest.mark.asyncio
async def test_an_unreadable_ownership_lookup_never_falls_through_to_legacy(
        edges, b1_live, monkeypatch):
    """When we cannot tell whether we own the meal, we must not guess "no".

    `owning()` is tri-state on purpose: a FAILED query raises rather than
    returning None, because None means "nothing owns this — proceed legacy" and
    a database blip must never be read as permission to run the old writer
    against a meal the canonical path may already hold. Fails closed: no row is
    better than two.
    """
    await ask_for(edges, b1_live, "I had some chicken breast", B1_ELIGIBLE)

    import core.b1_quantity_operation as b1

    async def _boom(db, user):
        raise b1.OwnershipUnknown("simulated lookup failure")

    monkeypatch.setattr(b1, "owning", _boom)
    await say(b1_live, "6 oz")

    assert not await rows(b1_live), (
        "an unreadable ownership lookup fell through and wrote a meal anyway: "
        f"{[(r.parsed_food_name, r.quantity) for r in await rows(b1_live)]}")
