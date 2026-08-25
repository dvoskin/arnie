"""⛔⛔⛔ CF24 — TRUSTED MEMORY IS A CACHE OF A CANONICAL DECISION.

The forward half of the memory-authority migration. CF23 made history
untrusted; this makes trust REACHABLE without reopening the class.

⛔ `origin_tier` CANNOT ESTABLISH TRUST. It is free text, and every lookup path
writes through the same public door — a guard keyed on it is a magic word one
keyword argument from useless. Trust is a RESOLVED LINK:

    memory row -> settled_by_operation_id -> a real meal_commits row
               -> the basis and evidence id the settlement actually priced on

A fabricated id does not resolve. A non-settlement writer has no id at all.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from db.queries import (get_user_food_match, memory_nutrition_is_trusted,
                        remember_canonical_settlement, upsert_user_food_match)
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401

_P100 = {"calories": 165.0, "protein": 31.0, "carbs": 0.0, "fat": 3.6}


@pytest_asyncio.fixture
async def _session(app_db, seeded):          # noqa: F811
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session, seeded


async def _a_real_settlement(db, uid, operation_id="op:cf24:1"):
    """A genuine `meal_commits` row — the thing the linkage must resolve to."""
    from db.models import MealCommit
    db.add(MealCommit(operation_id=operation_id, operation_revision=0,
                      user_id=uid, status="committed"))
    await db.commit()
    return operation_id


# ── WHAT EARNS TRUST ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_produced_row_is_trusted(_session):
    db, uid = _session
    op = await _a_real_settlement(db, uid, "op:cf24:earn")
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf24earn", display_name="Chicken breast",
        operation_id=op, per100=dict(_P100), evidence_id="171077",
        basis="per_100g", fdc_id="171077")
    row = await get_user_food_match(db, uid, "cf24earn")
    assert await memory_nutrition_is_trusted(db, row) is True


# ── WHAT DOES NOT ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_stamp_pointing_at_NO_settlement_is_refused(_session):
    """⛔⛔ THE TAMPER CASE. A row can carry a perfectly well-formed operation
    id that names nothing. If the predicate believed the field instead of
    resolving it, trust would be forgeable by writing a string."""
    db, uid = _session
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf24ghost", display_name="Ghost",
        operation_id="op:does-not-exist", per100=dict(_P100),
        evidence_id="1", basis="per_100g")
    row = await get_user_food_match(db, uid, "cf24ghost")
    assert row is not None, "the row should still exist as a cache"
    assert await memory_nutrition_is_trusted(db, row) is False


@pytest.mark.asyncio
async def test_the_public_writer_still_cannot_mint_trust(_session):
    """⛔ Every USDA/OFF/legacy/correction write goes through this door and it
    has no linkage to give."""
    db, uid = _session
    await upsert_user_food_match(db, uid, "cf24public", "Public", "171077",
                                 dict(_P100), "exact",
                                 origin_tier="canonical_settlement")
    row = await get_user_food_match(db, uid, "cf24public")
    assert row.origin_tier != "canonical_settlement"
    assert await memory_nutrition_is_trusted(db, row) is False


@pytest.mark.asyncio
async def test_an_unresolvable_check_is_not_trust(_session):
    """⛔ "WE COULD NOT CHECK" MUST NEVER READ AS "IT CHECKED OUT" — the exact
    silence this whole incident kept producing."""
    db, uid = _session
    op = await _a_real_settlement(db, uid, "op:cf24:nodb")
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf24nodb", display_name="NoDb",
        operation_id=op, per100=dict(_P100), evidence_id="1", basis="per_100g")
    row = await get_user_food_match(db, uid, "cf24nodb")
    assert await memory_nutrition_is_trusted(None, row) is False


# ── REPLACEMENT IS WHOLESALE, AND IDEMPOTENT ──────────────────────────────


@pytest.mark.asyncio
async def test_an_untrusted_wrong_row_is_REPLACED_atomically(_session):
    """⛔⛔⛔ DEFECT D's RESOLUTION. The corrupt row is not patched and not
    deleted — the evidence-owned state moves TOGETHER, so there is no hybrid
    of new calories over an old basis."""
    db, uid = _session
    await upsert_user_food_match(db, uid, "cf24repl", "Milk, whole", "999999",
                                 {"calories": 582.0, "protein": 9.0,
                                  "carbs": 49.3, "fat": 39.7}, "likely",
                                 serving_text="4 pieces (16.7 g)")
    op = await _a_real_settlement(db, uid, "op:cf24:repl")
    await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf24repl", display_name="Milk, whole",
        operation_id=op, per100={"calories": 61.0, "protein": 3.2,
                                 "carbs": 4.8, "fat": 3.3},
        evidence_id="171265", basis="per_100g", fdc_id="171265")
    row = await get_user_food_match(db, uid, "cf24repl")

    assert row.cal_100 == 61.0, "the corrupt nutrition survived"
    assert row.fdc_id == "171265", "the evidence id was not replaced with it"
    assert row.settled_evidence_id == "171265"
    assert row.serving_text is None, (
        "the wrong-product serving panel survived the replacement — hybrid "
        "state is Defect D surviving its own repair")
    assert await memory_nutrition_is_trusted(db, row) is True


@pytest.mark.asyncio
async def test_a_replayed_settlement_does_not_create_a_second_row(_session):
    """⛔ THE RUNG THAT IS SUPPOSED TO BE CERTAIN CANNOT DISAGREE WITH ITSELF.
    A retry of the same operation must not mint a conflicting trusted row."""
    db, uid = _session
    op = await _a_real_settlement(db, uid, "op:cf24:replay")
    for _ in range(3):
        await remember_canonical_settlement(
            db, user_id=uid, name_norm="cf24replay", display_name="Rice",
            operation_id=op, per100=dict(_P100), evidence_id="1",
            basis="per_100g")

    from sqlalchemy import func, select
    from db.models import UserFoodMatch
    n = (await db.execute(select(func.count()).select_from(UserFoodMatch).where(
        UserFoodMatch.user_id == uid,
        UserFoodMatch.name_norm == "cf24replay"))).scalar()
    assert n == 1, f"a replay produced {n} rows for one operation"


@pytest.mark.asyncio
async def test_the_sanity_ceiling_still_applies_to_a_settlement(_session):
    """⭐ A SETTLEMENT IS NOT LICENCE TO STORE A NON-FOOD. The `>900` ceiling
    is a sanity check, never an authority check — it binds the producer too."""
    db, uid = _session
    op = await _a_real_settlement(db, uid, "op:cf24:ceiling")
    got = await remember_canonical_settlement(
        db, user_id=uid, name_norm="cf24ceiling", display_name="Impossible",
        operation_id=op, per100={"calories": 5030.0, "protein": 0.0,
                                 "carbs": 0.0, "fat": 0.0},
        evidence_id="1", basis="per_100g")
    assert got is None
    assert await get_user_food_match(db, uid, "cf24ceiling") is None


# ══════════════════════════════════════════════════════════════════════════
# END TO END — THE REAL SETTLEMENT PRODUCES THE ROW
#
# ⛔ Every case above calls the producer DIRECTLY. That proves the producer and
# says nothing about whether settlement ever calls it — the "a function that is
# called is not a function whose result is used" trap, one layer out. These
# drive `GeneralSettlementOwner.settle` and then read memory back.
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a_real_settlement_produces_trusted_memory(_session, monkeypatch):
    """⭐ THE WIRE PROOF. An authoritative settle must leave behind a memory row
    that BOTH owners will accept next time — that is the whole point of the
    producer, and nothing else in this file demonstrates it."""
    from core.canonical_pricing import Rung
    from core.food_intelligence import memory_key
    from core.general_settlement import GeneralSettlementOwner
    from types import SimpleNamespace

    db, uid = _session
    owner = GeneralSettlementOwner()

    async def _assemble(*_a, **_k):
        return {"memory": None, "product": None, "artifact": None,
                "estimate": None}

    def _price(**kw):
        """⭐ THE REAL `PricedFood`, NOT A STAND-IN. My first version used a
        SimpleNamespace and failed on `.estimated`, then wanted five more
        fields — a fake thin enough to write quickly is a fake that does not
        exercise the code under test. The real dataclass carries whatever
        settlement reads, by construction."""
        from core.canonical_pricing import PricedFood
        return PricedFood(
            calories=247.5, protein=46.5, carbs=0.0, fats=5.4,
            rung=Rung.ARTIFACT, evidence_id="usda:171077", basis="per_100g",
            scaling_factor=1.5, resolved_grams=150.0)

    import core.canonical_pricing as CP
    import core.canonical_pricing_inputs as CPI
    monkeypatch.setattr(CPI, "assemble", _assemble)
    monkeypatch.setattr(CP, "price", _price)

    user = SimpleNamespace(id=uid, timezone="UTC")
    items = [{"food_name": "Chicken breast", "quantity": "150 g"}]
    await owner.settle(db, user=user, items=items,
                       source_turn_id="turn:cf24:wire",
                       source_text="150 g chicken breast")

    row = await get_user_food_match(db, uid, memory_key("Chicken breast", ""))
    assert row is not None, "the settlement produced no memory row"
    assert await memory_nutrition_is_trusted(db, row) is True, (
        "settlement wrote a row the trust predicate rejects — the linkage did "
        "not survive the wire")
    # 247.5 kcal for 150 g -> 165 per 100 g
    assert round(row.cal_100) == 165, (
        f"the stored density is not the settled one: {row.cal_100}")
    assert row.settled_evidence_id == "usda:171077"
    assert row.settled_basis == "per_100g"


@pytest.mark.asyncio
async def test_a_settlement_that_never_commits_produces_nothing(_session,
                                                                monkeypatch):
    """⛔⛔ STAMPED AFTER THE WRITE, NEVER BESIDE IT. A stamp written before the
    commit lands would vouch for a settlement that may not exist — and
    `PricingRefused` propagates by design (A8), so this path is reachable."""
    from core.canonical_pricing import PricingRefused
    from core.food_intelligence import memory_key
    from core.general_settlement import GeneralSettlementOwner
    from types import SimpleNamespace

    db, uid = _session

    async def _assemble(*_a, **_k):
        return {"memory": None, "product": None, "artifact": None,
                "estimate": None}

    def _price(**kw):
        raise PricingRefused("no rung could price it")

    import core.canonical_pricing as CP
    import core.canonical_pricing_inputs as CPI
    monkeypatch.setattr(CPI, "assemble", _assemble)
    monkeypatch.setattr(CP, "price", _price)

    with pytest.raises(PricingRefused):
        await GeneralSettlementOwner().settle(
            db, user=SimpleNamespace(id=uid, timezone="UTC"),
            items=[{"food_name": "Refused food", "quantity": "150 g"}],
            source_turn_id="turn:cf24:refused", source_text="x")

    assert await get_user_food_match(
        db, uid, memory_key("Refused food", "")) is None, (
        "a refused settlement still left trusted memory behind")


@pytest.mark.asyncio
async def test_a_RESOLVABLE_settlement_still_needs_its_basis_and_evidence(_session):
    """⛔⛔⛔ THE CASE EVERY OTHER TEST HERE MASKED.

    Mutation P3 deleted the `operation and basis and evidence` check and the
    whole suite stayed GREEN. Not because the check is idle — because every
    row written without a basis was ALSO written without a resolvable
    operation, so the resolution step refused it first and the presence check
    never got to speak. Two guards in series, and the outer one was answering
    for both.

    ⭐ So this row names a settlement that REALLY EXISTS, and is missing only
    the basis. If the fields ever become optional, this is the row that walks
    through: a genuine settlement id used as a blanket over numbers whose
    derivation nobody recorded.
    """
    from db.models import MealCommit, UserFoodMatch

    db, uid = _session
    operation_id = "op:cf24-resolvable-but-baseless"
    db.add(MealCommit(operation_id=operation_id, operation_revision=0,
                      user_id=uid, status="committed"))
    row = UserFoodMatch(user_id=uid, name_norm="cf24baseless",
                        display_name="Baseless", cal_100=165.0,
                        protein_100=31.0, carbs_100=0.0, fat_100=3.6,
                        fdc_id="171077", confidence="canonical",
                        origin_tier="canonical_settlement",
                        settled_by_operation_id=operation_id,
                        settled_basis=None, settled_evidence_id="171077")
    db.add(row)
    await db.flush()

    assert await memory_nutrition_is_trusted(db, row) is False, (
        "a row naming a REAL settlement was trusted without recording the "
        "basis its numbers were derived on — the settlement id became a "
        "blanket, which is the tier stamp again under a longer name")

    # ⭐ THE NEGATIVE INVARIANT: the same row, with the basis, IS trusted —
    # otherwise this test would also pass if the predicate simply always
    # refused, and would prove nothing about the field it names.
    row.settled_basis = "per_100g"
    await db.flush()
    assert await memory_nutrition_is_trusted(db, row) is True, (
        "adding the basis did not make the row trusted — this test cannot "
        "distinguish the guard it is aimed at from a predicate that always "
        "says no")
