"""B-1.9 step 8.2 — the structured answer boundary, over real HTTP.

ASSERTING THE FACTS OBJECT IS NOT PROOF THE ENDPOINT CARRIES IT. Every gate
here sends a request through the ASGI app and decodes the bytes that come
back, because the contract iOS is built against is the response body — not an
internal dataclass that happens to have the right fields.

    POST /api/v1/chat/answer
      { operation_id, revision, field_id, option_id, client_message_id }
    ->
      { outcome, repair_reason, refusal_reason, bubbles, cards, turn_id, … }

A tap is not a sentence. Routing it through the message endpoint would put it
back through text parsing, which is the interpretation an option id exists to
avoid.
"""
import asyncio
import json
import os

import pytest

from api.chat import chat_answer  # noqa: F401 — named for the concurrency scan
from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, client, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say, operations, commits, vague, B1_ELIGIBLE,
)
from tests.test_b1b1_system_matrix import _ask, density  # noqa: F401

ANSWER = "/api/v1/chat/answer"


async def _open_question(edges, user):
    """One eligible ask, and the ids a client would have received."""
    await _ask(edges, user, food="Chicken breast", cal=280)
    ops = await operations(user)
    assert ops, "no operation to answer"
    payload = json.loads(ops[-1].canonical_payload)
    field = payload["interaction"]["groups"][0]["fields"][0]
    return {
        "operation_id": payload["interaction"]["operation_id"],
        "revision": payload["interaction"]["revision"],
        "field_id": field["options"][0]["field_id"],
        "option_id": field["options"][0]["option_id"],
    }


@pytest.mark.asyncio
async def test_a_tap_over_http_commits_and_says_what_it_did(
        client, edges, seeded, b1_live, density):
    ids = await _open_question(edges, seeded)
    response = await client.post(ANSWER, json={**ids,
                                               "client_message_id": "tap-1"})
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["outcome"] == "applied"
    assert body["repair_reason"] == "" and body["refusal_reason"] == ""
    assert body["entry_id"], "a committing answer named no row"
    assert body["turn_id"], "the response names no canonical turn"
    assert body["bubbles"] and "Logged" in body["bubbles"][0]
    assert body["cards"], "a committing answer returned no card"
    assert len(await commits(seeded)) == 1


@pytest.mark.asyncio
async def test_the_same_client_message_id_returns_the_original_result(
        client, edges, seeded, b1_live, density):
    """THE CLAIM RETURNS THE ORIGINAL, and does not re-run settlement.

    A phone with a flaky connection resends; without a stable key the only
    alternative is guessing from content, and two identical taps are
    indistinguishable from a user genuinely tapping twice.
    """
    ids = await _open_question(edges, seeded)
    first = await client.post(ANSWER, json={**ids,
                                            "client_message_id": "same-tap"})
    second = await client.post(ANSWER, json={**ids,
                                             "client_message_id": "same-tap"})

    assert first.status_code == second.status_code == 200
    assert len(await commits(seeded)) == 1, "a retried tap wrote twice"
    assert second.json().get("idempotent_replay") is True, second.json()
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert second.json()["turn_id"] == first.json()["turn_id"], (
        "the retry took a different turn identity than the claim it replays")


@pytest.mark.asyncio
async def test_two_concurrent_taps_write_one_meal(
        client, edges, seeded, b1_live, density):
    """THE RACE THE CLAIM EXISTS FOR — two deliveries in flight at once.

    Sequential retries are caught by a read-then-write; concurrent ones are
    not, which is why this route claims rather than checking. Run through the
    real ASGI app, so the claim, the turn identity and settlement all take
    part.
    """
    ids = await _open_question(edges, seeded)
    body = {**ids, "client_message_id": "concurrent-tap"}

    first, second = await asyncio.gather(
        client.post(ANSWER, json=body), client.post(ANSWER, json=body),
        return_exceptions=True)

    assert not isinstance(first, Exception), first
    assert not isinstance(second, Exception), second

    # ONE WRITES; THE OTHER IS TOLD SO. The loser gets 409 — the in-flight
    # conflict the claim framework already defines and clients already
    # understand — rather than a second commit or a silent success. A replay
    # (200) is also correct if the winner finished first; what is NOT correct
    # is two meals.
    codes = sorted((first.status_code, second.status_code))
    assert codes in ([200, 200], [200, 409]), codes
    assert len(await commits(seeded)) == 1, (
        "two concurrent deliveries of one tap wrote two meals")

    winner = first if first.status_code == 200 else second
    assert winner.json()["entry_id"], "the winning delivery wrote no row"


