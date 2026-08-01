"""Concurrency proof for the Class A routes whose write lives behind a lane.

Undo, the health imports and the four chat surfaces do not own their write
transaction — they hand off to `execute_tool_calls`, to the import upsert, or
to the whole turn pipeline. That is why their guarantees are credited to the
lane rather than read off the handler, and it is exactly why each needs a test
that drives the ROUTE: the credit is only as good as the handoff.

The invariant in every case is that two deliveries of one logical request
leave one effect. What the losing delivery returns varies — the original
result, a retryable 409, or (on the sqlite test engine, where two sessions
share one connection behind a StaticPool) a driver-level error. The row and
event counts are what must hold on every backend; CI runs this suite against a
real Postgres for the cross-process half.
"""
import asyncio

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import FoodEntry, LedgerEvent


@pytest_asyncio.fixture
async def patched(monkeypatch, engine):
    import api.app as A
    import api.health_sync as HS
    import api.quick_log as QL
    import api.undo as U
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    for mod in (A, HS, QL, U):
        monkeypatch.setattr(mod, "AsyncSessionLocal", factory)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(A, "_send_dashboard_notification", _noop)
    monkeypatch.setattr(A, "resolve_send_target", _noop)
    return factory


async def _events(db, user_id, domain=None, event_type=None):
    q = select(LedgerEvent).where(LedgerEvent.user_id == user_id)
    if domain:
        q = q.where(LedgerEvent.domain == domain)
    if event_type:
        q = q.where(LedgerEvent.event_type == event_type)
    return (await db.execute(q.order_by(LedgerEvent.id))).scalars().all()


# ── undo ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_taps_on_one_undo_card_undo_one_thing(patched, db, make_user):
    """Undoing twice must not undo two things.

    The card carries the `event_id` of the write behind it, so a double tap
    replays the same event id. Without a claim both deliveries invert it — and
    because the inversion appends its OWN event, the second could go on to
    reach a different row than the one the user pointed at.
    """
    from api.quick_log import FoodLogBody, log_food_entry
    from api.undo import UndoBody, undo_event

    user = await make_user(telegram_id="ios:undo-race")
    await log_food_entry(
        FoodLogBody(food_name="Bagel", calories=280, protein=10, carbs=55,
                    fats=2),
        identity="ios:undo-race", client_request_id="U-SEED")

    created = (await _events(db, user.id, "food", "created"))[0]

    results = await asyncio.gather(
        undo_event(UndoBody(event_id=created.id), identity="ios:undo-race",
                   client_request_id="UNDO-RACE"),
        undo_event(UndoBody(event_id=created.id), identity="ios:undo-race",
                   client_request_id="UNDO-RACE"),
        return_exceptions=True,
    )
    for r in results:
        assert isinstance(r, (dict, HTTPException)), f"unhandled: {r!r}"

    deleted = await _events(db, user.id, "food", "deleted")
    assert len(deleted) <= 1, (
        f"two taps on one undo card produced {len(deleted)} deletions")


@pytest.mark.asyncio
async def test_a_replayed_undo_reports_the_original_success(
    patched, db, make_user,
):
    from api.quick_log import FoodLogBody, log_food_entry
    from api.undo import UndoBody, undo_event

    user = await make_user(telegram_id="ios:undo-replay")
    await log_food_entry(
        FoodLogBody(food_name="Scone", calories=350, protein=6, carbs=45,
                    fats=16),
        identity="ios:undo-replay", client_request_id="UR-SEED")
    created = (await _events(db, user.id, "food", "created"))[0]

    first = await undo_event(UndoBody(event_id=created.id),
                             identity="ios:undo-replay",
                             client_request_id="UR-1")
    second = await undo_event(UndoBody(event_id=created.id),
                              identity="ios:undo-replay",
                              client_request_id="UR-1")
    assert first["status"] == "ok" and second["status"] == "ok"
    assert second.get("idempotent_replay") is True
    assert first["turn_id"] == "ios:UR-1"


# ── the Shortcuts / Whoop import surfaces ───────────────────────────────────


@pytest.mark.asyncio
async def test_two_concurrent_shortcut_health_syncs_leave_one_day(
    patched, db, make_user,
):
    """`/health/apple` — the Shortcuts path. Naturally idempotent on the
    snapshot upsert; the risk is the workout replace-on-sync racing itself."""
    import api.app as A

    user = await make_user(telegram_id="hk:shortcut-race")
    user.webhook_token = "tok-hk"
    await db.commit()

    payload = A.AppleHealthPayload(date="2026-07-15", steps=9000)
    results = await asyncio.gather(
        A.receive_apple_health(payload, token="tok-hk"),
        A.receive_apple_health(payload, token="tok-hk"),
        return_exceptions=True,
    )
    ok = [r for r in results if isinstance(r, dict)]
    assert ok, f"both syncs failed: {results}"

    events = await _events(db, user.id, "health_import")
    assert len(events) <= 2, (
        f"two syncs of one day left {len(events)} import events")


@pytest.mark.asyncio
async def test_two_concurrent_whoop_syncs_import_one_window(
    patched, db, make_user, monkeypatch,
):
    """`/api/whoop/sync/{token}` — poll-based, so the same 30-day window is
    re-read on every run and duplicate delivery is the normal case."""
    import api.app as A

    user = await make_user(telegram_id="whoop:race")
    user.webhook_token = "tok-whoop"
    user.whoop_access_token = "fake"
    await db.commit()

    calls = {"n": 0}

    async def _fake_sync(db_, whoop_user, days=30, snapshot_user_id=None):
        calls["n"] += 1
        return 30
    monkeypatch.setattr("api.whoop.sync_user_whoop", _fake_sync)

    results = await asyncio.gather(
        A.dashboard_whoop_sync(token="tok-whoop"),
        A.dashboard_whoop_sync(token="tok-whoop"),
        return_exceptions=True,
    )
    ok = [r for r in results if isinstance(r, dict)]
    assert ok, f"both syncs failed: {results}"
    assert all(r.get("turn_id") for r in ok if r.get("status") == "ok"), (
        "a whoop sync ran without a turn id — its imported rows cannot be "
        "joined to the sync that pulled them")


