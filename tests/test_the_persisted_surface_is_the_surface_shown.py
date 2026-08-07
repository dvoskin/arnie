"""The recorded question and the shown question must be the same question.

MEASURED IN PRODUCTION 2026-08-07. `chat_quantity:26:telegram:9241` — the
first Telegram B-1 turn after the candidate universe landed — persisted
`surface=id_addressed` for a channel that has no chips and where the sentence
is the entire interface.

The user was not harmed: `ask_copy` was handed the real per-channel capability
by its caller, so the bubble carried the options, and `surface` is serialized
rather than read, so neither selection nor rendering changed. What was wrong
was the DURABLE RECORD — it claimed a modality the interaction never used, and
`surface` participates in decision identity and in every later replay and
evidence analysis.

THE CAUSE WAS THREE DERIVATIONS OF ONE FACT:

    selection surface   `ID_ADDRESSED if client_capable else LABEL_TEXT`,
                        where `client_capable` meant "can read the payload at
                        all" and is TRUE for Telegram
    rendered sentence   `channel_capability(platform)` — correct
    persisted decision  whatever selection computed — wrong

One fact, read three ways, and the two that disagreed were the one shown and
the one stored. The lane gate now resolves capability once and `CanonicalAsk`
carries it; these gates hold that arrangement.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import b1_quantity_operation as b1
from db.models import Base, User
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, QuantityIntent,
                                      StagedFoodItem)

INTERPRETED = {"food": "chicken breast", "calories": 187, "protein": 35,
               "carbs": 0, "fats": 4}


def _material():
    item = StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken breast",
        identity=FoodIdentity(canonical_name="chicken breast"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        ambiguities=(FoodAmbiguity(
            ambiguity_id="a1", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
            field_name="estimated_mass_g", materiality_score=2.0,
            calorie_span=180.0),))
    return dict(staged_items=(item,), asked_item_id="si_1",
                items=[dict(INTERPRETED)],
                message="I had some chicken breast")


@pytest_asyncio.fixture
async def engine(tmp_path):
    from db.database import make_engine

    eng = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'surface.db'}")
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
        u = User(telegram_id="b1:surface", name="Surface", timezone="UTC")
        s.add(u)
        await s.commit()
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", str(u.id))
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    return u


async def _open(sessions, user, channel, turn_id):
    async with sessions() as s:
        u = await s.get(User, user.id)
        ask = await b1.try_take_ownership(
            s, user=u, material=_material(), turn_id=turn_id,
            channel=channel, locale="en")
        await s.commit()
    assert ask is not None, f"{channel} declined; this gate needs a real ask"
    return ask


async def _persisted_surface(sessions, ask):
    from db.models import CandidateSelectionDecisionRow, CandidateSetRow

    async with sessions() as s:
        row = (await s.execute(
            select(CandidateSelectionDecisionRow)
            .join(CandidateSetRow,
                  CandidateSetRow.candidate_set_id
                  == CandidateSelectionDecisionRow.candidate_set_id)
            .where(CandidateSetRow.operation_id == ask.operation_id))
        ).scalars().all()
    assert len(row) == 1, f"expected one decision, got {len(row)}"
    return row[0].surface


@pytest.mark.parametrize("channel,surface,options_in_sentence", [
    ("telegram", "label_text", True),
    ("imessage", "label_text", True),
    ("ios", "id_addressed", False),
])
@pytest.mark.asyncio
async def test_the_persisted_surface_matches_the_rendered_modality(
        sessions, user, channel, surface, options_in_sentence):
    """THE REGRESSION. One assertion per channel, over both halves at once.

    `options_in_sentence` is the OBSERVABLE half — on a label-text channel the
    options must be IN the words, because there is nothing else to read them
    from; on iOS they must not be, or the same list appears twice. Asserting
    only the persisted value would have passed throughout the production
    defect, since the persisted value was the only thing wrong.
    """
    ask = await _open(sessions, user, channel, f"t_{channel}")

    assert await _persisted_surface(sessions, ask) == surface

    said = ask.ask_copy()
    labels = ask.ask_facts().option_labels
    assert labels, "the fixture produced no options to check against"
    present = [lab for lab in labels if lab in said]
    if options_in_sentence:
        assert len(present) == len(labels), (
            f"{channel} renders the sentence as its whole interface, and "
            f"{[l for l in labels if l not in said]} never reached the user")
    else:
        assert not present, (
            f"{channel} renders options itself, so {present} appear twice")


@pytest.mark.asyncio
async def test_the_ask_carries_the_capability_rather_than_recomputing_it(
        sessions, user):
    """ONE DERIVATION. The caller must not be able to render an ask under a
    capability the decision was not made under — which is exactly what
    `conversation.py` did by calling `channel_capability(platform)` itself."""
    ask = await _open(sessions, user, "telegram", "t_carry")
    assert ask.capability == "label_text"


@pytest.mark.asyncio
async def test_ask_copy_has_no_silent_default(sessions, user):
    """It used to default to `LABEL_TEXT`, so a caller that forgot to pass a
    capability still got a plausible sentence — indistinguishable from asking
    correctly. The default is now the ask's own resolved capability."""
    import inspect

    signature = inspect.signature(b1.CanonicalAsk.ask_copy)
    assert signature.parameters["capability"].default is None

    ios = await _open(sessions, user, "ios", "t_default")
    assert ios.ask_copy() == ios.ask_copy(capability="id_addressed")


def test_one_module_owns_the_channel_capability_table():
    """A ratchet over the cause rather than the symptom.

    Three readings of one fact is what produced the defect. `selection_context`
    and the renderer must take the resolved value; only the lane gate may ask
    the table what a channel can do.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    allowed = {"core/b1_quantity_operation.py",   # defines the table
               "core/canonical_lane.py"}          # the one gate
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")):
            continue
        if rel in allowed:
            continue
        if "channel_capability(" in path.read_text(encoding="utf-8",
                                                   errors="ignore"):
            offenders.append(rel)
    assert not offenders, (
        f"{offenders} derive channel capability themselves — take it from "
        f"the lane decision or from the ask, so the shown modality and the "
        f"stored one cannot disagree")
