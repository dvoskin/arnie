"""
Shared conversation-history rendering — the single place that turns
ConversationLog rows into the chat message list both handlers feed to the LLM.

Pure function over rows: it does NOT touch the DB. The handlers still own
fetching (via db.queries.get_recent_conversations) and everything else they do
(the current-message append, extended/limit logic). This module owns only the
row → message transform, so the two handlers stay byte-identical for it.

DAY MARKERS — why they exist:
Past turns used to be fed to the model as plain user/assistant messages with
NO temporal context, so a turn from 2 days ago looked identical to one from
5 minutes ago. That made the model treat stale facts as current ("add this to
the water you logged today" when the last water was 2 days back). We now prefix
the FIRST turn of each distinct local day with a marker like "[Yesterday,
2026-06-26]" / "[3 days ago, …]" / "[Today, …]" so the model can place every
turn in time. Markers only appear when a row carries a usable ``timestamp`` and
a timezone is supplied — callers without timestamps (e.g. unit tests) are
unaffected.
"""
from __future__ import annotations

from datetime import datetime

import pytz


def _day_label(turn_date, today_date) -> str:
    """Human day marker relative to the user's local 'today'."""
    diff = (today_date - turn_date).days
    iso = turn_date.isoformat()
    if diff <= 0:
        return f"[Today, {iso}]"
    if diff == 1:
        return f"[Yesterday, {iso}]"
    return f"[{diff} days ago, {iso}]"


def conversations_to_messages(rows, user_timezone: str = "UTC", now=None) -> list[dict]:
    """Render ConversationLog rows into LLM-ready chat messages.

    CONTRACT: accepts rows **newest-first** (as returned by get_recent_conversations).
    Reverses internally to produce oldest-first chat order — callers must NOT call
    reversed() themselves. This is the single point of reversal; both handlers pass
    rows directly from the DB query.

    Normal row -> [{"role":"user","content":raw_message}, {"role":"assistant","content":response}].
    A proactive row (source_type == "proactive") has NO triggering user message -> emit a SINGLE
    {"role":"assistant","content": f"(I checked in:) {response}"} turn (never a synthetic empty user turn).

    ``user_timezone`` / ``now`` drive the day markers (see module docstring). When a
    row has no ``timestamp`` attribute, no marker is added — keeping the transform
    a pure pass-through for callers that don't supply timestamps.
    """
    try:
        tz = pytz.timezone(user_timezone or "UTC")
    except Exception:
        tz = pytz.utc
    now_local = (now.astimezone(tz) if now is not None else datetime.now(tz))
    today_local = now_local.date()

    def _local_date(conv):
        ts = getattr(conv, "timestamp", None)
        if ts is None:
            return None
        try:
            if ts.tzinfo is None:
                ts = pytz.utc.localize(ts)
            return ts.astimezone(tz).date()
        except Exception:
            return None

    msgs: list[dict] = []
    last_date = None
    for conv in reversed(rows):  # newest-first in → oldest-first out
        d = _local_date(conv)
        marker = None
        if d is not None and d != last_date:
            marker = _day_label(d, today_local)
            last_date = d

        if getattr(conv, "source_type", None) == "proactive":
            content = f"(I checked in:) {conv.response or ''}"
            if marker:
                content = f"{marker} {content}"
            msgs.append({"role": "assistant", "content": content})
        else:
            user_msg = conv.raw_message or ""
            if marker:
                user_msg = f"{marker} {user_msg}" if user_msg else marker
            msgs.append({"role": "user", "content": user_msg})
            msgs.append({"role": "assistant", "content": conv.response or ""})
    return msgs
