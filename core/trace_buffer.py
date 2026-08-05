"""The last N structured-food trace lines, readable over HTTP.

Every shadow landed in this migration emits telemetry — `identity_shadow`,
`clarification_shadow`, `refinement_refused`, `none_reason` on the fallback —
and none of it was readable by anyone without Render dashboard access. A shadow
whose output nobody can see measures nothing, which is the same failure as an
audit that under-reports: it says the work is being graded when it is not.

So the lines are kept in a bounded in-process ring and served behind the admin
token that already exists.

WHAT THIS IS NOT, stated here and REPORTED IN THE RESPONSE, because a partial
view mistaken for a complete one is exactly how the conversion audit missed
four weight-write paths:

  * PER PROCESS. With more than one worker you see one worker's lines. The
    same limitation as `food_ledger._SEEN`, and for the same reason — there is
    no shared store behind it.
  * LOST ON RESTART. A deploy empties it.
  * BOUNDED. Old lines are evicted silently by the ring; `dropped` counts them
    so a reader can tell "nothing happened" from "it scrolled past".

None of that makes it useless. It makes it a sample, and a sample that says so
is worth more than a log nobody can reach.
"""
from __future__ import annotations

import collections
import logging
import re
import threading
import time
from typing import Optional

#: Kept deliberately small. This is a diagnostic window, not storage, and an
#: unbounded buffer on a food turn is a memory leak with a nice name.
MAX_LINES = 2000

#: Only lines carrying a structured `event=` key. Prose log lines are noise
#: here and would evict the signal.
#: DIGITS ARE PART OF AN EVENT NAME. `[a-z_]+` stopped at the first digit, so
#: `event=b1_shown` was captured as the event `"b"` — not in WATCHED, so
#: silently discarded. Every b1_* event was emitted correctly, dropped here,
#: and its absence from `/admin/food-traces` was then read as evidence that
#: B-1 never ran. It cost a day of diagnosis and two wrong conclusions.
#:
#: The endpoint could not have returned those events under ANY allowlist,
#: which is the part worth remembering: a filter that silently renames what it
#: cannot parse reports "nothing happened" for "I could not read it".
_EVENT_RE = re.compile(r"\bevent=([a-z][a-z0-9_]*)")

#: The events this buffer exists to make readable. An allowlist rather than
#: "everything with event=", so a chatty new logger cannot silently push the
#: shadows out of the window.
WATCHED = frozenset({
    "identity_shadow", "clarification_shadow", "refinement_refused",
    "identity_preserved", "deferred_collapse", "deferred_commit",
    "structured_food", "structured_food_fallback", "turn_trace",
    "food_composer", "identity_shadow_disagree",
    "canonical_shadow", "canonical_meal_written",
    # B-1. AN ALLOWLIST IS A TRAP FOR NEW EVENTS, and this one caught me:
    # six b1_* events were emitted correctly for a day and dropped here at
    # the `not in WATCHED` line, and I read the resulting `matched: 0` as
    # evidence about B-1's BEHAVIOUR across several rounds of diagnosis —
    # including in a commit message asserting it "produced zero events".
    #
    # An endpoint that cannot return an event reports its absence exactly
    # like an event that never happened. That is the same cannot-say defect
    # /health had, for the third time in this slice, which is the argument
    # for a prefix rule rather than a list somebody must remember to edit.
    "b1_shown", "b1_declined", "b1_no_material", "b1_owns_turn",
    "b1_answered", "b1_committed", "b1_abandoned", "b1_corrected",
    "b1_answer_failed", "b1_ownership_unknown", "b1_operation_corrupt",
    "b1_failed", "b1_cancelled", "b1_replayed", "b1_interaction_shown",
    "b1_sweep", "b1_not_in_cohort", "b1_answer",
})

#: Any event whose name starts with one of these is watched without needing
#: to be listed. The list above stays for the established names; this is what
#: stops the next new event family from being invisible until somebody
#: notices — which took a day for `b1_*`.
WATCHED_PREFIXES = ("b1_", "canonical_")

_lock = threading.Lock()
_lines: collections.deque = collections.deque(maxlen=MAX_LINES)
_dropped = 0
_installed = False


class _RingHandler(logging.Handler):
    """Cheap by design: a regex on the formatted message and a deque append.

    This runs on every food turn, so anything expensive here is latency the
    user pays for a diagnostic they cannot see.
    """

    def emit(self, record: logging.LogRecord) -> None:
        global _dropped
        try:
            msg = record.getMessage()
            match = _EVENT_RE.search(msg)
            if match is None:
                return
            event = match.group(1)
            if event not in WATCHED and not event.startswith(WATCHED_PREFIXES):
                return
            entry = {"ts": record.created, "event": match.group(1),
                     "level": record.levelname, "logger": record.name,
                     "message": msg[:1000]}
            with _lock:
                if len(_lines) == _lines.maxlen:
                    _dropped += 1
                _lines.append(entry)
        except Exception:      # a diagnostic may never break the turn it traces
            pass


def install() -> bool:
    """Attach the handler once. Returns whether it is now active.

    Idempotent because app startup is not guaranteed to happen once — a
    reloader, a test client and a worker fork can all reach it.
    """
    global _installed
    with _lock:
        if _installed:
            return True
        handler = _RingHandler(level=logging.INFO)
        logging.getLogger().addHandler(handler)
        _installed = True
        return True


def recent(*, since_seconds: Optional[float] = None,
           event: str = "", limit: int = 200) -> dict:
    """The window, newest last, with its own limits attached.

    `truncated` and `dropped` are part of the answer rather than a footnote:
    a reader who cannot tell "nothing happened" from "it scrolled past" will
    conclude the first, and that is how a quiet failure reads as success.
    """
    cutoff = time.time() - since_seconds if since_seconds else None
    with _lock:
        rows = list(_lines)
        dropped = _dropped
    if cutoff is not None:
        rows = [r for r in rows if r["ts"] >= cutoff]
    if event:
        rows = [r for r in rows if r["event"] == event]
    total = len(rows)
    rows = rows[-max(1, min(limit, MAX_LINES)):]
    counts: collections.Counter = collections.Counter(r["event"] for r in rows)
    return {
        "lines": rows,
        "returned": len(rows),
        "matched": total,
        "truncated": total > len(rows),
        "dropped_from_ring": dropped,
        "capacity": MAX_LINES,
        "installed": _installed,
        "by_event": dict(counts),
        "caveats": [
            "per-process: with more than one worker this is one worker's view",
            "lost on restart",
            f"bounded at {MAX_LINES} lines; dropped_from_ring counts evictions",
        ],
    }


def reset() -> None:
    """Tests only."""
    global _dropped
    with _lock:
        _lines.clear()
        _dropped = 0
