"""Pending clarification expiry and concurrency (build order 17, 18).

A held meal is state that outlives its turn, so it has the two problems all
such state has.

It goes stale: "Which Fairlife was it?" answered twenty minutes later is a live
answer; answered tomorrow morning it is about yesterday's food, and applying it
silently to today is a wrong-day write nobody asked for.

It races: "Elite" and "half bottle" sent two seconds apart both target the same
row, and without a guard both apply — or worse, both commit.
"""
from datetime import date, datetime, timedelta

import pytest

from skills.nutrition.pending_store import (ACTIVE_WINDOW, ConcurrencyLost,
                                            Freshness, PENDING_KIND,
                                            PendingClarification,
                                            PendingStatus, from_payload,
                                            make_clarification_id,
                                            open_clarification)

NOON = datetime(2026, 7, 25, 12, 0)


def _pending(created=NOON, meal_date=None, version=1,
             status=PendingStatus.ACTIVE, **kw):
    return PendingClarification(
        clarification_id="clarify_abc", user_id=7, meal_group_id="meal_1",
        logical_meal_date=meal_date or created.date(), created_at=created,
        question_ids=("q1",), held_item_ids=("i1",),
        requested_fields={"q1": ("product_line", "consumed_fraction")},
        payload={"label": "Fairlife"}, version=version, status=status, **kw)


# ── staleness ─────────────────────────────────────────────────────────────────
def test_a_prompt_answer_binds_silently():
    p = _pending()
    f = p.freshness(NOON + timedelta(minutes=20))
    assert f is Freshness.ACTIVE
    assert f.binds_silently and not f.needs_confirmation


def test_an_answer_later_the_same_day_still_binds_but_names_the_meal():
    p = _pending()
    f = p.freshness(NOON + timedelta(hours=5))
    assert f is Freshness.RECOVERABLE
    assert not f.binds_silently
    assert not f.needs_confirmation


def test_an_answer_after_day_rollover_is_stale():
    p = _pending()
    f = p.freshness(NOON + timedelta(days=1))
    assert f is Freshness.STALE
    assert f.needs_confirmation


def test_day_rollover_is_checked_before_elapsed_time():
    """An answer at 00:30 about a 23:50 meal is forty minutes old and still
    about YESTERDAY. Elapsed time alone would call it fresh and write it to the
    wrong day."""
    late = datetime(2026, 7, 25, 23, 50)
    p = _pending(created=late)
    just_after_midnight = datetime(2026, 7, 26, 0, 30)
    assert just_after_midnight - late < ACTIVE_WINDOW      # only 40 minutes
    assert p.freshness(just_after_midnight) is Freshness.STALE


def test_a_late_night_meal_can_count_as_the_previous_day():
    """A 1am snack is the previous logging day, which is what users mean."""
    one_am = datetime(2026, 7, 26, 1, 0)
    p = open_clarification(user_id=7, meal_group_id="m", now=one_am,
                           day_start_hour=4)
    assert p.logical_meal_date == date(2026, 7, 25)
    assert p.freshness(datetime(2026, 7, 26, 2, 0),
                       day_start_hour=4) is Freshness.ACTIVE


def test_a_stale_row_is_still_answerable_it_just_asks_first():
    """Expiry does not delete the meal. It changes whether we apply the answer
    silently."""
    p = _pending()
    later = NOON + timedelta(days=1)
    assert p.is_answerable(later)
    assert p.freshness(later).needs_confirmation
    assert "Saturday" in p.confirmation_prompt()


def test_a_closed_row_is_not_answerable():
    for status in (PendingStatus.CONSUMED, PendingStatus.CANCELLED,
                   PendingStatus.EXPIRED):
        assert not _pending(status=status).is_answerable(NOON)


def test_the_logging_day_boundary_is_reported():
    p = _pending()
    assert p.expires_at() == datetime(2026, 7, 26, 0, 0)
    assert p.expires_at(day_start_hour=4) == datetime(2026, 7, 26, 4, 0)


