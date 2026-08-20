"""⛔⛔ P17 CLOSURE — PHASE 2: CANONICAL-OPERATION DURABILITY.

A canonical operation is a promise kept across turns, restarts and workers:
the question the user answers on Tuesday is the question we stored on Monday.
The directive's eight requirements, each proved here:

    1  the fingerprint's VERSION and DIGEST are persisted at creation — an
       old row is never recomputed as though it used today's rules
    2  the stored `schema_version` is validated
    3  the stored item is decoded STRICTLY: a dict, present; no falsy value
       is coerced into `{}`
    4  ownership is verified before reuse: user, domain, source turn, and the
       operation id itself
    5  a reuse renders ONLY from persisted authority: interaction, item,
       revision, locale, cohort, capability
    6  the same operation id with different semantic material REFUSES
    7  a race loser reuses only the exact matching stored winner
    8  a refusal is non-mutating: no food row, no legacy pending question, no
       replacement canonical operation; the conversation turn still commits
       and the session stays usable

`oneask001` remains the single-owner DATABASE backstop — and the application
behaviour is correct without it, which the last test proves by removing the
integrity error from the path entirely.
"""
from __future__ import annotations

import json

import pytest

from sqlalchemy import select


DOMAIN = "food"


async def _interaction(db, user, turn_id, *, food="Oatmeal", amount=1,
                       unit="bowl", calories=150):
    from core.b1_quantity_operation import _operation_id_for
    from core.food_pipeline import stage_items
    from skills.nutrition import quantity_clarification as qc
    op_id = _operation_id_for(user, turn_id)
    items, _ = stage_items({"items": [{"food": food, "amount": amount,
                                       "unit": unit, "calories": calories}]},
                           turn_id=turn_id, message="x", mode="strict")
    field = qc.quantity_field(operation_id=op_id, revision=0, item=items[0])
    return op_id, qc.build_interaction(operation_id=op_id, revision=0,
                                       item=items[0], options=field.options,
                                       introduction=f"How much {food}?",
                                       ask_preparation=False)


async def _row(db, op_id):
    from db.models import PendingOperation
    return (await db.execute(select(PendingOperation).where(
        PendingOperation.operation_id == op_id))).scalars().one()


async def _repayload(db, op_id, mutate):
    """Rewrite the stored payload through `mutate(dict) -> dict`."""
    row = await _row(db, op_id)
    data = json.loads(row.canonical_payload or "{}")
    row.canonical_payload = json.dumps(mutate(data))
    await db.commit()
    return row


# ═════ 1 — THE FINGERPRINT IS PERSISTED, WITH ITS VERSION ══════════════════

@pytest.mark.asyncio
async def test_1_the_fingerprint_and_its_version_are_persisted_at_creation(
        db, make_user):
    from core.b1_quantity_operation import (FINGERPRINT_VERSION,
                                            ID_ADDRESSED, open_operation,
                                            semantic_fingerprint)
    user = await make_user()
    tid = f"ios:fp-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    item = {"food": "Oatmeal", "amount": 1, "unit": "bowl"}
    opened = await open_operation(db, user=user, interpreter_item=item,
                                  interaction=inter, turn_id=tid, locale="en",
                                  cohort="allowlist", capability=ID_ADDRESSED)
    await db.commit()
    data = json.loads((await _row(db, op_id)).canonical_payload)
    assert data["fingerprint_version"] == FINGERPRINT_VERSION
    assert data["fingerprint"] == semantic_fingerprint(inter, item)
    assert data["fingerprint"] == opened.fingerprint
    assert data["capability"] == ID_ADDRESSED


