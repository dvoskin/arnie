"""⭐ THE PRODUCER — and the three ways it must refuse to be helpful.

Danny's outstanding acceptance gates land here:

    1  Russian `Помидор` resolves to the same canonical entity as `Tomato`
    2  `white rice` reaches the same base entity as `rice`, modifiers preserved
    3  `творог` must NOT become `cottage cheese` merely because that is a
       convenient English approximation

⛔ AND THE FAILURE MODES, WHICH ARE THE HALF THAT PROTECTS PRODUCTION. Every one
of them must produce NO ROW, because no row reproduces today's behaviour exactly
and any other outcome breaks the monotonicity guarantee this whole slice rests
on. A resolver that cannot fail safely is worse than no resolver: it converts an
outage into a durable wrong identity.

The model is stubbed throughout. What is under test is the CONTRACT — what the
producer does with each shape of reply — not the model's judgement, which no
unit test can pin and which the live smoke run measures separately.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio

from skills.nutrition import entity_resolver as producer
from skills.nutrition import entity_resolution as er
from skills.nutrition.entity_resolution import ResolutionState, surface_key
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Reply:
    def __init__(self, payload, stop_reason="end_turn"):
        self.content = [_Block(payload if isinstance(payload, str)
                               else json.dumps(payload, ensure_ascii=False))]
        self.stop_reason = stop_reason


class _Client:
    """Records what it was asked, answers what the test dictates."""

    def __init__(self, reply):
        self._reply, self.asked = reply, []
        self.messages = self

    async def create(self, **kw):
        self.asked.append(kw)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


@pytest.fixture
def model(monkeypatch):
    def _install(payload, stop_reason="end_turn"):
        client = _Client(payload if isinstance(payload, Exception)
                         else _Reply(payload, stop_reason))
        monkeypatch.setattr(producer, "_get_client", lambda: client)
        return client
    return _install


@pytest_asyncio.fixture
async def store(app_db, seeded):           # noqa: F811
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session


def _said(surface, state, entity, meaning="", language=""):
    return {"surface": surface, "state": state, "entity": entity,
            "meaning": meaning, "language": language}


# ── Danny's three ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pomidor_reaches_the_same_entity_as_tomato(store, model):
    """GATE 1. The 30.4% population's whole premise: a food named in another
    language must land on the entity the evidence layer already addresses."""
    model({"foods": [_said("Помидор", "resolved", "tomato",
                           "the raw fruit", "ru")]})

    got = await producer.ensure_resolved(store, ["Помидор"])

    assert got["Помидор"] == "tomato"
    assert await er.entity_id_for_surface(store, "помидор") == "tomato"


@pytest.mark.asyncio
async def test_a_modifier_stays_with_the_food_it_changes(store, model):
    """GATE 2, IN THE DIRECTION THAT PROTECTS ACCURACY. `white rice` and `rice`
    are not interchangeable — white and brown rice differ nutritionally — so the
    contract is that the modifier SURVIVES into the entity, not that it is
    stripped to reach a base that happens to be covered."""
    model({"foods": [_said("Белый рис", "resolved", "white rice", "", "ru")]})

    assert (await producer.ensure_resolved(store, ["Белый рис"]))["Белый рис"] \
        == "white rice"


@pytest.mark.asyncio
async def test_tvorog_is_not_forced_into_cottage_cheese(store, model):
    """⭐ GATE 3, AND THE ONE THE DESIGN EXISTS FOR. The producer must be able
    to say "this is a real food with no faithful English equivalent" and have
    that persist as an identity rather than as a failure."""
    model({"foods": [_said("Творог 2%", "distinct", "tvorog 2%",
                           "a fresh soured-milk curd, not cottage cheese", "ru")]})

    got = await producer.ensure_resolved(store, ["Творог 2%"])

    assert got["Творог 2%"] == "tvorog 2%"
    stored = await er.resolve(store, "Творог 2%")
    assert stored.state is ResolutionState.DISTINCT
    assert "cottage cheese" not in stored.canonical_entity_id


@pytest.mark.asyncio
async def test_the_prompt_hands_over_no_catalogue_of_entities(store, model):
    """⭐⭐ A CATALOGUE WOULD MAKE EVERY FOOD OUTSIDE IT `DISTINCT` BY
    CONSTRUCTION — asserting an answer the data never supported. The question
    asked is whether a faithful English term EXISTS, which is a fact about
    language rather than about our coverage."""
    from skills.nutrition.pricing_artifact import _artifact

    client = model({"foods": [_said("Помидор", "resolved", "tomato")]})
    await producer.ensure_resolved(store, ["Помидор"])

    sent = json.dumps(client.asked[0], ensure_ascii=False)
    artifact = _artifact()
    entities = [k.split("|")[0] for k in (artifact.entries if artifact else {})]
    leaked = [e for e in entities if e and f'"{e}"' in sent]
    assert not leaked, f"the artifact's entity list reached the prompt: {leaked}"


# ── every failure produces NO ROW ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_outage_records_nothing(store, model):
    model(RuntimeError("provider down"))

    assert await producer.ensure_resolved(store, ["Помидор"]) == {}
    assert await er.resolve(store, "Помидор") is None
    assert await er.entity_id_for_surface(store, "Помидор") == ""


@pytest.mark.asyncio
async def test_a_truncated_reply_abstains_the_WHOLE_batch(store, model):
    """⚠ THE TRAP THIS PROJECT HAS PAID FOR ONCE. A reply cut mid-string is not
    a shorter correct answer — it is an answer about some foods and silence
    about the rest, and the silence becomes a verdict the moment it is written
    down. The bound is OUTPUT LENGTH, not record count."""
    model({"foods": [_said("Помидор", "resolved", "tomato"),
                     _said("Творог 2%", "distinct", "tvorog")]},
          stop_reason="max_tokens")

    assert await producer.ensure_resolved(store, ["Помидор", "Творог 2%"]) == {}
    assert await er.resolve(store, "Помидор") is None, (
        "a food from a truncated batch was recorded — the foods that happened "
        "to arrive first are not more trustworthy than the ones cut off")


@pytest.mark.asyncio
async def test_an_unparseable_reply_records_nothing(store, model):
    model("I'd be happy to help with that!")

    assert await producer.ensure_resolved(store, ["Помидор"]) == {}
    assert await er.resolve(store, "Помидор") is None


@pytest.mark.asyncio
async def test_a_resolution_for_a_food_nobody_asked_about_is_discarded(store, model):
    """The model can echo, invent or merge a surface form. A row keyed on a
    string the user never typed is unreachable at best and wrong at worst."""
    model({"foods": [_said("Помидор", "resolved", "tomato"),
                     _said("Огурец", "resolved", "cucumber")]})

    got = await producer.ensure_resolved(store, ["Помидор"])

    assert got == {"Помидор": "tomato"}
    assert await er.resolve(store, "Огурец") is None


@pytest.mark.asyncio
async def test_a_binding_state_with_no_entity_is_dropped_not_downgraded(store, model):
    """Recording it as UNRESOLVED would invent a judgement the model did not
    make. Absence of a row already means exactly that, honestly."""
    model({"foods": [_said("Шакшука", "resolved", "")]})

    assert await producer.ensure_resolved(store, ["Шакшука"]) == {}
    assert await er.resolve(store, "Шакшука") is None


@pytest.mark.asyncio
async def test_an_unresolved_verdict_is_recorded_and_binds_nothing(store, model):
    """⭐ AN EXPLICIT REFUSAL IS AN ANSWER AND IS WORTH STORING — it stops the
    same food being re-asked every turn — but it must bind no entity, so the
    caller still gets today's behaviour."""
    model({"foods": [_said("Шакшука", "unresolved", "", "not confident")]})

    assert await producer.ensure_resolved(store, ["Шакшука"]) == {}
    stored = await er.resolve(store, "Шакшука")
    assert stored is not None and stored.state is ResolutionState.UNRESOLVED
    assert stored.canonical_entity_id == ""
    assert await er.entity_id_for_surface(store, "Шакшука") == ""


