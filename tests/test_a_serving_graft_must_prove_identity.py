"""⛔⛔⛔ CF24-C — A SERVING MAY ONLY GRAFT ONTO THE SAME AUTHORITY.

The write-side half of the CF23 story. Containment stopped corrupt rows being
READ; this stops one being BUILT.

`upsert_user_food_match`, existing-row branch:

    if serving_text and not existing.serving_text:
        existing.serving_text = serving_text          # no identity comparison

The row is keyed by `name_norm`; the incoming serving comes from whichever
candidate won THIS lookup. Nothing checks they describe the same product —
there are ZERO references to `existing.fdc_id` in the entire writer.

⭐ THAT IS HOW A *PIECES* SERVING REACHED WHOLE MILK. Production row 1029:
`Milk, whole`, `cal_100=582.0`, `serving_text="4 pieces (16.7 g)"`.

⚠ NARROWER SINCE CF23, NOT CLOSED. With both web lanes disabled the graft can
still arrive from a USDA or OFF candidate that resolved to a different record
than the one the row was built from.

THE RULE: a stored serving may graft only when the incoming evidence and the
stored row prove the SAME underlying authority. Identifiers must be present on
both sides and equal. ⛔ No semantic-name comparison, no token overlap, no
calorie plausibility — those are the guesses this whole incident came from.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from db.queries import get_user_food_match, upsert_user_food_match
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


@pytest_asyncio.fixture
async def _session(app_db, seeded):          # noqa: F811
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session, seeded


_P100 = {"calories": 61.0, "protein": 3.2, "carbs": 4.8, "fat": 3.3}


async def _seed(db, uid, key, fdc, serving=""):
    """⛔⛔ CF26 — NUTRITION CAN NO LONGER BE SEEDED THROUGH THE PUBLIC WRITER.

    `upsert_user_food_match` runs during candidate gathering, before the meal
    is priced, so it stores identity and never nutrition. Seeding through it
    left every row here holding NULL macros, and the D-tests then asserted
    immutability of a value that was never written.

    ⭐ AND THAT IS THE PROOF, NOT THE INCONVENIENCE: if a test could still put
    nutrition in through that door, so could production. The producer is the
    only writer that may, so the fixture uses it.
    """
    from db.models import MealCommit
    from db.queries import remember_canonical_settlement

    operation_id = f"op:graft-seed:{key}"
    db.add(MealCommit(operation_id=operation_id, operation_revision=0,
                      user_id=uid, status="committed"))
    await db.flush()
    await remember_canonical_settlement(
        db, user_id=uid, name_norm=key, display_name="Milk, whole",
        operation_id=operation_id, per100=dict(_P100), evidence_id=fdc,
        basis="per_100g", fdc_id=fdc, serving_text=serving)
    return await get_user_food_match(db, uid, key)


@pytest.mark.asyncio
async def test_a_DIFFERENT_source_cannot_graft_its_serving(_session):
    """⛔⛔⛔ ROW 1029, PREVENTED. The stored row was built from one record; a
    later lookup resolves to another and offers `"4 pieces (16.7 g)"`. A
    *pieces* serving on a liquid — and arithmetically it would then divide the
    label by 16.7 g forever after."""
    db, uid = _session
    await _seed(db, uid, "milkwhole_c1", "171265")

    await upsert_user_food_match(db, uid, "milkwhole_c1", "Milk, whole",
                                 # ⛔ SHARES A PREFIX WITH THE STORED ID.
                                 # `171265` vs `999999` would also be refused
                                 # by a sloppy prefix comparison, so the case
                                 # could not tell exact from approximate —
                                 # mutation C3 proved that by staying green.
                                 "171999",            # a DIFFERENT record
                                 dict(_P100), "likely",
                                 serving_text="4 pieces (16.7 g)")
    row = await get_user_food_match(db, uid, "milkwhole_c1")

    assert row.serving_text is None, (
        f"a serving from a different record grafted onto the row: "
        f"{row.serving_text!r} — this is production row 1029")


@pytest.mark.asyncio
async def test_the_SAME_source_may_graft_its_serving(_session):
    """⭐ THE NEGATIVE INVARIANT. Fail-closed must not mean fail-always: the
    backfill exists because rows cached before `serving001` hold per-100g
    alone, which is what makes a counted portion unanswerable. Same record,
    same authority — the graft is exactly right."""
    db, uid = _session
    await _seed(db, uid, "milkwhole_c2", "171265")

    await upsert_user_food_match(db, uid, "milkwhole_c2", "Milk, whole",
                                 "171265",            # the SAME record
                                 dict(_P100), "likely",
                                 serving_text="240 ml")
    row = await get_user_food_match(db, uid, "milkwhole_c2")

    assert row.serving_text == "240 ml"


@pytest.mark.asyncio
async def test_identity_that_cannot_be_PROVEN_does_not_graft(_session):
    """⛔ ABSENCE IS NOT AGREEMENT. If either side carries no identifier, the
    two cannot be shown to describe the same product — and "we could not tell"
    must never read as "they match". This is the case the disabled web lanes
    used to produce constantly: candidates with `fdc_id=None`."""
    db, uid = _session
    # ⛔ CF26 — THE PRODUCER CANNOT MAKE THIS ROW ANY MORE. A settlement
    # projection must name what it was projected from, so a trusted row with
    # no identifier is no longer constructible. The shape still EXISTS in
    # production as history, though — 838 rows predate all of this — so the
    # fixture builds it the only way it can now arise: directly, as a legacy
    # row. That is exactly the population this guard defends.
    from db.models import UserFoodMatch
    db.add(UserFoodMatch(user_id=uid, name_norm="milkwhole_c3",
                         display_name="Milk, whole", fdc_id=None,
                         cal_100=_P100["calories"], protein_100=_P100["protein"],
                         carbs_100=_P100["carbs"], fat_100=_P100["fat"],
                         confidence="likely", origin_tier="generic_exact"))
    await db.flush()

    await upsert_user_food_match(db, uid, "milkwhole_c3", "Milk, whole", None,
                                 dict(_P100), "likely",
                                 serving_text="4 pieces (16.7 g)")
    row = await get_user_food_match(db, uid, "milkwhole_c3")

    assert row.serving_text is None, (
        "a serving grafted between two records that cannot prove they are the "
        "same product")


@pytest.mark.asyncio
async def test_an_existing_serving_is_never_replaced(_session):
    """⭐ THE PRE-EXISTING RULE STILL HOLDS — "never CLEARS a stored panel with
    an empty one", and equally never overwrites a good one."""
    db, uid = _session
    await _seed(db, uid, "milkwhole_c4", "171265", serving="240 ml")

    await upsert_user_food_match(db, uid, "milkwhole_c4", "Milk, whole",
                                 "171265", dict(_P100), "likely",
                                 serving_text="1 cup")
    row = await get_user_food_match(db, uid, "milkwhole_c4")

    assert row.serving_text == "240 ml"


