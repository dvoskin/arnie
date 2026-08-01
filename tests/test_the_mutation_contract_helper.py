"""`mutation_turn` is credited by the inventory, so it has to earn it.

`scripts/mutation_inventory.py` treats the presence of `mutation_turn` in a
handler as evidence of turn identity, a request trace and build attribution.
That credit is only honest if the helper actually provides all three — every
route that adopts it inherits whatever is proven (or missed) here.

The properties below are the ones the copied-by-hand version got wrong at
least once each in this codebase's history.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.mutation_contract import client_key, mutation_turn
from core.turn_identity import CURRENT_TURN_ID
from db.models import LedgerEvent, TurnMetric


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    async with factory() as s:
        yield s


# ── identity ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_client_key_becomes_the_turn_id(session, make_user):
    user = await make_user(telegram_id="mt:key")
    async with mutation_turn(session, channel="dashboard", command="c",
                             user_id=user.id, client_key="ABC") as turn:
        assert turn.turn_id == "dashboard:ABC"


@pytest.mark.asyncio
async def test_no_client_key_falls_back_to_the_documented_hash(session, make_user):
    user = await make_user(telegram_id="mt:nokey")
    async with mutation_turn(session, channel="dashboard", command="c",
                             user_id=user.id, dedup="banana") as turn:
        assert turn.turn_id.startswith("dashboard:h:")


@pytest.mark.asyncio
async def test_the_dedup_signature_separates_two_different_requests(
    session, make_user,
):
    """Two genuinely different writes must not collapse onto one turn."""
    user = await make_user(telegram_id="mt:dedup")
    ids = []
    for sig in ("banana|1", "rice|200g"):
        async with mutation_turn(session, channel="dashboard", command="c",
                                 user_id=user.id, dedup=sig) as t:
            ids.append(t.turn_id)
    assert ids[0] != ids[1]


@pytest.mark.asyncio
async def test_the_turn_is_ambient_inside_and_gone_outside(session, make_user):
    """The leak that stamps the NEXT request's writes with this turn."""
    user = await make_user(telegram_id="mt:scope")
    assert CURRENT_TURN_ID.get() is None
    async with mutation_turn(session, channel="dashboard", command="c",
                             user_id=user.id, client_key="S1") as turn:
        assert CURRENT_TURN_ID.get() == turn.turn_id
    assert CURRENT_TURN_ID.get() is None


@pytest.mark.asyncio
async def test_the_turn_scope_is_released_even_when_the_body_raises(
    session, make_user,
):
    from fastapi import HTTPException

    user = await make_user(telegram_id="mt:scope-raise")
    with pytest.raises(HTTPException):
        async with mutation_turn(session, channel="dashboard", command="c",
                                 user_id=user.id, client_key="S2"):
            raise HTTPException(status_code=404, detail="nope")
    assert CURRENT_TURN_ID.get() is None, (
        "a failed request left its turn id bound for the next one")


# ── the ambient turn reaches the write ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_ledger_event_written_inside_carries_the_turn(session, make_user):
    """The whole point of binding it: `record_ledger_event` stamps the
    contextvar, so a write inside the body is joinable to the request."""
    from db.queries import record_ledger_event

    user = await make_user(telegram_id="mt:ambient")
    async with mutation_turn(session, channel="dashboard", command="c",
                             user_id=user.id, client_key="AMB") as turn:
        await record_ledger_event(session, user.id, "updated", domain="water",
                                  entry_id=1, payload={"amount_ml": 1})

    ev = (await session.execute(
        select(LedgerEvent).where(LedgerEvent.user_id == user.id)
    )).scalars().first()
    assert ev.turn_id == "dashboard:AMB"


# ── trace and build attribution ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_completed_turn_persists_a_metric_naming_its_build(
    session, make_user,
):
    user = await make_user(telegram_id="mt:build")
    async with mutation_turn(session, channel="dashboard", command="log_food",
                             user_id=user.id, client_key="B1"):
        pass

    m = (await session.execute(
        select(TurnMetric).where(TurnMetric.turn_id == "dashboard:B1")
    )).scalars().first()
    assert m is not None, "no turn metric — the route has no build attribution"
    assert m.build_sha, "the turn does not name the build that served it"
    assert m.command == "log_food"


@pytest.mark.asyncio
async def test_a_refusal_is_recorded_as_an_outcome_not_a_crash(
    session, make_user,
):
    """A 404 is a thing that happened, not a failure of the tracing."""
    from fastapi import HTTPException

    user = await make_user(telegram_id="mt:404")
    with pytest.raises(HTTPException):
        async with mutation_turn(session, channel="dashboard", command="c",
                                 user_id=user.id, client_key="N1") as turn:
            turn.note(entry=7)
            raise HTTPException(status_code=404, detail="nope")
    assert turn.trace.fields.get("outcome") == "http_404"


# ── idempotency ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_claim_true_deduplicates_and_claim_false_does_not(
    session, make_user,
):
    """Class A takes a claim; Class B declares it does not need one, and must
    genuinely not take one — a claim there would add a failure mode."""
    user = await make_user(telegram_id="mt:claim")

    async with mutation_turn(session, channel="dashboard", command="cA",
                             user_id=user.id, client_key="K", payload={"a": 1},
                             claim=True) as first:
        assert first.replay is False
        assert first.claim_id is not None
        # A route completes its claim with the write; here there is no write,
        # so use the documented fallback. Without EITHER, the claim stays
        # in_progress and the retry below is refused rather than replayed —
        # which is the correct behaviour, and the trap this makes explicit.
        await first.complete(session, entry_id=42)

    async with mutation_turn(session, channel="dashboard", command="cA",
                             user_id=user.id, client_key="K", payload={"a": 1},
                             claim=True) as second:
        assert second.replay is True, "the second delivery was not a replay"

    async with mutation_turn(session, channel="dashboard", command="cB",
                             user_id=user.id, client_key="K", payload={"a": 1},
                             claim=False) as unclaimed:
        assert unclaimed.claim is None
        assert unclaimed.replay is False
        assert unclaimed.claim_id is None


@pytest.mark.asyncio
async def test_the_same_key_with_a_different_payload_is_a_409(session, make_user):
    from fastapi import HTTPException

    user = await make_user(telegram_id="mt:conflict")
    async with mutation_turn(session, channel="dashboard", command="cC",
                             user_id=user.id, client_key="X", payload={"a": 1},
                             claim=True) as t:
        await t.complete(session, entry_id=1)

    with pytest.raises(HTTPException) as e:
        async with mutation_turn(session, channel="dashboard", command="cC",
                                 user_id=user.id, client_key="X",
                                 payload={"a": 2}, claim=True):
            pass
    assert e.value.status_code == 409


# ── the FieldInfo trap ──────────────────────────────────────────────────────


def test_an_unresolved_header_default_is_not_a_client_key():
    """A direct call receives the unresolved `Header(...)` default.
    Stringifying it gave every keyless request the SAME unique-looking id."""
    from fastapi import Header

    assert client_key(Header(None, alias="Idempotency-Key")) is None
    assert client_key(None) is None
    assert client_key("  ") is None
    assert client_key(" ABC ") == "ABC"
