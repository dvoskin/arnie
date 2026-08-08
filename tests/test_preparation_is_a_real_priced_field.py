"""B-1.5 commit 2: preparation is a real field, and it PRICES the food.

The claim this file exists to prove, and the one it must not overstate:

    a production-shaped food generates quantity AND preparation as two
    independent semantic fields, both are answerable, and the preparation
    answer materially changes the committed nutrition where real evidence
    distinguishes the preparations.

THE LAST CLAUSE IS THE WHOLE DIFFICULTY. Preparation reaches pricing by
COMPOSING THE CANONICAL NAME — `settle` looks up "chicken breast, grilled"
rather than "chicken breast" — and the enrichment lane and
`skills.nutrition.validators` do the rest, the latter downgrading candidates
whose preparation disagrees with the request. Both mechanisms already existed;
this slice gives them the fact they were missing.

So the honest gate is NOT "grilled and fried always differ by N calories". A
fixed multiplier here would be exactly the invented arithmetic B-1.75 deleted
on the quantity side. The gate is:

    the composed NAME reaches pricing            always
    the number moves                             when the evidence differs
    the number does NOT move                     when it does not

A test that asserted a difference for every food would pass by accident on a
resolver that ignored preparation entirely and hallucinated variance.
"""
from __future__ import annotations

import json

import pytest

from core.canonical_pricing import PricedFood as _PricedFood
from core.canonical_pricing import Rung as _Rung


def _mass(consumed):
    """The answered mass as the old stub reported it, so the
    existing assertions keep their meaning."""
    g = getattr(consumed, 'grams', None)
    return f'{g:g}g' if g is not None else ''
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_answer_turn as answer_turn
from core import b1_quantity_operation as b1
from core.clarification_answer import Outcome
from core.semantics import ClarificationAttribute
from db.models import Base, FoodEntry, PendingOperation, User
from skills.nutrition import preparation_ontology as onto
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, PreparationIntent,
                                      QuantityIntent, StagedFoodItem)

INTERPRETED = {"food": "chicken breast", "calories": 187, "protein": 35,
               "carbs": 0, "fats": 4}


def _staged(*, preparation=None, with_prep_ambiguity=True):
    ambiguities = [FoodAmbiguity(
        ambiguity_id="a1", staged_item_id="si_1",
        ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="estimated_mass_g", materiality_score=2.0,
        calorie_span=180.0)]
    if with_prep_ambiguity:
        ambiguities.append(FoodAmbiguity(
            ambiguity_id="a2", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.PREPARATION,
            field_name="preparation", materiality_score=1.5,
            calorie_span=90.0))
    return StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken breast",
        identity=FoodIdentity(canonical_name="chicken breast"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        preparation=preparation or PreparationIntent(),
        ambiguities=tuple(ambiguities))


def _material(**kw):
    return dict(staged_items=(_staged(**kw),), asked_item_id="si_1",
                items=[dict(INTERPRETED)],
                message="I had some chicken breast")


@pytest_asyncio.fixture
async def engine(tmp_path):
    from db.database import make_engine

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'prep.db'}")
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
        u = User(telegram_id="b15:prep", name="Prep", timezone="UTC")
        s.add(u)
        await s.commit()
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(u.id))
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    return u


@pytest.fixture
def priced(monkeypatch):
    """A resolver that PRICES BY NAME, and records the names it was asked.

    Grilled and fried chicken really do differ; the numbers here stand in for
    that evidence rather than inventing a rule. `seen` is what makes the
    "composed name reached pricing" claim checkable directly, instead of being
    inferred from a calorie count that could have moved for another reason.
    """
    seen = []
    by_name = {"chicken breast, grilled": 165.0,
               "chicken breast, fried": 260.0,
               "chicken breast, roasted": 165.0,
               "chicken breast": 165.0}

    class _Analysis:
        protein, carbs, fat = 31.0, 0.0, 4.0
        fiber = sugar = sodium = None
        micros, micros_estimated, assumptions = None, False, ()
        provenance = None
        confidence = "likely"

        def __init__(self, calories):
            self.calories = calories

    def _fake(*, entity, consumed=None, **kw):
        seen.append(entity)
        return _PricedFood(
            calories=by_name.get(entity.strip().lower(), 165.0),
            protein=31.0, carbs=0.0, fats=3.6,
            rung=_Rung.ARTIFACT, evidence_id="usda:test")

    monkeypatch.setattr("core.canonical_pricing.price", _fake)
    return seen


async def _open(sessions, user, *, turn_id="t_1", **kw):
    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=_material(**kw), turn_id=turn_id,
            channel="ios", locale="en")
        await s.commit()
    return ask