# ── the store is consulted before the model ───────────────────────────────────

@pytest.mark.asyncio
async def test_a_known_food_never_reaches_the_model(store, model):
    """⭐ WHAT MAKES THIS AFFORDABLE AND DETERMINISTIC. A food logged weekly is
    interpreted once, ever; every later turn is a lookup."""
    first = model({"foods": [_said("Помидор", "resolved", "tomato")]})
    await producer.ensure_resolved(store, ["Помидор"])
    assert len(first.asked) == 1

    second = model({"foods": [_said("Помидор", "resolved", "WRONG")]})
    got = await producer.ensure_resolved(store, ["Помидор"])

    assert second.asked == [], "a stored resolution was re-asked"
    assert got["Помидор"] == "tomato"


@pytest.mark.asyncio
async def test_only_the_unknown_foods_are_sent(store, model):
    known = model({"foods": [_said("Помидор", "resolved", "tomato")]})
    await producer.ensure_resolved(store, ["Помидор"])

    batch = model({"foods": [_said("Огурец", "resolved", "cucumber")]})
    await producer.ensure_resolved(store, ["Помидор", "Огурец"])

    # ⚠ THE USER MESSAGE, NOT THE WHOLE CALL. The system prompt names `Помидор`
    # as an ILLUSTRATION of the decision, so asserting over the entire payload
    # fails on the example rather than on the batch — which is what the first
    # version of this test did.
    sent = json.loads(batch.asked[0]["messages"][0]["content"])["foods"]
    assert sent == ["Огурец"]
    assert len(known.asked) == 1


