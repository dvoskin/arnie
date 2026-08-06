"""B-1 part 3: an owned answer completes canonically, or not at all.

The required assertions, one test each. Two of them are about things that must
be UNREACHABLE rather than merely unused, and those are checked against the
source: a rule enforced only by discipline is a rule that regresses on the
next edit.

Two distinctions this file pins, because both are easy to collapse and both
matter to the user:

  * AN UNREADABLE USER ANSWER repairs — we ask the same field again, because
    the user can answer it.
  * A CORRUPT STORED OPERATION fails internally — asking again would invite an
    answer we still could not apply, so the user is told plainly and the
    operation terminates rather than looping.

and:

  * TAPPING AN OFFERED OPTION is `USER_SELECTED`, even on a channel with no
    structured tap, where "6 oz" comes back as literal text. The meaning is
    still loaded from the stored patch.
  * TYPING A QUANTITY WE DID NOT OFFER is `USER_STATED`.
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_answer_turn as answer_turn
from core import b1_quantity_operation as b1
from core.semantics import Provenance
from db.models import (Base, DailyLog, FoodEntry, LedgerEvent, MealCommit,
                       PendingOperation, User)
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

INTERPRETED = {"food": "chicken breast", "calories": 187, "protein": 35,
               "carbs": 0, "fats": 4}


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

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'ans.db'}")
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
        u = User(telegram_id="b1:ans", name="Ans", timezone="UTC")
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

    seen = {}

    async def _fake(db, user, food_name, inp):
        seen["quantity"] = inp.get("quantity")
        return _Analysis()

    monkeypatch.setattr("handlers.tool_executor._analyze_food", _fake)
    return seen


@pytest_asyncio.fixture
async def opened(sessions, user):
    """An owned, unanswered operation — the state every test below starts in."""
    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=_material(), turn_id="t_1",
            client_capable=True, locale="en")
        await s.commit()
    assert ask is not None
    return ask


@pytest_asyncio.fixture
async def opened_with_history(sessions, user):
    """An owned operation whose option row includes the user's OWN prior.

    Since B-1.9 an estimate may only commit from user- or product-specific
    evidence, so a test about what an assumed portion DISCLOSES has to build a
    supportable one — otherwise it measures the refusal and the disclosure
    contract silently stops being covered.

    The prior is seeded before ownership is taken, because candidates are
    generated at ask time.
    """
    from datetime import date

    from db.models import DailyLog, FoodEntry

    async with sessions() as s:
        log = DailyLog(user_id=user.id, date=date.today())
        s.add(log)
        await s.flush()
        s.add(FoodEntry(daily_log_id=log.id,
                        parsed_food_name="Chicken breast",
                        quantity="182 g", calories=300.0,
                        estimated_flag=False))
        await s.commit()

    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=_material(), turn_id="t_1",
            client_capable=True, locale="en")
        await s.commit()
    assert ask is not None
    sources = {str(getattr(getattr(o, "source", None), "value", ""))
               for o in ask.interaction.groups[0].fields[0].options}
    assert "user_history" in sources, (
        f"the seeded prior produced no history candidate ({sources}); this "
        f"fixture cannot support an estimate")
    return ask


async def _answer(sessions, user, **kw):
    async with sessions() as s:
        u = await s.get(User, user.id)
        out = await answer_turn.handle(s, user=u, source_turn_id="t_2", **kw)
        await s.commit()
        return out


def _field_id(ask):
    return ask.interaction.groups[0].fields[0].field_id


async def _counts(sessions):
    async with sessions() as s:
        return {
            "food": (await s.execute(
                select(func.count()).select_from(FoodEntry))).scalar(),
            "commits": (await s.execute(
                select(func.count()).select_from(MealCommit))).scalar(),
            "ledger": (await s.execute(
                select(func.count()).select_from(LedgerEvent))).scalar(),
        }


async def _row(sessions):
    async with sessions() as s:
        return (await s.execute(select(PendingOperation))).scalar_one()


# ── unreachability, checked against the source ───────────────────────────────

def test_the_answer_path_cannot_consult_the_rollout_gate():
    """Not "does not" — CANNOT. The gate is asked once, before ownership; a
    read here would be the mid-flight fallback the directive forbids, and a
    convention is one careless import away from breaking.

    By AST, not by substring: the module's own docstring explains at length
    WHY the gate is absent, and a text search cannot tell an explanation from
    an import. That is the same defect as a grep-based ratchet, one file over.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(answer_turn))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    assert not [m for m in imported if "quantity_rollout" in m], \
        f"the answer path imports the rollout gate: {imported}"

    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "may_take_ownership" not in called
    assert "in_cohort" not in called and "halted" not in called


