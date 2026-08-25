"""⛔⛔⛔ CF23 — HISTORICAL MEMORY NUTRITION IS NOT AUTHORITY.

A live fleet-wide wrong-nutrition incident, found 2026-08-24 while looking for
a food to run the P17g canonical canary against.

`_web_lookup_packaged` FABRICATES a density when its serving-size regex misses
(`handlers/tool_executor.py`):

    per100 = {"calories": 200.0,
              "protein": (pro / cal) * 200.0 if cal else None, ...}

Not a measurement — an assumed 200 kcal/100g for any packaged food, with the
macros scaled to that fiction. `upsert_user_food_match` then caches it, and
because the existing-row branch NEVER refreshes nutrition, the wrong value is
permanent. Measured in production:

    fleet rows at exactly 200.0 kcal/100g                    163
    still live to legacy (fresh/confirmed AND sole-binding)  154
    distinct users affected                                   13

⛔ AND THE 2026-08-16 CONTAINMENT CANNOT SEE THIS CLASS.
`address_has_one_authority` tests agreement BETWEEN bindings, explicitly "NO
CALORIE PLAUSIBILITY, NO FOOD NAMES, NO EXCEPTIONS". A sole binding is
uncontested — and uncontested is not correct. `Milk, whole` cached at 582
kcal/100g against a true 61, carrying another food's serving panel
(`"4 pieces (16.7 g)"`), passes it and legacy prices from it.

⭐ SO THE TEST IS PROVENANCE, NOT PLAUSIBILITY. A calorie ceiling would be a
second guess layered on the first. A row earns authority by naming the
authority that produced it under a checkable basis — and today essentially no
historical row can.

⭐ ONE GUARD, TWO OWNERS. 2026-08-16 is the reason: canonical declined the
corrupt cucumber address and legacy priced the meal from the very same row,
reproducing the error canonical had just prevented. A guard only one owner
applies has a longer fuse.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from db.queries import memory_nutrition_is_trusted
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401


class _Row:
    """A production-SHAPED memory row. Fields mirror `user_food_matches`."""
    def __init__(self, **kw):
        self.cal_100 = kw.get("cal_100", 200.0)
        self.protein_100 = kw.get("protein_100", 10.0)
        self.carbs_100 = kw.get("carbs_100", 20.0)
        self.fat_100 = kw.get("fat_100", 5.0)
        self.fdc_id = kw.get("fdc_id")
        self.origin_tier = kw.get("origin_tier", "generic_exact")
        self.user_confirmed = kw.get("user_confirmed", False)
        self.serving_text = kw.get("serving_text")
        self.display_name = kw.get("display_name", "Thing")
        # ── CF24: the columns that carry the LINK to a real settlement ──
        self.settled_by_operation_id = kw.get("settled_by_operation_id")
        self.settled_basis = kw.get("settled_basis")
        self.settled_evidence_id = kw.get("settled_evidence_id")


# ── THE TWO PRODUCTION DEFECTS, AS FIXTURES ───────────────────────────────


@pytest.mark.asyncio
async def test_the_fabricated_200_placeholder_is_not_evidence(_session):
    """The exact shape the web branch writes: no serving parsed, no fdc_id,
    calories exactly 200.0, macros scaled to it. 154 live rows look like this."""
    db, _uid = _session
    row = _Row(display_name="Quest Chips Sweet Chili", cal_100=200.0,
               fdc_id=None, serving_text=None, origin_tier="branded_exact")
    assert await memory_nutrition_is_trusted(db, row) is False


@pytest.mark.asyncio
async def test_whole_milk_at_582_with_another_foods_serving_is_not_evidence(_session):
    """⛔ THE ROW THE 08-16 GUARD LETS THROUGH. Sole binding, fresh,
    internally consistent — and 9.5x the truth, carrying a *pieces* serving on
    a liquid. Nothing about agreement-between-bindings can see it."""
    db, _uid = _session
    row = _Row(display_name="Milk, whole", cal_100=582.0, protein_100=9.0,
               carbs_100=49.3, fat_100=39.7, serving_text="4 pieces (16.7 g)",
               origin_tier="branded_exact")
    assert await memory_nutrition_is_trusted(db, row) is False


@pytest.mark.asyncio
async def test_an_internally_consistent_but_unproven_row_is_still_not_evidence(_session):
    """⭐ THE CASE THAT DEFEATS EVERY INTERNAL CHECK. When a whole row is
    scaled by one wrong factor, `4P + 4C + 9F` reconstructs the calories
    perfectly. Banana at 312, cucumber at 179, white rice at 333 are all
    self-consistent and all false. Consistency is not provenance."""
    db, _uid = _session
    row = _Row(display_name="Banana", cal_100=312.0, protein_100=3.9,
               carbs_100=70.0, fat_100=1.2, origin_tier="generic_exact")
    recon = 4 * 3.9 + 4 * 70.0 + 9 * 1.2
    assert abs(recon - 312.0) < 30, "fixture must be self-consistent to be honest"
    assert await memory_nutrition_is_trusted(db, row) is False


# ── WHAT DOES NOT EARN AUTHORITY ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_confirmed_alone_does_not_earn_authority(_session):
    """⛔ A user confirming a NUMBER says nothing about the BASIS it was
    derived on. 441 of 444 rows on the affected account are unconfirmed; the
    3 that are confirmed are not thereby evidence either."""
    db, _uid = _session
    assert await memory_nutrition_is_trusted(db, _Row(user_confirmed=True, origin_tier="user_regular")) is False


@pytest.mark.asyncio
async def test_a_tier_is_not_a_provenance_stamp(_session):
    """`origin_tier` records which ladder rung answered, INFERRED at write
    time. `generic_exact` and `branded_exact` are on 114 and 49 of the
    fabricated rows respectively — the tier was never a claim about truth."""
    db, _uid = _session
    for tier in ("generic_exact", "branded_exact", "estimated", "user_regular"):
        assert await memory_nutrition_is_trusted(db, _Row(origin_tier=tier)) is False


@pytest.mark.asyncio
async def test_no_calorie_threshold_is_used_as_authority(_session):
    """⛔⛔ A PLAUSIBLE NUMBER IS STILL NOT EVIDENCE. Olive oil at 800 and
    peanut butter at 594 are CORRECT — and unproven, so they are rejected too.
    Adding a plausibility band here would be a second guess on top of the
    first, and would have admitted milk at 582 while rejecting olive oil."""
    db, _uid = _session
    for cal in (15.0, 61.0, 89.0, 200.0, 594.0, 800.0, 899.0):
        assert await memory_nutrition_is_trusted(db, _Row(cal_100=cal)) is False


# ── WHAT DOES ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_canonically_settled_row_with_a_basis_remains_eligible(_session):
    """⭐ THE GUARD IS NOT 'ALWAYS FALSE'. A row stamped by an authoritative
    canonical settlement, carrying the source identifier its numbers came
    from, is still evidence — which is what makes the forward path a stamp
    rather than a rewrite of this predicate."""
    db, uid = _session
    from tests.trusted_memory_fixture import trusted

    from db.models import UserFoodMatch
    row = trusted(db, UserFoodMatch(user_id=uid, name_norm="eligible anchor",
                                    display_name="Eligible Anchor",
                                    cal_100=165.0, protein_100=31.0,
                                    carbs_100=0.0, fat_100=3.6,
                                    fdc_id="171077"))
    db.add(row)
    await db.flush()
    assert await memory_nutrition_is_trusted(db, row) is True


@pytest.mark.asyncio
async def test_a_canonical_stamp_without_a_source_identifier_is_refused(_session):
    """⛔ THE STAMP ALONE IS NOT ENOUGH — the basis has to travel with it, or
    'trusted' means only 'we wrote it'."""
    db, _uid = _session
    assert await memory_nutrition_is_trusted(db, _Row(
        origin_tier="canonical_settlement",
        settled_by_operation_id="op:whatever", settled_basis="per_100g",
        settled_evidence_id=None, fdc_id=None)) is False


# ── ONE GUARD, BOTH OWNERS ────────────────────────────────────────────────


def test_both_owners_call_the_SAME_function():
    """⛔ STRUCTURAL HALF ONLY — and it is NOT sufficient on its own.

    Mutation M5 replaced legacy's `if not memory_nutrition_is_trusted(m):`
    with `if False:` and this test STAYED GREEN, because the identifier still
    appears in the comment above the call. A grep trap in the very proof
    written to prevent one. `test_legacy_does_not_price_from_untrusted_memory`
    below is the behavioural half, and it is the one that counts."""
    import inspect

    from core import canonical_pricing_inputs as CPI

    canonical_src = inspect.getsource(CPI._memory)
    assert "memory_nutrition_evidence" in canonical_src, (
        "the canonical memory rung does not go through the shared door — "
        "`memory_nutrition_evidence` is the ONE conversion from a stored row "
        "to pricing evidence, and it is what makes the consumer of a given "
        "row answerable from a log line")


@pytest.mark.asyncio
async def test_legacy_does_not_price_from_untrusted_memory(_session,
                                                           monkeypatch):
    """⛔⛔⛔ THE BEHAVIOURAL PROOF, DRIVEN THROUGH THE REAL LEGACY LANE.

    2026-08-16: canonical declined a corrupt cucumber address and legacy
    priced the meal from that same row — "declining to a known-unsafe owner
    reproduced the exact error canonical had just prevented". A guard only one
    owner applies has a longer fuse, and asserting it structurally is how the
    fuse stays lit.

    So this seeds an untrusted row and drives `fetch_candidates`, asserting the
    legacy pricer takes NO memory from it."""
    from types import SimpleNamespace

    import handlers.tool_executor as TE
    from db.queries import upsert_user_food_match

    db, uid = _session
    food = "Untrusted Legacy Food"

    # no web/USDA/OFF noise — this test is about the memory rung alone
    async def _none(*a, **k):
        return None
    monkeypatch.setattr(TE, "_web_lookup_packaged", _none)
    monkeypatch.setattr("api.usda.search_food", lambda *a, **k: _none())

    from core.food_intelligence import normalize_name
    await upsert_user_food_match(
        db, uid, normalize_name(food), food, "12345",
        {"calories": 200.0, "protein": 10.0, "carbs": 20.0, "fat": 5.0},
        "likely")

    got = await TE.fetch_candidates(
        db, SimpleNamespace(id=uid, timezone="UTC"), food,
        {"food_name": food, "quantity": "100 g"})

    assert got.memory is None, (
        "the legacy pricer took nutrition from an untrusted memory row — this "
        "is the 2026-08-16 shape, where canonical declines and legacy commits "
        f"the same numbers: {got.memory!r}")



# ── STAMP INTEGRITY — THE TIER IS NOT A MAGIC WORD ────────────────────────


@pytest.mark.asyncio
async def test_the_public_writer_cannot_mint_a_trusted_tier(_session):
    """⛔⛔⛔ WITHOUT THIS, THE GUARD IS ONE KEYWORD ARGUMENT FROM USELESS.

    `upsert_user_food_match` is called after every successful lookup — web,
    USDA, OFF, legacy estimate, ordinary correction. If any of them could pass
    `origin_tier="canonical_settlement"`, the 163 fabricated rows would have
    been trusted by saying so.

    Sanitised rather than refused: refusing would drop the identity and usage
    record legacy still needs, and only the unearned authority has to go."""
    from db.queries import get_user_food_match, upsert_user_food_match

    db, uid = _session
    if True:
        await upsert_user_food_match(
            db, uid, "sneakyfood", "Sneaky Food", "12345",
            {"calories": 200.0, "protein": 10.0, "carbs": 20.0, "fat": 5.0},
            "likely", origin_tier="canonical_settlement")
        row = await get_user_food_match(db, uid, "sneakyfood")

    assert row is not None, "the row should still be cached for identity/usage"
    assert row.origin_tier != "canonical_settlement", (
        "the public writer minted a trusted tier — the guard is a magic word")
    assert await memory_nutrition_is_trusted(db, row) is False


@pytest.mark.asyncio
async def test_an_untrusted_row_cannot_be_upgraded_by_use_or_confirmation(_session):
    """⛔ NO LAUNDERING PATH. An existing untrusted row must not become
    authority through repeat use, a correction, or a user confirming the
    number — `user_confirmed` says nothing about the BASIS."""
    from db.queries import get_user_food_match, upsert_user_food_match

    db, uid = _session
    if True:
        per100 = {"calories": 200.0, "protein": 10.0, "carbs": 20.0, "fat": 5.0}
        await upsert_user_food_match(db, uid, "launder", "Launder", "1",
                                     per100, "likely")
        # repeat use, then a user confirmation, then a trusted-tier attempt
        await upsert_user_food_match(db, uid, "launder", "Launder", "1",
                                     per100, "likely")
        await upsert_user_food_match(db, uid, "launder", "Launder", "1",
                                     per100, "user-confirmed",
                                     user_confirmed=True)
        await upsert_user_food_match(db, uid, "launder", "Launder", "1",
                                     per100, "likely",
                                     origin_tier="canonical_settlement")
        row = await get_user_food_match(db, uid, "launder")

    assert row.user_confirmed is True, "the confirmation itself should stick"
    assert await memory_nutrition_is_trusted(db, row) is False, (
        "an untrusted row was laundered into authority through usage and "
        "confirmation — neither establishes the basis its numbers came from")


@pytest_asyncio.fixture
async def _session(app_db, seeded):          # noqa: F811
    """Yields (session, seeded_user_id). The user must EXIST: `user_food_matches`
    carries a foreign key, and inventing an id gets a ForeignKeyViolation."""
    """The repo's own session idiom — `app_db` yields an ENGINE, not a
    callable. My first version did `async with app_db() as db` and every case
    died on `'AsyncEngine' object is not callable`."""
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session, seeded


@pytest.mark.asyncio
async def test_a_stamp_naming_a_settlement_that_does_not_exist_is_refused(_session):
    """⛔⛔⛔ THE CF24 CASE. A dangling link is exactly as fakeable as a magic
    word: if the predicate reads the column without resolving it, writing
    `settled_by_operation_id="anything"` restores the defect the tier stamp
    had. The link has to RESOLVE, against `meal_commits`, or it is decoration.

    The row below is complete in every other respect — tier, basis, evidence
    id — and is refused solely because the operation it names never happened."""
    db, _uid = _session
    assert await memory_nutrition_is_trusted(db, _Row(
        origin_tier="canonical_settlement",
        settled_by_operation_id="op:never-happened",
        settled_basis="per_100g", settled_evidence_id="171077",
        fdc_id="171077")) is False