# ══════════════════════════════════════════════════════════════════════════
# CF24-D — HISTORICAL NUTRITION IS IMMUTABLE TO ORDINARY LOOKUPS
#
# ⛔⛔⛔ THE FIX FOR "WRITE-ONCE BAD MEMORY" IS NOT "LAST WRITER WINS".
# Letting any later USDA/OFF/legacy lookup overwrite `cal_100` would trade a
# permanent wrong number for a number that changes under the user without
# provenance — strictly worse, because at least the first is auditable.
#
# THE INVARIANT: historical cache rows are IMMUTABLE NUTRITION unless a trusted
# canonical producer replaces them under explicit provenance. Ordinary lookups
# may still bump usage and enrich absent non-authoritative fields; they may not
# rewrite nutrition authority.
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_an_ordinary_lookup_cannot_rewrite_stored_nutrition(_session):
    """⛔ A LATER LOOKUP — even a CORRECT one, even from the SAME record —
    does not get to restate the numbers. Authority is not something a cache
    write can confer on itself."""
    db, uid = _session
    await _seed(db, uid, "immutable_d1", "171265")     # 61 kcal/100g stored

    # ⛔ 500, NOT 999. The first version used 999 kcal/100g, which trips the
    # `>900` ceiling ("nothing edible exceeds 900 per 100 g") and returns
    # BEFORE the existing-row branch — so the test passed because the write
    # was refused by the ceiling, not by immutability. Mutation D1 injected an
    # overwrite into that branch and stayed green, which is how it surfaced.
    await upsert_user_food_match(db, uid, "immutable_d1", "Milk, whole",
                                 "171265",
                                 {"calories": 500.0, "protein": 1.0,
                                  "carbs": 1.0, "fat": 1.0}, "exact")
    row = await get_user_food_match(db, uid, "immutable_d1")

    assert row.cal_100 == 61.0, (
        f"an ordinary lookup rewrote stored nutrition to {row.cal_100} — "
        f"write-once memory became last-writer-wins memory")


@pytest.mark.asyncio
async def test_usage_still_accrues_while_nutrition_stays_frozen(_session):
    """⭐ THE NEGATIVE INVARIANT. Immutable nutrition must not mean an inert
    row: identity, usage and absent metadata still move, because legacy relies
    on them and freezing those would break the cache rather than secure it."""
    db, uid = _session
    row = await _seed(db, uid, "immutable_d2", "171265")
    before = row.times_used or 1

    await upsert_user_food_match(db, uid, "immutable_d2", "Milk, whole",
                                 "171265", dict(_P100), "likely")
    row = await get_user_food_match(db, uid, "immutable_d2")

    assert (row.times_used or 0) > before, "the usage bump stopped working"
    assert row.cal_100 == 61.0
