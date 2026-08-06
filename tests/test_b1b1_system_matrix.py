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


@pytest.fixture
def density(monkeypatch):
    """A deterministic per-100g source: 2 cal/g, 0.2 g protein/g, 0.1 carb, 0.05 fat.

    WHY A FAKE WITH ROUND NUMBERS. Repricing can only be PROVEN against an
    expected value, and `assert calories` is satisfied by the very defect this
    is meant to catch — B-1.75 persisted the answered quantity correctly while
    the ask-time calories survived unchanged. With a known density, 50 g must
    be exactly 100 cal and nothing else, so a stale number cannot pass.
    """
    import api.usda as usda

    async def _hit(query, page_size=5):
        return [{"fdc_id": 1, "_match": "exact", "description": query,
                 "per100g": {"calories": 200.0, "protein": 20.0,
                             "carbs": 10.0, "fat": 5.0}}]
    monkeypatch.setattr(usda, "search_food", _hit)
    return {"cal_per_g": 2.0, "protein_per_g": 0.2,
            "carbs_per_g": 0.1, "fat_per_g": 0.05}


async def _persisted_ask(user):
    """The interaction as STORED — the only evidence of what was offered.

    A parameter labelled "a quantity that was offered" is not evidence that it
    was offered. Candidate selection dedupes and re-ranks on evidence, so the
    option row has to be read back before an answer can be called offered or
    not offered.
    """
    import json
    ops = await operations(user)
    assert ops, "no operation to read"
    field = json.loads(ops[-1].canonical_payload)["interaction"]["groups"][0]["fields"][0]
    return {
        "labels": [o["label"] for o in field["options"]],
        "grams": [float((o.get("patch") or {}).get("quantity", {}).get("grams") or 0)
                  for o in field["options"]],
        "sources": [o.get("source") for o in field["options"]],
    }


async def _observation(user):
    """The durable record of WHICH ROUTE owned the answer."""
    import db.database as D
    from sqlalchemy import select
    from db.models import B1AnswerObservation
    async with D.AsyncSessionLocal() as s:
        r = await s.execute(select(B1AnswerObservation)
                            .order_by(B1AnswerObservation.id))
        rows = list(r.scalars().all())
    return rows[-1] if rows else None


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
        "protein": board[-1].protein if board else None,
        "carbs": board[-1].carbs if board else None,
        "fats": board[-1].fats if board else None,
        "row_id": board[-1].id if board else None,
    }


# ── answer routes, each DEMONSTRATED rather than labelled ────────────────────

@pytest.mark.parametrize("answer,rows_expected,status_expected,modality,label", [
    ("6 oz",       1, "committed", "label",   "the exact text of an offered option"),
    ("137 grams",  1, "committed", "text",    "a quantity we never offered"),
    ("not sure",   0, "awaiting_answer", "command",
     "estimate with NO supporting evidence — stays unresolved"),
    ("cancel",     0, "cancelled", "command", "explicit cancel"),
])
@pytest.mark.asyncio
async def test_each_answer_route_reaches_its_own_terminal_state(
        edges, b1_live, app_db, answer, rows_expected, status_expected,
        modality, label):
    """EXACT status, and the route PROVEN from the persisted record.

    Two things this used to get wrong. `status in ("committed","cancelled")`
    accepted an accidental cancellation of a valid quantity answer and only
    failed indirectly through the row count. And nothing checked WHICH route
    owned the answer, so every case could have travelled the same generic
    typed-quantity path while the parameter label asserted otherwise.

    `modality` is the durable answer to that: an exact stored label binds as a
    SELECTION, a quantity we never offered is the user STATING one, and a
    command is neither.
    """
    ops = await _ask(edges, b1_live)
    assert ops, "the ask did not open an operation; the scenario proves nothing"

    offered = await _persisted_ask(b1_live)
    if answer == "6 oz":
        assert "6 oz" in offered["labels"], (
            f"this case claims to answer with an OFFERED option and "
            f"{offered['labels']} does not contain it")
    if answer == "137 grams":
        assert "137" not in " ".join(offered["labels"]), (
            f"this case claims to answer with something NOT offered, but "
            f"{offered['labels']} contains it")

    await say(b1_live, answer)
    st = await _state(b1_live)

    assert st["operations"] == 1, f"{label}: {st}"
    assert st["status"] == status_expected, f"{label}: {st}"
    assert st["food_rows"] == rows_expected, f"{label}: {st}"
    assert st["meal_commits"] == rows_expected, (
        f"{label}: meal commits and food rows disagree — {st}")

    obs = await _observation(b1_live)
    assert obs is not None, f"{label}: no durable observation of the answer"
    assert obs.modality == modality, (
        f"{label}: answered via {obs.modality!r}, expected {modality!r} — the "
        f"route that owned this answer is not the one this case names")


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
async def test_the_same_transport_delivery_twice_is_deduped(
        edges, b1_live, app_db):
    """One message arriving twice on the wire. Handled ABOVE B-1.

    Verified by mutation: disabling `settle`'s replay guard does not change
    this outcome, so the protection here is transport-level idempotency, not
    B-1's. Recorded as its own scenario precisely so it cannot be mistaken for
    the canonical replay proof below — the two live in different layers and
    only one of them is B-1's to keep working.
    """
    await _ask(edges, b1_live)
    await say(b1_live, "6 oz", msg_id=777001)
    before = (await rows(b1_live))[0].id

    await say(b1_live, "6 oz", msg_id=777001)      # the SAME delivery

    board = await rows(b1_live)
    assert len(board) == 1 and board[0].id == before, (
        f"a redelivered message wrote twice: {[(r.id, r.quantity) for r in board]}")


