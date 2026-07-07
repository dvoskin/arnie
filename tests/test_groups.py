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


@pytest.mark.asyncio
async def test_reactions_toggle_and_aggregate(patched, make_user):
    from api.groups import ReactBody, toggle_reaction
    await make_user(telegram_id="ios:R1", name="Ann")
    await make_user(telegram_id="ios:R2", name="Bob")
    gs = await list_groups(identity="ios:R1")
    beta = [g for g in gs if g.kind == "open"][0]
    msg = await post_message(beta.id, PostBody(text="pr day"), identity="ios:R1")

    await toggle_reaction(beta.id, msg.id, ReactBody(emoji="❤️"), identity="ios:R2")
    await toggle_reaction(beta.id, msg.id, ReactBody(emoji="❤️"), identity="ios:R1")
    view = await get_messages(beta.id, identity="ios:R1")
    r = view[-1].reactions
    assert r and r[0].emoji == "❤️" and r[0].count == 2 and r[0].mine

    # Toggle off removes mine, count drops.
    await toggle_reaction(beta.id, msg.id, ReactBody(emoji="❤️"), identity="ios:R1")
    view2 = await get_messages(beta.id, identity="ios:R1")
    r2 = view2[-1].reactions
    assert r2[0].count == 1 and r2[0].mine is False


@pytest.mark.asyncio
async def test_reply_carries_quote(patched, make_user):
    await make_user(telegram_id="ios:Q1", name="Ann")
    await make_user(telegram_id="ios:Q2", name="Bob")
    gs = await list_groups(identity="ios:Q1")
    beta = [g for g in gs if g.kind == "open"][0]
    first = await post_message(beta.id, PostBody(text="how do I hit 250g protein"),
                               identity="ios:Q1")
    reply = await post_message(
        beta.id, PostBody(text="chicken", reply_to_id=first.id), identity="ios:Q2")
    assert reply.reply_to and reply.reply_to.sender_name == "Ann"
    view = await get_messages(beta.id, identity="ios:Q1")
    assert view[-1].reply_to.excerpt.startswith("how do I hit")


@pytest.mark.asyncio
async def test_photo_message_and_lazy_image(patched, make_user, monkeypatch):
    from api.groups import get_message_image
    await make_user(telegram_id="ios:P1", name="Ann")
    await make_user(telegram_id="ios:P2", name="Bob")
    gs = await list_groups(identity="ios:P1")
    beta = [g for g in gs if g.kind == "open"][0]
    msg = await post_message(beta.id, PostBody(text="", image_b64="AAAA"),
                             identity="ios:P1")
    assert msg.has_image and msg.text == ""
    img = await get_message_image(beta.id, msg.id, identity="ios:P2")
    assert img["image_b64"] == "AAAA"   # open room: any member fetches

    # Feedback: another member can NOT fetch someone's image; admin can.
    admin = await make_user(telegram_id="ios:PADMIN", name="Danny")
    monkeypatch.setenv("GROUP_ADMIN_USER_IDS", str(admin.id))
    fb = [g for g in gs if g.kind == "feedback"][0]
    fmsg = await post_message(fb.id, PostBody(text="screenshot", image_b64="BBBB"),
                              identity="ios:P1")
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await get_message_image(fb.id, fmsg.id, identity="ios:P2")
    assert (await get_message_image(fb.id, fmsg.id, identity="ios:PADMIN"))["image_b64"] == "BBBB"


@pytest.mark.asyncio
async def test_unsend_own_only_and_quote_unlinks(patched, make_user):
    from api.groups import unsend_message
    from fastapi import HTTPException
    await make_user(telegram_id="ios:U1", name="Ann")
    await make_user(telegram_id="ios:U2", name="Bob")
    gs = await list_groups(identity="ios:U1")
    beta = [g for g in gs if g.kind == "open"][0]
    first = await post_message(beta.id, PostBody(text="oops typo"), identity="ios:U1")
    _reply = await post_message(beta.id, PostBody(text="lol", reply_to_id=first.id),
                                identity="ios:U2")

    with pytest.raises(HTTPException):        # not Bob's to unsend
        await unsend_message(beta.id, first.id, identity="ios:U2")
    await unsend_message(beta.id, first.id, identity="ios:U1")

    view = await get_messages(beta.id, identity="ios:U2")
    texts = [m.text for m in view]
    assert "oops typo" not in texts
    assert view[-1].text == "lol" and view[-1].reply_to is None   # quote unlinked


@pytest.mark.asyncio
async def test_empty_post_rejected(patched, make_user):
    from fastapi import HTTPException
    await make_user(telegram_id="ios:E1", name="Ann")
    gs = await list_groups(identity="ios:E1")
    beta = [g for g in gs if g.kind == "open"][0]
    with pytest.raises(HTTPException):
        await post_message(beta.id, PostBody(text="   "), identity="ios:E1")


@pytest.mark.asyncio
async def test_feedback_reply_cannot_leak_others_messages(patched, make_user, monkeypatch):
    """H2 regression: a non-admin must NOT be able to reply-to another member's
    Feedback message (the reply echoes the quoted text+sender). Iterating
    reply_to_id used to leak the private line."""
    ann = await make_user(telegram_id="ios:FBR1", name="Ann")
    bob = await make_user(telegram_id="ios:FBR2", name="Bob")
    admin = await make_user(telegram_id="ios:FBRADMIN", name="Danny")
    monkeypatch.setenv("GROUP_ADMIN_USER_IDS", str(admin.id))
    gs = await list_groups(identity="ios:FBR1")
    fb = [g for g in gs if g.kind == "feedback"][0]
    secret = await post_message(fb.id, PostBody(text="my private bug"), identity="ios:FBR1")

    from fastapi import HTTPException
    # Bob (non-admin) cannot reply-to Ann's message → 404, no leak.
    with pytest.raises(HTTPException):
        await post_message(fb.id, PostBody(text="probe", reply_to_id=secret.id),
                           identity="ios:FBR2")
    # Admin CAN reply-to it.
    r = await post_message(fb.id, PostBody(text="on it", reply_to_id=secret.id),
                           identity="ios:FBRADMIN")
    assert r.reply_to and r.reply_to.excerpt.startswith("my private bug")


@pytest.mark.asyncio
async def test_feedback_reaction_cannot_probe_others_messages(patched, make_user, monkeypatch):
    """M1 regression: reacting to a hidden Feedback message leaks its existence."""
    from api.groups import ReactBody, toggle_reaction
    from fastapi import HTTPException
    ann = await make_user(telegram_id="ios:FBX1", name="Ann")
    bob = await make_user(telegram_id="ios:FBX2", name="Bob")
    admin = await make_user(telegram_id="ios:FBXADMIN", name="Danny")
    monkeypatch.setenv("GROUP_ADMIN_USER_IDS", str(admin.id))
    gs = await list_groups(identity="ios:FBX1")
    fb = [g for g in gs if g.kind == "feedback"][0]
    secret = await post_message(fb.id, PostBody(text="private note"), identity="ios:FBX1")
    with pytest.raises(HTTPException):
        await toggle_reaction(fb.id, secret.id, ReactBody(emoji="❤️"), identity="ios:FBX2")
    # Owner can react to their own.
    assert (await toggle_reaction(fb.id, secret.id, ReactBody(emoji="❤️"),
                                  identity="ios:FBX1"))["ok"]