async def _answer(sessions, user, **kw):
    async with sessions() as s:
        u = await s.get(User, user.id)
        out = await answer_turn.handle(s, user=u, **kw)
        await s.commit()
        return out


def _fields(ask):
    fields = ask.interaction.groups[0].fields
    by_attr = {f.attribute: f for f in fields}
    return (by_attr.get(ClarificationAttribute.QUANTITY),
            by_attr.get(ClarificationAttribute.PREPARATION))


async def _rows(sessions):
    async with sessions() as s:
        return (await s.execute(select(FoodEntry))).scalars().all()


async def _tap(sessions, user, ask, field, option_id, turn):
    return await _answer(sessions, user, source_turn_id=turn,
                         field_id=field.field_id, option_id=option_id,
                         revision=ask.revision, message="")


# ── the ontology maps onto the resolver, or it is decorative ────────────────

def test_preparation_ids_are_tokens_the_resolver_acts_on():
    """THE LOAD-BEARING GATE FOR THE WHOLE SLICE.

    Preparation prices the food by going into the name, and
    `validators._PREPARATIONS` is what makes a name-borne preparation
    actionable — it downgrades candidates whose preparation disagrees. An id
    outside that table is INERT: the question is asked, the answer stored, and
    no number moves. This is also why `breaded` and `plain` are not offered
    and why the baked option's id is `roasted`.
    """
    from skills.nutrition.validators import _PREPARATIONS

    known = {p.preparation_id for p in onto.OFFERED if p.known}
    assert known, "the ontology offers no known preparation at all"
    assert known <= set(_PREPARATIONS), (
        f"{sorted(known - set(_PREPARATIONS))} are not preparations the "
        f"resolver acts on — offering them asks a question that cannot "
        f"change an answer")


def test_the_unknown_option_changes_no_name():
    """"Not sure" must leave the food exactly as it was. Adding a word for an
    answer that carried no information would price a food nobody described."""
    assert onto.name_with("chicken breast", onto.UNKNOWN) == "chicken breast"


def test_composition_is_idempotent():
    """If the interpreter already read "grilled" out of the message, appending
    again yields "chicken, grilled, grilled" — a string no candidate matches,
    so a correct answer would price WORSE than no answer."""
    once = onto.name_with("grilled chicken", "grilled")
    assert once == "grilled chicken"
    assert onto.name_with(once, "grilled") == once


# ── the producer ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_preparation_dependent_food_produces_both_fields(
        sessions, user, priced):
    """This turn used to decline to legacy with PREPARATION_DEPENDENCY."""
    ask = await _open(sessions, user)
    assert ask is not None, "the turn still declines to legacy"
    quantity, preparation = _fields(ask)
    assert quantity is not None and preparation is not None
    assert len(ask.interaction.groups) == 1, "one food is one group"


@pytest.mark.asyncio
async def test_the_two_fields_are_independently_addressable(
        sessions, user, priced):
    """Distinct ids, and every option belongs to exactly one field — the
    structure that makes a mixed chip row unconstructable."""
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    assert quantity.field_id != preparation.field_id
    for field in (quantity, preparation):
        assert field.options, f"{field.attribute} shipped a blank select"
        assert all(o.field_id == field.field_id for o in field.options)
        assert all(o.patch is not None for o in field.options)


@pytest.mark.asyncio
async def test_a_stated_preparation_is_not_asked_again(sessions, user, priced):
    """Asking someone to repeat themselves is how a clarification becomes an
    interrogation. `stated` exists to tell a told method from an inferred."""
    ask = await _open(sessions, user,
                      preparation=PreparationIntent(method="grilled",
                                                    stated=True))
    _quantity, preparation = _fields(ask)
    assert preparation is None


# ── both orders converge ────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("quantity_first", [True, False])
async def test_either_order_reaches_the_same_committed_state(
        sessions, user, priced, quantity_first):
    """Answer order is presentation. The committed semantic state is not."""
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    steps = [(quantity, quantity.options[0].option_id),
             (preparation, "prep_grilled")]
    if not quantity_first:
        steps.reverse()

    first = await _tap(sessions, user, ask, *steps[0], "t_2")
    assert first.outcome is Outcome.PARTIAL, f"{first.outcome}: {first.reason}"
    assert not await _rows(sessions), "committed with a field still open"

    second = await _tap(sessions, user, ask, *steps[1], "t_3")
    assert second.outcome is Outcome.APPLIED, f"{second.outcome}"

    rows = await _rows(sessions)
    assert len(rows) == 1, "exactly one food event"
    assert "chicken breast, grilled" in priced, (
        f"pricing never saw the composed name; it saw {priced}")


