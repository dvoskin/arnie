"""B-1 items 5–7: eligibility wired in, ownership taken, interaction persisted.

The acceptance criteria this file exists to measure:

  * the rollout gate is evaluated ONCE, before the operation exists;
  * a decline emits its reason, so "how often and for what" is countable;
  * an eligible turn bypasses the legacy quantity producer;
  * an ineligible turn is untouched;
  * canonical and legacy never both fire — one meal, one pending record;
  * the persisted interaction carries field identity, option ids, CONCRETE
    typed patches, candidate source, provenance, revision and locale, and an
    option id reloaded from storage binds to the EXACT persisted patch rather
    than regenerating candidates.

The last one is the whole point of persisting patches at all: regeneration
would re-run history and ontology lookups on the answer turn, and evidence
that moved between the two turns would silently change what the user's tap
meant.
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_quantity_operation as b1
from db.models import Base, PendingOperation, PendingQuestion, User
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

INTERPRETED = {"food": "chicken breast", "calories": 187, "protein": 35,
               "carbs": 0, "fats": 4}


def _staged(**kw):
    base = dict(
        staged_item_id="si_1", original_text="some chicken breast",
        identity=FoodIdentity(canonical_name="chicken breast"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        ambiguities=(FoodAmbiguity(
            ambiguity_id="a1", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
            field_name="estimated_mass_g", materiality_score=2.0,
            calorie_span=180.0),))
    base.update(kw)
    return StagedFoodItem(**base)


def _material(**kw):
    base = dict(staged_items=(_staged(),), asked_item_id="si_1",
                items=[dict(INTERPRETED)],
                message="I had some chicken breast")
    base.update(kw)
    return base


@pytest_asyncio.fixture
async def engine(tmp_path):
    from db.database import make_engine

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'wire.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessions(engine):
    return async_sessionmaker(engine, class_=AsyncSession,
                              expire_on_commit=False)


@pytest_asyncio.fixture
async def user(sessions, monkeypatch):
    async with sessions() as s:
        u = User(telegram_id="b1:wire", name="Wire", timezone="UTC")
        s.add(u)
        await s.commit()
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(u.id))
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    return u


async def _attempt(sessions, user, *, material=None, capable=True,
                   locale="en", turn_id="t_1"):
    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=material if material is not None else _material(),
            turn_id=turn_id, client_capable=capable, locale=locale)
        await s.commit()
    return ask


# ── the gate ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_eligible_turn_in_the_cohort_takes_ownership(sessions, user):
    ask = await _attempt(sessions, user)
    assert ask is not None
    assert ask.revision == 0 and ask.locale == "en"
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(PendingOperation))).scalar() == 1


@pytest.mark.asyncio
async def test_a_user_outside_the_cohort_is_left_entirely_alone(
        sessions, user, monkeypatch):
    """Not in the rollout: no operation, no canonical question, nothing
    changed. The turn is byte-for-byte the turn it is today."""
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "")
    monkeypatch.setenv("B1_QUANTITY_PERCENT", "0")
    assert await _attempt(sessions, user) is None
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(PendingOperation))).scalar() == 0


@pytest.mark.asyncio
async def test_the_gate_is_read_before_the_row_exists_not_after(
        sessions, user, monkeypatch):
    """Ordering, stated as a test: halting must prevent creation, not undo
    it. A halt that fired after the write would leave an owned operation
    nobody intends to serve."""
    monkeypatch.setenv("B1_QUANTITY_HALT", "true")
    assert await _attempt(sessions, user) is None
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(PendingOperation))).scalar() == 0


@pytest.mark.asyncio
async def test_an_incapable_client_never_reaches_the_gate(sessions, user):
    assert await _attempt(sessions, user, capable=False) is None
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(PendingOperation))).scalar() == 0


def test_only_server_rendered_channels_are_capable_today():
    """iOS is deliberately absent until B-1b ships a build that renders
    fields/options — claiming otherwise here would be a capability claim about
    software that does not exist."""
    assert b1.client_renders_interactions("telegram")
    assert b1.client_renders_interactions("imessage")
    assert not b1.client_renders_interactions("ios")
    assert not b1.client_renders_interactions(None)


@pytest.mark.asyncio
async def test_every_decline_names_its_reason(sessions, user, caplog):
    """A decline has to be countable — the ineligibility mix is what sizes
    B-1.5 and B-2, and a silent False cannot report it."""
    import logging

    with caplog.at_level(logging.INFO):
        await _attempt(sessions, user, material=_material(
            staged_items=(_staged(), _staged(staged_item_id="si_2"))))
    assert "event=b1_declined" in caplog.text
    assert "reason=multiple_items" in caplog.text


@pytest.mark.asyncio
async def test_an_ineligible_turn_writes_nothing(sessions, user):
    await _attempt(sessions, user, material=_material(
        message="actually make that 8oz"))          # a correction
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(PendingOperation))).scalar() == 0


# ── one meal, one pending record ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_canonical_ownership_leaves_no_legacy_pending_question(
        sessions, user):
    """The legacy `pending_questions` stash is SKIPPED when B-1 owns the turn.
    Two representations of one question in two stores is the condition this
    migration exists to end — and the answer turn would then have to pick."""
    await _attempt(sessions, user)
    async with sessions() as s:
        assert (await s.execute(
            select(func.count()).select_from(PendingOperation))).scalar() == 1
        assert (await s.execute(
            select(func.count()).select_from(PendingQuestion))).scalar() == 0


# ── what is persisted ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_row_carries_the_whole_operation_context(sessions, user):
    ask = await _attempt(sessions, user)
    async with sessions() as s:
        row = (await s.execute(select(PendingOperation))).scalar_one()

    assert row.operation_id == ask.operation_id
    assert row.revision == 0
    assert row.domain == "food"
    assert row.status == b1.AWAITING
    assert row.source_turn_id == "t_1"
    assert row.expires_at is not None, \
        "an unanswered question must not stay answerable forever"

    payload = json.loads(row.canonical_payload)
    assert payload["locale"] == "en"
    assert payload["item"]["food"] == "chicken breast", \
        "the draft the answer turn prices from"
    field = payload["interaction"]["groups"][0]["fields"][0]
    assert field["attribute"] == "quantity"
    assert field["response_type"] == "single_select"


@pytest.mark.asyncio
async def test_every_persisted_option_carries_a_concrete_typed_patch(
        sessions, user):
    await _attempt(sessions, user)
    async with sessions() as s:
        row = (await s.execute(select(PendingOperation))).scalar_one()
    options = (json.loads(row.canonical_payload)["interaction"]
               ["groups"][0]["fields"][0]["options"])

    assert options, "a select with no options must not have been persisted"
    for o in options:
        assert o["option_id"] and o["label"]
        assert o["source"], "the candidate source must survive storage"
        assert o["patch"]["patch_type"] == "set_quantity", \
            "a discriminator, or the server key-sniffs on reload"
        assert o["patch"]["schema_version"] == 1
        assert o["patch"]["provenance"] == "user_selected"
        assert o["patch"]["quantity"]["dimension"] == "mass"
        assert o["patch"]["quantity"]["grams"], "grams, as a string"
        assert o["adapter_built"] is False


@pytest.mark.asyncio
async def test_a_reloaded_option_id_binds_to_the_exact_persisted_patch(
        sessions, user):
    """THE REASON PATCHES ARE STORED AT ALL.

    The alternative is regenerating candidates on the answer turn — re-running
    the history query and the ontology lookup. Evidence that moved between the
    two turns (a new log, a changed row) would then silently change what the
    user's tap meant, and the tap would still look correct.
    """
    ask = await _attempt(sessions, user)
    live = ask.interaction.groups[0].fields[0]
    live_by_id = {o.option_id: o.patch for o in live.options}

    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)

    assert owned is not None and owned.readable
    for option_id, live_patch in live_by_id.items():
        loaded = owned.interaction.patch_for(live.field_id, option_id)
        assert loaded == live_patch, \
            f"{option_id} reloaded as a different patch than it was offered"
        assert type(loaded) is type(live_patch)


@pytest.mark.asyncio
async def test_the_locale_pinned_at_the_ask_governs_the_answer(sessions, user):
    """The question was asked in Russian; the answer must not be judged by an
    English command lexicon two turns later."""
    ask = await _attempt(sessions, user, locale="ru")
    assert ask is not None and ask.locale == "ru"
    async with sessions() as s:
        u = await s.get(User, user.id)
        owned = await b1.owning(s, u)
    assert owned.locale == "ru"


# ── the wire ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_wire_payload_carries_ids_and_never_meanings(sessions, user):
    ask = await _attempt(sessions, user)
    wire = ask.wire_payload()

    assert wire["operation_id"] == ask.operation_id
    assert wire["revision"] == 0 and wire["locale"] == "en"
    field = wire["groups"][0]["fields"][0]
    assert field["field_id"].endswith(":quantity:0")
    for option in field["options"]:
        assert set(option) == {"option_id", "label"}, \
            "a patch on the wire is a meaning the client could edit"


@pytest.mark.asyncio
async def test_the_legacy_projection_is_the_same_field_not_a_second_producer(
        sessions, user):
    """It exists so an older client keeps working during the rollout, and it
    dies with QuickReplyEngine.swift at promotion. Because both rows are
    rendered from ONE field, they cannot disagree."""
    ask = await _attempt(sessions, user)
    legacy = ask.legacy_questions()
    canonical = ask.wire_payload()["groups"][0]["fields"][0]["options"]

    assert len(legacy) == 1
    assert legacy[0]["options"] == [o["label"] for o in canonical]
    assert legacy[0]["item"] == "chicken breast"