@pytest.mark.asyncio
async def test_an_owned_turn_never_reaches_the_legacy_interpreter(
        sessions, user, opened, monkeypatch):
    """`_sft_run` is the broad food interpreter. Reaching it with an answer in
    hand is how "6 oz" became a second meal."""
    called = {"n": 0}

    async def _boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("the legacy interpreter was reached")

    monkeypatch.setattr("core.food_turn.run", _boom)
    out = await _answer(sessions, user, message="6 oz")
    assert out.applied
    assert called["n"] == 0


# ── the answer modalities ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_exact_persisted_label_maps_to_the_stored_patch(
        sessions, user, opened):
    """Telegram and iMessage have no structured tap: an offered chip comes
    back as its literal label. The meaning must still be LOADED, not re-parsed
    — and it is a selection, not a statement."""
    label = opened.interaction.groups[0].fields[0].options[0].label
    stored = opened.interaction.groups[0].fields[0].options[0].patch

    out = await _answer(sessions, user, message=label)
    assert out.applied
    assert out.patch == stored, "the label bound to its stored patch"
    assert out.patch.provenance is Provenance.USER_SELECTED


@pytest.mark.asyncio
async def test_a_structured_tap_selects(sessions, user, opened):
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    assert out.applied
    assert out.patch.provenance is Provenance.USER_SELECTED


@pytest.mark.asyncio
async def test_a_free_typed_quantity_is_a_statement(sessions, user, opened,
                                                    _priced):
    out = await _answer(sessions, user, message="about 6 ounces")
    assert out.applied
    assert out.patch.provenance is Provenance.USER_STATED
    assert _priced["quantity"] == "170.1g"


@pytest.mark.asyncio
async def test_chip_and_typed_agree_on_the_quantity_and_differ_on_provenance(
        sessions, user, opened):
    """C14. The offered label and its own number typed by hand are the same
    answer; only who produced it differs."""
    option = opened.interaction.groups[0].fields[0].options[0]
    tapped = await _answer(sessions, user, field_id=_field_id(opened),
                           option_id=option.option_id, revision=0)
    assert tapped.patch.quantity.grams == option.patch.quantity.grams
    assert tapped.patch.provenance is Provenance.USER_SELECTED


# ── failing closed ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_stale_revision_cannot_mutate_state(sessions, user, opened):
    before = await _row(sessions)
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=99)
    assert out.refused
    after = await _row(sessions)
    assert after.revision == before.revision
    assert after.status == b1.AWAITING
    assert (await _counts(sessions))["food"] == 0


@pytest.mark.asyncio
async def test_a_foreign_field_cannot_mutate_state(sessions, user, opened):
    out = await _answer(sessions, user,
                        field_id="op_other:food_x:quantity:0",
                        option_id="opt_ont_mid", revision=0)
    assert out.refused
    assert (await _row(sessions)).revision == 0


@pytest.mark.asyncio
async def test_an_invalid_option_id_cannot_mutate_state(sessions, user, opened):
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_nope", revision=0)
    assert out.refused
    assert (await _row(sessions)).revision == 0


@pytest.mark.asyncio
async def test_refused_does_not_bump_the_revision(sessions, user, opened):
    """A stale-tap storm must not walk the revision forward — that would
    invalidate the very chips still on the user's screen."""
    for _ in range(3):
        await _answer(sessions, user, field_id=_field_id(opened),
                      option_id="opt_nope", revision=0)
    assert (await _row(sessions)).revision == 0


@pytest.mark.asyncio
async def test_repair_keeps_the_same_operation_and_field_and_revision(
        sessions, user, opened):
    out = await _answer(sessions, user, message="it was pretty good")
    assert out.repair
    row = await _row(sessions)
    assert row.status == b1.AWAITING, "the operation stays open to be answered"
    assert row.revision == 0, "a repair changes no persisted semantic state"
    assert out.field_id == _field_id(opened), "the SAME field is re-asked"
    assert out.operation_id == opened.operation_id


# ── corrupt storage is not the user's problem ────────────────────────────────

