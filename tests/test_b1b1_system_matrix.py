"""B-1b.1 — THE DETERMINISTIC SYSTEM-VALIDATION MATRIX.

Every axis of the canonical path crossed, and every scenario asserted against
DATABASE STATE rather than reply text. What a turn says is a rendering; what it
wrote is the fact, and this slice has already shipped a reply that claimed a
log with no row behind it.

WHAT THIS CLASS OF EVIDENCE MAY PROVE — system correctness only: ownership,
persistence, settlement, idempotency, replay, pricing, card/totals agreement,
telemetry. It may NOT be reported as acceptance, preference or abandonment.
Those are facts about people and require people (B-1b.3, B-1b.4).

WHAT THIS FILE DOES NOT YET COVER, STATED HERE SO THE GAP CANNOT BE MISREAD
AS COVERAGE. B-1b.1 requires production-like **Postgres** with **real
enrichment**. This runs on the shared in-memory SQLite harness with USDA and
Open Food Facts pinned off, so:

  * every axis below is exercised, and the DATABASE assertions are real;
  * the storage engine is not the one production runs — the model/migration
    drift this repo has already suffered lives exactly in that difference
    (`tests/test_the_migrations_build_what_the_models_declare.py`);
  * `analyze()` runs, but with no candidate lane answering, so the pricing
    proven here is the ESTIMATE path rather than the density path. Real
    enrichment needs `USDA_API_KEY`, which is not available locally.

Both are environment gaps, not logic gaps, and both are tracked in the
directive's coverage ledger. B-1b.1 is **not green** until they close.

SEQUENCES, NOT CONSTRUCTED STATE. Every scenario starts from a raw user
message and passes through real routing, candidate generation, persistence,
answer application and commit. Nothing here builds a PendingOperation and then
asserts something about it — that shortcut is how four defects in this slice
shipped green, because a fixture that builds the state it asserts cannot fail.
"""
import pytest

from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say, operations, commits, vague, B1_ELIGIBLE,
)


async def _ask(edges, user, food="Chicken breast", cal=280, amount=6, unit="oz"):
    """One eligible turn, reached the way production reaches it."""
    edges.plans.append({
        "action": "ask",
        "points": [{"label": food, "q": "How much?"}],
        "items": [vague(food, cal=cal, amount=amount, unit=unit)],
        "ready": [],
    })
    await say(user, f"I had some {food.lower()}")
    return await operations(user)


async def _state(user):
    """The facts a scenario is judged on. Never the reply."""
    ops = await operations(user)
    board = await rows(user)
    mc = await commits(user)
    return {
        "operations": len(ops),
        "status": ops[-1].status if ops else None,
        "revision": ops[-1].revision if ops else None,
        "food_rows": len(board),
        "meal_commits": len(mc),
        "quantity": board[-1].quantity if board else None,
        "calories": board[-1].calories if board else None,
    }


# ── answer routes ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("answer,rows_expected,label", [
    ("6 oz",            1, "typed quantity that was offered"),
    ("137 grams",       1, "typed quantity we never offered"),
    ("not sure",        1, "estimate route — MODE_DEFAULT"),
    ("cancel",          0, "explicit cancel writes nothing"),
])
@pytest.mark.asyncio
async def test_each_answer_route_reaches_the_right_terminal_state(
        edges, b1_live, app_db, answer, rows_expected, label):
    """One operation, one terminal state, and the row count the route implies."""
    ops = await _ask(edges, b1_live)
    assert ops, "the ask did not open an operation; the scenario proves nothing"

    await say(b1_live, answer)
    st = await _state(b1_live)

    assert st["operations"] == 1, f"{label}: {st}"
    assert st["food_rows"] == rows_expected, f"{label}: {st}"
    assert st["meal_commits"] == rows_expected, (
        f"{label}: meal commits and food rows disagree — {st}")
    assert st["status"] in ("committed", "cancelled"), f"{label}: {st}"


@pytest.mark.asyncio
async def test_a_malformed_answer_repairs_without_writing_or_moving_revision(
        edges, b1_live, app_db):
    """REPAIR changes no persisted semantic state.

    Bumping the revision would invalidate the options still on the user's
    screen, so a stale-tap storm would follow every misread word.
    """
    ops = await _ask(edges, b1_live)
    before = ops[-1].revision

    await say(b1_live, "somewhere thereabouts")
    st = await _state(b1_live)

    assert st["food_rows"] == 0, f"a repair wrote a meal: {st}"
    assert st["status"] == "awaiting_answer", st
    assert st["revision"] == before, (
        f"repair moved the revision {before} -> {st['revision']}")


@pytest.mark.asyncio
async def test_duplicate_delivery_cannot_write_twice(edges, b1_live, app_db):
    """The same answer twice is one meal, and the SAME meal."""
    await _ask(edges, b1_live)
    await say(b1_live, "6 oz")
    first = (await rows(b1_live))[0]
    before = (first.id, first.calories, first.quantity)

    await say(b1_live, "6 oz")
    st = await _state(b1_live)
    after_row = (await rows(b1_live))[0]

    assert st["food_rows"] == 1 and st["meal_commits"] == 1, st
    assert (after_row.id, after_row.calories, after_row.quantity) == before, (
        f"the replay changed the meal under the user: {before} -> "
        f"{(after_row.id, after_row.calories, after_row.quantity)}")


# ── quantity basis ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("unit,amount", [("g", 100), ("oz", 6),
                                         ("cup cooked", 1), ("breast", 1)])
@pytest.mark.asyncio
async def test_the_answered_mass_replaces_any_ask_time_basis(
        edges, b1_live, app_db, unit, amount):
    """A mass answer overrides whatever basis the ask carried.

    B-1.75: the ask-time macros described a DIFFERENT quantity, so leaving them
    in the pricing input let a policy meant for arbitrating sources arbitrate
    the user's own answer instead.
    """
    await _ask(edges, b1_live, amount=amount, unit=unit)
    await say(b1_live, "50 g")
    st = await _state(b1_live)

    assert st["food_rows"] == 1, st
    assert "50" in (st["quantity"] or ""), (
        f"ask-time basis {amount}{unit} survived into the row: {st}")
    assert st["calories"], f"a committed row with no calories: {st}"


# ── the turn is watched ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_committing_turn_ran_its_health_check(
        edges, b1_live, app_db):
    """B-1c's coverage, asserted as part of the matrix rather than beside it.

    A lane that returns early skips every cross-cutting check the old path
    flows through, and nothing fails when it does.
    """
    from core import conversation

    ran = {}
    real = conversation.detect_turn_flags

    def _spy(**kw):
        ran.update(kw)
        return real(**kw)

    conversation.detect_turn_flags = _spy
    try:
        await _ask(edges, b1_live)
        ran.clear()
        result = await say(b1_live, "6 oz")
    finally:
        conversation.detect_turn_flags = real

    assert ran, "a committing canonical turn ran no health check"
    assert ran.get("wrote_this_turn") is True, (
        f"the turn committed but reported no write: {ran.get('wrote_this_turn')}")
    assert "phantom_log_claim" not in (result.health_flags or []), (
        f"a real commit was flagged as a phantom: {result.health_flags}")
