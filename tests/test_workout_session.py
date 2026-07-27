"""A WORKOUT IS A THING; until now only its sets were.

`exercise_entries` stores one row per logged set and nothing bound those rows
into an exercise or a session. Five rows of `sets=1` for the same movement,
minutes apart, are one exercise inside one workout — and because nothing said
so, cross-source dedup ended up guessing at "starts within 30 min, durations
within 40%", and a rest timer had nothing to attach to.

Measured against production before this landed: 528 exercise entries, 3 ledger
events. Food had 217 for a comparable volume. The `domain` column was built for
this from the start and fitness was never wired in.

These tests pin the CONTRACT — a set joins the session underway, a cold start
opens a new one, and the session reads back as a session. The gap threshold
itself lives in `db/queries.WORKOUT_SESSION_GAP_MINUTES` and is a claim about
training, not about text.
"""
from datetime import datetime, timedelta

import pytest

from db.queries import (WORKOUT_SESSION_GAP_MINUTES, new_workout_group_id)


def test_a_session_id_is_opaque():
    """It carries identity, not meaning. Anything parseable invites a reader to
    reconstruct the workout from the id instead of from the rows."""
    a, b = new_workout_group_id(), new_workout_group_id()
    assert a != b
    assert a.startswith("wk_")
    assert len(a) > 10
    # no date, no user, no exercise — nothing to parse back out
    assert not any(ch.isspace() for ch in a)


def test_the_gap_is_long_enough_for_real_rest_and_short_enough_to_split_days():
    """Sets inside a session are separated by rest, and rest is minutes. A
    threshold under ~an hour would split a long leg session into several
    workouts; one over a few hours would merge a morning and evening session."""
    assert 60 <= WORKOUT_SESSION_GAP_MINUTES <= 240


class _Row:
    def __init__(self, gid, ts):
        self.workout_group_id, self.timestamp = gid, ts


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _DB:
    """Just enough session to answer the one query `current_workout_group`
    makes — the point under test is the recency rule, not SQLAlchemy."""

    def __init__(self, row):
        self._row = row

    async def execute(self, *a, **k):
        return _Result(self._row)


@pytest.mark.asyncio
async def test_a_set_logged_mid_workout_joins_the_session_underway():
    from db.queries import current_workout_group
    recent = datetime.utcnow() - timedelta(minutes=4)
    got = await current_workout_group(_DB(("wk_abc123", recent)), user_id=1)
    assert got == "wk_abc123"


@pytest.mark.asyncio
async def test_a_set_after_a_long_silence_starts_a_new_session():
    """Two hours of quiet is a different workout even when the movement
    repeats — which is exactly the case similarity matching cannot call."""
    from db.queries import current_workout_group
    stale = datetime.utcnow() - timedelta(
        minutes=WORKOUT_SESSION_GAP_MINUTES + 30)
    assert await current_workout_group(_DB(("wk_abc123", stale)),
                                       user_id=1) is None


@pytest.mark.asyncio
async def test_a_user_who_has_never_trained_is_not_mid_session():
    from db.queries import current_workout_group
    assert await current_workout_group(_DB(None), user_id=1) is None


@pytest.mark.asyncio
async def test_historic_rows_without_a_session_are_never_adopted():
    """NULL group means "no session we can honestly reconstruct". Treating one
    as current would attach today's sets to a workout from June."""
    from db.queries import current_workout_group
    recent = datetime.utcnow() - timedelta(minutes=2)
    assert await current_workout_group(_DB((None, recent)),
                                       user_id=1) is None
