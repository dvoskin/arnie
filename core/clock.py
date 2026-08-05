"""One clock: the database's, readable from Python without a round trip.

STEP 2 of docs/ONE_CLOCK_MIGRATION.md. Step 1 pinned every session to UTC,
which made the two clocks AGREE about the zone. It did not make them ONE
clock — the application host and the database host still keep time separately,
bounded by NTP at seconds rather than hours, and unbounded if NTP fails on
either.

WHY THE DATABASE WINS. Not preference — measurement. Every one of the 17
freshness comparisons in this codebase reads a timestamp that the DATABASE
wrote (`server_default=func.now()`) and compares it against `datetime.utcnow()`.
All 17 are cross-domain, and the values themselves live in the database, so the
database is the only candidate that makes the two sides of every comparison
agree by construction.

HOW, WITHOUT PAYING FOR IT. Computing every age in SQL would mean rewriting
comparisons that operate on already-loaded objects — `core/llm.py` holds a
`User` and asks how old the account is; there is no query there to extend. And
`SELECT now()` per comparison would put a round trip inside scheduler loops.

So the offset between the two clocks is MEASURED once and applied everywhere:

    clock.now() == datetime.utcnow() + (db_now - app_now)

which is the database's clock, arrived at by arithmetic instead of I/O.

THE DEFAULT IS SAFE. Before the first `sync()`, the offset is zero and `now()`
is exactly `datetime.utcnow()` — today's behaviour, unchanged. A deployment
that never syncs is no worse off than before this module existed, which is what
makes it adoptable one caller at a time without a flag.

SKEW BECOMES VISIBLE. The measurement is the point as much as the correction:
a drifting host is currently silent, and would stay silent under any scheme
that simply picked one clock and trusted it. `sync()` logs the offset, and
anything past `SKEW_ALERT_SECONDS` is logged as a fault — that is NTP failing,
and it is worth knowing before a 90-second staleness threshold starts lying.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

#: Past this, the hosts are not merely imprecise — something is wrong. The
#: tightest threshold that depends on this is `STALE_CLAIM_SECONDS = 90`, so
#: the alert has to fire well below it to be worth anything.
SKEW_ALERT_SECONDS = 5.0

_lock = threading.Lock()
_offset = timedelta(0)
_synced_at: Optional[datetime] = None
_last_skew: Optional[float] = None


def now() -> datetime:
    """The database's current time, naive UTC.

    A drop-in for `datetime.utcnow()` at every site that compares against a
    database-written timestamp. Cheap by construction — no I/O — because it is
    called inside scheduler loops and per board item.
    """
    with _lock:
        return datetime.utcnow() + _offset


def skew_seconds() -> Optional[float]:
    """How far the application host is from the database host, or None if it
    has never been measured. None is not zero, and callers that report health
    must not print one as the other."""
    with _lock:
        return _last_skew


def synced_at() -> Optional[datetime]:
    with _lock:
        return _synced_at


async def sync(db) -> Optional[float]:
    """Measure the offset against the database. Returns it, or None.

    Never raises: a clock measurement that fails must not take down the caller
    that asked for it, and failing leaves the previous offset in place rather
    than resetting to zero — a stale correction is closer than none.
    """
    global _offset, _synced_at, _last_skew
    try:
        from sqlalchemy import text

        bind = (getattr(db, "bind", None)
                or getattr(db, "engine", None)
                or getattr(db, "get_bind", lambda: None)())
        dialect = getattr(getattr(bind, "dialect", None), "name", "")
        if dialect and dialect != "postgresql":
            # sqlite has no server clock distinct from ours — it runs in this
            # process. Measuring would report our own clock as the reference
            # and imply a guarantee that does not exist here.
            return None

        before = datetime.utcnow()
        db_time = (await db.execute(text("SELECT now()::timestamp"))).scalar()
        after = datetime.utcnow()
    except Exception as exc:
        logger.warning("event=clock_sync outcome=error error=%s: %s — keeping "
                       "the previous offset", type(exc).__name__, str(exc)[:160])
        return None
    if db_time is None:
        return None

    # The round trip straddles the reading, so the honest comparison point is
    # the midpoint of the request rather than either end. Without this the
    # measured skew carries the query's own latency as if it were drift.
    midpoint = before + (after - before) / 2
    offset = db_time - midpoint
    seconds = offset.total_seconds()

    with _lock:
        _offset, _synced_at, _last_skew = offset, datetime.utcnow(), seconds

    if abs(seconds) >= SKEW_ALERT_SECONDS:
        logger.error(
            "event=clock_sync outcome=skewed offset_s=%.3f threshold_s=%.1f — "
            "the application and database hosts disagree by more than NTP "
            "should allow; freshness comparisons are being corrected but the "
            "cause is worth finding", seconds, SKEW_ALERT_SECONDS)
    else:
        logger.info("event=clock_sync outcome=ok offset_s=%.3f", seconds)
    return seconds


def reset() -> None:
    """Tests only."""
    global _offset, _synced_at, _last_skew
    with _lock:
        _offset, _synced_at, _last_skew = timedelta(0), None, None
