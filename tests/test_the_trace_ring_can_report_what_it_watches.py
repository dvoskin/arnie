"""The diagnostic endpoint must be able to return the events it is asked for.

COST A DAY, 2026-08-05. `_EVENT_RE` was `\\bevent=([a-z_]+)` — no digits — so
`event=b1_shown` was captured under the event name `"b"`, which is not in
`WATCHED` and was discarded. Every `b1_*` event was emitted correctly by
production and dropped here.

Then `/admin/food-traces?event=b1_shown` returned `matched: 0`, and I read that
as evidence about B-1's BEHAVIOUR — across several rounds of diagnosis, in a
commit message, and in two wrong conclusions about which code path production
takes. The endpoint could not have returned those events under any allowlist.

THE GENERAL SHAPE, which is the reason this file exists rather than a one-line
regex fix: a filter that silently renames what it cannot parse reports
"nothing happened" for "I could not read it". Those must never look alike —
it is the same defect `/health` had when it flattened B1_QUANTITY to nulls,
and the same one the B-1 probe's `unevaluated` verdict exists to prevent.
"""
import logging

import pytest

from core import trace_buffer


@pytest.fixture(autouse=True)
def _clean_ring():
    trace_buffer.install()
    trace_buffer._lines.clear()
    yield
    trace_buffer._lines.clear()


def _emit(*messages, logger_name="core.b1_metrics"):
    log = logging.getLogger(logger_name)
    log.setLevel(logging.INFO)
    for m in messages:
        log.info(m)


@pytest.mark.parametrize("event", [
    "b1_shown", "b1_declined", "b1_no_material", "b1_committed",
    "b1_abandoned", "b1_corrected", "b1_ownership_unknown",
])
def test_an_event_name_containing_a_digit_survives_capture(event):
    """`[a-z_]+` stopped at the first digit and captured `b1_shown` as `b`."""
    _emit(f"event={event} user=26 detail=x")
    assert [l["event"] for l in trace_buffer.recent(limit=10)["lines"]] == [event]


def test_the_endpoint_can_filter_by_a_digit_bearing_event():
    """Capturing it is half the job — the query has to find it too."""
    _emit("event=b1_shown operation=op_1 user=26",
          "event=turn_trace telegram:26 route=structured_ask")
    found = trace_buffer.recent(event="b1_shown", limit=10)["lines"]
    assert len(found) == 1
    assert "operation=op_1" in found[0]["message"]


def test_a_new_event_family_is_visible_without_editing_a_list():
    """An allowlist is a trap for new events: the family stays invisible until
    somebody remembers to add it, and its silence reads as absence. The prefix
    rule is what stops the next one costing another day."""
    _emit("event=b1_some_event_added_next_month user=26")
    assert trace_buffer.recent(limit=5)["lines"], \
        "a b1_* event must not need a WATCHED entry to be seen"


def test_an_unwatched_family_is_still_excluded():
    """The prefix rule widens what is watched; it must not watch everything —
    this handler runs on every food turn."""
    _emit("event=totally_unrelated_subsystem x=1")
    assert not trace_buffer.recent(limit=5)["lines"]


def test_the_established_events_still_capture():
    """The fix must not narrow what already worked."""
    _emit("event=turn_trace telegram:26 route=structured_ask",
          "event=canonical_meal_written operation=q lane=canonical:create",
          "event=structured_food action=ask telegram:26")
    assert {l["event"] for l in trace_buffer.recent(limit=10)["lines"]} == {
        "turn_trace", "canonical_meal_written", "structured_food"}


def test_every_event_this_repo_emits_can_be_captured():
    """The check that would have caught it at authoring time: scan the source
    for `event=` names and assert the regex can read each one back.

    Not a list to maintain — derived from the code, so a name the ring cannot
    parse fails here rather than in production three deploys later.
    """
    import pathlib
    import re

    emitted = set()
    root = pathlib.Path(__file__).resolve().parent.parent
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/")):
            continue
        # Lowercase only: the ring's convention, and it excludes Python
        # kwargs like `event=CanonicalEvent(...)` which are not log events.
        for name in re.findall(r'event=([a-z][a-z0-9_]*)', path.read_text()):
            emitted.add(name)

    unreadable = [n for n in emitted
                  if (trace_buffer._EVENT_RE.search(f"event={n}") or
                      type("m", (), {"group": lambda s, i: None})()
                      ).group(1) != n]
    assert not unreadable, (
        f"the ring's regex cannot read these event names back: "
        f"{sorted(unreadable)} — they would be captured under a truncated "
        f"name and silently dropped"
    )