@pytest.mark.asyncio
async def test_a_second_structured_answer_replays_the_persisted_result(
        edges, b1_live, app_db):
    """B-1'S OWN IDEMPOTENCY — the guard in `settle`, and the one that matters.

    A chip stays on screen after the meal lands, so a second tap is a real
    delivery that transport dedup does NOT catch: it is a distinct message
    carrying the same option. Settlement advances the revision, so without the
    guard the second pass forms its own valid claim and writes a SECOND meal —
    the coordinator cannot see it, because the two claims are genuinely
    distinct.

    Answering through the structured boundary is the only way to reach that
    branch; two `say()` calls are declined earlier by ownership and prove
    something else. Mutation-verified: disable the guard and this fails.
    """
    from tests.test_a_conversation_across_turns import (_live_field_and_option,
                                                        _structured)

    await _ask(edges, b1_live)
    field_id, option_id, revision = await _live_field_and_option(b1_live)

    await _structured(b1_live, field_id=field_id, option_id=option_id,
                      revision=revision)
    first = (await rows(b1_live))[0]
    before = (first.id, first.calories, first.protein, first.quantity)
    commits_before = len(await commits(b1_live))

    # The same tap again, against the now-settled operation.
    await _structured(b1_live, field_id=field_id, option_id=option_id,
                      revision=revision)

    board = await rows(b1_live)
    assert len(board) == 1, (
        f"a second structured answer wrote a second meal: "
        f"{[(r.id, r.quantity, r.calories) for r in board]}")
    after = (board[0].id, board[0].calories, board[0].protein, board[0].quantity)
    assert after == before, f"the replay changed the meal: {before} -> {after}"
    assert len(await commits(b1_live)) == commits_before, (
        "a second commit claim executed for one meal")


# ── quantity basis: the answer must REPRICE, not merely persist ─────────────

@pytest.mark.parametrize("unit,amount", [("g", 100), ("oz", 6),
                                         ("cup cooked", 1), ("breast", 1)])
@pytest.mark.asyncio
async def test_the_answered_mass_reprices_every_macro(
        edges, b1_live, app_db, density, unit, amount):
    """B-1.75, asserted against an EXPECTED value rather than truthiness.

    The defect was: the answered quantity persisted correctly while the
    ask-time calories survived unchanged. `assert calories` passes with that
    bug fully present — the row has a number, it is simply the wrong one.

    So the ask-time nutrition is seeded deliberately incompatible (280 cal for
    the ask-time basis), a deterministic 2 cal/g source is available, and 50 g
    must therefore be exactly 100 cal. Every macro is checked, because
    calories alone can be right while protein rides in stale.
    """
    ask_time_cal = 280
    await _ask(edges, b1_live, cal=ask_time_cal, amount=amount, unit=unit)
    await say(b1_live, "50 g")
    st = await _state(b1_live)

    assert st["food_rows"] == 1, st
    assert "50" in (st["quantity"] or ""), (
        f"ask-time basis {amount}{unit} survived into the row: {st}")
    assert st["calories"] != ask_time_cal, (
        f"the ask-time calories survived the answer — this is B-1.75: {st}")
    assert st["calories"] == pytest.approx(50 * density["cal_per_g"], rel=0.02), (
        f"50 g at 2 cal/g must be 100 cal, got {st['calories']} ({unit})")
    assert st["protein"] == pytest.approx(50 * density["protein_per_g"], rel=0.05), st
    assert st["carbs"] == pytest.approx(50 * density["carbs_per_g"], rel=0.05), st
    assert st["fats"] == pytest.approx(50 * density["fat_per_g"], rel=0.05), st


