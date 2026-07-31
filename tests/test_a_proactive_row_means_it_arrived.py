"""A proactive history row means the message reached someone.

`_send` returned None on every path it has — the kill switch, the allowlist,
APNs not configured, no registered device, a provider rejection, a swallowed
exception, and a genuine delivery. `_send_logged` wrote a `conversation_logs`
row regardless, so the row meant "we reached the send function".

Three things read that row and all three inherited the ambiguity: the rolling
24h cadence budget, the silence streak, and engagement analysis. The budget is
the worst of them — a user whose pushes all fail was rate-limited as though
they were being reached, so the failure suppressed its own retry.

These tests are about the CONTRACT, not about any channel: a send reports what
happened, and history follows the report.
"""
import pytest
from sqlalchemy import select

from core.delivery import (ACCEPTED, FAILED, INVALID_DESTINATION, SUPPRESSED,
                           DeliveryResult)
from db.models import ConversationLog, DeliveryAttempt


# ── the vocabulary ───────────────────────────────────────────────────────────


def test_only_an_accepted_send_counts_as_reaching_the_user():
    """`reached_user` is the predicate history and cadence must use. Every
    other status describes a message that did not arrive."""
    assert DeliveryResult.accepted("ios", count=1).reached_user is True
    assert DeliveryResult.suppressed("kill_switch").reached_user is False
    assert DeliveryResult.failed("ios", code="500").reached_user is False
    assert DeliveryResult.no_destination("ios").reached_user is False


def test_accepted_with_no_destinations_is_not_reaching_anyone():
    """A fan-out that accepted zero devices is not a delivery, whatever its
    status says. The count is the fact."""
    r = DeliveryResult(status=ACCEPTED, channel="ios", accepted_count=0)
    assert r.reached_user is False


def test_suppressed_is_not_a_failure():
    """A kill switch or allowlist stop is not an error to alert on — nothing
    was supposed to be sent. Conflating the two makes a quiet rollout look
    like an outage."""
    r = DeliveryResult.suppressed("not_on_allowlist", "telegram")
    assert r.status == SUPPRESSED
    assert r.failure_code == ""


def test_no_destination_is_distinct_from_failure():
    """Retrying a user with no device cannot help; the fix is to stop holding
    a dead destination. Collapsing it into `failed` hides that."""
    assert DeliveryResult.no_destination("ios").status == INVALID_DESTINATION
    assert DeliveryResult.failed("ios").status == FAILED


# ── history follows the report ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_send_writes_no_history_row(db, make_user, monkeypatch):
    """THE regression. A refused push used to leave a proactive row that the
    cadence budget then counted as contact."""
    import scheduler.proactive_scheduler as PS

    user = await make_user(telegram_id="123456")
    monkeypatch.setattr(PS, "_send", lambda *a, **k: _result(
        DeliveryResult.failed("telegram", code="Forbidden")))
    monkeypatch.setattr(PS, "_within_proactive_budget", _true)

    await PS._send_logged(db, user.id, "123456", "morning check-in", "am_nolog")

    rows = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == user.id)
    )).scalars().all()
    assert rows == [], (
        "a refused send wrote history — the cadence budget will count it as "
        "having reached the user"
    )


@pytest.mark.asyncio
async def test_an_accepted_send_still_writes_history(db, make_user, monkeypatch):
    """The other half: gating must not silence real deliveries."""
    import scheduler.proactive_scheduler as PS

    user = await make_user(telegram_id="123457")
    monkeypatch.setattr(PS, "_send", lambda *a, **k: _result(
        DeliveryResult.accepted("telegram", provider="telegram")))
    monkeypatch.setattr(PS, "_within_proactive_budget", _true)

    await PS._send_logged(db, user.id, "123457", "morning check-in", "am_nolog")

    rows = (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == user.id)
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_suppressed_send_writes_no_history(db, make_user, monkeypatch):
    """A message the kill switch stopped never existed as far as the user is
    concerned, and must not appear in their conversation."""
    import scheduler.proactive_scheduler as PS

    user = await make_user(telegram_id="123458")
    monkeypatch.setattr(PS, "_send", lambda *a, **k: _result(
        DeliveryResult.suppressed("proactive_disabled", "telegram")))
    monkeypatch.setattr(PS, "_within_proactive_budget", _true)

    await PS._send_logged(db, user.id, "123458", "hi", "am_nolog")

    assert (await db.execute(
        select(ConversationLog).where(ConversationLog.user_id == user.id)
    )).scalars().all() == []


# ── the attempt is durable either way ────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_attempt_is_recorded_including_the_failures(
    db, make_user, monkeypatch,
):
    """Not writing history must not mean writing nothing. A failure that
    leaves no trace is indistinguishable from a message never generated, and
    per-channel failure rates become unqueryable."""
    import scheduler.proactive_scheduler as PS

    user = await make_user(telegram_id="123459")
    monkeypatch.setattr(PS, "_send", lambda *a, **k: _result(
        DeliveryResult.no_destination("ios", "no_active_device_tokens")))
    monkeypatch.setattr(PS, "_within_proactive_budget", _true)

    await PS._send_logged(db, user.id, "ios:abc", "hi", "am_nolog")

    attempts = (await db.execute(
        select(DeliveryAttempt).where(DeliveryAttempt.user_id == user.id)
    )).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].status == INVALID_DESTINATION
    assert attempts[0].accepted_at is None
    assert attempts[0].slot_key == "am_nolog"


@pytest.mark.asyncio
async def test_an_accepted_attempt_records_when_it_was_accepted(
    db, make_user, monkeypatch,
):
    import scheduler.proactive_scheduler as PS

    user = await make_user(telegram_id="123460")
    monkeypatch.setattr(PS, "_send", lambda *a, **k: _result(
        DeliveryResult.accepted("ios", provider="apns", count=2)))
    monkeypatch.setattr(PS, "_within_proactive_budget", _true)

    await PS._send_logged(db, user.id, "ios:abc", "hi", "pm_recap")

    row = (await db.execute(select(DeliveryAttempt))).scalars().one()
    assert row.status == ACCEPTED
    assert row.accepted_at is not None
    assert row.delivered_at is None, (
        "accepted is a provider promise, not proof of display — delivered must "
        "stay unset until something actually confirms it"
    )


# ── helpers ──────────────────────────────────────────────────────────────────


async def _true(*a, **k):
    return True


def _result(value):
    async def _inner(*a, **k):
        return value
    return _inner()