@pytest.mark.asyncio
async def test_a_stale_contract_is_re_asked_rather_than_trusted(store, model):
    """When the entity namespace eventually moves, every stored row is an
    answer to a different question — and gets asked again rather than reused."""
    model({"foods": [_said("Помидор", "resolved", "tomato")]})
    await producer.ensure_resolved(store, ["Помидор"])

    again = model({"foods": [_said("Помидор", "resolved", "ent_tomato")]})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(er, "ENTITY_NAMESPACE", "opaque_entity_v2")
        got = await producer.ensure_resolved(store, ["Помидор"])

    assert len(again.asked) == 1, "a resolution from a dead contract was reused"
    assert got["Помидор"] == "ent_tomato"


@pytest.mark.asyncio
async def test_the_same_food_written_differently_is_asked_once(store, model):
    """`surface_key` is the unit of work, so casing and punctuation variants of
    one name do not each pay for a model call."""
    client = model({"foods": [_said("Творог 2%", "distinct", "tvorog 2%")]})

    await producer.ensure_resolved(store, ["Творог 2%", "ТВОРОГ 2%", "творог 2%"])

    payload = json.loads(client.asked[0]["messages"][0]["content"])
    assert len(payload["foods"]) == 1
    assert surface_key("ТВОРОГ 2%") == surface_key("Творог 2%")


def test_the_client_factory_actually_resolves():
    """⚠ THE ONE LINE EVERY OTHER GATE IN THIS FILE STUBS OUT.

    `_get_client` originally imported `_get_anthropic` from
    `core.micro_estimator`, which imports it from `core.llm` and does not
    re-export it. Fourteen gates passed against that, because every one of them
    replaces `_get_client` — so the single line they could not exercise was the
    single line that was broken, and only a live run surfaced it.

    A stub is a statement about the CONTRACT. It is never evidence that the
    thing being stubbed exists.
    """
    client = producer._get_client()
    assert hasattr(client, "messages") and hasattr(client.messages, "create")
