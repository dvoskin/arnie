"""A portion correction rescales the food; it does not re-guess it (cause B).

Production, 2026-07-29/30: "Update the sun chips to just 9 chips please",
"Okay make that 3/4 of that cube lol". The update path wrote the interpreter's
freshly-invented macros straight to the entry's columns — no basis, no
arithmetic, no lookup either. The identity had not changed, so the
re-resolution branch did not fire; nothing else did anything at all.

The reason it could not do better is the same missing thing as §8.1 one layer
over: the entry was written FROM a resolution — a source, a per-100g row, an
anchor — and kept none of it. An entry holds committed macros and a quantity
string, so there was nothing to correct against.

These tests run the real `execute_tool_calls` against a real database. Nothing
is stubbed but the enrichment network, and the assertions are on the row.
"""
import json

import pytest

from handlers.tool_executor import execute_tool_calls

#: Sun Chips as the label reads: 536 cal/100 g.
_PER100 = {"calories": 536, "protein": 7.1, "carbs": 64.3, "fat": 26.8,
           "sodium": 571}


class _Analysis:
    """What the enrichment ladder returns for the original log."""
    calories = 210.0
    protein = 3.0
    carbs = 25.0
    fat = 10.0
    fiber = 2.0
    sugar = 2.0
    sodium = 224.0
    fdc_id = "167625"
    confidence = "likely"
    source = "usda"
    protein_density = None
    satiety = None
    quality = None
    per100 = dict(_PER100)
    serving_text = "28 g (about 15 chips)"
    micros: dict = {}
    micros_estimated = False
    coach_note = ""
    enrichment_source = "usda"
    provenance = None


@pytest.fixture
def priced(monkeypatch):
    """The log turn resolves to a real per-100g basis, once."""
    async def _analyze(db, user, food_name, inp, *a, **k):
        return _Analysis()
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _analyze)
    return _Analysis


