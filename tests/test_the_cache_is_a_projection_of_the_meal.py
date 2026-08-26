"""⛔⛔⛔ CF26 — TRUSTED MEMORY IS A PROJECTION OF THE COMMITTED MEAL.

Danny, 2026-08-25:

    A cache row may only record nutrition the meal actually used. If the
    committed meal cannot be converted back to a defensible per-100g profile
    from AUTHORITATIVE mass, write no nutrition cache row.

The cache was answering the wrong question. It stored *"what richer profile
happened to win some upstream authority competition?"* when the only question
memory may answer is *"what nutrition did settlement actually use for this
food?"*

⭐⭐⭐ AND THE WRITE SITE STRUCTURALLY CANNOT ANSWER THE RIGHT ONE. The call at
`tool_executor.py:3077` lives inside `fetch_candidates` — the CANDIDATE
GATHERING phase, which runs BEFORE the meal is priced. It is not that it picks
the wrong number; the committed number does not exist yet. Under the rule
above that site has exactly one legal output: no nutrition.

Measured consequences of it writing anyway, three weeks apart:

    2026-08-02  entry 2687   committed 150 kcal      cached 437.5/100g
    2026-08-25  entry 3053   committed 590 kcal      cached 643/100g
                             (the interpreter had said 500)

Every poisoned row the CF24 probes hunted was made this way — 936, 886, 292,
1029, 1031.

⛔ EXPLICITLY PROHIBITED, and each has a test below or in the sibling suites:
candidate-vs-commit tolerance bands · "close enough" equality · calorie
plausibility · rung superiority overriding the committed result · caching a
per-100g candidate merely because it carries more information.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


@pytest_asyncio.fixture
async def _session(app_db, seeded):  # noqa: F811
    import db.database as D
    async with D.AsyncSessionLocal() as s:
        yield s, seeded


@pytest.mark.asyncio
async def test_the_prepricing_writer_stores_no_nutrition(_session):
    """⛔⛔⛔ THE 3053 SHAPE, REFUSED AT THE SOURCE.

    A candidate says 643 kcal/100g. The meal has not been priced yet — this
    code runs before `analyze()` — so no value here can be a projection of the
    committed meal. The row may still record identity and usage; it may not
    record nutrition."""
    from db.queries import get_user_food_match, upsert_user_food_match

    db, uid = _session
    await upsert_user_food_match(
        db, uid, "cf26 crispy fried onions", "Crispy fried onions", "173160",
        {"calories": 643.0, "protein": 14.3, "carbs": 42.9, "fat": 50.0},
        "likely", origin_tier="branded_exact", serving_text="2 Tbsp")
    row = await get_user_food_match(db, uid, "cf26 crispy fried onions")

    assert row is not None, "identity and usage must still be cached"
    assert row.cal_100 is None, (
        f"a candidate's per-100g was cached before the meal was priced — this "
        f"is how row 1031 came to hold 643 while the entry committed 590: "
        f"{row.cal_100}")
    assert row.protein_100 is None and row.carbs_100 is None
    assert row.fat_100 is None


@pytest.mark.asyncio
async def test_identity_usage_and_serving_survive(_session):
    """⭐ THE NEGATIVE INVARIANT. Refusing the nutrition must not delete the
    cache — identity, the usage record and the serving panel are what legacy
    still needs, and none of them claim to be nutrition the meal used."""
    from db.queries import get_user_food_match, upsert_user_food_match

    db, uid = _session
    for _ in range(2):
        await upsert_user_food_match(
            db, uid, "cf26 identity", "Identity Food", "12345",
            {"calories": 500.0, "protein": 5.0, "carbs": 40.0, "fat": 36.0},
            "likely", serving_text="1 portion (30 g)")
    row = await get_user_food_match(db, uid, "cf26 identity")

    assert row.display_name == "Identity Food"
    assert row.fdc_id == "12345"
    assert row.serving_text == "1 portion (30 g)"
    assert (row.times_used or 0) >= 2, (
        "the usage record was lost — the cache was deleted rather than "
        "corrected, and every repeat log now pays a fresh lookup")


@pytest.mark.asyncio
async def test_the_committed_projection_round_trips(_session):
    """⭐⭐⭐ THE POSITIVE CASE, AND IT IS THE ONLY WRITER LEFT THAT MAY STORE
    NUTRITION. 120 g of shrimp committing 118.8 kcal against an authoritative
    mass projects to exactly 99 kcal/100g, and 99 x 1.2 returns 118.8. The
    stored row is a reversible representation of the meal, not a claim of its
    own."""
    from db.models import MealCommit
    from db.queries import get_user_food_match, remember_canonical_settlement

    db, uid = _session
    op = "op:cf26-projection"
    db.add(MealCommit(operation_id=op, operation_revision=0, user_id=uid,
                      status="committed"))
    await db.flush()

    committed_kcal, grams = 118.8, 120.0
    per100 = {"calories": committed_kcal / (grams / 100.0),
              "protein": 28.8 / (grams / 100.0),
              "carbs": 0.2 / (grams / 100.0), "fat": 0.3 / (grams / 100.0)}
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf26 shrimp", display_name="Shrimp",
        operation_id=op, per100=per100, evidence_id="175180",
        basis="per_100g", fdc_id="175180")
    row = await get_user_food_match(db, uid, "cf26 shrimp")

    assert row is not None and row.cal_100 is not None
    assert abs(row.cal_100 - 99.0) < 0.05, (
        f"the projection is not the committed meal: {row.cal_100}")
    assert abs(row.cal_100 * (grams / 100.0) - committed_kcal) < 0.05, (
        "the stored per-100g does not round-trip to the committed calories, "
        "so it is a claim of its own rather than a representation of the meal")


@pytest.mark.asyncio
async def test_no_authoritative_mass_no_nutrition_row(_session):
    """⛔⛔ THE SECOND NEGATIVE, AND IT IS WHAT STOPS 'CACHE THE COMMITTED
    VALUES' FROM QUIETLY RECREATING INVENTED DENSITY.

    `1 bar -> 200 kcal` establishes no density. A per-100g profile written
    from it would be an invention wearing the committed meal's authority —
    exactly row 644's shape, which claimed 200 kcal/100g for a bar whose mass
    nobody ever established."""
    from db.queries import get_user_food_match, remember_canonical_settlement

    db, uid = _session
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf26 bar", display_name="Some Bar",
        operation_id="op:cf26-no-mass", per100={"calories": 200.0},
        evidence_id="", basis="")
    assert await get_user_food_match(db, uid, "cf26 bar") is None, (
        "a per-100g row was written for a meal with no authoritative mass — "
        "the density was invented, not projected")


@pytest.mark.asyncio
async def test_a_basis_without_an_evidence_id_is_still_refused(_session):
    """⛔⛔ GUARDS IN SERIES, AND MUTATION Y3 FOUND IT.

    `test_no_authoritative_mass_no_nutrition_row` passes BOTH an empty basis
    and an empty evidence id, so dropping the evidence requirement left every
    proof green — the basis check refused those rows first and the evidence
    check never got to speak. This row names a real normalization and cannot
    say what it was normalized against.

    A basis is HOW the meal was projected; the evidence id is WHAT it was
    projected from. A projection missing either half is a claim of its own."""
    from db.models import MealCommit
    from db.queries import get_user_food_match, remember_canonical_settlement

    db, uid = _session
    op = "op:cf26-basis-no-evidence"
    db.add(MealCommit(operation_id=op, operation_revision=0, user_id=uid,
                      status="committed"))
    await db.flush()

    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf26 baseless evidence",
        display_name="Baseless", operation_id=op,
        per100={"calories": 99.0, "protein": 24.0}, evidence_id="",
        basis="per_100g")
    assert await get_user_food_match(db, uid, "cf26 baseless evidence") is None, (
        "a projection was stored that cannot name what it was projected from")


@pytest.mark.asyncio
async def test_the_public_writer_never_writes_micros_ON_ANY_ROW(_session):
    """⛔⛔⛔ THE BLOCKER DANNY CAUGHT IN REVIEW, AND WHY THE FIRST FIX WAS WORSE
    THAN THE BUG.

    CF26's first draft kept the micro self-heal and gated it on
    `existing.cal_100 is not None`. That gate fires ONLY on rows that already
    carry macros — **trusted ones included** — so a candidate found during
    gathering could staple its micronutrients onto a row whose authority was
    earned by a prior COMMITTED meal:

        historical macros  +  today's candidate's micros

    A profile no single meal ever produced, wearing the older meal's
    authority. Narrowing the graft concentrated it on exactly the rows that
    could least afford it.

    ⭐ SO THE CONTRACT IS ABSOLUTE, AND THIS TEST STATES IT THAT WAY: the
    public writer writes ZERO nutrition fields, on INSERT and on UPDATE, to a
    row with macros and to a row without. Not "refuses when NULL" — cannot.
    """
    from db.models import MealCommit, UserFoodMatch
    from db.queries import (get_user_food_match, remember_canonical_settlement,
                            upsert_user_food_match)

    db, uid = _session
    rich = {"calories": 500.0, "protein": 5.0, "carbs": 40.0, "fat": 36.0,
            "calcium": 120.0, "iron": 2.0, "potassium": 300.0}

    # ── a row WITH macros, earned by a real settlement ────────────────────
    op = "op:cf26-micro-graft"
    db.add(MealCommit(operation_id=op, operation_revision=0, user_id=uid,
                      status="committed"))
    await db.flush()
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf26 earned", display_name="Earned",
        operation_id=op, per100={"calories": 99.0, "protein": 24.0},
        evidence_id="175180", basis="per_100g", fdc_id="175180")
    earned = await get_user_food_match(db, uid, "cf26 earned")
    assert earned.cal_100 == 99.0 and earned.micros_100_json is None, (
        "precondition: a settled row carrying macros and no micro panel")

    # ── candidate gathering passes by with a richer, differently-bound panel
    await upsert_user_food_match(db, uid, "cf26 earned", "Earned", "999999",
                                 rich, "likely")
    row = await get_user_food_match(db, uid, "cf26 earned")

    assert row.micros_100_json is None, (
        "a candidate's micronutrients were grafted onto a row whose macros "
        f"were earned by a committed meal — the hybrid CF26 deletes: "
        f"{row.micros_100_json}")
    assert row.cal_100 == 99.0, "the earned macros must be untouched"
    assert (row.times_used or 0) >= 2, "usage must still accrue"

    # ── and equally on a row with NO macros ───────────────────────────────
    for _ in range(2):
        await upsert_user_food_match(db, uid, "cf26 bare", "Bare", "888",
                                     rich, "likely")
    bare = await get_user_food_match(db, uid, "cf26 bare")
    assert bare.cal_100 is None and bare.micros_100_json is None, (
        "the writer stored nutrition on a row it created")


@pytest.mark.asyncio
async def test_a_settlement_still_delivers_the_micro_panel(_session):
    """⭐ THE NEGATIVE INVARIANT. Refusing the graft must not mean micros are
    unreachable — a pre-micros row still gains its panel, from the settlement
    that earned it rather than from a candidate that passed by."""
    import json as _json

    from db.models import MealCommit
    from db.queries import get_user_food_match, remember_canonical_settlement

    db, uid = _session
    op = "op:cf26-micro-projection"
    db.add(MealCommit(operation_id=op, operation_revision=0, user_id=uid,
                      status="committed"))
    await db.flush()
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf26 panel", display_name="Panel",
        operation_id=op,
        per100={"calories": 99.0, "protein": 24.0, "calcium": 120.0,
                "iron": 2.0},
        evidence_id="175180", basis="per_100g", fdc_id="175180")
    row = await get_user_food_match(db, uid, "cf26 panel")

    assert row.micros_100_json is not None, (
        "the settlement projection lost the micro panel — fail-closed became "
        "fail-always and micros are now unreachable by any writer")
    assert _json.loads(row.micros_100_json)["calcium"] == 120.0