# ── preparation actually moves the number ───────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("option_id,expected_name", [
    ("prep_grilled", "chicken breast, grilled"),
    ("prep_fried", "chicken breast, fried"),
])
async def test_the_chosen_preparation_is_what_gets_priced(
        sessions, user, priced, option_id, expected_name):
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    await _tap(sessions, user, ask, quantity,
               quantity.options[0].option_id, "t_2")
    out = await _tap(sessions, user, ask, preparation, option_id, "t_3")

    assert out.outcome is Outcome.APPLIED
    assert priced[-1] == expected_name, (
        f"priced {priced[-1]!r}, but the user chose {option_id}")


@pytest.mark.asyncio
async def test_an_unknown_preparation_prices_the_bare_food(
        sessions, user, priced):
    """"Not sure" must not invent a preparation, and must still settle."""
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    await _tap(sessions, user, ask, quantity,
               quantity.options[0].option_id, "t_2")
    out = await _tap(sessions, user, ask, preparation,
                     f"prep_{onto.UNKNOWN}", "t_3")

    assert out.outcome is Outcome.APPLIED
    assert priced[-1] == "chicken breast"
    assert len(await _rows(sessions)) == 1


@pytest.mark.asyncio
async def test_nutrition_differs_when_the_evidence_differs(sessions, user,
                                                           priced, monkeypatch):
    """The claim, stated carefully: the number moves BECAUSE the name did.

    Two operations, identical but for the preparation tapped. Anything that
    ignored preparation would commit the same calories twice.
    """
    calories = {}
    for turn, option in (("g", "prep_grilled"), ("f", "prep_fried")):
        ask = await _open(sessions, user, turn_id=f"t_{turn}")
        quantity, preparation = _fields(ask)
        await _tap(sessions, user, ask, quantity,
                   quantity.options[0].option_id, f"{turn}_2")
        await _tap(sessions, user, ask, preparation, option, f"{turn}_3")
        rows = await _rows(sessions)
        calories[option] = float(rows[-1].calories or 0)

    assert calories["prep_grilled"] != calories["prep_fried"], (
        f"preparation changed nothing: {calories} — the question is "
        f"decorative and the chip is a lie")


@pytest.mark.asyncio
async def test_preparation_does_not_move_a_food_whose_evidence_is_the_same(
        sessions, user, monkeypatch):
    """THE OTHER HALF, and the one that keeps the gate above honest.

    A resolver that hallucinated variance would satisfy "grilled != fried"
    while understanding nothing. Here the evidence is identical for both, and
    the committed number must be identical too — no preparation factor, no
    adjustment, nothing applied on top of what the evidence said.
    """
    seen = []

    class _Flat:
        calories, protein, carbs, fat = 200.0, 30.0, 0.0, 5.0
        fiber = sugar = sodium = None
        micros, micros_estimated, assumptions = None, False, ()
        provenance = None
        confidence = "likely"

    def _fake(*, entity, consumed=None, **kw):
        seen.append(entity)
        return _PricedFood(calories=200.0, protein=20.0, carbs=5.0, fats=8.0,
                           rung=_Rung.ARTIFACT, evidence_id="usda:flat")

    monkeypatch.setattr("core.canonical_pricing.price", _fake)

    calories = {}
    for turn, option in (("g", "prep_grilled"), ("f", "prep_fried")):
        ask = await _open(sessions, user, turn_id=f"t_{turn}")
        quantity, preparation = _fields(ask)
        await _tap(sessions, user, ask, quantity,
                   quantity.options[0].option_id, f"{turn}_2")
        await _tap(sessions, user, ask, preparation, option, f"{turn}_3")
        calories[option] = float((await _rows(sessions))[-1].calories or 0)

    assert calories["prep_grilled"] == calories["prep_fried"], (
        f"identical evidence produced different numbers ({calories}) — "
        f"something is adjusting nutrition on its own")
    # One pricing call per settlement, so two names for two operations. That
    # they DIFFER while the calories do not is the point: preparation reached
    # pricing and pricing declined to invent a difference the evidence did
    # not support.
    assert len(seen) == 2, f"expected one pricing call per settlement: {seen}"
    assert seen[0] != seen[1], "the composed names should still differ"


