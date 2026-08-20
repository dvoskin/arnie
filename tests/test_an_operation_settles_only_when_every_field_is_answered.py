"""B-1.5 gate: a meal commits when the QUESTION is answered, not when AN
answer arrives.

B-1 asks about one field, so "an answer applied" and "the question is
answered" have been the same sentence since the slice was written. B-1.5 makes
them different: one item, several independent material fields, and the user
may answer them one at a time or not at all.

    Chicken breast
    Amount        [3 oz] [5 oz] [8 oz]
    Preparation   [Plain] [Breaded] [Fried] [Not sure]

Today `_handle_owned` calls `settle()` on the first APPLIED answer. With two
fields that commits the meal while Preparation is still on screen — and then
the second tap finds a COMMITTED operation and replays it, so the user's
answer is silently discarded. Both halves of the directive's rule break at
once: "unanswered fields remain open" and "one meal still commits once".

THE FIELDS ARE BUILT HERE, NOT PRODUCED. B-1's generator emits one field and
this commit does not change that — settlement has to be able to hold a partial
answer BEFORE anything is allowed to ask for one, or the first production
two-field question commits half a meal. The quantity field is the real one
from `try_take_ownership`; only the preparation field is constructed, exactly
as the producer will emit it.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_answer_turn as answer_turn
from core import b1_quantity_operation as b1
from core.clarification_answer import Outcome
from core.semantics import (CandidateSource, ClarificationAttribute,
                            ClarificationGroup, ClarificationInteraction,
                            ClarificationOption, Provenance, ResponseType,
                            SetPreparation, UnresolvedField)
from db.models import Base, FoodEntry, PendingOperation, User
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

INTERPRETED = {"food": "chicken breast", "calories": 187, "protein": 35,
               "carbs": 0, "fats": 4}

#: The compact category the directive names for the first expansion.
PREPARATIONS = ("plain", "breaded", "fried")


def _staged():
    return StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken breast",
        identity=FoodIdentity(canonical_name="chicken breast"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        ambiguities=(FoodAmbiguity(
            ambiguity_id="a1", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
            field_name="estimated_mass_g", materiality_score=2.0,
            calorie_span=180.0),))


def _material():
    return dict(staged_items=(_staged(),), asked_item_id="si_1",
                items=[dict(INTERPRETED)],
                message="I had some chicken breast")


@pytest_asyncio.fixture
async def engine(tmp_path):
    from db.database import make_engine

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'ready.db'}")
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
        u = User(telegram_id="b15:ready", name="Ready", timezone="UTC")
        s.add(u)
        await s.commit()
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(u.id))
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    return u


@pytest.fixture(autouse=True)
def _priced(monkeypatch):
    class _Analysis:
        calories, protein, carbs, fat = 231.0, 43.0, 0.0, 5.0
        fiber = sugar = sodium = None
        micros, micros_estimated, assumptions = None, False, ()
        provenance = None
        confidence = "likely"

    async def _fake(db, user, food_name, inp):
        return _Analysis()

    monkeypatch.setattr("handlers.tool_executor._analyze_food", _fake)


def _preparation_field(ask):
    """The second field, exactly as the producer will emit it.

    Same operation, same revision, same event — the interaction's own
    `__post_init__` refuses anything else, which is the invariant that keeps a
    tap from patching a different operation than the one on screen.
    """
    group = ask.interaction.groups[0]
    quantity = group.fields[0]
    base = dict(operation_id=ask.operation_id, revision=ask.revision,
                event_id=quantity.event_id,
                attribute=ClarificationAttribute.PREPARATION)
    # The id derives from SEMANTICS — operation, event, attribute, revision —
    # so a free-text probe carries the same one a select will. Building the
    # probe as a select would trip C15 for having no options yet, which is
    # that gate doing its job on an object that was never going to be shown.
    field_id = UnresolvedField(**base).field_id
    return UnresolvedField(
        **base, response_type=ResponseType.SINGLE_SELECT,
        options=tuple(
            ClarificationOption(
                label=p.title(), option_id=f"prep_{p}", field_id=field_id,
                source=CandidateSource.ONTOLOGY,
                patch=SetPreparation(event_id=quantity.event_id,
                                     field_id=field_id, preparation_id=p,
                                     provenance=Provenance.USER_SELECTED))
            for p in PREPARATIONS))


async def _make_two_field(sessions, ask):
    """Persist the two-field form of an operation B-1 really opened."""
    group = ask.interaction.groups[0]
    prep = _preparation_field(ask)
    two = ClarificationInteraction(
        interaction_id=ask.interaction.interaction_id,
        operation_id=ask.operation_id, revision=ask.revision,
        introduction=ask.interaction.introduction,
        groups=(ClarificationGroup(event_id=group.event_id, label=group.label,
                                   fields=(group.fields[0], prep)),))
    async with sessions() as s:
        row = await _row(s, ask.operation_id)
        payload = json.loads(row.canonical_payload)
        payload["interaction"] = two.to_payload()
        # ⛔ A REAL OPERATION'S DIGEST DESCRIBES ITS STORED MATERIAL *(P17
        # Phase 2)*. This fixture emulates the multi-field form B-1 really
        # opens, so it must keep the payload self-consistent the way the one
        # production write seam does — otherwise it is indistinguishable from
        # an outside edit, which the strict decoder correctly refuses.
        payload["fingerprint_version"] = b1.FINGERPRINT_VERSION
        payload["fingerprint"] = b1.fingerprint_of_payload(payload)
        row.canonical_payload = json.dumps(payload)
        await s.commit()
    return two


async def _row(s, operation_id):
    """`operation_id` is unique but is NOT the primary key — `id` is."""
    return (await s.execute(
        select(PendingOperation)
        .where(PendingOperation.operation_id == operation_id))
    ).scalars().one()


@pytest_asyncio.fixture
async def two_field(sessions, user):
    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=_material(), turn_id="t_1",
            channel="ios", locale="en")
        await s.commit()
    assert ask is not None, "the fixture needs a real B-1 operation"
    interaction = await _make_two_field(sessions, ask)
    fields = interaction.groups[0].fields
    assert len(fields) == 2, "the fixture must present two fields"
    return ask, fields[0], fields[1]


async def _answer(sessions, user, **kw):
    async with sessions() as s:
        u = await s.get(User, user.id)
        out = await answer_turn.handle(s, user=u, **kw)
        await s.commit()
        return out


async def _meals(sessions, user):
    async with sessions() as s:
        return (await s.execute(
            select(func.count()).select_from(FoodEntry)
            .join(FoodEntry.daily_log)  # noqa: E501 — one user, one fixture
        )).scalar_one()


async def _status(sessions, operation_id):
    async with sessions() as s:
        return (await _row(s, operation_id)).status


# ── the rule ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_answering_one_of_two_fields_does_not_commit_the_meal(
        sessions, user, two_field):
    """THE DEFECT. One tap on Amount, and today the meal lands with
    Preparation unanswered and still on screen."""
    ask, quantity, _prep = two_field

    out = await _answer(sessions, user, source_turn_id="t_2",
                        field_id=quantity.field_id,
                        option_id=quantity.options[0].option_id,
                        revision=ask.revision, message="")

    assert out is not None
    assert await _meals(sessions, user) == 0, (
        "the meal committed while Preparation was still unanswered — the "
        "user's next tap will find a settled operation and be discarded")
    assert out.outcome is Outcome.PARTIAL, (
        f"a partial answer is not APPLIED and not a repair; got {out.outcome}")


@pytest.mark.asyncio
async def test_the_operation_stays_open_and_answerable(
        sessions, user, two_field):
    """A partial answer must leave the operation exactly as answerable as it
    was — same revision, so the chips still on screen stay valid."""
    ask, quantity, _prep = two_field

    await _answer(sessions, user, source_turn_id="t_2",
                  field_id=quantity.field_id,
                  option_id=quantity.options[0].option_id,
                  revision=ask.revision, message="")

    assert await _status(sessions, ask.operation_id) == b1.AWAITING
    async with sessions() as s:
        owned = await b1.owning(s, user=await s.get(User, user.id))
    assert owned is not None, "the operation stopped owning its own answer"
    assert owned.interaction.revision == ask.revision, (
        "a partial answer bumped the revision, invalidating the very chips "
        "the user still has to tap")


@pytest.mark.asyncio
async def test_answering_the_last_field_commits_exactly_one_meal(
        sessions, user, two_field):
    """And the whole point: both answers, one meal."""
    ask, quantity, prep = two_field

    await _answer(sessions, user, source_turn_id="t_2",
                  field_id=quantity.field_id,
                  option_id=quantity.options[0].option_id,
                  revision=ask.revision, message="")
    out = await _answer(sessions, user, source_turn_id="t_3",
                        field_id=prep.field_id,
                        option_id=prep.options[1].option_id,
                        revision=ask.revision, message="")

    assert out.outcome is Outcome.APPLIED, f"got {out.outcome}: {out.reason}"
    assert await _meals(sessions, user) == 1, "one meal, once"
    assert await _status(sessions, ask.operation_id) == b1.COMMITTED


@pytest.mark.asyncio
async def test_the_first_answer_survives_into_the_commit(
        sessions, user, two_field):
    """A held answer that is not APPLIED at commit time is a held answer that
    was thrown away — the quantity must be the one tapped two turns ago."""
    ask, quantity, prep = two_field
    chosen = quantity.options[0]

    await _answer(sessions, user, source_turn_id="t_2",
                  field_id=quantity.field_id,
                  option_id=chosen.option_id, revision=ask.revision,
                  message="")
    await _answer(sessions, user, source_turn_id="t_3",
                  field_id=prep.field_id,
                  option_id=prep.options[1].option_id,
                  revision=ask.revision, message="")

    grams = float(chosen.patch.quantity.grams)
    async with sessions() as s:
        row = (await s.execute(select(FoodEntry))).scalars().one()
    assert f"{grams:g}" in (row.quantity or ""), (
        f"committed {row.quantity!r}, but the user tapped {chosen.label!r} "
        f"({grams:g} g) on the first turn")


@pytest.mark.asyncio
async def test_answering_the_same_field_twice_does_not_complete_the_question(
        sessions, user, two_field):
    """Readiness counts FIELDS, not answers.

    Two taps on Amount are two answers and one answered field. Counting
    answers would let a user commit a meal by changing their mind about the
    portion, with Preparation never asked.
    """
    ask, quantity, _prep = two_field

    for turn, option in (("t_2", quantity.options[0]),
                         ("t_3", quantity.options[-1])):
        out = await _answer(sessions, user, source_turn_id=turn,
                            field_id=quantity.field_id,
                            option_id=option.option_id,
                            revision=ask.revision, message="")
        assert out.outcome is Outcome.PARTIAL, f"{turn}: {out.outcome}"

    assert await _meals(sessions, user) == 0
    assert await _status(sessions, ask.operation_id) == b1.AWAITING


@pytest.mark.asyncio
async def test_a_single_field_operation_still_commits_on_one_answer(
        sessions, user):
    """B-1's behaviour is UNCHANGED. Readiness is a generalisation, and the
    one-field case must not acquire a second required turn — that would be a
    production regression dressed as a feature.
    """
    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=_material(), turn_id="t_1",
            channel="ios", locale="en")
        await s.commit()
    field = ask.interaction.groups[0].fields[0]

    out = await _answer(sessions, user, source_turn_id="t_2",
                        field_id=field.field_id,
                        option_id=field.options[0].option_id,
                        revision=ask.revision, message="")

    assert out.outcome is Outcome.APPLIED, f"got {out.outcome}: {out.reason}"
    assert await _meals(sessions, user) == 1