@pytest.mark.asyncio
async def test_a_corrupt_stored_operation_fails_internally_not_as_a_repair(
        sessions, user, opened):
    """Asking again would invite an answer we still could not apply — the user
    would answer into a void twice. It terminates, visibly, instead."""
    async with sessions() as s:
        row = (await s.execute(select(PendingOperation))).scalar_one()
        payload = json.loads(row.canonical_payload)
        payload["interaction"] = {"schema_version": 99}
        row.canonical_payload = json.dumps(payload)
        await s.commit()

    out = await _answer(sessions, user, message="6 oz")
    assert out.failed, "a corrupt operation is an internal failure"
    assert not out.repair
    row = await _row(sessions)
    assert row.status not in (b1.AWAITING,), \
        "a meal nobody can settle must not stay open forever"
    assert (await _counts(sessions))["food"] == 0


# ── settlement ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_successful_answer_produces_exactly_one_canonical_commit(
        sessions, user, opened):
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    assert out.applied and out.result is not None
    counts = await _counts(sessions)
    assert counts == {"food": 1, "commits": 1, "ledger": 1}
    async with sessions() as s:
        assert [e.source for e in
                (await s.execute(select(LedgerEvent))).scalars()] == \
            ["canonical:create"]
    assert (await _row(sessions)).status == b1.COMMITTED


@pytest.mark.asyncio
async def test_two_racing_identical_answers_produce_one_effect(
        sessions, user, opened):
    """One winner; the other replays or is refused. Never two meals."""
    async with sessions() as s:
        u = await s.get(User, user.id)
        first = await answer_turn.handle(
            s, user=u, source_turn_id="t_2", field_id=_field_id(opened),
            option_id="opt_ont_mid", revision=0)
        second = await answer_turn.handle(
            s, user=u, source_turn_id="t_2", field_id=_field_id(opened),
            option_id="opt_ont_mid", revision=0)
        await s.commit()

    assert first.applied
    assert second.applied or second.refused
    if second.applied:
        assert second.result.committed_items == first.result.committed_items
    assert (await _counts(sessions))["food"] == 1


@pytest.mark.asyncio
async def test_a_committed_operation_replays_the_stored_result_exactly(
        sessions, user, opened):
    first = await _answer(sessions, user, field_id=_field_id(opened),
                          option_id="opt_ont_mid", revision=0)
    again = await _answer(sessions, user, field_id=_field_id(opened),
                          option_id="opt_ont_mid", revision=0)
    assert again.result == first.result, "the SAME result object, rebuilt"
    assert (await _counts(sessions))["food"] == 1


@pytest.mark.asyncio
async def test_cancel_writes_no_food_row_and_no_meal_commit(sessions, user,
                                                            opened):
    out = await _answer(sessions, user, message="never mind")
    assert out.cancelled
    assert await _counts(sessions) == {"food": 0, "commits": 0, "ledger": 0}
    assert (await _row(sessions)).status == b1.CANCELLED


@pytest.mark.asyncio
async def test_an_estimate_uses_a_persisted_option_not_a_new_value(
        sessions, user, opened_with_history):
    offered = {o.patch.quantity.grams
               for o in opened_with_history.interaction.groups[0].fields[0].options}
    out = await _answer(sessions, user, message="I don't know")
    assert out.applied
    assert out.patch.quantity.grams in offered, \
        "an estimate may not synthesise a value the user never saw"
    assert out.patch.provenance is Provenance.MODE_DEFAULT
    # TWO: the seeded prior that makes this estimate supportable, plus the one
    # this answer just committed.
    assert (await _counts(sessions))["food"] == 2


# ── measurement ──────────────────────────────────────────────────────────────

def test_the_modality_split_is_derived_in_one_place():
    """The "Other" rate is `text / (chip + label + text)`. Deriving the split
    at each call site is how one branch quietly starts counting a label tap as
    free text and the rate stops meaning anything."""
    from core import b1_metrics as m

    assert m.modality_of(option_id="opt_1", reason="") == "chip"
    assert m.modality_of(option_id="", reason="label_selection") == "label"
    assert m.modality_of(option_id="", reason="estimate") == "command"
    assert m.modality_of(option_id="", reason="cancel_meal") == "command"
    assert m.modality_of(option_id="", reason="") == "text"


@pytest.mark.asyncio
async def test_a_typed_answer_is_counted_as_other_and_a_label_is_not(
        sessions, user, opened, caplog):
    """THE SIGNAL THE ROLLOUT DECISION TURNS ON. A technically correct option
    system that frequently forces "Other" has failed, and only this can say
    so — but only if a chip pressed on a channel without structured taps is
    NOT counted as Other. It arrives as text and it is not text."""
    import logging

    label = opened.interaction.groups[0].fields[0].options[0].label
    with caplog.at_level(logging.INFO):
        await _answer(sessions, user, message=label)
    assert "modality=label" in caplog.text
    assert "modality=text" not in caplog.text