# ── concurrency ───────────────────────────────────────────────────────────────
def test_consume_is_a_staleness_guard_not_the_atomic_one():
    """A frozen value object CANNOT arbitrate a race: two callers holding the
    same snapshot both see the same version, and neither can know the other
    already won. consume() rejects a stale version and a closed row; the
    authoritative guard is claim(), which the database resolves."""
    p = _pending(version=3)
    consumed = p.consume(expected_version=3)
    assert consumed.status is PendingStatus.CONSUMED
    assert consumed.version == 4

    # The already-spent RESULT refuses further consumption...
    with pytest.raises(ConcurrencyLost):
        consumed.consume(expected_version=4)
    # ...but the original snapshot is still a valid value, which is exactly
    # why an in-memory check is not sufficient protection.
    assert p.consume(expected_version=3).status is PendingStatus.CONSUMED


def test_a_stale_version_is_refused():
    p = _pending(version=5)
    with pytest.raises(ConcurrencyLost) as e:
        p.consume(expected_version=4)
    assert "v4" in str(e.value) and "v5" in str(e.value)


def test_losing_raises_rather_than_returning_a_flag():
    """The failure mode of a missed check here is a double commit, so the caller
    must handle it explicitly instead of remembering to read a boolean."""
    p = _pending(status=PendingStatus.CONSUMED)
    with pytest.raises(ConcurrencyLost):
        p.consume(expected_version=1)


def test_a_partial_answer_keeps_the_row_open_but_still_moves_the_version():
    """"Elite" with no portion. The row stays open — and a second message
    racing the first is still rejected."""
    p = _pending(version=2)
    partial = p.partially_answered({"product_line": "Core Power Elite"},
                                   expected_version=2)
    assert partial.status.is_open
    assert partial.version == 3
    assert partial.payload["answered"]["product_line"] == "Core Power Elite"

    # An answer written against the pre-partial version is refused.
    with pytest.raises(ConcurrencyLost):
        partial.partially_answered({"consumed_fraction": 0.5},
                                   expected_version=2)


def test_partial_answers_accumulate():
    p = _pending(version=1)
    p = p.partially_answered({"product_line": "Elite"}, expected_version=1)
    p = p.partially_answered({"consumed_fraction": 0.5},
                             expected_version=p.version)
    assert p.payload["answered"] == {"product_line": "Elite",
                                     "consumed_fraction": 0.5}


def test_re_asking_bumps_the_version_so_an_in_flight_answer_cannot_land():
    """The answer to the PREVIOUS phrasing was written against v1. After the
    re-ask it must not apply."""
    p = _pending(version=1)
    reasked = p.with_attempt()
    assert reasked.attempt_count == 1 and reasked.version == 2
    with pytest.raises(ConcurrencyLost):
        reasked.consume(expected_version=1)


def test_a_cancelled_row_is_a_terminal_state():
    p = _pending().consume(expected_version=1,
                           status=PendingStatus.CANCELLED)
    assert p.status is PendingStatus.CANCELLED
    assert not p.status.is_open


# ── construction and persistence ──────────────────────────────────────────────
def test_opening_a_clarification_captures_the_held_items_and_questions():
    class _Q:
        def __init__(self, qid, fields):
            self.question_id = qid
            self.requested_fields = fields

    class _P:
        def __init__(self, item_id):
            self.staged_item_id = item_id

    class _Res:
        pending = (_P("i1"), _P("i2"))

    p = open_clarification(user_id=7, meal_group_id="meal_1", now=NOON,
                           resolution=_Res(),
                           questions=[_Q("q1", ("product_line",))],
                           turn_id="imessage:G-1", label="Fairlife")
    assert p.held_item_ids == ("i1", "i2")
    assert p.question_ids == ("q1",)
    assert p.requested_fields == {"q1": ("product_line",)}
    assert p.logical_meal_date == NOON.date()
    assert p.status is PendingStatus.ACTIVE


