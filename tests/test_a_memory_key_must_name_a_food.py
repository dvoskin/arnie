"""⛔ THE CONTAINMENT FOR A LIVE PRODUCTION MISPRICE.

2026-08-14. `normalize_name` keeps `[a-z0-9 ]`, so a food named in a non-Latin
script normalizes to whatever DIGITS it happened to contain, and those digits
became the key into durable per-user food memory.

    'Творог 5%'                    -> '5'
    'Молоко (2.5%)'                -> '25'
    'Кукуруза варёная (2 початка)' -> '2'
    'Омлет из 2 яиц'               -> '2'

MEASURED, 180 days of production: 361 distinct non-English foods · 300
normalizing to EMPTY · 6 KEYS each shared by several DIFFERENT foods of one
user, one of them carrying nine.

⭐ AND ONE OF THEM PRICED A REAL MEAL FROM THE WRONG FOOD.

    cached   u=76 key '2'  'Кукуруза варёная (2 початка)'   (boiled corn)
             per100g  54.0 kcal · 3.33 p · 5.0 c · 2.08 f   last_used 2026-08-04
    entry    2026-08-04  'Творог 2%'  150 g                 (2% cottage cheese)
             committed 81.0 kcal · 5.0 p · 7.5 c · 3.1 f
             per100g   54.0 · 3.33 · 5.00 · 2.07   <- IDENTICAL, all four

Real 2% творог is ~86-100 kcal and ~18 g protein per 100 g. It committed at 54
and 3.33 — about a fifth of its protein, from the MEMORY rung, at high
confidence. A wrong number wearing evidence.

⭐⭐ THE GUARD IS ABOUT KEY QUALITY, NOT LANGUAGE (Danny). There is no Cyrillic
test here and there must never be one: a key that lost all of its letters is
non-addressable whoever wrote it. That is what makes this generalize to every
script normalization has not been taught, instead of to exactly the one that
happened to break first.

⚠ CONTAINMENT, NOT THE FIX. These foods are now SAFE rather than ADDRESSABLE.
The correction is the interpretation boundary — identity from interpreted
meaning rather than from surviving bytes.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from core.food_intelligence import memory_key_is_addressable, normalize_name
from db.models import UserFoodMatch
from db.queries import get_user_food_match, upsert_user_food_match
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


@pytest_asyncio.fixture
async def memory(app_db, seeded):          # noqa: F811
    """An open session bound to the harness engine, and the user id.

    Yields the SESSION rather than the engine because both doors under test
    take one, and building it per test would hide the thing that matters: the
    guard has to hold on the same session the pricer uses, not on a private
    one."""
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session, seeded

#: The production row, verbatim. Boiled corn, two ears.
CORN = "Кукуруза варёная (2 початка)"
CORN_PER_100G = {"calories": 54.0, "protein": 3.33, "carbs": 5.0, "fat": 2.08}
#: What the user logged three weeks later, and what it was priced from.
TVOROG = "Творог 2%"
#: A third food of the same user on the same key.
EGGS = "Омлет из 2 яиц"


# ── the predicate ─────────────────────────────────────────────────────────────

def test_the_three_colliding_foods_all_normalize_to_the_same_digit():
    """THE MECHANISM, ASSERTED RATHER THAN DESCRIBED. If normalization ever
    stops doing this the guard becomes unnecessary — and this test says so
    loudly instead of passing quietly on a premise that no longer holds."""
    assert normalize_name(CORN) == normalize_name(TVOROG) == normalize_name(EGGS)
    assert normalize_name(CORN) == "2"


@pytest.mark.parametrize("key", ["", "2", "5", "25", "32", "100", "  ", "2 5"])
def test_a_key_with_no_letters_is_not_addressable(key):
    assert memory_key_is_addressable(key) is False


@pytest.mark.parametrize("key", ["tomato", "white rice", "ground turkey 96 lean",
                                 "b", "2 eggs", "barebells salty peanut"])
def test_a_key_carrying_letters_stays_addressable(key):
    """ANTI-VACUITY. A guard that refused everything would also pass every
    negative test above, and would delete the memory rung."""
    assert memory_key_is_addressable(key) is True


def test_the_predicate_is_about_key_quality_and_not_about_a_script():
    """⭐ `'п'` IS alphabetic to Python, so a predicate written as
    `str.isalpha()` would answer True for a raw Cyrillic string — about a
    string nobody will ever key on, since normalization deletes every character
    of it first. The contract is about what SURVIVED."""
    assert memory_key_is_addressable("помидор") is False
    assert memory_key_is_addressable(normalize_name("Помидор")) is False
    # And an English name that degenerates the same way is refused the same way.
    assert memory_key_is_addressable(normalize_name("2%")) is False


# ── the read door ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tvorog_cannot_reach_the_corn_row(memory):
    """⭐ THE PRODUCTION DEFECT, AS A FIXTURE. Same user, corn cached, cottage
    cheese looked up — and before the guard this returned the corn."""
    db, user_id = memory
    db.add(UserFoodMatch(origin_tier="canonical_settlement", 
        user_id=user_id, name_norm=normalize_name(CORN), display_name=CORN,
        cal_100=CORN_PER_100G["calories"], protein_100=CORN_PER_100G["protein"],
        carbs_100=CORN_PER_100G["carbs"], fat_100=CORN_PER_100G["fat"],
        confidence="exact"))
    await db.commit()

    found = await get_user_food_match(db, user_id, normalize_name(TVOROG))

    assert found is None, (
        "cottage cheese reached the boiled-corn row — the exact production "
        "misprice of 2026-08-04, which committed 3.33 g protein per 100 g for "
        "a food that carries about 18")


@pytest.mark.asyncio
async def test_two_different_foods_do_not_share_a_memory_identity(memory):
    """Corn and an omelette are not the same food, and normalizing both to
    `'2'` is not a reason to treat them as one."""
    db, user_id = memory
    db.add(UserFoodMatch(origin_tier="canonical_settlement", 
        user_id=user_id, name_norm=normalize_name(CORN), display_name=CORN,
        cal_100=54.0, protein_100=3.33, confidence="exact"))
    await db.commit()

    assert await get_user_food_match(db, user_id, normalize_name(EGGS)) is None


@pytest.mark.asyncio
async def test_an_empty_key_is_never_a_valid_memory_key(memory):
    """`Помидор` normalizes to `''`. An empty key must not address a row —
    including a legacy row that was somehow written with one."""
    db, user_id = memory
    db.add(UserFoodMatch(origin_tier="canonical_settlement", user_id=user_id, name_norm="", display_name="Помидор",
                         cal_100=18.0, confidence="exact"))
    await db.commit()

    assert await get_user_food_match(db, user_id, normalize_name("Помидор")) is None
    assert await get_user_food_match(db, user_id, "") is None


@pytest.mark.asyncio
async def test_an_ordinary_english_food_still_hits_its_row(memory):
    """⭐ ANTI-VACUITY AT THE DOOR, not only on the predicate. The measured
    44.6% of production that memory carries must be untouched by this."""
    db, user_id = memory
    db.add(UserFoodMatch(origin_tier="canonical_settlement", user_id=user_id, name_norm=normalize_name("Chicken breast"),
                         display_name="Chicken breast", cal_100=165.0,
                         protein_100=31.0, confidence="exact"))
    await db.commit()

    found = await get_user_food_match(db, user_id, normalize_name("Chicken breast"))
    assert found is not None and found.cal_100 == 165.0


# ── the write door ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_letterless_key_is_never_written(memory):
    """⛔ GUARDING ONLY THE READ WOULD HAVE BEEN WORSE THAN GUARDING NEITHER.

    `upsert_user_food_match` looks up the existing row through the guarded
    reader, so a refused read makes it take the CREATE branch — and every
    non-Latin food would mint a fresh `'2'` row on every single log. One
    collision would become an unbounded pile of them, and `scalar_one_or_none`
    raises on multiple matches. Both doors, one rule.
    """
    db, user_id = memory
    written = await upsert_user_food_match(
        db, user_id, normalize_name(TVOROG), TVOROG, "", {"calories": 98.0},
        "exact")

    assert written is None
    rows = (await db.execute(select(UserFoodMatch).where(
        UserFoodMatch.user_id == user_id))).scalars().all()
    assert rows == [], (
        "a letterless key was written — the read guard then turns every "
        "later log of that food into another new row")


@pytest.mark.asyncio
async def test_an_addressable_food_is_still_cached(memory):
    """ANTI-VACUITY on the write door."""
    db, user_id = memory
    written = await upsert_user_food_match(
        db, user_id, normalize_name("Chicken breast"), "Chicken breast", "171077",
        {"calories": 165.0, "protein": 31.0}, "exact")

    assert written is not None and written.cal_100 == 165.0
