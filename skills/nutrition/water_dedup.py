"""
Server-side guard against re-log-on-context-shift for water entries.

Same failure mode as food/exercise: model carries chat-history context of a
prior log forward, then re-fires the tool when the user pivots topic. For
water the damage is total_water_ml getting silently inflated on DailyLog,
distorting hydration coaching downstream.

Window: 60 minutes. Tighter than food (90 min) because water re-logging at
short intervals is more common in reality (people sip throughout the day,
log multiple times an hour), so the false-positive risk is higher with a
longer window. 60 min is enough to catch the model-pivot re-log without
blocking a real second drink within the hour.

Match key: amount_ml within ±30ml + same context bucket. The 30ml slack
absorbs unit-conversion rounding (16oz → 473.18ml vs 16oz → 473ml).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional


def _ml_close(a: Optional[float], b: Optional[float], tol_ml: float = 30) -> bool:
    """Both None → match. Either-None → no match. Otherwise within tol_ml."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol_ml
    except (TypeError, ValueError):
        return False


def _ctx_equal(a: Optional[str], b: Optional[str]) -> bool:
    """Normalize None / '' / 'random' as the same bucket (default context
    when caller omits it). Otherwise exact string match on the enum value."""
    aa = (a or "random").strip().lower()
    bb = (b or "random").strip().lower()
    return aa == bb


def is_duplicate_water(
    *,
    amount_ml: Optional[float],
    context: Optional[str],
    existing_entries: Iterable,
    now_utc: datetime,
    window_sec: int = 3600,  # 60 minutes
):
    """Return the most-recent matching water entry within window_sec, or None.

    Match key: close amount_ml (±30ml) + same context bucket. Both must
    agree. Caller is responsible for snapshot filtering (only entries that
    existed BEFORE this tool batch).
    """
    if amount_ml is None:
        return None
    cutoff = now_utc - timedelta(seconds=window_sec)
    candidates = []
    for e in existing_entries:
        ts = getattr(e, "timestamp", None)
        if ts is None:
            continue
        candidates.append((ts, e))
    candidates.sort(key=lambda pair: pair[0], reverse=True)

    for ts, e in candidates:
        if ts < cutoff:
            break
        if not _ml_close(getattr(e, "amount_ml", None), amount_ml):
            continue
        if not _ctx_equal(getattr(e, "context", None), context):
            continue
        return e
    return None


def format_dedup_result(dup, now_utc: datetime) -> str:
    """'Already on the board: ...' tool-result string for the executor."""
    amt = getattr(dup, "amount_ml", None) or 0
    age_sec = max(0, int((now_utc - dup.timestamp).total_seconds()))
    age_part = (
        f"{age_sec}s ago" if age_sec < 90
        else f"{age_sec // 60} min ago"
    )
    return (
        f"Already on the board: water ({round(amt)}ml). "
        f"Logged as [#{dup.id}] {age_part}. "
        f"YOUR REPLY: do NOT emit a fresh log line — already saved. "
        f"acknowledge briefly if relevant and continue. never tell the "
        f"user a log was skipped."
    )
