"""B-0c: the B-0b types must survive storage, not just construction.

B-0b proved the contracts hold in memory. That is not the property B-1 needs.
B-1's wire contract is that a chip tap submits only
`operation_id · revision · field_id · option_id` and THE SERVER LOADS THE
STORED PATCH — so the types cross a process boundary and a JSON column in
between, and every guarantee that lives only in `__post_init__` has to survive
the trip.

What this file measures, and why each one is here:

  * ROUND TRIP RETURNS THE CONCRETE TYPE. `SetQuantity -> JSON -> SetQuantity`,
    never `-> dict`. Without a discriminator the server would recover meaning
    by sniffing which keys are present — re-inferring semantics from shape,
    which is the prose-parsing defect moved server-side.
  * DECIMALS SURVIVE EXACTLY. Through a JSON float, `Decimal("0.1")` comes
    back as something that is not equal to what went in, and portion
    arithmetic is why `CanonicalQuantity` uses `Decimal` at all.
  * VALIDATION RE-RUNS ON LOAD. A corrupted or hand-edited row fails at the
    read, not at the application boundary with a transaction already open.
  * THE STRUCTURE ENFORCES ITS OWN DOCSTRING. The mixed chip row, the
    foreign-event option, the empty select, the interaction carrying another
    operation's field — all were describable in prose and constructable in
    code.
  * IMMUTABILITY IS REAL. A frozen dataclass holding the caller's mutable dict
    is not frozen; the caller can keep editing it after construction.
  * THE FULL PERSISTENCE PATH. Not a serialization unit test: a real engine, a
    real `pending_operations` row, a committed transaction, a CLOSED session,
    a new session, and a typed patch recovered from an option id.
"""
import json
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.meal_commit import OutboxEvent, UnserializableResult
from core.semantics import (PATCH_SCHEMA_VERSION, PATCH_TYPES,
                            CandidateSource, CanonicalQuantity,
                            ClarificationAttribute, ClarificationGroup,
                            ClarificationInteraction, ClarificationOption,
                            Dimension, Provenance, ResponseType, SelectEntity,
                            SelectProductVariant, SemanticPatch,
                            SetConsumedFraction, SetPreparation, SetQuantity,
                            SetServingBasis, UncertaintyEvidence,
                            UnknownPatchType, UnresolvedField,
                            patch_from_payload)

OP, REV, EVENT = "op_1", 3, "food_chicken"
FIELD_ID = f"{OP}:{EVENT}:quantity:{REV}"


def _quantity(amount="5", grams="141.7"):
    return CanonicalQuantity(amount=Decimal(amount), unit_id="oz",
                             dimension=Dimension.MASS, grams=Decimal(grams),
                             provenance=Provenance.USER_SELECTED)


def _patch(**kw):
    base = dict(event_id=EVENT, field_id=FIELD_ID, quantity=_quantity(),
                provenance=Provenance.USER_SELECTED)
    base.update(kw)
    return SetQuantity(**base)


def _option(option_id="opt_5oz", **kw):
    base = dict(label="5 oz", option_id=option_id, field_id=FIELD_ID,
                patch=_patch(), source=CandidateSource.USER_HISTORY)
    base.update(kw)
    return ClarificationOption(**base)


def _field(**kw):
    base = dict(operation_id=OP, revision=REV, event_id=EVENT,
                attribute=ClarificationAttribute.QUANTITY,
                response_type=ResponseType.SINGLE_SELECT,
                options=(_option(),))
    base.update(kw)
    return UnresolvedField(**base)


def _interaction(**kw):
    base = dict(interaction_id="ix_1", operation_id=OP, revision=REV,
                introduction="How much chicken?",
                groups=(ClarificationGroup(event_id=EVENT, label="Chicken",
                                           fields=(_field(),)),))
    base.update(kw)
    return ClarificationInteraction(**base)


# ── patch serialization ──────────────────────────────────────────────────────

