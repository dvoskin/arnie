"""THE RULE OF THREE: is the field mechanism generic, or bespoke for two?

Quantity and preparation both resolve to a SINGLE SCALAR ANSWER chosen from a
short list. An abstraction that fits exactly those two proves very little —
two points define a line, and the line can be an accident. So genericity is
not claimed by the contract suite; it is claimed here, and only by a third
family that is structurally different passing through unchanged.

THE THIRD FAMILY IS A PROBE, NOT A SHIPPED FIELD. It registers, produces,
presents, is answered, is held, and settles — through exactly the same
machinery — and is then removed. Shipping it would mean a field with no
producer and no user, which is the defect that got `UNUSABLE_AMOUNT` deleted.
Building it here answers the only question that matters: does adding a field
require the COORDINATOR to learn anything about it?

WHAT WOULD FAIL THIS FILE, and each is a real way the abstraction could be
secretly bespoke:

  * settlement needing a new branch to read the third field
  * the answer turn needing to know the attribute
  * readiness needing to special-case it
  * persistence needing a column, a table or a payload key
  * the wire needing a new shape
  * the coordinator importing anything about the field's meaning

If any of those is required, adding field four costs the same again, and the
mechanism is a two-field special case wearing a registry.
"""
from __future__ import annotations

import inspect

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_answer_turn as answer_turn
from core import b1_quantity_operation as b1
from core import semantic_fields as sf
from core.clarification_answer import Outcome
from core.semantics import (CandidateSource, ClarificationAttribute,
                            ClarificationGroup, ClarificationInteraction,
                            ClarificationOption, Provenance, ResponseType,
                            SetServingBasis, UnresolvedField)
from db.models import Base, FoodEntry, PendingOperation, User
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

INTERPRETED = {"food": "chicken breast", "calories": 187, "protein": 35,
               "carbs": 0, "fats": 4}

#: THE THIRD FAMILY. `serving_basis` is deliberately unlike the other two: it
#: answers "the numbers you have are per WHAT" rather than naming an amount or
#: a cooking method, it carries `Pricing.NONE` so it exercises the path where a
#: field is recorded and prices nothing, and its patch type is one no other
#: registered field uses.
THIRD = ClarificationAttribute.SERVING_BASIS
BASES = (("per_serving", "Per serving"), ("per_container", "Whole thing"))


@pytest.fixture(autouse=True)
def third_family_registered():
    """Register the probe, and put the registry back afterwards."""
    sf.register(sf.FieldSpec(
        attribute=THIRD,
        value_space=sf.ValueSpace.ENUMERATED,
        patch_type="set_serving_basis",
        # NONE, so no resolver-vocabulary check applies — the point of this
        # family is that a field can be recorded without pricing anything.
        pricing=sf.Pricing.NONE,
        evidence=sf.Evidence.ONTOLOGY,
        vocabulary=tuple(b for b, _ in BASES),
        caption="Per", order=30))
    yield
    sf._reset_for_tests()


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

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'three.db'}")
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
        u = User(telegram_id="b15:three", name="Three", timezone="UTC")
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


def _third_field(ask):
    """The probe field, built the way ANY field is built — nothing here is
    special-cased for it, which is the whole point."""
    group = ask.interaction.groups[0]
    identity = dict(operation_id=ask.operation_id, revision=ask.revision,
                    event_id=group.fields[0].event_id, attribute=THIRD)
    field_id = UnresolvedField(**identity).field_id
    return UnresolvedField(
        **identity, response_type=ResponseType.SINGLE_SELECT,
        options=tuple(
            ClarificationOption(
                label=label, option_id=f"basis_{basis}", field_id=field_id,
                source=CandidateSource.ONTOLOGY,
                patch=SetServingBasis(event_id=identity["event_id"],
                                      field_id=field_id, basis_id=basis,
                                      provenance=Provenance.USER_SELECTED))
            for basis, label in BASES))


