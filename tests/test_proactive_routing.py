"""
Proactive send-target routing + iOS banner construction.

Routing rule (2026-07-06): proactive messages FOLLOW THE CONVERSATION — the
platform of the user's most recent real message wins, then an explicit
channel_preference (new/quiet users), then the canonical identity. Regression
for Gi (user 5): canonical iMessage row + linked Telegram + linked iOS, stale
channel_preference='telegram' — after he went all-in on the iOS app his nudges
kept landing on Telegram.
"""
import pytest

from db.queries import (
    _platform_of, get_or_create_user, log_conversation, resolve_send_target,
)
from scheduler.proactive_scheduler import _push_banner


# ── _platform_of learns iOS ──────────────────────────────────────────────────

def test_platform_of_classifies_all_prefixes():
    assert _platform_of("ios:8A86D93A") == "ios"
    assert _platform_of("apple:001361.abc") == "ios"
    assert _platform_of("im:+17187901322") == "imessage"
    assert _platform_of("5526578962") == "telegram"
    assert _platform_of(None) == "telegram"


# ── resolve_send_target: activity-first ─────────────────────────────────────

async def _link(db, canonical, secondary):
    secondary.linked_to_user_id = canonical.id
    await db.commit()


@pytest.mark.asyncio
async def test_activity_on_ios_beats_stale_telegram_pref(db, make_user):
    """Gi's exact shape: canonical im:, linked telegram + ios, pref='telegram',
    most recent real message on iOS → route to the iOS identity."""
    gi = await make_user(telegram_id="im:+17187901322", name="Gi",
                         channel_preference="telegram")
    tg = await get_or_create_user(db, "5526578962")
    ios = await get_or_create_user(db, "ios:9F312E5F")
    await _link(db, gi, tg)
    await _link(db, gi, ios)

    await log_conversation(db, gi.id, "hello from telegram", "hey",
                           source_type="text", platform="telegram")
    await log_conversation(db, gi.id, "had a celsius today", "logged",
                           source_type="ios", platform="ios")

    assert await resolve_send_target(db, gi) == "ios:9F312E5F"


@pytest.mark.asyncio
async def test_proactive_rows_do_not_steer_routing(db, make_user):
    """Our own proactive sends must not count as 'activity' — only real user
    turns move the target (otherwise sends self-reinforce the current channel)."""
    u = await make_user(telegram_id="im:+15550001111", name="Quiet")
    ios = await get_or_create_user(db, "ios:QUIET-DEVICE")
    await _link(db, u, ios)

    await log_conversation(db, u.id, "checking in from ios", "hey",
                           source_type="ios", platform="ios")
    # A later proactive that went out on iMessage must not flip routing back.
    await log_conversation(db, u.id, "", "End of day check.",
                           source_type="proactive", platform="imessage")

    assert await resolve_send_target(db, u) == "ios:QUIET-DEVICE"


@pytest.mark.asyncio
async def test_pref_still_wins_for_users_with_no_activity(db, make_user):
    u = await make_user(telegram_id="100", name="Fresh",
                        channel_preference="imessage")
    im = await get_or_create_user(db, "im:+15559998888")
    await _link(db, u, im)
    assert await resolve_send_target(db, u) == "im:+15559998888"


@pytest.mark.asyncio
async def test_unlinked_user_falls_back_to_canonical(db, make_user):
    u = await make_user(telegram_id="200", name="Solo")
    assert await resolve_send_target(db, u) == "200"


@pytest.mark.asyncio
async def test_activity_platform_without_identity_falls_through(db, make_user):
    """Last activity on a platform we hold no identity for (e.g. the row was
    unlinked later) falls through to preference, then canonical."""
    u = await make_user(telegram_id="300", name="Movedon")
    await log_conversation(db, u.id, "hi", "hey",
                           source_type="ios", platform="ios")  # no ios identity
    assert await resolve_send_target(db, u) == "300"


# ── iOS push banner ──────────────────────────────────────────────────────────

def test_banner_promotes_short_opener_to_title():
    title, body = _push_banner(
        "You up?|||Haven't seen breakfast logged yet.|||Sleep was light at 5.5h.",
        "late_morning_nolog",
    )
    assert title == "You up?"
    assert body == "Haven't seen breakfast logged yet."


def test_banner_strips_markdown():
    title, body = _push_banner(
        "End of day check, Danny.|||**1,482/2,164 cal**, 682 under.",
        "night_closeout",
    )
    assert title == "End of day check, Danny."
    assert "**" not in body and "1,482/2,164 cal" in body


def test_banner_long_lead_keeps_slot_title():
    long_lead = ("You're at 360 cal with 1,804 left and protein's only at 20g "
                 "so dinner needs to carry you hard tonight.")
    title, body = _push_banner(long_lead + "|||Recovery's green.", "evening_pacing")
    assert title == "Evening check-in"
    assert body.startswith("You're at 360 cal")


def test_banner_single_bubble_falls_back_to_slot_title():
    title, body = _push_banner("Hop on the scale, what are we working with?",
                               "morning_checkin")
    assert title == "Morning check-in"
    assert body == "Hop on the scale, what are we working with?"


def test_banner_empty_text_safe():
    title, body = _push_banner("", None)
    assert title == "Arnie" and body