ONE_OF_EACH = (
    SetQuantity(event_id="e", field_id="f", quantity=_quantity(),
                provenance=Provenance.USER_SELECTED),
    SetConsumedFraction(event_id="e", field_id="f", fraction=Decimal("0.5"),
                        provenance=Provenance.USER_STATED),
    SelectEntity(event_id="e", field_id="f", entity_id="food.chicken"),
    SelectProductVariant(event_id="e", field_id="f", entity_id="off:301762",
                         serving_id="bottle_14oz"),
    SetPreparation(event_id="e", field_id="f", preparation_id="prep.grilled"),
    SetServingBasis(event_id="e", field_id="f", basis_id="per_container"),
)


@pytest.mark.parametrize("patch", ONE_OF_EACH, ids=lambda p: p.patch_type)
def test_every_patch_round_trips_as_its_concrete_type(patch):
    """`SetQuantity -> JSON -> SetQuantity`, not `-> dict`.

    Through real `json.dumps`/`loads`, because the storage substrate is a JSON
    text column — a round trip that skips the encoder proves nothing about it.
    """
    restored = patch_from_payload(json.loads(json.dumps(patch.to_payload())))
    assert type(restored) is type(patch), \
        "a loaded patch must be the type it was, or the server is key-sniffing"
    assert restored == patch


def test_the_registry_covers_every_patch_class():
    """A patch class without a registry entry is unstorable and would be
    discovered by the first producer, in production."""
    defined = {cls for cls in SemanticPatch.__subclasses__()}
    assert defined == set(PATCH_TYPES.values()), \
        f"unregistered patch classes: {defined - set(PATCH_TYPES.values())}"
    assert len(PATCH_TYPES) == len(defined), "two classes share a patch_type"


def test_decimals_survive_the_trip_exactly():
    """A JSON float would return 0.1000000000000000055…, and the whole reason
    quantities are Decimal is that portion arithmetic must not drift."""
    q = CanonicalQuantity(amount=Decimal("0.1"), unit_id="cup",
                          dimension=Dimension.VOLUME,
                          milliliters=Decimal("23.6588236"))
    p = SetQuantity(event_id="e", field_id="f", quantity=q)
    back = patch_from_payload(json.loads(json.dumps(p.to_payload())))
    assert back.quantity.amount == Decimal("0.1")
    assert str(back.quantity.milliliters) == "23.6588236"
    assert back == p


def test_an_unknown_patch_type_fails_closed():
    """Never "load it as a dict and hope" — that is the re-interpretation the
    discriminator exists to end."""
    good = _patch().to_payload()
    with pytest.raises(UnknownPatchType, match="unknown patch_type"):
        patch_from_payload({**good, "patch_type": "set_vibes"})
    with pytest.raises(UnknownPatchType):
        patch_from_payload({k: v for k, v in good.items()
                            if k != "patch_type"})
    with pytest.raises(UnknownPatchType, match="newer than"):
        patch_from_payload({**good,
                            "schema_version": PATCH_SCHEMA_VERSION + 1})
    with pytest.raises(UnknownPatchType):
        patch_from_payload("set_quantity")


def test_validation_re_runs_on_load_not_at_apply():
    """A corrupted row must fail at the read. Failing later means failing with
    the meal transaction already open."""
    payload = SetConsumedFraction(event_id="e", field_id="f",
                                  fraction=Decimal("0.5")).to_payload()
    with pytest.raises(ValueError, match="consumed fraction"):
        patch_from_payload({**payload, "fraction": "1.5"})
    with pytest.raises(ValueError):
        patch_from_payload({**_patch().to_payload(), "event_id": ""})


# ── enum coercion symmetry ───────────────────────────────────────────────────

