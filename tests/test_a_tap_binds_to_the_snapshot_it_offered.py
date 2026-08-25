"""⭐ B-1.8c2.2 — A TAP BINDS TO THE SNAPSHOT IT WAS OFFERED FROM. THE CHAIN
IS ENFORCED, NOT INVENTED.

    tap (field_id, option_id, revision)
      -> answer_from_chip -> interaction.patch_for  (the STORED patch)
      -> reopen the exact universe (candidate_set_id / operation_id / user)
      -> verify_selection: option == candidate == snapshot == entity
      -> correct_identity(product_evidence_id, BOUND)
           assemble(bound)  never READS memory / artifact / estimate
           price(bound)     that snapshot, or PricingRefused — no fallback
      -> ONE canonical correction transaction

Two non-negotiables *(Danny)*: a v1 SelectProductVariant with
product_evidence_id=0 is UNBOUND — refused from bound pricing, never weakly
bound to "the latest snapshot for that entity"; and verify_selection proves
the WHOLE triangle, not one edge of it.

Every refusal below is proven NON-MUTATING: the row is byte-identical and no
correction ledger event exists afterwards.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from core.canonical_correction import (CORRECTION_SOURCE, CorrectionRefused,
                                       ProductSelectionRefused,
                                       select_product_variant)
from core.semantics import (CandidateSet, ClarificationAttribute,
                            ClarificationGroup, ClarificationInteraction,
                            EvidenceContext, ExactProductCandidate,
                            Provenance, ResponseType, SelectProductVariant,
                            UnresolvedField)
from tests.trusted_memory_fixture import trusted  # noqa: E402

OP = "op:c22"
EVENT = "food_ev_1"


# ── fixtures: a canonical row, snapshots, a persisted universe, an interaction ─

async def _canonical_row(db, user, *, name="Protein bar", quantity="2 bars"):
    from core.canonical_writer import (CanonicalEvent, DirectOperation,
                                       ResolvedFood, ResolvedMeal,
                                       ResolutionStatus, write_canonical_meal)
    from db.models import FoodEntry
    meal = ResolvedMeal(
        operation_id=f"c22_{user.id}_{name}", revision=0, user_id=user.id,
        logging_day=dt.date(2026, 8, 18), user_timezone="America/New_York",
        items=(ResolvedFood(
            event=CanonicalEvent(id="e", domain="food", surface_text=name,
                                 resolution_status=ResolutionStatus.RESOLVED),
            calories=200.0, protein=10.0, carbs=5.0, fats=8.0,
            quantity_text=quantity,
            attributes={"pricing": {"rung": "estimate", "evidence_id": "",
                                    "basis": "per_portion"}}),))
    await write_canonical_meal(db, operation=DirectOperation(meal),
                               resolved_meal=meal)
    await db.commit()
    return (await db.execute(select(FoodEntry).where(
        FoodEntry.parsed_food_name == name,
    ).order_by(FoodEntry.id.desc()))).scalars().first()


async def _snap(db, code="70004199", rev=1, kcal_serving=110):
    from skills.nutrition.product_store import append_product_evidence
    return await append_product_evidence(db, record={
        "code": code, "product_name": "Barebell salty peanut", "brands": "Barebell",
        "serving_size": "55.0g", "serving_quantity": 55,
        "serving_quantity_unit": "g", "rev": rev, "last_modified_t": rev,
        "nutrition_data_per": "100g",
        # per-100 g and per-serving must AGREE or the store refuses the record
        # (its own consistency gate) — so a hotter label is hotter both ways.
        "nutriments": {"energy-kcal_100g": round(kcal_serving / 0.55, 1),
                       "proteins_100g": 20,
                       "carbohydrates_100g": 18, "fat_100g": 7.3,
                       "energy-kcal_serving": kcal_serving,
                       "proteins_serving": 11, "carbohydrates_serving": 9.9,
                       "fat_serving": 4}},
        serving_unit="bar")


def _universe(user_id, candidates, *, set_id, op=OP):
    return CandidateSet(
        candidate_set_id=set_id, operation_id=op, user_id=user_id,
        context=EvidenceContext(user_id=user_id, canonical_entity_id="",
                                product_variant_id=None),
        interaction_revision=0, field_id="product_variant",
        generator_version="product_variant_reopen_v1",
        generation_input_fingerprint="fp", candidates=candidates,
        candidate_kind="product")


async def _persist(db, user, candidates, *, set_id, op=OP):
    from core import candidate_repository as repo
    sid = await repo.ensure_candidate_set(
        db, _universe(user.id, candidates, set_id=set_id, op=op))
    await db.commit()
    return sid


async def _interaction(db, user, set_id, *, op=OP):
    """The interaction a producer would persist: ONE field, its options
    generated from the reopened universe with the three ids written together."""
    from skills.nutrition.product_variant_clarification import options_for, reopen
    universe = await reopen(db, operation_id=op, user_id=user.id,
                            candidate_set_id=set_id)
    field_id = f"{op}:{EVENT}:product_variant:0"
    options = options_for(universe, event_id=EVENT, field_id=field_id)
    field = UnresolvedField(operation_id=op, revision=0, event_id=EVENT,
                            attribute=ClarificationAttribute.PRODUCT_VARIANT,
                            response_type=ResponseType.SINGLE_SELECT,
                            options=options)
    assert field.field_id == field_id
    return ClarificationInteraction(
        interaction_id=f"ix:{op}", operation_id=op, revision=0,
        groups=(ClarificationGroup(event_id=EVENT, label="Protein bar",
                                   fields=(field,)),)), options


def _tap(interaction, option):
    """The tap, through the REAL answer path: ids in, STORED patch out."""
    from core.clarification_answer import Outcome, answer_from_chip
    answer = answer_from_chip(interaction, field_id=option.field_id,
                              option_id=option.option_id, revision=0)
    assert answer.outcome is Outcome.APPLIED, answer
    return answer.patch


async def _snapshot_of_row(db, row_id):
    """Core-table read: no ORM identity map, no expired-attribute lazy load."""
    from db.models import FoodEntry
    t = FoodEntry.__table__
    return dict((await db.execute(
        select(t).where(t.c.id == row_id))).mappings().one())


async def _correction_events(db, row_id):
    from db.models import LedgerEvent
    return (await db.execute(select(LedgerEvent).where(
        LedgerEvent.entry_id == row_id,
        LedgerEvent.source == CORRECTION_SOURCE))).scalars().all()


# ── THE HAPPY PATH IS THE SNAPSHOT-123 RULE, END TO END ─────────────────────

@pytest.mark.asyncio
async def test_a_tap_on_an_option_from_snapshot_123_prices_123_after_124_exists(
        db, make_user):
    """Option rendered from 123; 124 for the same product appears LATER; the
    user taps -> the row is priced from 123's label and the receipt SAYS 123.
    Never latest_product_evidence() at answer time."""
    user = await make_user()
    row = await _canonical_row(db, user)
    snap123 = await _snap(db, kcal_serving=110)
    set_id = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199",
        product_evidence_id=snap123.id, label="Barebell salty peanut"),),
        set_id=f"cs:c22:{user.id}")
    interaction, options = await _interaction(db, user, set_id)

    snap124 = await _snap(db, rev=2, kcal_serving=150)   # later, hotter label
    assert snap124.id != snap123.id

    patch = _tap(interaction, options[0])
    assert isinstance(patch, SelectProductVariant)
    assert patch.product_evidence_id == snap123.id

    result = await select_product_variant(
        db, user=user, entry_id=row.id, patch=patch, operation_id=OP,
        candidate_set_id=set_id, idempotency=("t_c22_1", "the Barebell one"))
    assert result is not None and result.rung == "product"
    after = await _snapshot_of_row(db, row.id)
    assert after["product_evidence_id"] == snap123.id          # the receipt
    assert after["pricing_rung"] == "product"
    assert after["calories"] == pytest.approx(220.0)           # 2 x 110, NOT 2 x 150
    assert after["quantity"] == "2 bars"                       # omitted -> preserved
    assert after["parsed_food_name"] == "Barebell salty peanut"
    events = await _correction_events(db, row.id)
    assert len(events) == 1

    # exactly once: the same turn again is a replay, not a second write
    again = await select_product_variant(
        db, user=user, entry_id=row.id, patch=patch, operation_id=OP,
        candidate_set_id=set_id, idempotency=("t_c22_1", "the Barebell one"))
    assert again is None
    assert len(await _correction_events(db, row.id)) == 1


# ── THE ADVERSARIAL TWINS *(Danny)* — every one non-mutating ─────────────────

async def _refuses(db, row, exc, **kw):
    row_id = int(row.id)          # captured BEFORE the rollback expires the ORM row
    before = await _snapshot_of_row(db, row_id)
    with pytest.raises(exc):
        await select_product_variant(db, entry_id=row_id, **kw)
    await db.rollback()
    await db.refresh(kw["user"])  # rollback expired the ORM user; reload it
    assert await _snapshot_of_row(db, row_id) == before, "a refusal mutated the row"
    assert await _correction_events(db, row_id) == []


@pytest.mark.asyncio
async def test_a_candidate_from_another_set_is_refused(db, make_user):
    """The tap's patch names an entity that is a member of a DIFFERENT
    persisted universe. Not close enough — a universe is per operation."""
    user = await make_user()
    row = await _canonical_row(db, user)
    a, b = await _snap(db, code="70004199"), await _snap(db, code="70004200")
    set_a = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199", product_evidence_id=a.id),),
        set_id=f"cs:c22a:{user.id}")
    set_b = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004200", product_evidence_id=b.id),),
        set_id=f"cs:c22b:{user.id}", op="op:other")
    _, options_b = await _interaction(db, user, set_b, op="op:other")
    patch_from_b = options_b[0].patch
    await _refuses(db, row, ProductSelectionRefused, user=user,
                   patch=patch_from_b, operation_id=OP, candidate_set_id=set_a)


@pytest.mark.asyncio
async def test_another_operation_or_another_user_is_refused(db, make_user):
    owner, other = await make_user("c22-owner"), await make_user("c22-other")
    row = await _canonical_row(db, owner)
    snap = await _snap(db)
    set_id = await _persist(db, owner, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199", product_evidence_id=snap.id),),
        set_id=f"cs:c22:{owner.id}")
    _, options = await _interaction(db, owner, set_id)
    patch = options[0].patch
    # another operation
    await _refuses(db, row, ProductSelectionRefused, user=owner, patch=patch,
                   operation_id="op:NOT_THIS", candidate_set_id=set_id)
    # another user (their own row, the owner's universe)
    await db.refresh(other)                       # expired by the rollback above
    other_row = await _canonical_row(db, other, name="Other bar")
    await _refuses(db, other_row, ProductSelectionRefused, user=other,
                   patch=patch, operation_id=OP, candidate_set_id=set_id)


@pytest.mark.asyncio
async def test_patch_says_123_but_the_candidate_says_124_is_refused(
        db, make_user):
    """The option and its candidate DISAGREE about which observation was
    offered. Neither is trusted; the tap is refused."""
    user = await make_user()
    row = await _canonical_row(db, user)
    s123, s124 = await _snap(db, rev=1), await _snap(db, rev=2)
    set_id = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199", product_evidence_id=s124.id),),
        set_id=f"cs:c22:{user.id}")
    lying = SelectProductVariant(event_id=EVENT,
                                 field_id=f"{OP}:{EVENT}:product_variant:0",
                                 provenance=Provenance.USER_SELECTED,
                                 entity_id="off:70004199",
                                 product_evidence_id=s123.id)
    await _refuses(db, row, ProductSelectionRefused, user=user, patch=lying,
                   operation_id=OP, candidate_set_id=set_id)


@pytest.mark.asyncio
async def test_a_v1_patch_with_evidence_0_is_unbound_and_refused(db, make_user):
    """⛔⛔ NON-NEGOTIABLE 1. A SelectProductVariant whose payload carries no
    product_evidence_id parses as 0 = UNBOUND. It is refused from bound
    pricing — never "weakly bound" to the newest snapshot for the entity, even
    when exactly one such snapshot exists and would have priced."""
    from core.semantics import patch_from_payload
    from skills.nutrition.product_variant_clarification import UnboundSelection
    user = await make_user()
    row = await _canonical_row(db, user)
    snap = await _snap(db)
    set_id = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199", product_evidence_id=snap.id),),
        set_id=f"cs:c22:{user.id}")
    v1_payload = {"patch_type": "select_product_variant", "schema_version": 1,
                  "event_id": EVENT, "field_id": f"{OP}:{EVENT}:product_variant:0",
                  "provenance": "user_selected",
                  "entity_id": "off:70004199", "serving_id": ""}   # no evidence id
    v1 = patch_from_payload(v1_payload)
    assert isinstance(v1, SelectProductVariant) and v1.product_evidence_id == 0
    with pytest.raises(UnboundSelection):
        from skills.nutrition.product_variant_clarification import (
            reopen, verify_selection)
        universe = await reopen(db, operation_id=OP, user_id=user.id,
                                candidate_set_id=set_id)
        await verify_selection(db, patch=v1, universe=universe)
    await _refuses(db, row, ProductSelectionRefused, user=user, patch=v1,
                   operation_id=OP, candidate_set_id=set_id)


def test_bound_pricing_with_no_snapshot_refuses_instead_of_falling_through():
    """The pricer half of non-negotiable 1: `bound=True` with product=None is
    a refusal even when memory/artifact/estimate COULD have priced."""
    from core.canonical_pricing import (EstimateEvidence, MemoryEvidence,
                                        PricingRefused, price)
    from skills.nutrition.canonical_adapter import to_canonical
    from skills.nutrition.normalize import normalize_quantity
    memory = MemoryEvidence(per100g={"calories": 400, "protein": 30,
                                     "carbs": 30, "fat": 15}, source_id="ufm:1")
    estimate = EstimateEvidence(calories=200, protein=10, carbs=5, fat=8)
    consumed = normalize_quantity("100 g", "Protein bar")
    # unbound: memory prices it
    assert price(entity="Protein bar", consumed=consumed, memory=memory,
                 estimate=estimate).rung.value == "memory"
    # bound with nothing bound: refuse; the ladder is not consulted
    with pytest.raises(PricingRefused, match="no product evidence"):
        price(entity="Protein bar", consumed=consumed, memory=memory,
              estimate=estimate, bound=True)


@pytest.mark.asyncio
async def test_memory_that_disagrees_is_never_consulted(db, make_user, monkeypatch):
    """⛔⛔ MEMORY DISAGREES -> NEVER CONSULTED. Not "outranked": NEVER READ.
    A memory row for the very same identity, with absurd numbers, exists; the
    bound repair prices from the snapshot, and `_memory` is proven not to have
    been called at all."""
    from core import canonical_pricing_inputs as inputs
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    user = await make_user()
    # 110 g, not "2 bars": memory is per-100 g and MUST be able to price this
    # quantity for the proof to mean anything (with "2 bars" memory cannot
    # scale, and the ladder would reach PRODUCT even unbound — vacuous).
    row = await _canonical_row(db, user, quantity="110 g")
    snap = await _snap(db, kcal_serving=110)
    # per-test label: the memory rung QUARANTINES a surface key bound to
    # disagreeing source records fleet-wide (the banana rule), and these tests
    # share one session — a reused label would make memory abstain and this
    # proof vacuous. Verified: with `bound` mutated off, this test goes RED.
    label = f"Barebell salty peanut u{user.id}"
    db.add(trusted(db, UserFoodMatch(user_id=user.id, name_norm=memory_key(label, ""),
                         display_name=label, cal_100=9000, protein_100=1,
                         carbs_100=1, fat_100=1, fdc_id="900001",
                         confidence="exact")))
    await db.commit()
    set_id = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199", product_evidence_id=snap.id,
        label=label),), set_id=f"cs:c22:{user.id}")
    interaction, options = await _interaction(db, user, set_id)

    calls = []
    real = inputs._memory
    async def spy(*a, **k):
        calls.append(a)
        return await real(*a, **k)
    monkeypatch.setattr(inputs, "_memory", spy)

    result = await select_product_variant(
        db, user=user, entry_id=row.id, patch=_tap(interaction, options[0]),
        operation_id=OP, candidate_set_id=set_id)
    assert result.rung == "product"
    after = await _snapshot_of_row(db, row.id)
    assert after["calories"] == pytest.approx(220.0)      # 200/100 g x 110 g, not 9900
    assert after["pricing_rung"] == "product"
    assert calls == [], "a bound repair READ memory — the constraint is not mechanical"


@pytest.mark.asyncio
async def test_a_bound_product_that_cannot_scale_refuses_with_no_fallback(
        db, make_user):
    """The bar's label is per-100 g and per-bar; "2 pieces" has no mass and is
    not the label's unit. Bound: REFUSE — no fallback, no
    silently-repriced-from-elsewhere row. (Not "2 cups": the vessel heuristic
    invents 260 g from the word "peanut" and the product rung scales it —
    a P17 heuristic-authority question, flagged on the board, not this proof.)"""
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    user = await make_user()
    row = await _canonical_row(db, user, quantity="2 pieces")
    snap = await _snap(db)
    # per-test label: the memory rung QUARANTINES a surface key bound to
    # disagreeing source records fleet-wide (the banana rule), and these tests
    # share one session — a reused label would make memory abstain and this
    # proof vacuous. Verified: with `bound` mutated off, this test goes RED.
    label = f"Barebell salty peanut u{user.id}"
    db.add(trusted(db, UserFoodMatch(user_id=user.id, name_norm=memory_key(label, ""),
                         display_name=label, cal_100=400, protein_100=30,
                         carbs_100=30, fat_100=15, fdc_id="900002",
                         confidence="exact")))
    await db.commit()
    set_id = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199", product_evidence_id=snap.id,
        label=label),), set_id=f"cs:c22:{user.id}")
    interaction, options = await _interaction(db, user, set_id)
    patch = _tap(interaction, options[0])
    await _refuses(db, row, CorrectionRefused, user=user, patch=patch,
                   operation_id=OP, candidate_set_id=set_id)
    # and the SAME identity, UNBOUND (no snapshot named), does price from
    # memory — which is exactly why "bound" must be a constraint, not a rank.
    from core.canonical_correction import correct_identity
    await db.refresh(row)
    unbound = await correct_identity(db, user=user, entry_id=row.id,
                                     new_identity=label,
                                     new_quantity_text="100 g")
    assert unbound.rung == "memory"


@pytest.mark.asyncio
async def test_a_snapshot_binding_on_correct_identity_is_bound_by_itself(
        db, make_user):
    """The primitive, not just the tap: correct_identity(product_evidence_id=
    X) with a memory row for the same name prices from X. Before c2.2 the
    ladder ran MEMORY first and the explicit binding lost."""
    from core.canonical_correction import correct_identity
    from core.food_intelligence import memory_key
    from db.models import UserFoodMatch
    user = await make_user()
    row = await _canonical_row(db, user, quantity="110 g")   # memory CAN price this
    snap = await _snap(db, kcal_serving=110)
    # per-test label: the memory rung QUARANTINES a surface key bound to
    # disagreeing source records fleet-wide (the banana rule), and these tests
    # share one session — a reused label would make memory abstain and this
    # proof vacuous. Verified: with `bound` mutated off, this test goes RED.
    label = f"Barebell salty peanut u{user.id}"
    db.add(trusted(db, UserFoodMatch(user_id=user.id, name_norm=memory_key(label, ""),
                         display_name=label, cal_100=9000, protein_100=1,
                         carbs_100=1, fat_100=1, fdc_id="900003",
                         confidence="exact")))
    await db.commit()
    result = await correct_identity(db, user=user, entry_id=row.id,
                                    new_identity=label,
                                    product_evidence_id=snap.id)
    assert result.rung == "product"
    after = await _snapshot_of_row(db, row.id)
    assert after["calories"] == pytest.approx(220.0)
    assert after["product_evidence_id"] == snap.id


@pytest.mark.asyncio
async def test_an_unlabeled_candidate_cannot_rename_the_row_by_omission(
        db, make_user):
    """A candidate with no label would leave parsed_food_name PRESERVED while
    the receipt says off:<code> — one row, two foods. Refused, non-mutating."""
    user = await make_user()
    row = await _canonical_row(db, user)
    snap = await _snap(db)
    set_id = await _persist(db, user, (ExactProductCandidate(
        candidate_id="c1", entity_id="off:70004199", product_evidence_id=snap.id),),
        set_id=f"cs:c22:{user.id}")
    interaction, options = await _interaction(db, user, set_id)
    patch = _tap(interaction, options[0])
    await _refuses(db, row, ProductSelectionRefused, user=user, patch=patch,
                   operation_id=OP, candidate_set_id=set_id)