async def _loaded(db, user_id):
    """The user with preferences already attached — the executor reads them,
    and a lazy load inside an async session raises rather than fetching."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from db.models import User
    return (await db.execute(
        select(User).where(User.id == user_id)
        .options(selectinload(User.preferences)))).scalars().one()


async def _log(db, user):
    from db.queries import get_or_create_today_log
    return await get_or_create_today_log(db, user.id)


async def _log_a_bag(db, user):
    await execute_tool_calls(
        [{"name": "log_food",
          "input": {"food_name": "Sun Chips Harvest Cheddar",
                    "quantity": "1 bag", "calories": 210, "protein": 3,
                    "carbs": 25, "fats": 10}}],
        user, await _log(db, user), db)
    from sqlalchemy import select

    from db.models import FoodEntry
    row = (await db.execute(select(FoodEntry))).scalars().first()
    assert row is not None, "the log did not write an entry"
    return row


async def _correct(db, user, entry_id, **fields):
    await execute_tool_calls(
        [{"name": "update_food_entry",
          "input": {"entry_id": entry_id, **fields}}],
        user, await _log(db, user), db)
    from db.models import FoodEntry
    row = await db.get(FoodEntry, entry_id)
    await db.refresh(row)
    return row


# ── the basis survives the write ──────────────────────────────────────────────
async def test_the_entry_records_what_it_was_priced_from(db, make_user, priced):
    """The created event is the entry's provenance record and I3 guarantees
    exactly one per entry, so it is where the basis belongs."""
    from db.queries import get_ledger_events

    user = await _loaded(db, (await make_user()).id)
    row = await _log_a_bag(db, user)
    events = await get_ledger_events(db, user.id, domain="food",
                                     entry_id=row.id)
    created = [e for e in events if e.event_type == "created"]
    assert created, "no created event"
    resolution = json.loads(created[0].payload_json or "{}").get("resolution")
    assert resolution, "the row kept no basis — a correction has nothing to use"
    assert resolution["per100"]["calories"] == 536
    assert resolution["source_id"] == "167625"
    # The panel that knows what ONE of this product weighs. Without it "9
    # chips" of a branded name has no mass at all: PIECE_WEIGHTS_G matches on
    # the head noun, and "Sun Chips Harvest Cheddar" is a cheddar.
    assert resolution["serving_text"] == "28 g (about 15 chips)"


# ── the correction is arithmetic ──────────────────────────────────────────────
async def test_nine_chips_are_priced_from_the_basis_not_re_guessed(
        db, make_user, priced, monkeypatch):
    """The production message, and the number the label actually implies.

    The label says 28 g is about 15 chips, so 9 of them is 16.8 g, and at 536
    cal/100 g that is ~90. The interpreter's own guess on this call is 120 and
    must not reach the row.
    """
    async def _boom(*a, **k):
        raise AssertionError("a portion correction looked the food up again")

    user = await _loaded(db, (await make_user()).id)
    row = await _log_a_bag(db, user)
    # Armed AFTER the log: the log is allowed its one lookup; the correction
    # is not.
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _boom)
    fixed = await _correct(db, user, row.id, quantity="9 chips", calories=120)

    assert fixed.calories == pytest.approx(90.1, abs=2.0)
    assert fixed.protein == pytest.approx(1.2, abs=0.3)
    # Everything the basis knew scales together. A row whose calories moved and
    # whose sodium did not is describing two different portions.
    assert fixed.sodium == pytest.approx(95.9, abs=3.0)


async def test_a_stated_number_still_wins(db, make_user, priced):
    """"it says 80 online" is the user reading a label to us. No arithmetic
    outranks that — the same rule the identity arm keeps."""
    user = await _loaded(db, (await make_user()).id)
    row = await _log_a_bag(db, user)
    fixed = await _correct(db, user, row.id, calories=80)
    assert fixed.calories == pytest.approx(80.0)


async def test_a_correction_that_cannot_be_scaled_is_left_alone(
        db, make_user, priced):
    """No mass either end and no panel unit that answers it: the honest outcome
    is the behaviour we ship today, not a guessed ratio."""
    user = await _loaded(db, (await make_user()).id)
    row = await _log_a_bag(db, user)
    fixed = await _correct(db, user, row.id, quantity="whatever was left",
                           calories=150, protein=2)
    assert fixed.calories == pytest.approx(150.0)
    assert fixed.quantity == "whatever was left"


async def test_the_identity_arm_is_untouched(db, make_user, priced,
                                             monkeypatch):
    """A changed identity is still a full re-resolution. The portion arm may
    only ever handle the food that is already resolved."""
    seen = []

    async def _re(db_, user_, name, inp, *a, **k):
        seen.append(name)
        return _Analysis()
    user = await _loaded(db, (await make_user()).id)
    row = await _log_a_bag(db, user)
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _re)
    await _correct(db, user, row.id, food_name="Doritos Nacho Cheese",
                   quantity="1 bag")
    assert seen == ["Doritos Nacho Cheese"]


# ── rows written before the basis existed ─────────────────────────────────────
async def test_an_older_row_scales_by_ratio(db, make_user, monkeypatch):
    """No stored basis — the entry predates it — but both portions resolve to a
    mass, so the row's own committed numbers scale by their ratio. Arithmetic
    on numbers that were once resolved beats a fresh guess about the same
    food."""
    from skills.nutrition.correction_application import apply_portion

    scaled = apply_portion(
        food_name="chicken breast", old_quantity="200 g",
        new_quantity="150 g",
        committed={"calories": 330.0, "protein": 62.0, "carbs": 0.0,
                   "fats": 7.2})
    assert scaled["calories"] == pytest.approx(247.5, abs=0.1)
    assert scaled["protein"] == pytest.approx(46.5, abs=0.1)


async def test_a_panel_that_counts_something_else_does_not_convert():
    """"9 chips" against a panel of "1 bar" is not the same object, and scaling
    one by the other turns a portion into a package."""
    from skills.nutrition.correction_application import apply_portion

    assert apply_portion(
        food_name="Sun Chips Harvest Cheddar", old_quantity="1 bag",
        new_quantity="9 chips",
        committed={"calories": 210.0, "protein": 3.0},
        per100={"calories": 536, "protein": 7.1},
        serving_text="1 bar (55 g)") is None


async def test_an_echoed_quantity_does_not_rescale_a_stated_number(
        db, make_user, priced):
    """"Check your numbers it says 80 online" arrives as calories=80 with the
    quantity echoed unchanged — the interpreter routinely repeats fields it is
    not correcting. Rescaling on that echo would overwrite the user's own
    figure with arithmetic they never asked for.

    Through the executor, because the guard is the executor's: the module
    below it cannot tell an echo from a correction that happens to agree.
    """
    user = await _loaded(db, (await make_user()).id)
    row = await _log_a_bag(db, user)
    fixed = await _correct(db, user, row.id, quantity="1 bag", calories=80)
    assert fixed.calories == pytest.approx(80.0)


def test_the_same_portion_written_two_ways_is_not_a_correction():
    """By mass where both resolve to one, so a re-worded portion does not read
    as a change."""
    from handlers.tool_executor import _same_quantity

    assert _same_quantity("1 bag", "1 bag")
    assert _same_quantity("200 g", "200g")
    assert not _same_quantity("200 g", "150 g")