# ── failing shut ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_foreign_preparation_option_cannot_settle(sessions, user,
                                                          priced):
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    await _tap(sessions, user, ask, quantity,
               quantity.options[0].option_id, "t_2")
    out = await _tap(sessions, user, ask, preparation, "prep_sous_vide", "t_3")

    assert out.outcome is Outcome.REFUSED
    assert not await _rows(sessions), "a bad option id wrote a meal"


@pytest.mark.asyncio
async def test_a_stale_revision_cannot_answer_preparation(sessions, user,
                                                          priced):
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    await _tap(sessions, user, ask, quantity,
               quantity.options[0].option_id, "t_2")
    out = await _answer(sessions, user, source_turn_id="t_3",
                        field_id=preparation.field_id,
                        option_id="prep_grilled",
                        revision=ask.revision + 5, message="")

    assert out.outcome is Outcome.REFUSED
    assert not await _rows(sessions)


@pytest.mark.asyncio
async def test_revising_the_preparation_replaces_it(sessions, user, priced):
    """Two taps on Preparation are a correction and one answered field."""
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    first = await _tap(sessions, user, ask, preparation, "prep_fried", "t_2")
    assert first.outcome is Outcome.PARTIAL
    second = await _tap(sessions, user, ask, preparation, "prep_grilled", "t_3")
    assert second.outcome is Outcome.PARTIAL, "a re-tap completed the question"
    assert not await _rows(sessions)

    await _tap(sessions, user, ask, quantity,
               quantity.options[0].option_id, "t_4")
    assert priced[-1] == "chicken breast, grilled", (
        f"the revision did not replace the first answer: {priced[-1]!r}")


@pytest.mark.asyncio
async def test_a_late_first_answer_is_still_only_a_partial_answer(
        sessions, user, priced):
    """THE EXPIRY DOOR.

    An expired operation stops being entitled to messages that were never
    addressed to it, but a real answer arriving late is still an answer — so
    it takes the ordinary path. That path used to settle IMMEDIATELY, which
    was right while B-1 had one field and commits half a meal now: one late
    tap on Amount, and Preparation is never asked.

    Found by `test_the_sweep_never_closes_an_operation_someone_just_answered`
    failing with "reached settlement with no quantity answer" — readiness was
    enforced on the main path and reachable around it.
    """
    from datetime import timedelta

    from core.clock import now as _now

    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    async with sessions() as s:
        row = (await s.execute(
            select(PendingOperation).where(
                PendingOperation.operation_id == ask.operation_id))
        ).scalars().one()
        row.expires_at = _now() - timedelta(minutes=1)
        await s.commit()

    late = await _tap(sessions, user, ask, quantity,
                      quantity.options[0].option_id, "t_late")
    assert late.outcome is Outcome.PARTIAL, (
        f"a late tap settled a two-field question: {late.outcome}")
    assert not await _rows(sessions), "half a meal committed through expiry"

    done = await _tap(sessions, user, ask, preparation, "prep_grilled", "t_2")
    assert done.outcome is Outcome.APPLIED
    assert len(await _rows(sessions)) == 1
    assert priced[-1] == "chicken breast, grilled"


@pytest.mark.asyncio
async def test_the_answers_survive_a_restart(sessions, user, priced):
    """Held answers are DURABLE. The next tap may come from a relaunched app
    or another worker, so nothing may live only in this turn's memory."""
    ask = await _open(sessions, user)
    quantity, preparation = _fields(ask)
    await _tap(sessions, user, ask, quantity,
               quantity.options[0].option_id, "t_2")

    async with sessions() as s:
        row = (await s.execute(
            select(PendingOperation).where(
                PendingOperation.operation_id == ask.operation_id))
        ).scalars().one()
        held = json.loads(row.canonical_payload).get("answered") or {}
    assert len(held) == 1, f"the answer was not persisted: {held}"

    out = await _tap(sessions, user, ask, preparation, "prep_grilled", "t_3")
    assert out.outcome is Outcome.APPLIED
    assert priced[-1] == "chicken breast, grilled"


# ── the wire ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_wire_exposes_both_fields_with_ids_and_labels_only(
        sessions, user, priced):
    """The client renders two rows and generates no semantics: ids and labels
    go out, the patch stays here (C11)."""
    ask = await _open(sessions, user)
    payload = ask.wire_payload()

    fields = payload["groups"][0]["fields"]
    assert len(fields) == 2, f"the wire carries {len(fields)} fields"
    assert {f["attribute"] for f in fields} == {"quantity", "preparation"}
    for field in fields:
        for option in field["options"]:
            assert set(option) == {"option_id", "label"}, (
                f"the wire leaked {set(option) - {'option_id', 'label'}} — a "
                f"client that receives meaning can form its own view of it")