def test_provenance_is_an_enum_everywhere_after_construction():
    """A string provenance made `is_users_own` raise AttributeError and every
    `is` comparison silently False — reclassifying a user's own figure as an
    estimate, the exact 2026-08-04 disclosure defect."""
    p = SetQuantity(event_id="e", field_id="f", quantity=_quantity(),
                    provenance="user_stated")
    assert p.provenance is Provenance.USER_STATED
    assert p.provenance.is_users_own

    q = CanonicalQuantity(amount=Decimal("1"), unit_id="g",
                          dimension="mass", grams=Decimal("1"),
                          provenance="user_stated")
    assert q.provenance is Provenance.USER_STATED
    assert q.dimension is Dimension.MASS
    assert not q.is_estimated

    for bad in ("user_statedd", "vibes"):
        with pytest.raises(ValueError):
            SetQuantity(event_id="e", field_id="f", quantity=_quantity(),
                        provenance=bad)
        with pytest.raises(ValueError):
            ClarificationOption(label="x", option_id="o", source=bad)


def test_an_option_refuses_an_untyped_patch():
    """The 'authoritative meaning' slot may not hold the unvalidated dict the
    patch type exists to replace."""
    with pytest.raises(ValueError, match="SemanticPatch"):
        ClarificationOption(label="5 oz", option_id="o",
                            patch={"patch_type": "set_quantity"})


def test_adapter_built_is_the_c10_enforcement_key():
    """`patch=None` is permitted only on inventoried legacy measurement paths.
    Before this field there was nothing to key that predicate on, so a new
    canonical producer could ship a patchless option and evade C8, C9 and the
    unwritten C10 alike."""
    from skills.nutrition import clarification_adapter

    legacy = clarification_adapter._option_of("Grilled", "legacy:0:text")
    assert legacy.adapter_built and legacy.patch is None
    assert _option().adapter_built is False


# ── structural validation ────────────────────────────────────────────────────

def test_a_group_cannot_hold_another_events_field():
    """The canonical defect one level down: the mixed chip row was only ever
    forbidden in a docstring."""
    with pytest.raises(ValueError, match="mixed chip row"):
        ClarificationGroup(event_id="food_fairlife",
                           fields=(_field(event_id=EVENT),))
    with pytest.raises(ValueError, match="addressed by its event"):
        ClarificationGroup(event_id="", fields=(_field(),))
    with pytest.raises(ValueError, match="no fields"):
        ClarificationGroup(event_id=EVENT)
    with pytest.raises(ValueError, match="duplicate field"):
        ClarificationGroup(event_id=EVENT, fields=(_field(), _field()))


def test_an_interaction_owns_one_operation_and_one_revision():
    """A field from another operation would render a chip whose tap patches
    something other than the operation being answered."""
    text_only = dict(response_type=ResponseType.FREE_TEXT, options=())
    foreign = ClarificationGroup(
        event_id=EVENT, fields=(_field(operation_id="op_2", **text_only),))
    with pytest.raises(ValueError, match="mixed operation ownership"):
        _interaction(groups=(foreign,))

    stale = ClarificationGroup(
        event_id=EVENT, fields=(_field(revision=REV + 1, **text_only),))
    with pytest.raises(ValueError, match="cannot carry field"):
        _interaction(groups=(stale,))

    twice = ClarificationGroup(event_id=EVENT, fields=(_field(),))
    with pytest.raises(ValueError, match="two groups"):
        _interaction(groups=(twice, twice))


def test_a_select_with_no_options_must_say_so():
    """C15: never a blank row the client 'repairs' by parsing prose."""
    with pytest.raises(ValueError, match="FREE_TEXT_FALLBACK"):
        _field(response_type=ResponseType.SINGLE_SELECT, options=())
    with pytest.raises(ValueError, match="IS a select"):
        _field(response_type=ResponseType.FREE_TEXT, options=(_option(),))
    fallback = _field(response_type=ResponseType.FREE_TEXT_FALLBACK,
                      options=())
    assert fallback.response_type is ResponseType.FREE_TEXT_FALLBACK


