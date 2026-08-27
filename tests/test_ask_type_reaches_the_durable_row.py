"""Every canonical ask type survives the REAL persistence path.

⭐ NOT A FAKE LOGGING PATH (Danny, 2026-08-27). These write through
`db.queries.record_pending_question` and the same `payload_json` shape
`core/conversation.py` writes, then read the row back the way a production
consumer would. Types that a live turn already proved are marked below; the
rest are pinned here because they were not elicitable on demand — not because
a shortcut was taken.

PROVEN BY LIVE TURN under production config, 2026-08-27 (durable row read back):
    menu_size            "A McDonald's Big Mac and fries"
    continuous_portion   "8 oz grilled salmon with a side of white rice"
    preparation_fat      "8 oz sirloin, a loaded baked potato, and a Caesar salad"
    compound             "A bowl of oatmeal" -> [continuous_portion, preparation_fat]

⛔ portion_multiplier WAS NOT REACHABLE. The Panda Bigger Plate probe -- the
utterance that produces "regular single scoop, or did you double it up?" --
called the typing helper with an EMPTY `ambiguities` list: the interpreter asked
the question without recording what was ambiguous. No interpreter field maps to
PORTION_MULTIPLIER today, so the constant exists in the vocabulary but nothing
produces it. Registered, not papered over.
"""
from __future__ import annotations

import json

import pytest

from skills.nutrition import ask_type as AT

pytestmark = pytest.mark.asyncio


async def _write_and_read(db, uid, types):
    """The SAME shape core/conversation.py writes on the structured lane."""
    from db.queries import record_pending_question
    from core.food_turn import ASK_KIND
    pq = await record_pending_question(
        db, uid, kind=ASK_KIND, question="pinned", tier="food_clarification",
        hook_style="question")
    pq.payload_json = json.dumps({"original": "", "question": "pinned",
                                  "ask_types": list(types)})
    await db.commit()
    from sqlalchemy import select
    from db.models import PendingQuestion
    row = (await db.execute(select(PendingQuestion)
           .where(PendingQuestion.id == pq.id))).scalar_one()
    return (json.loads(row.payload_json or "{}") or {}).get("ask_types")


@pytest.mark.parametrize("t", [t for t in AT.ALL if t != AT.UNCLASSIFIED])
async def test_each_canonical_type_survives_the_durable_round_trip(db, make_user, t):
    assert await _write_and_read(db, (await make_user(telegram_id=f"at-{t}")).id, [t]) == [t]


async def test_a_COMPOUND_ask_survives_with_every_type_intact(db, make_user):
    """⭐ Asks are compound — case 2 asks identity, consumption, extras and
    portion in one turn. A persistence path that keeps only the first type
    would discard most of what was asked, and the discarded part is exactly
    what a per-type policy needs."""
    types = [AT.CONTINUOUS_PORTION, AT.CONSUMPTION_COMPLETE,
             AT.UNSTATED_EXTRAS, AT.IDENTITY_VARIANT]
    assert await _write_and_read(db, (await make_user(telegram_id="at-compound")).id, types) == types


async def test_consumption_complete_survives_AS_ITSELF(db, make_user):
    """⛔ THE NEGATIVE INVARIANT AT THE STORAGE LAYER. If persistence ever
    collapsed this into a portion type, a defaulting policy reading the row
    would silently acquire licence over user state it can never know."""
    got = await _write_and_read(db, (await make_user(telegram_id="at-consume")).id,
                               [AT.CONSUMPTION_COMPLETE])
    assert got == [AT.CONSUMPTION_COMPLETE]
    assert not set(got) & set(AT.DEFAULTABLE_CANDIDATES)


async def test_the_tool_path_writes_the_SAME_canonical_vocabulary(db, make_user):
    """The second producer. Its enum is now sourced from the one vocabulary, so
    a value it writes must be readable as canonical without translation."""
    import core.tools as T
    tool = next(x for x in T.ALL_TOOLS if x.get("name") == "note_food_clarification")
    # ⚠ THE TOOL PATH DOES NOT WRITE payload_json -- deliberately. See the
    # comment at its record site: adding that write breaks the
    # pending-mutation ratchet, and the tool path carries ~1 of 27 asks. Its
    # canonical value rides the existing `tier` piggyback. What must hold is
    # that every value it can write IS canonical and round-trips unchanged.
    for kind in tool["input_schema"]["properties"]["kind"]["enum"]:
        assert kind in AT.ALL, kind
        assert AT.classify(kind) in AT.ALL
        uid = (await make_user(telegram_id=f"at-{kind}")).id
        assert await _write_and_read(db, uid, [kind]) == [kind]