async def _open_with_three(sessions, user):
    import json

    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=_material(), turn_id="t_1",
            channel="ios", locale="en")
        await s.commit()
    assert ask is not None

    group = ask.interaction.groups[0]
    from skills.nutrition import quantity_clarification as qc
    prep = qc.preparation_field(operation_id=ask.operation_id,
                                revision=ask.revision, item=_staged())
    three = ClarificationInteraction(
        interaction_id=ask.interaction.interaction_id,
        operation_id=ask.operation_id, revision=ask.revision,
        introduction=ask.interaction.introduction,
        groups=(ClarificationGroup(
            event_id=group.event_id, label=group.label,
            fields=(group.fields[0], prep, _third_field(ask))),))

    async with sessions() as s:
        row = (await s.execute(
            select(PendingOperation).where(
                PendingOperation.operation_id == ask.operation_id))
        ).scalars().one()
        payload = json.loads(row.canonical_payload)
        payload["interaction"] = three.to_payload()
        # ⛔ A REAL OPERATION'S DIGEST DESCRIBES ITS STORED MATERIAL *(P17
        # Phase 2)*. This fixture emulates the multi-field form B-1 really
        # opens, so it must keep the payload self-consistent the way the one
        # production write seam does — otherwise it is indistinguishable from
        # an outside edit, which the strict decoder correctly refuses.
        payload["fingerprint_version"] = b1.FINGERPRINT_VERSION
        payload["fingerprint"] = b1.fingerprint_of_payload(payload)
        row.canonical_payload = json.dumps(payload)
        await s.commit()
    return ask, three.groups[0].fields


async def _tap(sessions, user, ask, field, option_id, turn):
    async with sessions() as s:
        u = await s.get(User, user.id)
        out = await answer_turn.handle(
            s, user=u, source_turn_id=turn, field_id=field.field_id,
            option_id=option_id, revision=ask.revision, message="")
        await s.commit()
        return out


async def _rows(sessions):
    async with sessions() as s:
        return (await s.execute(select(FoodEntry))).scalars().all()


# ── the claim ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_three_fields_settle_once_through_the_same_machinery(
        sessions, user):
    """THE RULE OF THREE. Three structurally different fields, one operation,
    one commit — and not one line of coordinator code knows there are three.
    """
    ask, fields = await _open_with_three(sessions, user)
    quantity, preparation, basis = fields
    assert {f.attribute for f in fields} == {
        ClarificationAttribute.QUANTITY, ClarificationAttribute.PREPARATION,
        THIRD}

    first = await _tap(sessions, user, ask, quantity,
                       quantity.options[0].option_id, "t_2")
    assert first.outcome is Outcome.PARTIAL
    second = await _tap(sessions, user, ask, basis, "basis_per_serving", "t_3")
    assert second.outcome is Outcome.PARTIAL, "two of three settled the meal"
    assert not await _rows(sessions)

    third = await _tap(sessions, user, ask, preparation, "prep_grilled", "t_4")
    assert third.outcome is Outcome.APPLIED, f"{third.outcome}: {third.reason}"
    assert len(await _rows(sessions)) == 1, "three fields, one meal"


@pytest.mark.asyncio
async def test_the_third_field_is_held_and_settled_like_any_other(
        sessions, user):
    """Persistence learns nothing new: the same `answered` map, keyed by the
    same field ids, decoded by the same `patch_from_payload`."""
    import json

    ask, fields = await _open_with_three(sessions, user)
    _quantity, _preparation, basis = fields
    await _tap(sessions, user, ask, basis, "basis_per_container", "t_2")

    async with sessions() as s:
        row = (await s.execute(
            select(PendingOperation).where(
                PendingOperation.operation_id == ask.operation_id))
        ).scalars().one()
        held = json.loads(row.canonical_payload)["answered"]
    assert list(held) == [basis.field_id]
    assert held[basis.field_id]["patch_type"] == "set_serving_basis"

    async with sessions() as s:
        owned = await b1.owning(s, user=await s.get(User, user.id))
    resolved = b1.resolved_fields(owned.answered)
    assert resolved.of_type("set_serving_basis"), (
        "ResolvedFields could not carry a field it was not written for")
    assert resolved.quantity is None, "readiness would have let this settle"


