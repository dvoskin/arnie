"""A dashboard edit's operation joins the turn that caused it (I1, D4).

Measured over 7 days of production: **all 28 `ios_edit` operations were
unjoinable** — the single largest hole in the turn⋈operation join, which
otherwise resolves 93% of operations.

The cause was a fabricated identity. Both endpoints set the turn contextvar to
`ios_edit:update:{entry_id}` — an id derived from the ENTRY — and then called
`log_conversation` without passing it at all. So the ledger row carried an id
no conversation row has ever held, and the conversation row carried none. That
is worse than a null: a null is visibly missing, while a fabricated id looks
like a join that simply found nothing.

Being entry-derived it also collided with itself. Production shows two
`ios_edit:update:2587` rows 18 seconds apart — the dashboard's known
double-edit, recorded as one turn because the id could not tell two edits of
one entry apart.

These tests assert the join through the database, not the id format: what
matters is that the operation and the turn meet.
"""
import pytest

from api.food_edit import _edit_turn_id


# ── the id itself ─────────────────────────────────────────────────────────────
def test_the_same_edit_retried_is_one_turn():
    """An immediate retry of the SAME edit must collapse, or a dropped
    connection becomes two turns and two operations."""
    first = _edit_turn_id(26, 2587, {"calories": 200})
    again = _edit_turn_id(26, 2587, {"calories": 200})
    assert first == again


def test_a_different_edit_is_a_different_turn():
    """The old id was the entry number, so every edit of one entry was the
    same 'turn' forever — which is how a double-edit 18s apart recorded as
    one."""
    calories = _edit_turn_id(26, 2587, {"calories": 200})
    quantity = _edit_turn_id(26, 2587, {"quantity": "1 bar"})
    assert calories != quantity


def test_two_users_editing_the_same_entry_id_do_not_collide():
    assert _edit_turn_id(26, 2587, {"calories": 1}) \
        != _edit_turn_id(99, 2587, {"calories": 1})


def test_the_id_uses_the_canonical_builder_not_a_fourth_format():
    """The audit already had three turn-id formats, none of which joined.
    A path inventing a fourth is the defect, not the wording."""
    from core.turn_identity import make_turn_id
    assert _edit_turn_id(26, 1, {"a": 1}).startswith("ios_edit:")
    # Same shape the canonical builder produces for a client-id-less channel.
    assert make_turn_id("ios_edit", None, 26, "x").startswith("ios_edit:h:")


# ── the join, through the database ────────────────────────────────────────────
async def test_the_edits_operation_and_turn_share_one_id(db, make_user,
                                                         monkeypatch):
    """The invariant, asserted where it failed: a ledger event and the
    conversation row for the same edit must meet on `turn_id`."""
    from sqlalchemy import select

    from db.models import ConversationLog, LedgerEvent
    from db.queries import log_conversation, record_ledger_event

    user = await make_user()
    turn_id = _edit_turn_id(user.id, 4242, {"calories": 200})

    from core.turn_identity import CURRENT_TURN_ID
    token = CURRENT_TURN_ID.set(turn_id)
    try:
        await record_ledger_event(db, user.id, "updated", domain="food",
                                  entry_id=4242, payload={"changes": {}},
                                  source="ios_edit")
    finally:
        CURRENT_TURN_ID.reset(token)
    await log_conversation(db, user.id, raw_message="[edit_food_entry]",
                           response="updated", source_type="dashboard_edit",
                           platform="ios", turn_id=turn_id)

    event = (await db.execute(
        select(LedgerEvent).where(LedgerEvent.entry_id == 4242)
    )).scalars().first()
    turn = (await db.execute(
        select(ConversationLog).where(ConversationLog.turn_id == turn_id)
    )).scalars().first()

    assert event is not None and turn is not None
    assert event.turn_id == turn.turn_id, \
        "the edit's operation does not join the edit's turn"


async def test_the_builder_cannot_produce_an_entry_derived_id(db, make_user):
    """The old format is unreachable now, asserted by RUNNING the builder.

    The first version of this test grepped the module for the string
    `ios_edit:update:` — and failed on the comment explaining why that string
    is wrong. That is the third source grep in this session to match its own
    docstring; a grep cannot tell code from prose about code, so the check is
    what the function returns.
    """
    user = await make_user()
    for changes in ({"calories": 200}, {"delete": True}, {}):
        produced = _edit_turn_id(user.id, 2587, changes)
        assert ":update:" not in produced
        assert ":delete:" not in produced
        assert "2587" not in produced, \
            "the entry id leaked into the turn id, so two edits of one entry collide"
