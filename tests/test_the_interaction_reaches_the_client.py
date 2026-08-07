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


# ── the capability claim ────────────────────────────────────────────────────

def test_ios_can_answer_by_id():
    """THE LAST STEP OF B-1b, and it is a CLAIM about a client.

    The table entry says "a build exists that renders fields and options and
    submits ids". It was deliberately absent until `arnie-ios@48cb626`, so
    that the claim and the software became true at the same moment.
    """
    from core.b1_quantity_operation import (ID_ADDRESSED, channel_capability,
                                            client_renders_interactions)

    assert channel_capability("ios") == ID_ADDRESSED
    assert client_renders_interactions("ios") is True


def test_a_capable_client_is_not_sent_the_options_as_prose():
    """ID_ADDRESSED GETS THE INTRODUCTION ONLY. The client renders the row
    from the interaction, so listing them in the sentence too would print the
    same three choices twice."""
    from core.b1_quantity_operation import ID_ADDRESSED, LABEL_TEXT

    assert ID_ADDRESSED != LABEL_TEXT


@pytest.mark.asyncio
async def test_an_ios_turn_now_owns_its_question_and_carries_the_ids(
        client, edges, seeded, b1_live, density):
    """END TO END OVER THE iOS ENDPOINT, which skipped on a designed
    exclusion until this commit. Now it must not skip."""
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Chicken breast", "q": "How much?"}],
        "items": [vague("Chicken breast", cal=280, amount=6, unit="oz")],
        "ready": [],
    })
    body = (await client.post(
        "/api/v1/chat",
        json={"message": "I had some chicken breast"})).json()

    ops = await operations(seeded)
    assert ops, "B-1 still declines iOS; the capability flag did not take"
    interaction = body.get("interaction")
    assert interaction, "an owned iOS ask sent no interaction"

    field = interaction["groups"][0]["fields"][0]
    assert field["field_id"] and field["options"]
    assert all(o["option_id"] for o in field["options"])


@pytest.mark.asyncio
async def test_an_ios_tap_commits_the_meal_end_to_end(client, edges, seeded,
                                                      b1_live, density):
    """THE WHOLE POINT, in one test: ask over iOS, read the ids off the wire,
    answer by id, get a meal."""
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Chicken breast", "q": "How much?"}],
        "items": [vague("Chicken breast", cal=280, amount=6, unit="oz")],
        "ready": [],
    })
    ask = (await client.post(
        "/api/v1/chat",
        json={"message": "I had some chicken breast"})).json()
    interaction = ask.get("interaction")
    assert interaction, "no question to answer"

    field = interaction["groups"][0]["fields"][0]
    answer = await client.post("/api/v1/chat/answer", json={
        "operation_id": interaction["operation_id"],
        "revision": interaction["revision"],
        "field_id": field["field_id"],
        "option_id": field["options"][0]["option_id"],
        "client_message_id": "ios:e2e-tap-1",
    })
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["outcome"] == "applied", body
    assert body["entry_id"], "the tap named no row"
    assert len(await commits(seeded)) == 1
