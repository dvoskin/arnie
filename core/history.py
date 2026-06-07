"""
Shared conversation-history rendering — the single place that turns
ConversationLog rows into the chat message list both handlers feed to the LLM.

Pure function over rows: it does NOT touch the DB. The handlers still own
fetching (via db.queries.get_recent_conversations) and everything else they do
(the current-message append, extended/limit logic). This module owns only the
row → message transform, so the two handlers stay byte-identical for it.
"""
from __future__ import annotations


def conversations_to_messages(rows) -> list[dict]:
    """Render ConversationLog rows into LLM-ready chat messages.

    CONTRACT: accepts rows **newest-first** (as returned by get_recent_conversations).
    Reverses internally to produce oldest-first chat order — callers must NOT call
    reversed() themselves. This is the single point of reversal; both handlers pass
    rows directly from the DB query.

    Normal row -> [{"role":"user","content":raw_message}, {"role":"assistant","content":response}].
    A proactive row (source_type == "proactive") has NO triggering user message -> emit a SINGLE
    {"role":"assistant","content": f"(I checked in:) {response}"} turn (never a synthetic empty user turn).
    """
    msgs: list[dict] = []
    for conv in reversed(rows):  # newest-first in → oldest-first out
        if getattr(conv, "source_type", None) == "proactive":
            msgs.append({
                "role": "assistant",
                "content": f"(I checked in:) {conv.response or ''}",
            })
        else:
            msgs.append({"role": "user", "content": conv.raw_message or ""})
            msgs.append({"role": "assistant", "content": conv.response or ""})
    return msgs
