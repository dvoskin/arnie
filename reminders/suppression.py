"""
Suppression — one-shot slot de-duplication.

Many proactive touchpoints fire at most once (the day-1 warmup burst, the
one-time city ask, the weekly recap). We persist which have fired in the
comma-separated `user.nudges_sent` string so they survive deploys. These helpers
are the read/write seam for that string — pure, so the scheduler's dedup logic is
testable without a User row.

(Per-question follow-up suppression — re-ask caps and spacing — lives in
reminders.pending, since it keys off PendingQuestion rows rather than slot flags.)
"""
from __future__ import annotations


def parse_slots(nudges_sent: str | None) -> set[str]:
    """Comma-separated slot string → set of fired slot keys (empties dropped)."""
    return set(s for s in (nudges_sent or "").split(",") if s)


def has_fired(nudges_sent: str | None, slot_key: str) -> bool:
    """True if `slot_key` has already been recorded as fired."""
    return slot_key in parse_slots(nudges_sent)


def add_slot(nudges_sent: str | None, slot_key: str) -> str:
    """
    Return a new nudges_sent string with `slot_key` recorded. Sorted + de-duped so
    the column is stable/diffable. Pure — the caller assigns + commits.
    """
    slots = parse_slots(nudges_sent)
    slots.add(slot_key)
    return ",".join(sorted(slots))