def test_clarification_ids_are_stable_per_meal_and_turn():
    a = make_clarification_id(7, "meal_1", "imessage:G-1")
    assert a == make_clarification_id(7, "meal_1", "imessage:G-1")
    assert a != make_clarification_id(7, "meal_2", "imessage:G-1")
    assert a != make_clarification_id(8, "meal_1", "imessage:G-1")


def test_it_round_trips_through_storage():
    p = _pending(version=4)
    restored = from_payload(p.to_payload(), user_id=7)
    assert restored.clarification_id == p.clarification_id
    assert restored.logical_meal_date == p.logical_meal_date
    assert restored.created_at == p.created_at
    assert restored.version == 4
    assert restored.requested_fields == {"q1": ("product_line",
                                                "consumed_fraction")}
    assert restored.held_item_ids == ("i1",)


def test_the_other_pending_kinds_are_never_read_as_a_meal():
    """The entity-bound nutrient kind and the plan-confirm kind must not cross
    into this store."""
    assert from_payload('{"kind": "nutrition", "target": {"entry_id": 4}}') is None
    assert from_payload('{"kind": "confirm", "items": []}') is None
    assert from_payload("not json at all") is None
    assert from_payload("") is None


def test_a_corrupt_row_is_none_rather_than_a_crash():
    """A malformed payload must not take down the turn that reads it."""
    assert from_payload('{"kind": "meal", "logical_meal_date": "nope"}') is None
    assert from_payload('{"kind": "meal"}') is None


def test_the_pending_kind_is_distinct_from_the_others():
    from core.pending_clarification import CLARIFY_KIND
    assert PENDING_KIND != CLARIFY_KIND
    assert PENDING_KIND == "food_meal_clarification"


# ── the atomic claim (build order 18) ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_exactly_one_caller_wins_the_claim(db, make_user):
    """The race the value object cannot arbitrate, arbitrated. Two messages
    two seconds apart both read an open row; the database decides."""
    from skills.nutrition import pending_store as PS
    user = await make_user()

    pending = open_clarification(user_id=user.id, meal_group_id="meal_race",
                                 now=NOON, label="Fairlife")
    assert await PS.save(db, pending)

    first = await PS.claim(db, pending)
    second = await PS.claim(db, pending)
    assert first is True
    assert second is False        # the loser is told, and must not proceed


@pytest.mark.asyncio
async def test_a_claim_that_cannot_be_attempted_reports_a_loss(db, make_user):
    """A caller that cannot PROVE it won must behave as though it lost —
    failing open here would be the double write."""
    from skills.nutrition import pending_store as PS
    user = await make_user()
    never_saved = open_clarification(user_id=user.id,
                                     meal_group_id="meal_missing", now=NOON)
    assert await PS.claim(db, never_saved) is False


@pytest.mark.asyncio
async def test_a_saved_row_round_trips_through_the_store(db, make_user):
    from skills.nutrition import pending_store as PS
    user = await make_user()
    pending = open_clarification(user_id=user.id, meal_group_id="meal_1",
                                 now=NOON, turn_id="imessage:G-1",
                                 label="Fairlife")
    assert await PS.save(db, pending)
    loaded = await PS.load_open(db, user.id)
    assert loaded is not None
    assert loaded.meal_group_id == "meal_1"
    assert loaded.logical_meal_date == NOON.date()
    assert loaded.status is PendingStatus.ACTIVE


@pytest.mark.asyncio
async def test_no_pending_row_is_a_cold_turn_not_a_failure(db, make_user):
    from skills.nutrition import pending_store as PS
    user = await make_user()
    assert await PS.load_open(db, user.id) is None


@pytest.mark.asyncio
async def test_a_claimed_row_is_no_longer_open(db, make_user):
    from skills.nutrition import pending_store as PS
    user = await make_user()
    pending = open_clarification(user_id=user.id, meal_group_id="meal_1",
                                 now=NOON)
    await PS.save(db, pending)
    await PS.claim(db, pending)
    assert await PS.load_open(db, user.id) is None