@pytest.mark.asyncio
async def test_an_unoffered_quantity_is_counted_as_other(sessions, user,
                                                         opened, caplog):
    import logging

    with caplog.at_level(logging.INFO):
        await _answer(sessions, user, message="about 6 ounces")
    assert "modality=text" in caplog.text


@pytest.mark.asyncio
async def test_the_answer_metric_carries_latency_and_provenance(
        sessions, user, opened, caplog):
    """Latency is the gap between the ask and the answer, so it can only come
    off the stored row — anything the answer turn holds would measure the
    answer turn."""
    import logging
    import re

    with caplog.at_level(logging.INFO):
        await _answer(sessions, user, field_id=_field_id(opened),
                      option_id="opt_ont_mid", revision=0)
    line = next(l for l in caplog.text.splitlines() if "event=b1_answered" in l)
    assert "provenance=user_selected" in line
    latency = re.search(r"latency_ms=(\d+)", line)
    assert latency and int(latency.group(1)) >= 0
    assert "event=b1_committed" in caplog.text


@pytest.mark.asyncio
async def test_measurement_never_costs_the_turn(sessions, user, opened,
                                                monkeypatch):
    """A missing datapoint is a worse outcome than a lost meal only to a
    dashboard."""
    def _boom(**kw):
        raise RuntimeError("metrics backend down")

    monkeypatch.setattr("core.b1_metrics.answered", _boom)
    monkeypatch.setattr("core.b1_metrics.committed", _boom)
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    assert out.applied
    assert (await _counts(sessions))["food"] == 1


@pytest.mark.asyncio
async def test_the_wire_offers_a_free_text_route(sessions, user, opened):
    """C15 on the wire. Without it a `single_select` says "three chips and
    nothing else", and a user whose portion is not among them has no visible
    way to say so — the forced-"Other" failure shipped as a design."""
    field = opened.wire_payload()["groups"][0]["fields"][0]
    assert field["allows_free_text"] is True
    assert field["response_type"] == "single_select"


# ── ownership is tri-state ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failed_lookup_is_not_the_same_as_not_owned(sessions, user,
                                                            opened,
                                                            monkeypatch):
    """THE THIRD STATE. A database blip must not read as "nothing owns this
    meal" — that hands a possibly-pending meal to the broad interpreter and
    turns a transient error into a duplicate, silently, when nobody is
    watching. Two states cannot express three."""
    async def _blow_up(*a, **kw):
        raise RuntimeError("connection reset")

    monkeypatch.setattr("core.b1_quantity_operation.owning", _blow_up)
    out = await _answer(sessions, user, message="6 oz")

    assert out is not None, "None means 'not ours' and licenses the legacy lane"
    assert out.failed
    assert (await _counts(sessions))["food"] == 0, "nothing may be logged"
    assert (await _row(sessions)).status == b1.AWAITING, \
        "the operation is untouched — it is still answerable"


@pytest.mark.asyncio
async def test_the_lookup_raises_rather_than_returning_none_on_failure(
        sessions, user, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession as _AS

    async def _blow_up(*a, **kw):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(_AS, "execute", _blow_up)
    async with sessions() as s:
        u = User(id=user.id)
        with pytest.raises(b1.OwnershipUnknown):
            await b1.owning(s, u)


@pytest.mark.asyncio
async def test_a_failure_after_ownership_still_completes_canonically(
        sessions, user, opened, monkeypatch):
    """`handle` is TOTAL once ownership is established. An owned meal handed
    to the interpreter because settle() threw is the duplicate-meal path
    arriving through an error handler."""
    async def _blow_up(*a, **kw):
        raise RuntimeError("writer exploded")

    monkeypatch.setattr("core.b1_quantity_operation.settle", _blow_up)
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    assert out is not None and out.failed
    assert (await _counts(sessions))["food"] == 0


# ── one facts value ──────────────────────────────────────────────────────────

def test_the_renderers_take_facts_not_the_result():
    """A renderer holding the raw commit can recompute, and a renderer that
    can recompute is a second owner of the number. Checked by signature, so
    the seam cannot be reopened by a later edit."""
    import inspect

    for fn in (answer_turn.copy_for, answer_turn.card_for):
        params = list(inspect.signature(fn).parameters)
        assert params == ["facts"], f"{fn.__name__}{params}"
    assert list(inspect.signature(answer_turn.facts_for).parameters) == ["turn"]


@pytest.mark.asyncio
async def test_one_extraction_feeds_every_renderer(sessions, user, opened):
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    facts = answer_turn.facts_for(out)
    card = answer_turn.card_for(facts)["payload"]
    said = answer_turn.copy_for(facts)

    assert card["calories"] == int(round(facts.calories))
    assert f"{card['calories']} cal" in said
    # Frozen, so a renderer cannot mutate the facts the next one will read.
    with pytest.raises(Exception):
        facts.calories = 1


# ── card and totals ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_card_and_the_sentence_cannot_disagree(sessions, user,
                                                         opened):
    """Not "agree" — CANNOT disagree. Both are renderings of one `facts_for`
    result, so the shape has no way to express the mismatch that produced 789
    vs 788 from three owners of the day total."""
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    card = answer_turn.card_for(answer_turn.facts_for(out))["payload"]
    facts = answer_turn.facts_for(out)
    said = answer_turn.copy_for(answer_turn.facts_for(out))

    assert card["calories"] == int(round(facts.calories))
    assert card["protein_g"] == int(round(facts.protein))
    assert card["entry_id"] == facts.entry_id
    assert card["name"] == facts.name
    assert f"{card['calories']} cal" in said
    assert f"{card['protein_g']}g protein" in said


