"""Web and proactive turns carry an identity, like every other surface.

Measured over an 18-hour production window: 10 of 77 turns had no `turn_id`.
They were not scattered — they were two surfaces:

    web         5   the /api/chat endpoint calls run_turn and log_conversation
                    directly instead of going through core.chat_service, which
                    does mint an id. So the one path that skipped the shared
                    helper skipped the identity with it.
    proactive   4   a message Arnie starts had no id at all, so its history
                    row, its delivery attempt and any write it triggered could
                    not be joined to each other or to anything else.

A turn with no id is invisible to every audit query in the repository. That is
why the 07-30 audit could not check 79 proactive sends even in principle.

These tests are about identity existing and being shaped like everyone else's,
not about what either surface says.
"""
import pytest
from sqlalchemy import select

from core.turn_identity import CURRENT_TURN_ID, make_turn_id
from db.models import ConversationLog


# ── proactive ────────────────────────────────────────────────────────────────


def test_a_proactive_send_binds_a_turn():
    import scheduler.proactive_scheduler as PS

    assert CURRENT_TURN_ID.get() is None
    with PS._proactive_turn(7, "am_nolog", "morning check-in") as tid:
        assert CURRENT_TURN_ID.get() == tid
        assert tid.startswith("proactive:")
    assert CURRENT_TURN_ID.get() is None, "the turn leaked past its send"


def test_the_same_slot_on_the_same_day_is_the_same_turn():
    """A redelivery of one nudge must not mint a second identity for it —
    otherwise the same message counts twice everywhere it is joined."""
    import scheduler.proactive_scheduler as PS

    with PS._proactive_turn(7, "am_nolog", "morning") as a:
        pass
    with PS._proactive_turn(7, "am_nolog", "morning") as b:
        pass
    assert a == b


def test_different_slots_are_different_turns():
    import scheduler.proactive_scheduler as PS

    with PS._proactive_turn(7, "am_nolog", "x") as a:
        pass
    with PS._proactive_turn(7, "pm_recap", "x") as b:
        pass
    assert a != b


def test_different_users_are_different_turns():
    import scheduler.proactive_scheduler as PS

    with PS._proactive_turn(7, "am_nolog", "x") as a:
        pass
    with PS._proactive_turn(8, "am_nolog", "x") as b:
        pass
    assert a != b


@pytest.mark.asyncio
async def test_a_delivered_proactive_row_carries_its_turn(db, make_user,
                                                          monkeypatch):
    """The history row is what audits read. Without the id it joins nothing."""
    import scheduler.proactive_scheduler as PS
    from core.delivery import DeliveryResult

    user = await make_user(telegram_id="223456")

    async def _ok(*a, **k):
        return DeliveryResult.accepted("telegram", provider="telegram")

    async def _yes(*a, **k):
        return True

    monkeypatch.setattr(PS, "_send", _ok)
    monkeypatch.setattr(PS, "_within_proactive_budget", _yes)

    await PS._send_logged(db, user.id, "223456", "morning check-in", "am_nolog")

    row = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == user.id)
    )).scalars().one()
    assert row.turn_id, "a proactive row with no turn id joins nothing"
    assert row.turn_id.startswith("proactive:")


@pytest.mark.asyncio
async def test_the_delivery_attempt_shares_that_turn(db, make_user, monkeypatch):
    """The whole point of binding it around the send: the history row and the
    delivery record describe ONE thing and must say so."""
    import scheduler.proactive_scheduler as PS
    from core.delivery import DeliveryResult
    from db.models import DeliveryAttempt

    user = await make_user(telegram_id="223457")

    async def _ok(*a, **k):
        return DeliveryResult.accepted("telegram", provider="telegram")

    async def _yes(*a, **k):
        return True

    monkeypatch.setattr(PS, "_send", _ok)
    monkeypatch.setattr(PS, "_within_proactive_budget", _yes)

    await PS._send_logged(db, user.id, "223457", "hi", "pm_recap")

    conv = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == user.id)
    )).scalars().one()
    attempt = (await db.execute(
        select(DeliveryAttempt).where(DeliveryAttempt.user_id == user.id)
    )).scalars().one()
    assert attempt.turn_id == conv.turn_id != None    # noqa: E711


# ── web ──────────────────────────────────────────────────────────────────────


def test_the_web_id_uses_the_documented_fallback():
    """A browser sends no stable message id, so the web turn takes
    `make_turn_id`'s hash form rather than inventing a format. Same text inside
    the hour is one turn; tomorrow's identical message is a new one."""
    a = make_turn_id("web", None, 7, "how many calories left")
    b = make_turn_id("web", None, 7, "how many calories left")
    c = make_turn_id("web", None, 7, "something else")

    assert a.startswith("web:h:")
    assert a == b
    assert a != c