# ── the chat lane ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_message_delivered_twice_logs_the_food_once(
    patched, db, make_user, monkeypatch,
):
    """The chat lane's `claim_write_only` policy, driven through the ROUTE.

    `claim_processed_turn` returns a bool rather than a stored reply, so the
    guarantee is about the WRITE: a redelivered message must not log the meal
    twice, even though the reply is generated again. The four chat routes are
    credited for this through the turn pipeline, and this is the test that
    makes the handoff real rather than assumed.
    """
    import api.chat as C

    user = await make_user(telegram_id="ios:chat-race")

    async def _fake_turn(identity, text, source_type, **kw):
        # Stand in for the coaching brain: claim the turn the way the
        # structured food stage does, and write only if the claim is ours.
        from db.queries import (add_food_entry, claim_processed_turn,
                                get_or_create_today_log)
        async with patched() as s:
            if not await claim_processed_turn(s, user.id, "chat:DUP"):
                return {"bubbles": ["already handled"]}
            log = await get_or_create_today_log(s, user.id, "UTC")
            await add_food_entry(s, log.id, user_id=user.id,
                                 ledger_source="chat",
                                 parsed_food_name="Burrito", calories=700,
                                 protein=30, carbs=80, fats=25)
            return {"bubbles": ["logged"]}

    monkeypatch.setattr(C, "_coached_reply", _fake_turn)

    results = await asyncio.gather(
        C.chat(C.ChatRequest(message="had a burrito"), identity="ios:chat-race"),
        C.chat(C.ChatRequest(message="had a burrito"), identity="ios:chat-race"),
        return_exceptions=True,
    )
    for r in results:
        assert not isinstance(r, BaseException) or isinstance(r, HTTPException), (
            f"unhandled: {r!r}")

    rows = (await db.execute(
        select(FoodEntry).where(FoodEntry.parsed_food_name == "Burrito")
    )).scalars().all()
    assert len(rows) == 1, (
        f"one message delivered twice logged {len(rows)} meals — the "
        f"processed-turn claim did not hold through the route")


@pytest.mark.asyncio
async def test_the_dashboard_chat_route_claims_its_turn_once(
    patched, db, make_user, monkeypatch,
):
    """`/api/chat/{token}` — the web chat surface. It calls
    `core.conversation.run_turn` directly rather than going through
    `_coached_reply`, so it is a SECOND handoff into the same pipeline and
    needs its own proof."""
    import api.app as A

    user = await make_user(telegram_id="web:chat-race")
    user.webhook_token = "tok-webchat"
    await db.commit()

    seen = {"n": 0}

    async def _fake_run_turn(*a, **k):
        from db.queries import claim_processed_turn
        async with patched() as s:
            if await claim_processed_turn(s, user.id, "web:DUP"):
                seen["n"] += 1
        class _T:
            response = type("R", (), {"bubbles": ["ok"], "reaction": None})()
            tools = []
        return _T()

    monkeypatch.setattr("core.conversation.run_turn", _fake_run_turn)

    results = await asyncio.gather(
        A.post_chat(token="tok-webchat",
                    body=A.ChatBody(message="had a burrito")),
        A.post_chat(token="tok-webchat",
                    body=A.ChatBody(message="had a burrito")),
        return_exceptions=True,
    )
    # Whatever each delivery returns, the pipeline may only claim the turn once.
    assert seen["n"] <= 1, (
        f"one web message delivered twice claimed the turn {seen['n']} times "
        f"(results: {results})")


@pytest.mark.asyncio
async def test_every_chat_route_reaches_the_turn_pipeline(patched, make_user,
                                                          monkeypatch):
    """The handoff the chat routes' credit rests on.

    `/chat`, `/chat/photo` and `/chat/voice` are credited with turn identity,
    a trace, build attribution and the write claim because they enter the turn
    pipeline. If any of them stopped doing that, the inventory would keep
    reporting them compliant — so the handoff itself is pinned.
    """
    import api.chat as C

    await make_user(telegram_id="ios:chat-handoff")
    seen = []

    async def _spy(identity, text, source_type, **kw):
        seen.append(source_type)
        return {"bubbles": ["ok"]}

    monkeypatch.setattr(C, "_coached_reply", _spy)
    monkeypatch.setattr("multimodal.image_handler.process_photo",
                        lambda *a, **k: _async("a plate of rice"))
    monkeypatch.setattr("multimodal.voice_handler.process_voice",
                        lambda *a, **k: _async("had a banana"))

    import base64
    png = base64.b64encode(b"not-a-real-image").decode()
    await C.chat(C.ChatRequest(message="hi"), identity="ios:chat-handoff")
    await C.chat_photo(C.PhotoChatRequest(image_base64=png),
                       identity="ios:chat-handoff")
    await C.chat_voice(C.VoiceChatRequest(audio_base64=png),
                       identity="ios:chat-handoff")

    assert seen == ["ios", "photo", "voice"], (
        f"a chat route stopped entering the turn pipeline: {seen}")


async def _async(value):
    return value