@pytest.mark.asyncio
async def test_the_card_mirrors_the_row_that_was_committed(sessions, user,
                                                           opened):
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    card = answer_turn.card_for(answer_turn.facts_for(out))["payload"]
    async with sessions() as s:
        entry = (await s.execute(select(FoodEntry))).scalar_one()
    assert card["entry_id"] == entry.id, "the card must be tappable"
    assert card["calories"] == int(round(entry.calories))


@pytest.mark.asyncio
async def test_an_assumed_portion_is_marked_on_the_card(sessions, user,
                                                        opened_with_history):
    """"Logged fast" and "logged fast and quietly guessed" are different
    products, and this is the difference."""
    out = await _answer(sessions, user, message="I don't know")
    assert answer_turn.card_for(answer_turn.facts_for(out))["payload"]["estimated"] is True

    chosen = await _answer(sessions, user, field_id=_field_id(opened_with_history),
                           option_id="opt_ont_mid", revision=0)
    card = answer_turn.card_for(answer_turn.facts_for(chosen))
    if card is not None:               # the replay path returns the same row
        assert card["payload"]["estimated"] is False


@pytest.mark.asyncio
async def test_no_card_leaks_onto_a_reply_that_logged_nothing(sessions, user,
                                                              opened):
    """A stale card on a repair or a cancel is the leak `_logged_entry_card`'s
    entry_id gate exists to stop, arriving through a new door."""
    for kw in ({"message": "it was pretty good"},          # repair
               {"message": "never mind"}):                 # cancel
        out = await _answer(sessions, user, **kw)
        assert answer_turn.card_for(answer_turn.facts_for(out)) is None, out.outcome


# ── the two signals no turn can emit ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_abandonment_is_swept_and_counted(sessions, user, opened,
                                                caplog, monkeypatch):
    """NOBODY IS HAVING A TURN WHEN A USER ABANDONS ONE. That is why this
    runs on a timer, and why it is the signal most likely to be missing from a
    dashboard that otherwise looks complete — a question walked away from is
    the loudest statement that it was not worth asking."""
    import logging
    from datetime import timedelta

    from core.clock import now as _now

    async with sessions() as s:
        row = (await s.execute(select(PendingOperation))).scalar_one()
        row.expires_at = _now() - timedelta(minutes=1)
        await s.commit()

    with caplog.at_level(logging.INFO):
        async with sessions() as s:
            swept = await b1.sweep_abandoned(s)
            await s.commit()

    assert swept == 1
    assert "event=b1_abandoned" in caplog.text
    assert "open_ms=" in caplog.text
    row = await _row(sessions)
    assert row.status == "expired", \
        "an unanswered row must not linger as awaiting_answer, or a message " \
        "weeks later reads as an answer to a forgotten meal"


