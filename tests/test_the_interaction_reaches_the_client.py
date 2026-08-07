"""B-1b.0 — the canonical interaction has a wire channel.

FOUND BY THE iOS INTEGRATION, which is what integrations are for.

`POST /chat/answer` requires `operation_id`, `revision`, `field_id` and
`option_id`. Nothing on the wire could tell a client what any of them were:

    buttons                 legacy quick replies whose `value` is a LABEL —
                            the round-trip C11 forbids, because a label
                            travelling back as semantics is re-parsed
    pending_clarifications  the legacy question shape, with no ids at all
    interaction             did not exist

So the endpoint was unanswerable by the client it was built for. The
interaction was constructed, persisted and rendered into the SENTENCE — right
for Telegram, where the sentence is the whole interface — and a native client
had no structured view of it.

ADDITIVE AND OPTIONAL. Absent on every turn a canonical operation does not
own, so its presence IS the signal that a structured answer is possible, and
older clients are unaffected.
"""
import json

import pytest

from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, client, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say, operations, commits, vague, B1_ELIGIBLE,
)
from tests.test_b1b1_system_matrix import _ask, density  # noqa: F401


async def _ask_on_a_capable_channel(edges, user):
    """THE CAPABLE CHANNEL, not the iOS endpoint.

    iOS is deliberately ABSENT from `_CHANNEL_CAPABILITY` until a build ships
    that renders fields and submits ids — naming it sooner would be a
    capability claim about software that does not exist. So a gate driven
    through `/api/v1/chat` skips on a designed exclusion and proves nothing,
    which is the shape of instrument failure this slice keeps finding.

    The wire channel is what is under test here, and it is channel-agnostic.
    """
    from core.platform import serialize_response

    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Chicken breast", "q": "How much?"}],
        "items": [vague("Chicken breast", cal=280, amount=6, unit="oz")],
        "ready": [],
    })
    turn = await say(user, "I had some chicken breast", platform=CAPABLE)
    return serialize_response(turn.response)


def test_the_wire_contract_has_a_place_for_the_interaction():
    """The field exists and defaults to null, so a client can branch on its
    presence rather than on the shape of a bubble."""
    from core.platform import Response, serialize_response

    payload = serialize_response(Response(bubbles=["hi"]))
    assert "interaction" in payload
    assert payload["interaction"] is None


@pytest.mark.asyncio
async def test_an_ordinary_turn_carries_no_interaction(edges, seeded,
                                                 b1_live, density):
    """ABSENT UNLESS OWNED. Its presence is the signal; a field stamped on
    every turn would signal nothing."""
    from core.platform import serialize_response

    edges.plans.append({"action": "log", "points": [], "items": [],
                        "ready": [{"food": "Black coffee",
                                   "quantity": "1 cup", "calories": 5}]})
    turn = await say(seeded, "a black coffee", platform=CAPABLE)
    assert serialize_response(turn.response).get("interaction") is None


@pytest.mark.asyncio
async def test_an_owned_ask_carries_the_ids_the_endpoint_requires(
        edges, seeded, b1_live, density):
    """THE DEFECT, AS A GATE. Every identifier `POST /chat/answer` demands
    must be readable from the ask that produced the question."""
    body = await _ask_on_a_capable_channel(edges, seeded)
    ops = await operations(seeded)
    # NOT A SKIP. If B-1 did not own this turn the gate tested nothing, and a
    # green run would say the opposite.
    assert ops, "B-1 did not own the ask; this gate proved nothing"

    interaction = body.get("interaction")
    assert interaction, "an owned ask sent no interaction to the client"
    assert interaction["operation_id"] == ops[-1].operation_id
    assert "revision" in interaction

    field = interaction["groups"][0]["fields"][0]
    # ON THE FIELD, not on the option — the wire projection differs from the
    # STORED shape here, where `field_id` rides each option because the field
    # computes it as a property and only options survive serialization. Both
    # are deliberate; a client reads it from the field.
    assert field["field_id"], "no field_id: the endpoint cannot be called"
    assert field["allows_free_text"] is True, (
        "without the free-text affordance a user whose portion is not offered "
        "has no visible way to say so")

    options = field["options"]
    assert options, "the interaction carried no options to render"
    for option in options:
        assert option["option_id"], "an option with no id cannot be answered"
        assert option["label"], "an option with no label cannot be rendered"
        # LABELS ONLY. The patch stays on the server.
        assert set(option) == {"option_id", "label"}


@pytest.mark.asyncio
async def test_the_wire_interaction_matches_what_was_persisted(
        edges, seeded, b1_live, density):
    """THE CLIENT AND THE RECORD SEE ONE QUESTION. If they could differ, a tap
    would resolve against a row that describes something else."""
    body = await _ask_on_a_capable_channel(edges, seeded)
    ops = await operations(seeded)
    assert ops, "B-1 did not own the ask; this gate proved nothing"

    stored = json.loads(ops[-1].canonical_payload)["interaction"]
    sent = body["interaction"]
    stored_field = stored["groups"][0]["fields"][0]
    sent_field = sent["groups"][0]["fields"][0]
    assert sent["operation_id"] == stored["operation_id"]
    assert sent["revision"] == stored["revision"]
    assert ([o["option_id"] for o in sent_field["options"]]
            == [o["option_id"] for o in stored_field["options"]])
    assert ([o["label"] for o in sent_field["options"]]
            == [o["label"] for o in stored_field["options"]])


@pytest.mark.asyncio
async def test_the_interaction_carries_no_semantics_a_client_could_reinterpret(
        edges, seeded, b1_live, density):
    """IDENTIFIERS AND LABELS. A client that received the patch or the
    candidate could price a meal itself, and then two things own one fact."""
    body = await _ask_on_a_capable_channel(edges, seeded)
    assert body.get("interaction"), "no interaction to inspect"

    flat = json.dumps(body["interaction"])
    for leaked in ("evidence", "serving_basis", "semantic_hash", "prior",
                   "candidate_set", "grams"):
        assert leaked not in flat, f"the interaction leaked {leaked!r}"
