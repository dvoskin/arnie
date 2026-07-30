"""Every turn names the build that produced it — including the quiet ones.

Invariant I1's measurable half. Over a 7-day production window, **130 turns
carried no `reasoning_json` at all**, and they were not scattered across the
population: they were three whole surfaces, each 100% blank.

    proactive        79 turns    0 with reasoning
    dashboard_edit   35 turns    0 with reasoning
    text             16 turns    0 with reasoning

A turn with no reasoning has no build stamp and no flags, so it is invisible to
every audit query in this repository. That is why the 79 proactive sends could
not be checked for delivery even in principle — and D2 found that roughly half
the users those sends target have no live push token.

The cause was one gate. `log_conversation` stamped the build under
`if reasoning:`, so any caller with nothing to add wrote NULL, while the
comment beside it described the site as "the single write site for
reasoning_json". It was the single write site; it just did not always write.

These tests go through `log_conversation` itself rather than any one surface,
because the fix is at the chokepoint and every surface inherits it.
"""
import json

import pytest

from db.models import ConversationLog
from db.queries import log_conversation


async def _row(db, user_id):
    from sqlalchemy import desc, select
    result = await db.execute(
        select(ConversationLog)
        .where(ConversationLog.user_id == user_id)
        .order_by(desc(ConversationLog.id)).limit(1))
    return result.scalars().first()


async def test_a_turn_with_no_receipt_still_names_its_build(db, make_user):
    """The proactive case: nothing to disclose, and still auditable."""
    user = await make_user()
    await log_conversation(db, user.id, raw_message="", response="you're at 619 cal",
                           source_type="proactive", skills_fired="preworkout")

    row = await _row(db, user.id)
    assert row.reasoning_json, "a proactive send landed with no reasoning at all"
    assert json.loads(row.reasoning_json)["build"]["sha"]


@pytest.mark.parametrize("source_type", ["proactive", "dashboard_edit", "text",
                                         "ios", "voice", "photo"])
async def test_every_surface_lands_a_stamped_row(db, make_user, source_type):
    """All three blank surfaces, and the ones that were already fine."""
    user = await make_user()
    await log_conversation(db, user.id, raw_message="x", response="y",
                           source_type=source_type)

    row = await _row(db, user.id)
    assert row.reasoning_json, f"{source_type} wrote no reasoning"
    assert "sha" in json.loads(row.reasoning_json)["build"]


async def test_a_caller_with_a_receipt_keeps_every_field(db, make_user):
    """The stamp is additive. A receipt that lost its route on the way to the
    database would trade one blind spot for another."""
    user = await make_user()
    receipt = {"route": {"lane": "structured_log", "owner": "gate_regex"},
               "steps": ["interpret", "execute"], "duration_ms": 1234}
    await log_conversation(db, user.id, raw_message="had eggs", response="logged",
                           source_type="ios", reasoning=receipt)

    stored = json.loads((await _row(db, user.id)).reasoning_json)
    assert stored["route"] == receipt["route"]
    assert stored["steps"] == receipt["steps"]
    assert stored["duration_ms"] == 1234
    assert stored["build"]["sha"]


async def test_the_callers_dict_is_not_mutated(db, make_user):
    """`build` belongs to the row, not to the caller's object — which may be
    the live turn trace still in use further up the stack."""
    user = await make_user()
    receipt = {"route": {"lane": "legacy"}}
    await log_conversation(db, user.id, raw_message="hi", response="hey",
                           source_type="ios", reasoning=receipt)
    assert "build" not in receipt


async def test_no_route_is_invented_for_a_turn_that_never_routed(db, make_user):
    """A proactive send made no routing decision, and a fabricated route would
    poison exactly the analytics D5 exists to repair. An empty receipt that
    names its build is honest; an invented one is not."""
    user = await make_user()
    await log_conversation(db, user.id, raw_message="", response="nudge",
                           source_type="proactive", skills_fired="checkin")

    stored = json.loads((await _row(db, user.id)).reasoning_json)
    assert "route" not in stored
    assert set(stored) == {"build"}