@pytest.mark.asyncio
async def test_the_sweep_cannot_be_starved_by_other_expired_operations(
        sessions, user, opened):
    """A REAL DEFECT, not a hypothetical. LIMIT applied before the slice
    filter draws the batch from ALL expired food operations and only then
    narrows to B-1's — so a backlog of expired non-B-1 operations fills every
    page and B-1's are never reached, forever, while the sweep reports
    success."""
    import json as _json
    from datetime import timedelta

    from core.clock import now as _now

    async with sessions() as s:
        # A wall of expired NON-B-1 food operations, all older than ours.
        for i in range(30):
            s.add(PendingOperation(
                operation_id=f"other:{i}", user_id=user.id, domain="food",
                status=b1.AWAITING, storage_status="active", revision=0,
                canonical_payload=_json.dumps({"slice": "something_else"}),
                expires_at=_now() - timedelta(hours=2)))
        await s.commit()
        row = (await s.execute(select(PendingOperation).where(
            PendingOperation.operation_id == opened.operation_id))).scalar_one()
        row.expires_at = _now() - timedelta(minutes=1)
        await s.commit()

    async with sessions() as s:
        swept = await b1.sweep_abandoned(s, limit=5)
        await s.commit()

    assert swept == 1, "the B-1 operation must be reached past the backlog"
    async with sessions() as sess:
        ours = (await sess.execute(select(PendingOperation).where(
            PendingOperation.operation_id == opened.operation_id))).scalar_one()
        assert ours.status == "expired"


@pytest.mark.asyncio
async def test_the_sweep_never_closes_an_operation_someone_just_answered(
        sessions, user, opened):
    """A sweep, not a race to close: if an answer landed between the query and
    the write, the answer wins."""
    from datetime import timedelta

    from core.clock import now as _now

    async with sessions() as s:
        row = (await s.execute(select(PendingOperation))).scalar_one()
        row.expires_at = _now() - timedelta(minutes=1)
        await s.commit()

    await _answer(sessions, user, field_id=_field_id(opened),
                  option_id="opt_ont_mid", revision=0)
    async with sessions() as s:
        assert await b1.sweep_abandoned(s) == 0
        await s.commit()
    assert (await _row(sessions)).status == b1.COMMITTED
    assert (await _counts(sessions))["food"] == 1


@pytest.mark.asyncio
async def test_a_correction_soon_after_the_commit_is_counted(
        sessions, user, opened, caplog):
    """The sharpest quality signal in the set: the user saw the number and it
    was wrong enough to fix. A rising rate here invalidates a green corpus —
    and the evidence arrives minutes later, from a different turn, so no
    answer turn could ever emit it."""
    import logging

    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    entry_id = out.result.committed_items[0]["entry_id"]

    async with sessions() as s:
        created = (await s.execute(select(LedgerEvent))).scalar_one()
        s.add(LedgerEvent(user_id=user.id, domain="food", entry_id=entry_id,
                          event_type="updated", source="dashboard:food_log",
                          created_at=created.created_at))
        await s.commit()

    with caplog.at_level(logging.INFO):
        async with sessions() as s:
            noted = await b1.note_corrections(s)
    assert noted == 1
    assert "event=b1_corrected" in caplog.text
    assert f"entry={entry_id}" in caplog.text


@pytest.mark.asyncio
async def test_a_correction_is_observed_exactly_once(sessions, user, opened):
    """The sweep runs on a timer. Without a persisted record it re-emits the
    same observation every tick, and the rate becomes a function of how often
    cron runs rather than of how often we were wrong."""
    from db.models import B1CorrectionObservation

    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    entry_id = out.result.committed_items[0]["entry_id"]
    async with sessions() as s:
        created = (await s.execute(select(LedgerEvent))).scalar_one()
        s.add(LedgerEvent(user_id=user.id, domain="food", entry_id=entry_id,
                          event_type="updated", source="dashboard:food_log",
                          created_at=created.created_at))
        await s.commit()

    counts = []
    for _ in range(3):                      # three cron ticks
        async with sessions() as s:
            counts.append(await b1.note_corrections(s))
            await s.commit()
    assert counts == [1, 0, 0], counts

    async with sessions() as s:
        rows = (await s.execute(
            select(B1CorrectionObservation))).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "updated"
    assert rows[0].entry_id == entry_id


@pytest.mark.asyncio
async def test_only_qualifying_event_types_inside_the_window_count(
        sessions, user, opened):
    """Not every later event on a row corrects its numbers, and a negative gap
    is clock skew rather than a correction that preceded what it corrects."""
    from datetime import timedelta

    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    entry_id = out.result.committed_items[0]["entry_id"]
    async with sessions() as s:
        created = (await s.execute(select(LedgerEvent))).scalar_one()
        # A non-qualifying type, and a qualifying one OUTSIDE the window.
        s.add(LedgerEvent(user_id=user.id, domain="food", entry_id=entry_id,
                          event_type="restored", source="x",
                          created_at=created.created_at))
        s.add(LedgerEvent(user_id=user.id, domain="food", entry_id=entry_id,
                          event_type="updated", source="x",
                          created_at=created.created_at + timedelta(hours=2)))
        await s.commit()

    async with sessions() as s:
        assert await b1.note_corrections(s) == 0


