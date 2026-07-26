"""Canonical turn identity (P0.1, architecture review 2026-07-24).

Arnie grew several overlapping duplicate-protections — iOS in-process locks,
ConversationLog.idempotency_key, text-window collapsing, the structured
ProcessedTurn claim, executor dedup — each keyed differently. This module is
the start of ONE transaction identity: every inbound message resolves to a
single canonical `turn_id`, and every write born from that turn can be traced
back to it (ledger_events.turn_id) and deduplicated by it (the structured
exactly-once claim keys on it when present).

The id prefers the CLIENT's message identity — iMessage message_guid,
Telegram message_id, the iOS idempotency UUID — because that is what a
transport retry preserves byte-for-byte. When no client id exists (webhooks
without ids, tests, internal turns) it falls back to a content hash bucketed
by hour: stable across an immediate retry, distinct across genuine repeats
on a later occasion.

Propagation is via a contextvar so the identity rides the whole turn (tool
execution, event recording) without threading a parameter through every
signature — run_turn sets it, record_ledger_event reads it, and it resets
when the turn ends. The legacy protections stay as inner nets; they are no
longer the identity.
"""
from __future__ import annotations

import hashlib
import time
from contextvars import ContextVar
from typing import Optional

# The turn currently executing in this task. Set by run_turn, read by the
# ledger event recorder; never survives past the turn (reset in finally).
CURRENT_TURN_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_TURN_ID",
                                                        default=None)

# True when this message was composed BEFORE the previous reply reached the
# user — they were still typing while the last turn was running, so whatever
# they sent cannot be an answer to it.
#
# Without this the model reads the transcript as a clean alternation and
# assumes every user message responds to the assistant message above it.
# Observed 2026-07-26: two messages sent back to back; reply 1 ended "training
# tonight, or is today shaping up to be a rest day?", and reply 2 opened
# "that's fine, rest days happen" — answering its own question, because
# "Just eating" landed after reply 1 was authored. Arnie held a conversation
# with himself and coached off the result.
#
# Debounce alone cannot fix this: the coalescing window is seconds while a
# pipeline run takes longer, and the debouncer deliberately never cancels a
# running turn — anything arriving mid-run becomes its own trailing turn with
# the previous reply already in history. So the surfaces that HAVE debounce
# hit this too, just less often than iOS, which has none.
PRIOR_REPLY_UNSEEN: ContextVar[bool] = ContextVar("PRIOR_REPLY_UNSEEN",
                                                  default=False)


def make_turn_id(channel: str, client_message_id: Optional[str],
                 user_id, text: str = "") -> str:
    """One canonical id per inbound message.

    channel: 'imessage' | 'telegram' | 'ios' | ... (scopes the client id —
    a Telegram message_id and an iMessage guid can never collide).
    client_message_id: the transport's stable per-message id, verbatim.
    Fallback: sha1 over (channel, user, text, hour bucket) — retries inside
    the hour dedupe, tomorrow's identical text is a new turn.
    """
    ch = (channel or "unknown").strip().lower()
    cid = (str(client_message_id).strip()
           if client_message_id not in (None, "") else "")
    if cid:
        return f"{ch}:{cid}"
    bucket = int(time.time() // 3600)
    digest = hashlib.sha1(
        f"{ch}|{user_id}|{(text or '').strip().lower()}|{bucket}"
        .encode("utf-8")).hexdigest()[:20]
    return f"{ch}:h:{digest}"


def current_turn_id() -> Optional[str]:
    return CURRENT_TURN_ID.get()
