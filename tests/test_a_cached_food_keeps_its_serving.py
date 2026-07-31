"""A counted portion stays answerable on the SECOND log, not just the first.

The defect these pin is not about any food. `user_food_matches` stored a
per-100g panel and nothing else, so the serving the product is actually sold in
— which Open Food Facts publishes, `off.search` already returns, and
`normalize.serving_unit_mass` already parses — was discarded at cache time.
Every repeat log of a branded food then arrived with per-100g alone.

At that point a counted portion has no answer. There is no mass, and no serving
to divide, so the model's calorie guess becomes the anchor and nothing can
check it. Measured in production 2026-07-31: five Twizzlers logged at 323 cal,
which is exactly the per-100g density, where the label gives 162. Three users
hit the same shape within 30 days and it errs in BOTH directions — two 16 oz
lattes logged as 200 cal understated by half.

So the property under test is a round trip, not a lookup table:

    a serving panel that went INTO the cache comes back OUT of it,
    and its absence still reads as absent.

No food is named in an assertion. Adding one would rebuild the table this
design exists to avoid — `PIECE_WEIGHTS_G` describes foods, and no table of
food-shaped averages knows that a Peanut M&M is three times a plain one.
"""
import pytest
from sqlalchemy import select

from db.models import UserFoodMatch
from db.queries import get_user_food_match, upsert_user_food_match
from skills.nutrition.normalize import serving_unit_mass

PER100 = {"calories": 323.5, "protein": 0.0, "carbs": 76.5, "fat": 1.5}


# ── the round trip ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_serving_panel_survives_the_cache(db, make_user):
    """The whole defect, in one assertion: what the label said must still be
    there the next time this food is logged."""
    user = await make_user(telegram_id="serving:roundtrip")
    await upsert_user_food_match(db, user.id, "confection", "Confection",
                                 None, PER100, "exact",
                                 serving_text="3 pieces (30 g)")

    row = await get_user_food_match(db, user.id, "confection")
    assert row is not None
    assert row.serving_text == "3 pieces (30 g)", (
        "the label's serving was dropped at cache time — a counted portion is "
        "unanswerable on every log after the first"
    )


@pytest.mark.asyncio
async def test_a_cached_panel_makes_a_counted_portion_resolvable(db, make_user):
    """The point of storing it. The parser is not re-implemented here — this
    asserts the CACHE feeds it, which is the link that was broken."""
    user = await make_user(telegram_id="serving:resolvable")
    await upsert_user_food_match(db, user.id, "confection", "Confection",
                                 None, PER100, "exact",
                                 serving_text="3 pieces (30 g)")

    row = await get_user_food_match(db, user.id, "confection")
    resolved = serving_unit_mass(row.serving_text)

    assert resolved is not None, (
        "a stored panel that cannot be parsed is no better than no panel"
    )
    grams_per_unit, unit = resolved
    assert unit == "piece"
    # 5 units against the CACHED panel — the arithmetic production could not do.
    assert round(5 * grams_per_unit) == 50


# ── absence keeps its meaning ────────────────────────────────────────────────


@pytest.mark.parametrize("panel", ["", "50 g", "1 portion (28 g)"])
@pytest.mark.asyncio
async def test_an_unusable_panel_stays_unusable(db, make_user, panel):
    """A mass with no count, a count with no mass, or nothing at all must NOT
    become a guess. `serving_unit_mass` returning None is what lets the ask
    ladder act; inventing a number here would defeat the entire design."""
    user = await make_user(telegram_id=f"serving:absent-{len(panel)}")
    await upsert_user_food_match(db, user.id, "thing", "Thing", None, PER100,
                                 "exact", serving_text=panel)

    row = await get_user_food_match(db, user.id, "thing")
    assert serving_unit_mass(row.serving_text or "") is None, (
        f"{panel!r} does not define a unit mass and must stay unscalable"
    )


@pytest.mark.asyncio
async def test_no_panel_at_all_is_not_an_error(db, make_user):
    """Callers with no label — a user correction, a plain estimate — must keep
    working. The column is nullable and that is a legitimate state."""
    user = await make_user(telegram_id="serving:none")
    await upsert_user_food_match(db, user.id, "estimate", "Estimate", None,
                                 PER100, "estimated")

    row = await get_user_food_match(db, user.id, "estimate")
    assert row.serving_text is None


# ── the cache heals, and never forgets ───────────────────────────────────────


@pytest.mark.asyncio
async def test_a_row_cached_before_this_gains_its_panel_later(db, make_user):
    """Every row that exists today predates the column. They must not stay
    unanswerable forever — the first lookup carrying a label fills one in."""
    user = await make_user(telegram_id="serving:heal")
    await upsert_user_food_match(db, user.id, "legacy", "Legacy", None,
                                 PER100, "likely")
    assert (await get_user_food_match(db, user.id, "legacy")).serving_text is None

    await upsert_user_food_match(db, user.id, "legacy", "Legacy", None,
                                 PER100, "likely",
                                 serving_text="about 30 chips (28 g)")

    healed = await get_user_food_match(db, user.id, "legacy")
    assert healed.serving_text == "about 30 chips (28 g)"


@pytest.mark.asyncio
async def test_a_later_lookup_without_a_label_does_not_erase_one(db, make_user):
    """A refresh from a source that publishes no panel must not clear a panel
    already stored — that would silently return the food to unanswerable."""
    user = await make_user(telegram_id="serving:noclear")
    await upsert_user_food_match(db, user.id, "kept", "Kept", None, PER100,
                                 "exact", serving_text="4 pieces (45 g)")
    await upsert_user_food_match(db, user.id, "kept", "Kept", None, PER100,
                                 "likely")          # no label this time

    assert (await get_user_food_match(db, user.id, "kept")).serving_text \
        == "4 pieces (45 g)"


@pytest.mark.asyncio
async def test_one_row_per_food_still_holds(db, make_user):
    """The panel rides on the existing row; it must not fork the cache."""
    user = await make_user(telegram_id="serving:onerow")
    for panel in ("", "3 pieces (30 g)", "3 pieces (30 g)"):
        await upsert_user_food_match(db, user.id, "one", "One", None, PER100,
                                     "exact", serving_text=panel)

    rows = (await db.execute(
        select(UserFoodMatch).where(UserFoodMatch.user_id == user.id,
                                    UserFoodMatch.name_norm == "one")
    )).scalars().all()
    assert len(rows) == 1