@pytest.mark.asyncio
async def test_an_untouched_commit_is_not_counted_as_corrected(sessions, user,
                                                               opened):
    await _answer(sessions, user, field_id=_field_id(opened),
                  option_id="opt_ont_mid", revision=0)
    async with sessions() as s:
        assert await b1.note_corrections(s) == 0


# ── locale ───────────────────────────────────────────────────────────────────

# ── the presentation boundary ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_response_facts_come_off_the_committed_result(sessions, user,
                                                                opened):
    """Voice renders THESE, and is never handed the result object — a renderer
    holding the raw commit is a renderer that can recompute, and a renderer
    that can recompute is a second owner of the number."""
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    facts = answer_turn.facts_for(out)

    assert facts.entry_id == out.result.committed_items[0]["entry_id"]
    assert facts.calories == out.result.meal_totals["calories"]
    assert facts.protein == out.result.meal_totals["protein"]
    assert facts.operation_id == out.operation_id
    # TWO QUESTIONS, deliberately not collapsed: they chose the portion, so
    # nothing is being assumed AT them — but the FIGURE is still one we
    # produced, which is what the row's estimated flag records.
    assert facts.estimated is False, "the user chose this portion"
    assert facts.system_supplied_figure is True, \
        "a tap is not the user's own figure — that distinction is the " \
        "2026-08-04 disclosure fix and must survive to the row"


@pytest.mark.asyncio
async def test_a_tap_is_not_told_that_we_guessed(sessions, user, opened):
    """Saying "(my estimate)" to someone who just tapped "6 oz" tells them we
    guessed when they decided. The opposite error to the 2026-08-04 one, and
    the same conflation underneath."""
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    assert "(my estimate)" not in answer_turn.copy_for(answer_turn.facts_for(out))


@pytest.mark.asyncio
async def test_a_typed_figure_is_the_users_own(sessions, user, opened):
    out = await _answer(sessions, user, message="about 6 ounces")
    facts = answer_turn.facts_for(out)
    assert facts.estimated is False
    assert facts.system_supplied_figure is False, \
        "they produced this number themselves"


@pytest.mark.asyncio
async def test_an_assumed_portion_is_disclosed_in_the_facts_and_the_copy(
        sessions, user, opened_with_history):
    out = await _answer(sessions, user, message="I don't know")
    assert answer_turn.facts_for(out).estimated is True
    assert "(my estimate)" in answer_turn.copy_for(answer_turn.facts_for(out)), \
        "an assumption the user did not supply must be visible to them"


@pytest.mark.asyncio
async def test_the_copy_states_only_what_was_committed(sessions, user, opened):
    """The failure this forbids is specific and measured: a reply reading
    "logged, 970/98g" while nothing had been written."""
    out = await _answer(sessions, user, field_id=_field_id(opened),
                        option_id="opt_ont_mid", revision=0)
    said = answer_turn.copy_for(answer_turn.facts_for(out))
    assert f"{out.result.meal_totals['calories']:.0f} cal" in said
    assert "chicken breast" in said


@pytest.mark.asyncio
async def test_every_non_commit_outcome_has_deterministic_copy(sessions, user,
                                                               opened):
    """A voice pass that fails degrades to these — never to silence, and never
    to an invented sentence."""
    repaired = await _answer(sessions, user, message="it was pretty good")
    assert answer_turn.copy_for(answer_turn.facts_for(repaired)) and "?" in answer_turn.copy_for(answer_turn.facts_for(repaired))

    refused = await _answer(sessions, user, field_id=_field_id(opened),
                            option_id="opt_nope", revision=0)
    assert "older question" in answer_turn.copy_for(answer_turn.facts_for(refused))

    cancelled = await _answer(sessions, user, message="never mind")
    assert "nothing logged" in answer_turn.copy_for(answer_turn.facts_for(cancelled)).lower()