@pytest.mark.asyncio
async def test_1_a_row_written_under_another_fingerprint_version_refuses(
        db, make_user):
    """⛔ THE POINT OF THE VERSION: a row fingerprinted under other rules is
    NOT recomputed under today's — it is not comparable, and reuse refuses."""
    from core.b1_quantity_operation import (StoredFingerprintVersionMismatch,
                                            _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:fpv-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, locale="en", capability="id_addressed")
    await db.commit()
    row = await _repayload(db, op_id, lambda d: {**d,
                                                 "fingerprint_version": "fp0"})
    with pytest.raises(StoredFingerprintVersionMismatch, match="fp0"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


@pytest.mark.asyncio
async def test_1_a_row_with_no_stored_fingerprint_refuses(db, make_user):
    """A row written before the fingerprint was persisted cannot prove it
    means the same thing. Fail closed rather than recompute."""
    from core.b1_quantity_operation import (StoredFingerprintVersionMismatch,
                                            _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:fpnone-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    row = await _repayload(db, op_id, lambda d: {
        k: v for k, v in d.items()
        if k not in ("fingerprint", "fingerprint_version")})
    with pytest.raises(StoredFingerprintVersionMismatch, match="stores no fingerprint"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


@pytest.mark.asyncio
async def test_1_a_payload_edited_after_the_write_no_longer_matches_its_digest(
        db, make_user):
    """The stored digest is an integrity check on the payload: change the
    item after the write and the row refuses to be reused."""
    from core.b1_quantity_operation import (FingerprintUnreadable,
                                            _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:fptamper-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    row = await _repayload(db, op_id,
                           lambda d: {**d, "item": {"food": "Something else"}})
    with pytest.raises(FingerprintUnreadable, match="does not match the fingerprint"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


# ═════ 2 — THE STORED SCHEMA VERSION IS VALIDATED ══════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, 0, 2, "1", {"v": 1}])
async def test_2_an_unknown_schema_version_is_refused(db, make_user, stored):
    from core.b1_quantity_operation import (FingerprintUnreadable,
                                            _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:schema-{user.id}-{stored!r}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    row = await _repayload(db, op_id, lambda d: {**d, "schema_version": stored})
    with pytest.raises(FingerprintUnreadable, match="schema_version"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


@pytest.mark.asyncio
async def test_2_the_answer_side_also_validates_the_schema_version(db, make_user):
    """`owning()` keeps its fail-OPEN contract (the operation still owns the
    meal) but a payload it cannot read becomes the REPAIR path, never a
    question about nothing."""
    from core.b1_quantity_operation import open_operation, owning
    user = await make_user()
    tid = f"ios:schema-ans-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    assert (await owning(db, user)).interaction is not None
    await _repayload(db, op_id, lambda d: {**d, "schema_version": 99})
    owned = await owning(db, user)
    assert owned is not None, "the operation must still OWN the meal"
    assert owned.interaction is None and owned.item == {}


# ═════ 3 — THE STORED ITEM IS DECODED STRICTLY ═════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [0, "", [], None, False, "Oatmeal", 3.5])
async def test_3_a_non_dict_item_is_never_coerced_to_an_empty_dict(
        db, make_user, stored):
    """⛔ `data.get("item") or {}` turned every falsy value into `{}` — which
    then passed an isinstance check and rendered as a question about nothing.
    Present AND a dict, or refuse."""
    from core.b1_quantity_operation import (FingerprintUnreadable,
                                            _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:item-{user.id}-{stored!r}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    row = await _repayload(db, op_id, lambda d: {**d, "item": stored})
    with pytest.raises(FingerprintUnreadable, match="stored item is"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


@pytest.mark.asyncio
async def test_3_a_missing_item_key_is_refused_not_defaulted(db, make_user):
    from core.b1_quantity_operation import (FingerprintUnreadable,
                                            _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:item-missing-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    row = await _repayload(db, op_id,
                           lambda d: {k: v for k, v in d.items() if k != "item"})
    with pytest.raises(FingerprintUnreadable, match="stored item is NoneType"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


@pytest.mark.asyncio
async def test_3_the_answer_side_refuses_a_non_dict_item_too(db, make_user):
    from core.b1_quantity_operation import open_operation, owning
    user = await make_user()
    tid = f"ios:item-ans-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    await _repayload(db, op_id, lambda d: {**d, "item": []})
    owned = await owning(db, user)
    assert owned is not None and owned.interaction is None and owned.item == {}


# ═════ 2b — THE ANSWER PATH VERIFIES THE FINGERPRINT TOO ═══════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("what", ["item", "interaction"])
async def test_2_a_tampered_payload_is_refused_on_the_ANSWER_turn_too(
        db, make_user, what):
    """⛔ P17 PHASE 2, SECOND ROUND, BLOCKER 2. Verification lived only on the
    ask side: `_stored_open_result` checked the version and recomputed the
    digest, while `owning()` checked schema, item type and interaction
    decoding — so a payload edited after the write refused a REUSE and was
    still CONSUMED by the answer turn, which could settle the modified
    material. One decoder now answers both.

    Ownership is preserved (the operation still owns the meal) and the turn
    routes to REPAIR: no interaction, no item, nothing to settle."""
    from core.b1_quantity_operation import (ID_ADDRESSED, open_operation,
                                            owning)
    user = await make_user()
    tid = f"ios:tamper-{what}-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user,
                         interpreter_item={"food": "Oatmeal", "amount": 1},
                         interaction=inter, turn_id=tid, locale="en",
                         cohort="allowlist", capability=ID_ADDRESSED)
    await db.commit()
    assert (await owning(db, user)).interaction is not None    # readable first

    if what == "item":
        await _repayload(db, op_id,
                         lambda d: {**d, "item": {"food": "Chicken thighs",
                                                  "amount": 99}})
    else:
        bad = json.loads(json.dumps(inter.to_payload()))
        bad["introduction"] = "How much chicken?"
        await _repayload(db, op_id, lambda d: {**d, "interaction": bad})

    owned = await owning(db, user)
    assert owned is not None, "the operation stopped owning the meal"
    assert owned.interaction is None, "the tampered payload was consumed"
    assert owned.item == {}, owned.item
    # the metric facts about the row survive; the AUTHORITY does not
    assert owned.cohort == "allowlist"


@pytest.mark.asyncio
async def test_2_a_tampered_payload_settles_nothing_on_a_real_answer_turn(
        db, make_user, monkeypatch):
    """The consumer-side half: an actual answer turn over a tampered
    operation writes no food row, no ledger event, and never reaches the
    legacy executor."""
    import handlers.tool_executor as te
    from core import b1_answer_turn
    from core.b1_quantity_operation import ID_ADDRESSED, open_operation
    from db.models import FoodEntry, LedgerEvent
    from tests.test_a_scan_is_binding import _log

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor ran on a tampered operation")

    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    user = await make_user()
    log = await _log(db, user)
    tid = f"ios:tamper-answer-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user,
                         interpreter_item={"food": "Oatmeal", "amount": 1},
                         interaction=inter, turn_id=tid, locale="en",
                         cohort="allowlist", capability=ID_ADDRESSED)
    await db.commit()
    await _repayload(db, op_id,
                     lambda d: {**d, "item": {"food": "Chicken thighs",
                                              "amount": 99, "calories": 900}})

    turn = await b1_answer_turn.handle(
        db, user=user, source_turn_id=f"{tid}-ans", message="2 servings")
    await db.commit()

    rows = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all()
    assert rows == [], [r.parsed_food_name for r in rows]
    events = (await db.execute(select(LedgerEvent).where(
        LedgerEvent.user_id == user.id))).scalars().all()
    assert events == []
    if turn is not None:
        assert getattr(turn, "outcome", None) is not None
        assert str(getattr(turn.outcome, "name", turn.outcome)).upper() != "APPLIED"


# ═════ 4 — OWNERSHIP IS VERIFIED BEFORE REUSE ══════════════════════════════

@pytest.mark.asyncio
async def test_4_ownership_user_domain_turn_and_operation_id(db, make_user):
    from core.b1_quantity_operation import (ID_ADDRESSED, OpenedElsewhere,
                                            _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:own2-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, locale="en",
                         cohort="allowlist", capability=ID_ADDRESSED)
    await db.commit()
    row = await _row(db, op_id)
    good = dict(created=False, expect_user_id=user.id, expect_turn_id=tid,
                expect_operation_id=op_id)
    assert _stored_open_result(row, **good).operation_id == op_id
    for override, match in (
            ({"expect_user_id": user.id + 7}, "belongs to user"),
            ({"expect_turn_id": "ios:other"}, "opened on turn"),
            ({"expect_operation_id": "chat_quantity:elsewhere"}, "carries operation"),
            ({"expect_turn_id": ""}, "states no source turn")):
        with pytest.raises(OpenedElsewhere, match=match):
            _stored_open_result(row, **{**good, **override})
    row.domain = "workout"
    with pytest.raises(OpenedElsewhere, match="is domain"):
        _stored_open_result(row, **good)


# ═════ 5 — A REUSE RENDERS ONLY FROM PERSISTED AUTHORITY ═══════════════════

@pytest.mark.asyncio
async def test_5_a_reuse_renders_every_fact_from_the_row(db, make_user):
    """The retry arrives with DIFFERENT locale, cohort and capability. What
    is rendered is what persisted — including the capability, which decides
    whether the options are in the sentence."""
    from core.b1_quantity_operation import (ID_ADDRESSED, LABEL_TEXT,
                                            open_operation)
    user = await make_user()
    tid = f"ios:render-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    item = {"food": "Oatmeal", "amount": 1, "unit": "bowl"}
    first = await open_operation(db, user=user, interpreter_item=item,
                                 interaction=inter, turn_id=tid, locale="ru",
                                 cohort="allowlist", capability=ID_ADDRESSED)
    await db.commit()
    assert first.created and first.capability == ID_ADDRESSED
    again = await open_operation(db, user=user, interpreter_item=item,
                                 interaction=inter, turn_id=tid, locale="en",
                                 cohort="scan_bound", capability=LABEL_TEXT)
    assert again.reused
    assert (again.locale, again.cohort,
            again.capability) == ("ru", "allowlist", ID_ADDRESSED)
    assert again.item == item and again.revision == first.revision
    assert again.interaction.to_payload() == first.interaction.to_payload()


@pytest.mark.asyncio
async def test_5_the_bound_ask_renders_the_stored_capability(db, make_user,
                                                             monkeypatch):
    """The consumer-side proof: `CanonicalAsk.capability` comes from the row,
    not from the channel this retry happened to arrive on."""
    from tests.test_a_scan_is_binding import _log, _prod_snapshot
    from core.general_settlement import coverage_for
    from core.product_bound_ask import open_bound_quantity_ask
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _prod_snapshot(db)
    item = {"food": "Barebells", "food_name": "Barebells", "quantity": "2 bar",
            "product_evidence_id": snap.id}
    coverage = await coverage_for(db, user_id=int(user.id), items=[item])
    tid = f"ios:cap-{user.id}"
    first = await open_bound_quantity_ask(db, user=user, item=item,
                                          coverage=coverage, turn_id=tid,
                                          channel="ios", locale="en")
    from core.b1_quantity_operation import ID_ADDRESSED, LABEL_TEXT
    assert first is not None and first.capability == ID_ADDRESSED
    await db.commit()
    again = await open_bound_quantity_ask(db, user=user, item=item,
                                          coverage=coverage, turn_id=tid,
                                          channel="telegram", locale="en")
    assert again is not None
    assert again.capability == ID_ADDRESSED, (
        "the retry re-rendered under its own channel: telegram is "
        f"{LABEL_TEXT}, the stored ask was built for {ID_ADDRESSED}")


# ═════ 5b — PERSISTED RENDERING FIELDS ARE REQUIRED, NOT SYNTHESIZED ═══════

@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["locale", "cohort", "capability"])
async def test_5_deleting_a_persisted_rendering_field_refuses_rather_than_defaults(
        db, make_user, field):
    """⛔ P17 PHASE 2, SECOND ROUND, BLOCKER 3. The decoder used to default a
    missing `locale`/`cohort`/`capability` (`str(data.get(...) or "en")`),
    which SYNTHESISES a rendering fact the row never carried. Under this
    schema they are required: delete one and the reuse refuses."""
    from core.b1_quantity_operation import (FingerprintUnreadable,
                                            ID_ADDRESSED, _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:field-{field}-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, locale="en",
                         cohort="allowlist", capability=ID_ADDRESSED)
    await db.commit()
    row = await _repayload(db, op_id,
                           lambda d: {k: v for k, v in d.items() if k != field})
    with pytest.raises(FingerprintUnreadable, match=field):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["ios", "telegram", "chips", "", None, 1])
async def test_5_an_unrecognised_capability_is_refused_on_read(db, make_user, bad):
    """The field holds a CAPABILITY, not a channel. A stored value outside
    the vocabulary — including the channel names the product-bound wrapper
    used to write — is refused rather than rendered."""
    from core.b1_quantity_operation import (FingerprintUnreadable,
                                            ID_ADDRESSED, _stored_open_result,
                                            open_operation)
    user = await make_user()
    tid = f"ios:cap-bad-{user.id}-{bad!r}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, locale="en",
                         cohort="allowlist", capability=ID_ADDRESSED)
    await db.commit()
    row = await _repayload(db, op_id, lambda d: {**d, "capability": bad})
    with pytest.raises(FingerprintUnreadable, match="capability"):
        _stored_open_result(row, created=False, expect_user_id=user.id,
                            expect_turn_id=tid, expect_operation_id=op_id)


@pytest.mark.asyncio
async def test_5_an_unrecognised_capability_is_refused_on_WRITE_too(db, make_user):
    """An ask no client can be proved to answer is never persisted — so the
    row can never be unreadable to its own reuse."""
    from core.b1_quantity_operation import OpenedElsewhere, open_operation
    user = await make_user()
    tid = f"ios:cap-write-{user.id}"
    _op_id, inter = await _interaction(db, user, tid)
    for bad in ("ios", "chips", ""):
        with pytest.raises(OpenedElsewhere, match="capability"):
            await open_operation(db, user=user,
                                 interpreter_item={"food": "Oatmeal"},
                                 interaction=inter, turn_id=tid, locale="en",
                                 cohort="allowlist", capability=bad)


def test_5_no_consumer_falls_back_to_a_live_capability():
    """AST: neither consumer may write `opened.capability or <anything>` —
    that is the synthesis requirement 5 forbids."""
    import ast
    import inspect
    from core import b1_quantity_operation as m
    from core import product_bound_ask as pba

    for module in (m, pba):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for value in node.values:
                    if (isinstance(value, ast.Attribute)
                            and value.attr == "capability"
                            and isinstance(value.value, ast.Name)
                            and value.value.id == "opened"):
                        raise AssertionError(
                            f"{module.__name__} falls back from the persisted "
                            f"capability")


# ═════ 6 — SAME OPERATION ID, DIFFERENT MATERIAL, REFUSES ══════════════════

@pytest.mark.asyncio
async def test_6_same_operation_id_with_different_material_refuses(db, make_user):
    from core.b1_quantity_operation import OpenedElsewhere, open_operation
    user = await make_user()
    tid = f"ios:material-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    with pytest.raises(OpenedElsewhere, match="DIFFERENT semantic payload"):
        await open_operation(db, user=user,
                             interpreter_item={"food": "Chicken thighs"},
                             interaction=inter, turn_id=tid, capability="id_addressed")


@pytest.mark.asyncio
async def test_6_the_same_material_twice_is_an_idempotent_reuse(db, make_user):
    from core.b1_quantity_operation import open_operation
    from db.models import PendingOperation
    user = await make_user()
    tid = f"ios:idem-{user.id}"
    _op_id, inter = await _interaction(db, user, tid)
    item = {"food": "Oatmeal", "amount": 1}
    a = await open_operation(db, user=user, interpreter_item=item,
                             interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    b = await open_operation(db, user=user, interpreter_item=item,
                             interaction=inter, turn_id=tid, capability="id_addressed")
    assert a.created and b.reused and a.operation_id == b.operation_id
    rows = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().all()
    assert len(rows) == 1, "a retry inserted a second row"


# ═════ 7 — A RACE LOSER REUSES ONLY THE EXACT STORED WINNER ════════════════

@pytest.mark.asyncio
async def test_7_a_race_loser_reuses_only_an_exactly_matching_winner(
        db, make_user, monkeypatch):
    """The insert raises IntegrityError (the constraint fired); the winner
    row IS this operation and stores the same material -> reuse. The proof
    drives the real seam by making the create fail once."""
    from sqlalchemy.exc import IntegrityError
    import core.pending_repository as repo
    from core.b1_quantity_operation import open_operation
    user = await make_user()
    tid = f"ios:race-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    item = {"food": "Oatmeal", "amount": 1}
    winner = await open_operation(db, user=user, interpreter_item=item,
                                  interaction=inter, turn_id=tid,
                                  locale="en", cohort="allowlist", capability="id_addressed")
    await db.commit()

    real_load = repo.load_operation
    calls = {"n": 0}

    async def blind_first(dbx, operation_id):
        # the loser's pre-check runs BEFORE the winner is visible to it
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_load(dbx, operation_id)

    async def boom(*a, **k):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(repo, "load_operation", blind_first)
    monkeypatch.setattr(repo, "create_operation", boom)
    loser = await open_operation(db, user=user, interpreter_item=item,
                                 interaction=inter, turn_id=tid,
                                 locale="en", cohort="allowlist", capability="id_addressed")
    assert loser.reused and loser.operation_id == winner.operation_id
    assert loser.fingerprint == winner.fingerprint
    assert loser.locale == "en" and loser.cohort == "allowlist"


@pytest.mark.asyncio
async def test_7_a_race_loser_with_different_material_refuses(db, make_user,
                                                              monkeypatch):
    from sqlalchemy.exc import IntegrityError
    import core.pending_repository as repo
    from core.b1_quantity_operation import OpenedElsewhere, open_operation
    user = await make_user()
    tid = f"ios:race2-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()

    real_load = repo.load_operation
    calls = {"n": 0}

    async def blind_first(dbx, operation_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else await real_load(dbx, operation_id)

    async def boom(*a, **k):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(repo, "load_operation", blind_first)
    monkeypatch.setattr(repo, "create_operation", boom)
    with pytest.raises(OpenedElsewhere):
        await open_operation(db, user=user,
                             interpreter_item={"food": "Chicken thighs"},
                             interaction=inter, turn_id=tid, capability="id_addressed")


@pytest.mark.asyncio
async def test_7_a_race_lost_to_another_operation_entirely_refuses(
        db, make_user, monkeypatch):
    """The partial unique index fired for a DIFFERENT operation: the winner
    is not ours, so it is never rendered as ours."""
    from sqlalchemy.exc import IntegrityError
    import core.pending_repository as repo
    from core.b1_quantity_operation import OpenedElsewhere, open_operation
    user = await make_user()
    tid = f"ios:race3-{user.id}"
    _op_id, inter = await _interaction(db, user, tid)

    async def boom(*a, **k):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    async def none_after(dbx, operation_id):
        return None                         # our id never landed

    monkeypatch.setattr(repo, "create_operation", boom)
    monkeypatch.setattr(repo, "load_operation", none_after)
    with pytest.raises(OpenedElsewhere, match="lost the race"):
        await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                             interaction=inter, turn_id=tid, capability="id_addressed")


# ═════ 8 — A REFUSAL IS NON-MUTATING, AND THE SESSION SURVIVES IT ══════════

@pytest.mark.asyncio
async def test_8_a_refusal_writes_nothing_and_leaves_the_session_usable(
        db, make_user):
    """No food row, no legacy pending question, no REPLACEMENT canonical
    operation — the original row is byte-identical — and the next ordinary
    ask still opens."""
    from core.b1_quantity_operation import OpenedElsewhere, open_operation
    from db.models import FoodEntry, LedgerEvent, PendingOperation
    from tests.test_a_scan_is_binding import _log
    user = await make_user()
    log = await _log(db, user)
    tid = f"ios:refuse-{user.id}"
    op_id, inter = await _interaction(db, user, tid)
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter, turn_id=tid, capability="id_addressed")
    await db.commit()
    before = json.loads((await _row(db, op_id)).canonical_payload)
    before_rev = (await _row(db, op_id)).revision

    with pytest.raises(OpenedElsewhere):
        await open_operation(db, user=user, interpreter_item={"food": "Quinoa"},
                             interaction=inter, turn_id=tid, capability="id_addressed")

    rows = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id))).scalars().all()
    assert len(rows) == 1, "the refusal left a replacement operation behind"
    after = await _row(db, op_id)
    assert json.loads(after.canonical_payload) == before
    assert after.revision == before_rev and after.status == "awaiting_answer"
    assert (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all() == []
    assert (await db.execute(select(LedgerEvent).where(
        LedgerEvent.user_id == user.id))).scalars().all() == []
    from db.models import PendingQuestion
    assert (await db.execute(select(PendingQuestion).where(
        PendingQuestion.user_id == user.id))).scalars().all() == []

    # the session is usable: a NEW turn opens its own ask, superseding
    tid2 = f"ios:refuse-next-{user.id}"
    op2, inter2 = await _interaction(db, user, tid2, food="Quinoa")
    opened = await open_operation(db, user=user, interpreter_item={"food": "Quinoa"},
                                  interaction=inter2, turn_id=tid2, capability="id_addressed")
    await db.commit()
    assert opened.created and opened.operation_id == op2
    awaiting = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id,
        PendingOperation.status == "awaiting_answer",
        PendingOperation.storage_status == "active"))).scalars().all()
    assert len(awaiting) == 1 and awaiting[0].operation_id == op2


@pytest.mark.asyncio
async def test_8_the_application_is_correct_without_the_integrity_backstop(
        db, make_user, monkeypatch):
    """⛔ `oneask001` is a BACKSTOP, not control flow. With the database
    constraint removed from the path entirely (create never raises), the
    application still keeps ONE awaiting operation per user: the release runs
    BEFORE the insert, so the prior is superseded by application logic."""
    from core.b1_quantity_operation import open_operation
    from db.models import PendingOperation
    user = await make_user()
    t1 = f"ios:nobackstop-a-{user.id}"
    op1, inter1 = await _interaction(db, user, t1, food="Oatmeal")
    await open_operation(db, user=user, interpreter_item={"food": "Oatmeal"},
                         interaction=inter1, turn_id=t1, capability="id_addressed")
    await db.commit()

    import core.pending_repository as repo
    real_create = repo.create_operation
    seen = {"integrity": 0}

    async def create_never_conflicts(*a, **k):
        # if the application depended on the constraint, THIS is where the
        # duplicate would slip through
        try:
            return await real_create(*a, **k)
        except Exception:
            seen["integrity"] += 1
            raise

    monkeypatch.setattr(repo, "create_operation", create_never_conflicts)
    t2 = f"ios:nobackstop-b-{user.id}"
    op2, inter2 = await _interaction(db, user, t2, food="Quinoa")
    await open_operation(db, user=user, interpreter_item={"food": "Quinoa"},
                         interaction=inter2, turn_id=t2, capability="id_addressed")
    await db.commit()

    assert seen["integrity"] == 0, (
        "the insert relied on the database constraint firing — the release "
        "before it did not do its job")
    awaiting = (await db.execute(select(PendingOperation).where(
        PendingOperation.user_id == user.id,
        PendingOperation.status == "awaiting_answer",
        PendingOperation.storage_status == "active"))).scalars().all()
    assert [r.operation_id for r in awaiting] == [op2]
    prior = await _row(db, op1)
    assert prior.status != "awaiting_answer" or prior.storage_status != "active"


# ═════ BY CONSTRUCTION ═════════════════════════════════════════════════════

def test_the_decoder_never_coerces_a_falsy_item_or_skips_a_check():
    """⛔ AST, NOT GREP. The first cut of this gate asserted the STRING
    `data.get("item") or {}` was absent — and failed on the docstring that
    explains why it must be (the grep trap, again). The check is now
    structural: no `X or Y` fallback may wrap a `.get("item")` call anywhere
    in the decoder, whatever the surrounding prose says."""
    import ast
    import inspect
    from core import b1_quantity_operation as m
    tree = ast.parse(inspect.getsource(m._stored_open_result).lstrip())

    def _is_get_item(node) -> bool:
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and any(isinstance(a, ast.Constant) and a.value == "item"
                        for a in node.args))

    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            assert not any(_is_get_item(v) for v in node.values), (
                "the decoder coerces a falsy stored item through `or`")
    # ⛔ THE GATE FOLLOWS THE DECISION. Ownership is decided in
    # `_stored_open_result`; schema, item shape and fingerprint in the SHARED
    # `_decode_stored_payload` — assert each where it actually lives.
    own = inspect.getsource(m._stored_open_result).split('"""', 2)[-1]
    for needle in ("expect_operation_id", "expect_user_id", "expect_turn_id",
                   "DOMAIN", "_decode_stored_payload"):
        assert needle in own, needle
    payload = inspect.getsource(m._decode_stored_payload).split('"""', 2)[-1]
    for needle in ("schema_version", "fingerprint_version", "locale",
                   "cohort", "capability", "RECOGNISED_CAPABILITIES"):
        assert needle in payload, needle
    ptree = ast.parse(inspect.getsource(m._decode_stored_payload).lstrip())
    for node in ast.walk(ptree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            assert not any(_is_get_item(v) for v in node.values), (
                "the shared decoder coerces a falsy stored item through `or`")
    raises = [n for n in ast.walk(tree)] + [n for n in ast.walk(ptree)]
    raises = [n for n in raises if isinstance(n, ast.Raise)]
    assert len(raises) >= 8, f"only {len(raises)} refusals across the decoders"


def test_the_ask_and_answer_paths_share_one_decoder():
    """⛔ REQUIREMENT 2, BY CONSTRUCTION *(second round)*: verification used
    to live only on the ask side, so a payload edited after the write refused
    a REUSE while the ANSWER turn read it happily. Both call the SAME
    decoder, and `owning` has no decode of its own."""
    import ast
    import inspect
    from core import b1_quantity_operation as m

    def _calls(fn):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        return {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                for n in ast.walk(tree) if isinstance(n, ast.Call)}

    assert "_decode_stored_payload" in _calls(m._stored_open_result)
    assert "_decode_stored_payload" in _calls(m.owning)
    # and `owning` no longer builds an interaction itself
    owning_src = inspect.getsource(m.owning)
    assert "from_payload" not in owning_src, (
        "owning decodes the interaction itself — that is a second decoder")


def test_open_result_carries_every_rendering_fact():
    from core.b1_quantity_operation import OpenResult
    for name in ("interaction", "item", "revision", "locale", "cohort",
                 "capability", "fingerprint", "operation_id", "created"):
        assert name in OpenResult.__slots__ or hasattr(OpenResult, name), name