@pytest.mark.asyncio
async def test_a_different_answer_prices_differently(edges, b1_live, app_db,
                                                     density):
    """The relational form, which no stale-macro implementation can satisfy.

    Two answers to the same food must produce proportional nutrition. A row
    that ignores the answer commits the same number twice, whatever its
    absolute value happens to be.
    """
    await _ask(edges, b1_live)
    await say(b1_live, "50 g")
    small = (await rows(b1_live))[-1]

    await _ask(edges, b1_live)
    await say(b1_live, "100 g")
    large = (await rows(b1_live))[-1]

    assert large.calories == pytest.approx(2 * small.calories, rel=0.05), (
        f"doubling the answer did not double the price: "
        f"{small.calories} -> {large.calories}")
    assert large.protein == pytest.approx(2 * small.protein, rel=0.08), (
        f"protein did not follow: {small.protein} -> {large.protein}")


# ── presentation agrees with what was written ───────────────────────────────

@pytest.mark.asyncio
async def test_the_card_and_the_day_agree_with_the_committed_row(
        edges, b1_live, app_db, density):
    """Claimed in this file's coverage, so it is demonstrated here.

    Three owners of one number produced 789 and 788 once. The card, the row
    and the day total come from one commit and must agree exactly.
    """
    await _ask(edges, b1_live)
    result = await say(b1_live, "50 g")

    board = await rows(b1_live)
    assert len(board) == 1, board
    row = board[0]

    cards = getattr(getattr(result, "response", None), "cards", None) or []
    assert cards, "a committing turn rendered no card"
    blob = str(cards)
    assert str(int(row.calories)) in blob.replace(",", ""), (
        f"the card does not carry the committed calories {row.calories}: {blob[:300]}")

    day = sum(float(r.calories or 0) for r in board)
    assert day == pytest.approx(row.calories, rel=0.001), (
        f"the day total ({day}) disagrees with its only row ({row.calories})")


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


# ── candidate routes, which the earlier commit claimed and did not cover ─────

@pytest.mark.asyncio
async def test_a_history_candidate_is_offered_when_one_exists(
        edges, b1_live, app_db):
    """The candidate axis, asserted on the PERSISTED source rather than the amount.

    The previous version of this file crossed several ANSWER routes and
    claimed to cross every CANDIDATE route, while `_ask()` only ever seeded an
    ontology-backed item. Reading the stored option's `source` is the only way
    to tell a history candidate from an ontology one that happens to land on a
    similar number.
    """
    from datetime import date

    import db.database as D
    from db.models import DailyLog, FoodEntry

    async with D.AsyncSessionLocal() as s:
        log = DailyLog(user_id=b1_live, date=date.today())
        s.add(log)
        await s.flush()
        s.add(FoodEntry(daily_log_id=log.id,
                        parsed_food_name="Chicken breast",
                        quantity="182 g", calories=300.0,
                        estimated_flag=False))
        await s.commit()

    await _ask(edges, b1_live)
    offered = await _persisted_ask(b1_live)

    assert "user_history" in (offered["sources"] or []), (
        f"a trusted exact prior exists and history contributed no candidate: "
        f"{list(zip(offered['labels'], offered['sources']))}")
    idx = offered["sources"].index("user_history")
    assert offered["grams"][idx] == pytest.approx(182.0, rel=0.02), (
        f"the history option does not carry the amount actually logged: "
        f"{offered['grams'][idx]}")


@pytest.mark.asyncio
async def test_with_no_history_every_candidate_comes_from_the_ontology(
        edges, b1_live, app_db):
    """The control. Without a prior, history must contribute nothing.

    Asserted so the test above cannot pass for the wrong reason — a fixture
    that always produces a history option would satisfy it without the
    matcher working at all.
    """
    await _ask(edges, b1_live)
    offered = await _persisted_ask(b1_live)

    assert offered["sources"], "the ask offered nothing"
    assert "user_history" not in offered["sources"], (
        f"history contributed a candidate with no prior to draw on: "
        f"{list(zip(offered['labels'], offered['sources']))}")


# ── which engine actually backed all of the above ───────────────────────────

@pytest.mark.asyncio
async def test_the_matrix_reports_the_engine_it_ran_on(app_db, edges, b1_live):
    """B-1b.1's environment gate, asserted rather than assumed.

    "The suite passed with TEST_POSTGRES_URL set" and "these scenarios ran on
    Postgres" are different claims, and the harness made them look identical
    for as long as it was SQLite either way. Conflating them is how an engine
    difference hides a defect — this repo has already lost one there, a model
    default the migrations never created, invisible because every suite builds
    its schema from the models.

    So the backing store is a fact the file states about itself. With no
    `TEST_POSTGRES_URL` this passes on SQLite and says so; with one it must
    genuinely be Postgres, in an isolated schema, or the run is not the
    production-like evidence B-1b.1 requires.
    """
    import os

    from sqlalchemy import text

    import db.database as D

    dialect = app_db.dialect.name
    if not os.getenv("TEST_POSTGRES_URL"):
        assert dialect == "sqlite", dialect
        pytest.skip("no TEST_POSTGRES_URL — matrix ran SQLite-backed, which is "
                    "valid for logic and does NOT satisfy B-1b.1")

    assert dialect == "postgresql", (
        f"TEST_POSTGRES_URL is set and the harness still bound {dialect} — "
        f"the run would be reported as Postgres-backed and would not be")
    async with D.AsyncSessionLocal() as s:
        path = (await s.execute(text("SHOW search_path"))).scalar()
    assert "harness_" in (path or ""), (
        f"the harness is sharing a schema ({path!r}) — these scenarios write "
        f"real rows and count them, so a neighbour's leftovers would surface "
        f"as an off-by-one somewhere unrelated rather than as a failure here")