def test_an_option_cannot_answer_a_foreign_field():
    with pytest.raises(ValueError, match="mixed chip row, one level down"):
        _field(options=(_option(field_id="op_1:food_rice:quantity:3"),))
    with pytest.raises(ValueError, match="no option_id"):
        _field(options=(_option(option_id=""),))
    with pytest.raises(ValueError, match="duplicate option_id"):
        _field(options=(_option(), _option()))


def test_a_tap_resolves_against_stored_options_or_is_refused():
    """The server side of the wire contract. An unknown id is refused, never
    re-interpreted, and a patchless canonical option is an error rather than a
    silent fall back to the label."""
    ix = _interaction()
    assert ix.patch_for(FIELD_ID, "opt_5oz") == _patch()
    with pytest.raises(KeyError):
        ix.patch_for(FIELD_ID, "opt_nonexistent")
    with pytest.raises(KeyError):
        ix.patch_for("op_1:food_rice:quantity:3", "opt_5oz")

    patchless = _interaction(groups=(ClarificationGroup(
        event_id=EVENT, fields=(_field(options=(
            _option(patch=None, adapter_built=True),)),)),))
    with pytest.raises(ValueError, match="carries no patch"):
        patchless.patch_for(FIELD_ID, "opt_5oz")


def test_the_whole_interaction_round_trips():
    ix = _interaction()
    restored = ClarificationInteraction.from_payload(
        json.loads(json.dumps(ix.to_payload())))
    assert restored == ix
    assert isinstance(restored.patch_for(FIELD_ID, "opt_5oz"), SetQuantity)
    with pytest.raises(ValueError, match="newer than"):
        ClarificationInteraction.from_payload(
            {**ix.to_payload(),
             "schema_version": ClarificationInteraction.SCHEMA_VERSION + 1})
    with pytest.raises(ValueError):
        ClarificationInteraction.from_payload(
            {k: v for k, v in ix.to_payload().items()
             if k != "schema_version"})


def test_the_workout_seam_needs_no_food_edit():
    """A device-sourced duration candidate and an exercise identity patch must
    both be constructable from the shared types alone."""
    field = UnresolvedField(
        operation_id=OP, revision=REV, event_id="ex_bench",
        attribute=ClarificationAttribute.EXERCISE_IDENTITY,
        response_type=ResponseType.SINGLE_SELECT,
        uncertainty=UncertaintyEvidence(
            low=Decimal("60"), high=Decimal("100"), unit_id="kg",
            impact_spread=CanonicalQuantity(amount=Decimal("40"),
                                            unit_id="kg",
                                            dimension=Dimension.MASS,
                                            grams=Decimal("40000"))),
        options=(ClarificationOption(
            label="Barbell bench press", option_id="opt_bb",
            field_id=f"{OP}:ex_bench:exercise_identity:{REV}",
            source=CandidateSource.DEVICE,
            patch=SelectEntity(event_id="ex_bench",
                               field_id=f"{OP}:ex_bench:exercise_identity:{REV}",
                               entity_id="exercise.bench_press")),))
    assert field.options[0].source is CandidateSource.DEVICE
    assert field.uncertainty.impact_spread.dimension is Dimension.MASS
    restored = UnresolvedField.from_payload(
        json.loads(json.dumps(field.to_payload())))
    assert restored == field


# ── immutability ─────────────────────────────────────────────────────────────

def test_an_outbox_payload_cannot_be_edited_after_construction():
    """"Validated at construction" was untrue while the caller's dict was
    stored by reference: a producer that kept enriching its own dict injected
    a Decimal past the check, and `record_result` then raised INSIDE the meal
    transaction — unwinding a ledger write that had already succeeded."""
    mutable = {"user_id": 144}
    event = OutboxEvent(kind="memory_update", payload=mutable, dedup_key="k")
    mutable["injected"] = Decimal("1.5")

    assert "injected" not in event.payload
    json.dumps(event.to_payload())          # would raise on the aliased dict

    event.to_payload()["payload"]["tampered"] = True
    assert "tampered" not in event.payload