@pytest.mark.asyncio
async def test_the_locale_comes_from_the_operation_not_the_current_message(
        sessions, user):
    """The question was asked in Russian. An English-looking reply two turns
    later must not re-detect its way into the English command lexicon."""
    async with sessions() as s:
        u = await s.get(User, user.id)
        await b1.try_take_ownership(s, user=u, material=_material(),
                                    turn_id="t_ru", client_capable=True,
                                    locale="ru")
        await s.commit()

    out = await _answer(sessions, user, message="cancel")
    assert not out.cancelled, \
        "an English command must not fire under a Russian operation"
    assert out.repair
    assert (await _row(sessions)).status == b1.AWAITING


# ── a settled operation must not swallow the NEXT meal ───────────────────────

@pytest.mark.asyncio
async def test_a_new_food_message_after_settlement_is_not_a_replay(
        sessions, user, opened, _priced):
    """PRODUCTION DATA LOSS, 2026-08-05. Two new meals were swallowed.

        23:46  "I had some rice"    -> "Logged White rice, 64 cal"
        23:49  "Had some oatmeal"   -> "Logged White rice, 64 cal"

    Neither was written. `SETTLED_OWNERSHIP_MINUTES` made `owning()` claim
    EVERY food message for 30 minutes after a commit, and free text like
    "some oatmeal" parses as a quantity — precisely because the quantity
    parser is good at its job — so it "applied" and replayed the finished
    meal. The user was told it was logged twice. That is the phantom-log
    failure this migration exists to delete, reintroduced by my own ownership
    window.

    WHY MY TESTS MISSED IT: every lifecycle test sent an ANSWER to the open
    operation. None ever sent an unrelated new report afterwards, because I
    only tested the paths I had imagined. Same fixture blindness as the
    ambiguity-field-name bug, one layer up.

    The rule: after settlement, only an answer that can ONLY be an answer
    counts — a structured `option_id`, or the exact text of an offered option.
    """
    # Settle it.
    first = await _answer(sessions, user, field_id=_field_id(opened),
                          option_id="opt_ont_mid", revision=0)
    assert first.applied
    assert (await _counts(sessions))["food"] == 1

    # A NEW, UNRELATED report arrives well inside the ownership window.
    for message in ("I had some rice", "Had some oatmeal", "some chicken"):
        out = await _answer(sessions, user, message=message)
        assert out is None, (
            f"{message!r} was claimed as a replay of the settled operation — "
            f"the meal is lost and the user is told otherwise"
        )

    assert (await _counts(sessions))["food"] == 1, \
        "the settled operation must neither replay nor write again"


@pytest.mark.asyncio
async def test_an_exact_option_label_after_settlement_still_replays(
        sessions, user, opened, _priced):
    """The case the window exists for: the chip is still on screen and the
    user presses it again. That text can only be an answer."""
    label = opened.interaction.groups[0].fields[0].options[1].label
    first = await _answer(sessions, user, field_id=_field_id(opened),
                          option_id="opt_ont_mid", revision=0)

    again = await _answer(sessions, user, message=label)
    assert again is not None and again.applied
    assert again.result.committed_items == first.result.committed_items
    assert (await _counts(sessions))["food"] == 1


@pytest.mark.asyncio
async def test_a_structured_tap_after_settlement_still_replays(
        sessions, user, opened, _priced):
    first = await _answer(sessions, user, field_id=_field_id(opened),
                          option_id="opt_ont_mid", revision=0)
    again = await _answer(sessions, user, field_id=_field_id(opened),
                          option_id="opt_ont_mid", revision=0)
    assert again is not None and again.applied
    assert again.result.committed_items == first.result.committed_items
    assert (await _counts(sessions))["food"] == 1


@pytest.mark.asyncio
async def test_an_unsupported_estimate_leaves_the_operation_open(
        sessions, user, opened):
    """B-1.9 item 1, at the ownership boundary.

    `opened` builds an ontology-only option row — a population prior. "I don't
    know" must then leave the canonical state UNRESOLVED rather than commit a
    number nothing supports, and the operation must remain answerable.

    Its counterpart above uses `opened_with_history` and commits. Same words,
    same field, different evidence — which is the whole rule.
    """
    from core.clarification_answer import Outcome

    sources = {str(getattr(getattr(o, "source", None), "value", ""))
               for o in opened.interaction.groups[0].fields[0].options}
    assert "user_history" not in sources, sources

    out = await _answer(sessions, user, message="I don't know")
    assert out.outcome is Outcome.REPAIR, out
    counts = await _counts(sessions)
    assert counts["food"] == 0, f"an unsupported estimate wrote a meal: {counts}"
    assert counts["commits"] == 0, counts