# ── B-1.9 item 1: the estimate class, both sides ────────────────────────────

@pytest.mark.asyncio
async def test_not_sure_commits_when_the_users_own_history_supports_it(
        edges, b1_live, app_db):
    """The other half, or the containment would just be a refusal to help.

    "Not sure" is a real answer and must still work — when something actually
    supports it. A prior the user logged themselves is evidence about THIS
    person; a portion ontology is a statement about people in general. The
    first may be committed on their behalf, the second may not.
    """
    from datetime import date

    import db.database as D
    from db.models import DailyLog, FoodEntry

    async with D.AsyncSessionLocal() as s:
        log = DailyLog(user_id=b1_live, date=date.today())
        s.add(log)
        await s.flush()
        s.add(FoodEntry(daily_log_id=log.id, parsed_food_name="Chicken breast",
                        quantity="182 g", calories=300.0, estimated_flag=False))
        await s.commit()

    before = len(await rows(b1_live))          # the seeded prior IS a row
    await _ask(edges, b1_live)
    offered = await _persisted_ask(b1_live)
    assert "user_history" in offered["sources"], offered

    await say(b1_live, "not sure")
    st = await _state(b1_live)

    assert st["food_rows"] == before + 1, (
        f"an estimate WITH user evidence was refused: {st}")
    assert st["status"] == "committed", st
    assert "182" in (st["quantity"] or ""), (
        f"the estimate did not commit the user's own logged portion: "
        f"{st['quantity']!r}")


@pytest.mark.asyncio
async def test_an_unsupported_estimate_writes_nothing_and_stays_open(
        edges, b1_live, app_db):
    """The measured failure, as a CLASS rather than as chicken.

    Live, "not sure" committed 435 g of chicken breast — 718 cal — because a
    generic ontology bracket collapsed to `6 oz / 16 oz` and the estimate took
    the upper of two. The user asked us not to guess.

    The exit gate is exact: zero meal writes, operation still open, an explicit
    repair. Nothing about chicken appears in this test.
    """
    await _ask(edges, b1_live)
    offered = await _persisted_ask(b1_live)
    assert "user_history" not in (offered["sources"] or []), (
        "this case requires an ontology-only option set")

    result = await say(b1_live, "not sure")
    st = await _state(b1_live)

    assert st["food_rows"] == 0, (
        f"an unsupported estimate wrote a meal: {st}")
    assert st["meal_commits"] == 0, st
    assert st["status"] == "awaiting_answer", (
        f"the operation closed instead of staying answerable: {st}")
    text = " ".join(getattr(getattr(result, "response", None), "bubbles", None)
                    or [])
    assert text.strip(), "the user got no reply at all"


@pytest.mark.asyncio
async def test_the_policy_that_refused_an_estimate_is_persisted(
        edges, b1_live, app_db):
    """B-1.9 carry-forward 2: the version must survive the ring.

    `estimate_evidence_v1` was emitted to a log and nowhere else. The ring is
    a bounded in-memory deque that empties on deploy, so an analysis run weeks
    later could not say which sufficiency rule produced a given refusal — and
    the entire reason a policy carries a version is that observations
    collected under one rule stay separable from those collected under the
    next.
    """
    from core.clarification_answer import ESTIMATE_POLICY_VERSION

    await _ask(edges, b1_live)
    await say(b1_live, "not sure")

    obs = await _observation(b1_live)
    assert obs is not None and obs.outcome == "repair", obs
    assert obs.policy_version == ESTIMATE_POLICY_VERSION, (
        f"the refusal was recorded without naming the policy that made it: "
        f"{obs.policy_version!r}")


@pytest.mark.asyncio
async def test_a_plain_typed_answer_names_no_policy(edges, b1_live, app_db):
    """The control. A stated quantity decides itself.

    Stamping every row with a version regardless would make the field mean
    "some policy ran" rather than "this policy decided", and the comparison it
    exists for would be unavailable exactly where it matters.
    """
    await _ask(edges, b1_live)
    await say(b1_live, "137 grams")

    obs = await _observation(b1_live)
    assert obs is not None and obs.outcome == "applied", obs
    assert obs.policy_version == "", (
        f"a typed quantity claimed a policy governed it: {obs.policy_version!r}")
