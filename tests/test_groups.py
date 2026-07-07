"""Groups v1 — launch seed, join flow, and THE feedback visibility rule:
members see only their own Feedback messages; admins see the whole room."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from api import groups as groups_api
from api.groups import (
    get_messages, join_group, list_groups, post_message, PostBody,
)


@pytest_asyncio.fixture
async def patched(monkeypatch, engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(groups_api, "AsyncSessionLocal", factory)
    monkeypatch.setenv("GROUP_ADMIN_USER_IDS", "")  # set per-test
    return factory


@pytest.mark.asyncio
async def test_launch_groups_seed_and_join(patched, make_user, monkeypatch):
    await make_user(telegram_id="ios:G1", name="Gina")
    gs = await list_groups(identity="ios:G1")
    names = {g.name: g for g in gs}
    assert {"Beta Insiders", "Feedback"} <= set(names)
    assert names["Feedback"].kind == "feedback"
    assert all(not g.joined for g in gs)

    await join_group(names["Beta Insiders"].id, identity="ios:G1")
    gs2 = await list_groups(identity="ios:G1")
    joined = {g.name for g in gs2 if g.joined}
    assert joined == {"Beta Insiders"}
    assert [g for g in gs2 if g.name == "Beta Insiders"][0].member_count == 1


@pytest.mark.asyncio
async def test_open_group_messages_visible_to_all(patched, make_user):
    await make_user(telegram_id="ios:G2", name="Ann")
    await make_user(telegram_id="ios:G3", name="Bob")
    gs = await list_groups(identity="ios:G2")
    beta = [g for g in gs if g.kind == "open"][0]
    await post_message(beta.id, PostBody(text="hello crew"), identity="ios:G2")
    msgs = await get_messages(beta.id, identity="ios:G3")
    assert [m.text for m in msgs] == ["hello crew"]
    assert msgs[0].sender_name == "Ann" and msgs[0].mine is False


@pytest.mark.asyncio
async def test_feedback_visibility_rule(patched, make_user, monkeypatch):
    ua = await make_user(telegram_id="ios:F1", name="Ann")
    ub = await make_user(telegram_id="ios:F2", name="Bob")
    admin = await make_user(telegram_id="ios:ADMIN", name="Danny")
    monkeypatch.setenv("GROUP_ADMIN_USER_IDS", str(admin.id))

    gs = await list_groups(identity="ios:F1")
    fb = [g for g in gs if g.kind == "feedback"][0]
    await post_message(fb.id, PostBody(text="bug: streak froze"), identity="ios:F1")
    await post_message(fb.id, PostBody(text="idea: oura ring"), identity="ios:F2")

    # Each member sees ONLY their own thread.
    a_view = await get_messages(fb.id, identity="ios:F1")
    assert [m.text for m in a_view] == ["bug: streak froze"] and a_view[0].mine
    b_view = await get_messages(fb.id, identity="ios:F2")
    assert [m.text for m in b_view] == ["idea: oura ring"]

    # The admin reads the whole room.
    d_view = await get_messages(fb.id, identity="ios:ADMIN")
    assert [m.text for m in d_view] == ["bug: streak froze", "idea: oura ring"]
    assert {m.sender_name for m in d_view} == {"Ann", "Bob"}


@pytest.mark.asyncio
async def test_post_auto_joins(patched, make_user):
    await make_user(telegram_id="ios:G4", name="Cal")
    gs = await list_groups(identity="ios:G4")
    fb = [g for g in gs if g.kind == "feedback"][0]
    await post_message(fb.id, PostBody(text="love the app"), identity="ios:G4")
    gs2 = await list_groups(identity="ios:G4")
    assert [g for g in gs2 if g.id == fb.id][0].joined