def test_the_outbox_schema_version_key_is_reserved():
    """The enqueue envelope stamps `version`; a payload key of the same name
    silently replaced it, and the corrupt job row was shaped exactly like a
    valid one."""
    with pytest.raises(UnserializableResult, match="reserved key"):
        OutboxEvent(kind="analysis", payload={"version": "217"},
                    dedup_key="k")


# ── the persistence proof ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def engine(tmp_path):
    """OVERRIDES conftest's shared :memory: engine, deliberately.

    The claim under test is that a patch survives a CLOSED session. On the
    shared StaticPool connection every session is the same connection, so the
    test would pass without the data ever reaching storage — a test that
    cannot fail. A file database gives real per-session connections.
    """
    from db.database import make_engine
    from db.models import Base

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'b0c.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_a_stored_option_id_becomes_a_typed_patch_in_a_new_session(engine):
    """THE PROPERTY B-1 ACTUALLY DEPENDS ON, end to end.

        build interaction with a SetQuantity option
          -> serialize into the PendingOperation payload
          -> COMMIT
          -> close the session
          -> open a NEW session
          -> load the operation
          -> bind (field_id, option_id)
          -> get a typed SetQuantity back
          -> apply it

    Every in-memory contract test above can pass while this fails, which is
    why this one exists: the tap arrives on a different request, and possibly
    a different worker, from the turn that offered the chip.
    """
    from core import pending_repository as repo
    from db.models import PendingOperation

    Session = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    interaction = _interaction()

    async with Session() as write:
        await repo.create_operation(
            write, operation_id=OP, user_id=144, status="awaiting_answer",
            storage_status="active",
            payload=repo.encode_payload(
                items=[{"name": "Chicken breast"}],
                unresolved_fields=[interaction.to_payload()]))
        await write.commit()

    # The offering turn is over. Nothing of it survives except the row.
    del interaction

    async with Session() as read:
        row = (await read.execute(select(PendingOperation).where(
            PendingOperation.operation_id == OP))).scalar_one()
        stored = repo.decode_payload(row.canonical_payload)
        loaded = ClarificationInteraction.from_payload(
            stored["unresolved_fields"][0])

        # The tap: four ids and nothing else. No label travels back.
        patch = loaded.patch_for(FIELD_ID, "opt_5oz")

    assert isinstance(patch, SetQuantity), \
        "the server must recover the CONCRETE patch, not a dict to re-read"
    assert patch.quantity.grams == Decimal("141.7"), "Decimal, not 141.69999"
    assert patch.quantity.dimension is Dimension.MASS
    assert patch.provenance is Provenance.USER_SELECTED, \
        "a tapped chip is not the user's own figure — the distinction must " \
        "survive storage or the disclosure defect returns"
    assert patch.event_id == EVENT and patch.field_id == FIELD_ID


@pytest.mark.asyncio
async def test_a_stale_revision_cannot_be_answered_from_storage(engine):
    """Revision is part of `field_id`, so a tap on last turn's chip addresses
    a field the current interaction does not have — refused, not applied to
    whatever field looks closest."""
    Session = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    from core import pending_repository as repo

    async with Session() as write:
        await repo.create_operation(
            write, operation_id=OP, user_id=144, status="awaiting_answer",
            storage_status="active",
            payload=repo.encode_payload(
                unresolved_fields=[_interaction().to_payload()]))
        await write.commit()

    async with Session() as read:
        row = await repo.load_operation(read, OP)
        loaded = ClarificationInteraction.from_payload(
            repo.decode_payload(row.canonical_payload)["unresolved_fields"][0])

    with pytest.raises(KeyError, match="not a field"):
        loaded.patch_for(f"{OP}:{EVENT}:quantity:{REV - 1}", "opt_5oz")