@pytest.mark.asyncio
async def test_the_wire_needs_no_new_shape_for_a_third_field(sessions, user):
    """Three rows, same envelope. A field family that needed its own wire
    shape would mean the client learns the field too."""
    ask, fields = await _open_with_three(sessions, user)
    payload = b1.wire_payload_for(
        ClarificationInteraction(
            interaction_id="ix", operation_id=ask.operation_id,
            revision=ask.revision,
            groups=(ClarificationGroup(event_id=fields[0].event_id,
                                       label="Chicken breast",
                                       fields=tuple(fields)),)),
        locale="en")
    wired = payload["groups"][0]["fields"]
    assert len(wired) == 3
    assert {f["attribute"] for f in wired} == {
        "quantity", "preparation", "serving_basis"}
    for f in wired:
        assert set(f) == {"field_id", "attribute", "response_type",
                          "allows_free_text", "options"}


# ── the coordinator must not know any field's name ──────────────────────────

@pytest.mark.parametrize("function", ["settle", "hold_answer",
                                      "ready_to_settle", "open_fields"])
def test_the_coordinator_names_no_specific_field(function):
    """THE STRUCTURAL CLAIM, checked as source.

    `settle` reads `resolved.quantity` and `resolved.preparation_id` — those
    are accessors ON THE RESOLVED STATE, which is the domain layer's business.
    What must not appear is the coordinator branching on an attribute: any
    `if attribute == "preparation"` is field #4 costing the same as #3.
    """
    import ast as _ast
    import textwrap

    tree = _ast.parse(textwrap.dedent(inspect.getsource(getattr(b1, function))))
    offenders = [n.lineno for n in _ast.walk(tree)
                 if isinstance(n, _ast.Attribute)
                 and isinstance(n.value, _ast.Name)
                 and n.value.id == "ClarificationAttribute"]
    assert not offenders, (
        f"{function} names specific attributes at lines {offenders} — adding "
        f"a field should not require editing it")


def test_one_field_holds_exactly_one_answer_and_that_is_a_known_limit():
    """WHAT THE RULE OF THREE DOES *NOT* PROVE, written down as a test.

    All three families here answer with ONE option producing ONE patch, and
    `hold_answer` keys the held map by field id — so a second answer to a
    field REPLACES the first. That is correct for a correction and it is the
    behaviour B-1.5 wanted, but it means a genuinely MULTI-valued field
    ("no bun, extra cheese") cannot be expressed: it would need the held value
    to be a set, and `ResolvedFields._one` would have to stop assuming
    singularity.

    `ResponseType.MULTI_SELECT` exists in the vocabulary and nothing produces
    it. This gate is here so the day someone does, they find out from a test
    rather than from a user whose second selection vanished — and so
    "the mechanism is generic" is never read as broader than it is.
    """
    from core.semantics import ResponseType

    assert ResponseType.MULTI_SELECT, "the vocabulary member is gone"
    source = inspect.getsource(b1.hold_answer)
    assert "held[str(patch.field_id)] = patch" in source, (
        "hold_answer no longer stores one patch per field — if that is "
        "deliberate, multi-valued fields may now be possible and this limit "
        "should be re-tested rather than silently lifted")


def test_the_answer_turn_never_branches_on_an_attribute():
    import ast as _ast

    tree = _ast.parse(inspect.getsource(answer_turn))
    offenders = [n.lineno for n in _ast.walk(tree)
                 if isinstance(n, _ast.Attribute)
                 and isinstance(n.value, _ast.Name)
                 and n.value.id == "ClarificationAttribute"]
    assert not offenders, (
        f"the answer turn names specific attributes at lines {offenders} — "
        f"it must handle fields it has never heard of")