@pytest.mark.asyncio
async def test_a_second_distinct_tap_replays_rather_than_applying_again(
        client, edges, seeded, b1_live, density):
    """REPLAY IS ITS OWN OUTCOME. Two genuinely different deliveries carrying
    the same option: the claim cannot catch this one, so the settled operation
    must."""
    ids = await _open_question(edges, seeded)
    first = await client.post(ANSWER, json={**ids,
                                            "client_message_id": "tap-a"})
    second = await client.post(ANSWER, json={**ids,
                                             "client_message_id": "tap-b"})

    assert first.json()["outcome"] == "applied"
    assert second.json()["outcome"] == "replay", second.json()
    assert len(await commits(seeded)) == 1
    assert second.json()["entry_id"] == first.json()["entry_id"]


@pytest.mark.parametrize("mutate,expected_reason", [
    ({"option_id": "opt_never_offered"}, "unknown_option"),
    ({"field_id": "fld_from_another_operation"}, "foreign_field"),
    ({"revision": 99}, "revision_mismatch"),
])
@pytest.mark.asyncio
async def test_a_refusal_names_its_reason_over_the_wire(
        client, edges, seeded, b1_live, density, mutate, expected_reason):
    """A CLIENT BRANCHES ON A VALUE, NOT ON PROSE. "That option is gone" and
    "that screen is stale" are different repairs for the user."""
    ids = await _open_question(edges, seeded)
    response = await client.post(
        ANSWER, json={**ids, **mutate, "client_message_id": "bad-tap"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "refused", body
    assert body["refusal_reason"] == expected_reason, body
    assert len(await commits(seeded)) == 0


@pytest.mark.parametrize("missing", ["operation_id", "revision", "field_id",
                                     "option_id", "client_message_id"])
@pytest.mark.asyncio
async def test_every_identifier_is_required(client, edges, seeded, b1_live,
                                            density, missing):
    """FAILS AT THE BOUNDARY, not inside the turn. A partial envelope is a
    client bug, and answering it would mean guessing which question was
    meant."""
    ids = await _open_question(edges, seeded)
    body = {**ids, "client_message_id": "x"}
    body.pop(missing)
    response = await client.post(ANSWER, json=body)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_an_answer_with_no_open_question_fails_closed(
        client, edges, seeded, b1_live, density):
    response = await client.post(ANSWER, json={
        "operation_id": "chat_quantity:26:nothing", "revision": 0,
        "field_id": "fld_nothing", "option_id": "opt_nothing",
        "client_message_id": "orphan"})
    assert response.status_code == 200
    assert response.json()["outcome"] == "refused"
    assert len(await commits(seeded)) == 0


@pytest.mark.asyncio
async def test_the_response_carries_no_semantics_a_client_could_reinterpret(
        client, edges, seeded, b1_live, density):
    """IDENTIFIERS AND RENDERED TEXT. A client that received a candidate or a
    patch could form its own view of what an option means, and then there are
    two owners of one fact."""
    ids = await _open_question(edges, seeded)
    body = (await client.post(
        ANSWER, json={**ids, "client_message_id": "tap"})).json()

    flat = json.dumps(body)
    for leaked in ("candidate_set", "evidence", "serving_basis", "prior",
                   "semantic_hash", "generation_input_fingerprint"):
        assert leaked not in flat, f"the response leaked {leaked!r}"


# ── 8.3 — a replay returns the ORIGINAL result, not its shape ──────────────

#: Fields that legitimately differ between a first delivery and a redelivery.
#: Everything else is the authoritative result and must be identical.
_VARIABLE = {"idempotent_replay", "turn_id"}


@pytest.mark.asyncio
async def test_a_replay_returns_the_original_response_not_an_empty_shell(
        client, edges, seeded, b1_live, density):
    """THE P1. The response had the same SHAPE and not the same CONTENT.

    A phone can lose the HTTP response after the meal has committed. On retry
    it received `{outcome, entry_id}` with empty bubbles and no card — so the
    authoritative confirmation existed on the server and could not be shown,
    and the client would have to reconstruct it or re-fetch. That is precisely
    the client-side inference the frozen boundary exists to prevent.
    """
    ids = await _open_question(edges, seeded)
    body = {**ids, "client_message_id": "lost-response"}

    first = (await client.post(ANSWER, json=body)).json()
    replay = (await client.post(ANSWER, json=body)).json()

    assert replay["idempotent_replay"] is True
    assert replay["bubbles"] == first["bubbles"] != []
    assert replay["cards"] == first["cards"] != []
    assert {k: v for k, v in replay.items() if k not in _VARIABLE} == {
        k: v for k, v in first.items() if k not in _VARIABLE}, (
        "the redelivery is not the original result")
    assert len(await commits(seeded)) == 1


@pytest.mark.asyncio
async def test_the_replayed_card_still_names_the_row_that_was_written(
        client, edges, seeded, b1_live, density):
    """Rebuilt FROM THE ROW, so it cannot drift from what was committed."""
    import db.database as D
    from db.models import FoodEntry
    from sqlalchemy import select

    ids = await _open_question(edges, seeded)
    body = {**ids, "client_message_id": "rebuild-me"}
    await client.post(ANSWER, json=body)
    replay = (await client.post(ANSWER, json=body)).json()

    async with D.AsyncSessionLocal() as s:
        entry = (await s.execute(
            select(FoodEntry).order_by(FoodEntry.id.desc()))).scalars().first()
    card = replay["cards"][0]["payload"]
    assert card["entry_id"] == entry.id
    assert abs(float(card["calories"]) - float(entry.calories)) < 1.0
    assert str(int(round(float(entry.calories)))) in replay["bubbles"][0]


@pytest.mark.asyncio
async def test_a_crash_between_the_two_commits_does_not_write_twice(
        client, edges, seeded, b1_live, density, monkeypatch):
    """THE ACKNOWLEDGED WINDOW, tested rather than reasoned about.

    The meal commits first and the claim completes in a SECOND transaction, so
    a process that dies between them leaves durable work behind an incomplete
    claim. The shared contract documents this; nothing proved what a retry
    then does.

    The retry must not write a second meal. That safety does not come from the
    claim — which never completed — but from settlement itself: the turn id
    the claim was taken under is the same one settlement dedupes on, so the
    redelivery finds the operation already settled and replays it.
    """
    from core.mutation_contract import MutationTurn

    ids = await _open_question(edges, seeded)
    body = {**ids, "client_message_id": "crash-between"}

    async def _die(self, db, **kw):
        raise RuntimeError("process died after the meal committed")

    monkeypatch.setattr(MutationTurn, "complete", _die)
    with pytest.raises(Exception):
        await client.post(ANSWER, json=body)

    # The meal IS durable — that is what makes this window dangerous.
    assert len(await commits(seeded)) == 1, (
        "the domain write did not commit; this is not the window under test")

    monkeypatch.undo()
    retry = await client.post(ANSWER, json=body)
    assert retry.status_code in (200, 409), retry.text
    assert len(await commits(seeded)) == 1, (
        "a retry after a crash between the two commits wrote a second meal")
    if retry.status_code == 200:
        assert retry.json()["entry_id"], (
            "the retry returned no row for a meal that exists")


@pytest.mark.asyncio
async def test_a_replay_does_not_date_a_commit_it_did_not_make(
        client, edges, seeded, b1_live, density, monkeypatch):
    """`commit_visible_ms` belongs to the turn that COMMITTED, not to every
    turn that mentions the entry.

    A replay returns the ORIGINAL entry's id — that is what makes it a replay —
    so `entry_id` present was never evidence that this turn wrote anything. The
    mark was guarded on it anyway, and the funnel said so:
    `commit_visible_ms=9` on a turn reporting `written=0 committed=0`.

    The direction is what makes it worth catching. Replays are fast by
    construction, so those readings dragged the metric DOWN — a turn that did
    not commit made real commits look quicker than they are. A missing number
    is visibly missing; a wrong one that flatters the system is not.
    """
    import logging

    from core import food_trace as _ft

    # THE KILL SWITCH, PINNED. `food_trace.begin()` returns None when
    # `FOOD_TRACE` is off, and then there is no trace, no line, and nothing for
    # this test to read — a state indistinguishable from the defect it is
    # looking for. A test about trace CONTENT must not inherit whether tracing
    # is on from whatever ran before it.
    monkeypatch.setenv("FOOD_TRACE", "true")
    assert _ft.tracing_enabled(), "the kill switch is off; this test cannot see"

    ids = await _open_question(edges, seeded)

    # CAPTURED AT THE SOURCE LOGGER, NOT THROUGH `caplog`. Twice now this
    # assertion has failed for reasons that had nothing to do with what it
    # tests: `caplog` collects for the WHOLE test (so the ask in
    # `_open_question` was counted as subject), and it captures by handler on
    # the ROOT logger — which only works while `core.food_trace` still
    # propagates and nothing has called `logging.disable()`. Under CI's
    # shuffled order something upstream changes that, and the test saw ZERO
    # lines for two requests that had both plainly emitted one.
    #
    # A handler on the logger itself is immune to all of it, and scoping it to
    # the two POSTs removes the setup turn without needing to clear anything.
    captured = []

    class _Grab(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    # THE MODULE'S OWN LOGGER OBJECT, not one looked up by name. They are the
    # same object right up until they are not, and `getLogger` by name gives no
    # sign when they differ — the handler simply never fires and the test reads
    # as "nothing was traced".
    trace_log = _ft.logger
    handler = _Grab(level=logging.INFO)
    was_level, was_disabled = trace_log.level, trace_log.disabled
    was_global = logging.root.manager.disable
    trace_log.addHandler(handler)
    trace_log.setLevel(logging.INFO)
    trace_log.disabled = False
    logging.disable(logging.NOTSET)     # a global disable outranks any handler
    try:
        applied = await client.post(ANSWER, json={**ids,
                                                  "client_message_id": "tap-1"})
        replayed = await client.post(ANSWER, json={**ids,
                                                   "client_message_id": "tap-2"})
    finally:
        trace_log.removeHandler(handler)
        trace_log.setLevel(was_level)
        trace_log.disabled = was_disabled
        logging.disable(was_global)

    assert applied.json()["outcome"] == "applied"
    assert replayed.json()["outcome"] == "replay", replayed.json()

    lines = [m for m in captured if m.startswith("event=food_trace ")]
    # DIAGNOSABLE ON FAILURE. This assertion has already failed twice for
    # reasons in the capture rather than the product, and once under an
    # ordering that could not be reproduced from the run that reported it —
    # pytest-randomly's seed is not printed under `-q`. If it fails again, the
    # next reader gets the state that decides it instead of another
    # investigation from scratch.
    assert len(lines) == 2, (
        f"a replayed tap left no trace of its own — got {len(lines)} lines "
        f"for two requests.\n"
        f"  tracing_enabled={_ft.tracing_enabled()}\n"
        f"  FOOD_TRACE={os.getenv('FOOD_TRACE')!r}\n"
        f"  logger={_ft.logger.name!r} id={id(_ft.logger)} "
        f"same_by_name={_ft.logger is logging.getLogger('core.food_trace')}\n"
        f"  module={_ft.__name__!r} id={id(_ft)}\n"
        f"  every record captured on core.food_trace: {captured}\n"
        f"  matching lines: {lines}")

    def field(line, key):
        for token in line.split():
            if token.startswith(f"{key}="):
                return token[len(key) + 1:]
        raise AssertionError(f"{key}= missing from {line}")

    # THE INVARIANT OVER THE ACTUAL STREAM, not over a line count: no emitted
    # line may date a commit's visibility on a turn that wrote nothing.
    for line in lines:
        if field(line, "commit_visible_ms") != "-":
            assert int(field(line, "written")) > 0, (
                f"this turn dated the moment its committed truth became "
                f"visible, having written nothing: {line}")
        assert field(line, "funnel") == "ok", line

    wrote, replay = lines
    assert field(wrote, "written") == "1"
    assert field(wrote, "committed") == "1"
    assert field(wrote, "commit_visible_ms") != "-", (
        "the turn that actually committed lost its visibility measurement")

    assert field(replay, "written") == "0", (
        "a replay answered from storage counted as a second write")
    assert field(replay, "committed") == "0"
    assert field(replay, "stopped_at") == "execute", (
        "the replay's line does not say where the turn ended")
