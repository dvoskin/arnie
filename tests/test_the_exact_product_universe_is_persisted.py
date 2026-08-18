"""⭐ B-1.8c2.1 — PRODUCT_VARIANT WAS NOT MISSING A PARSER. IT WAS MISSING A
PERSISTED EXACT CANDIDATE UNIVERSE.

The candidate machinery — revision-pinned, tap-traceable, option_id ->
candidate_id -> candidate_set_id -> the exact revision shown — existed for ONE
kind: QuantityCandidate. This file proves the discriminated model (guardrail
1: never list[Any], never a mixed set), the exact candidate's binding to a
persisted snapshot, the registry, and Danny's snapshot-123 rule: an option
rendered from snapshot 123 settles snapshot 123 even after 124 exists.
"""
from __future__ import annotations

import pytest

from core.semantics import (CANDIDATE_KINDS, CandidateSet, EvidenceContext,
                            ExactProductCandidate, QuantityCandidate,
                            SelectProductVariant, patch_from_payload)


def _universe(user_id, candidates, kind="product", set_id=None):
    # set ids are per-user: the shared in-memory session outlives one test, and
    # the repository is (correctly) user-scoped on load.
    set_id = set_id or f"cs:prod:{user_id}"
    return CandidateSet(
        candidate_set_id=set_id, operation_id="op:1", user_id=user_id,
        context=EvidenceContext(user_id=user_id, canonical_entity_id="",
                                product_variant_id=None),
        interaction_revision=0, field_id="product_variant",
        generator_version="product_variant_reopen_v1",
        generation_input_fingerprint="fp", candidates=candidates,
        candidate_kind=kind)


# ── GUARDRAIL 1: DISCRIMINATED, NEVER MIXED, NEVER ANY ──────────────────────

def test_the_universe_declares_one_kind_and_refuses_the_other():
    prod = ExactProductCandidate(candidate_id="c1", entity_id="off:70004199",
                                 product_evidence_id=5)
    assert _universe(1, (prod,)).candidate_kind == "product"
    with pytest.raises(ValueError):          # a product candidate in a quantity set
        _universe(1, (prod,), kind="quantity")
    with pytest.raises(ValueError):          # an unknown kind
        _universe(1, (prod,), kind="fuzzy")
    assert sorted(CANDIDATE_KINDS) == ["product", "quantity"]


def test_a_search_result_cannot_enter_the_exact_universe():
    """⛔ No snapshot, no candidate. A ProductCandidate-shaped thing with
    scores and a match grade but no persisted observation is a SEARCH RESULT,
    and search results may not become PRODUCT — refused at construction."""
    with pytest.raises(ValueError, match="search result"):
        ExactProductCandidate(candidate_id="c1", entity_id="off:70004199",
                              product_evidence_id=0)


def test_the_three_ids_travel_together_on_the_patch():
    """entity_id = WHAT · product_evidence_id = WHICH observation · serving_id
    = which serving. Written together, round-tripped together."""
    from core.semantics import Provenance
    p = SelectProductVariant(event_id="e", field_id="product_variant",
                             provenance=Provenance.USER_SELECTED,
                             entity_id="off:70004199", serving_id="bar",
                             product_evidence_id=123)
    back = patch_from_payload(p.to_payload())
    assert (back.entity_id, back.product_evidence_id, back.serving_id) == \
        ("off:70004199", 123, "bar")


def test_product_variant_is_registered_beside_quantity_and_preparation():
    """Through the real bootstrap (`_ensure_installed`), not a bare
    register_all() — the registry refuses double registration, correctly."""
    from core.semantic_fields import Pricing, registered
    from core.semantics import ClarificationAttribute
    specs = registered()
    spec = specs.get(ClarificationAttribute.PRODUCT_VARIANT) or specs.get("product_variant")
    assert spec is not None, sorted(str(getattr(k, "value", k)) for k in specs)
    assert spec.pricing is Pricing.IDENTITY
    assert spec.patch_type == "select_product_variant"
    # ⛔ NO static vocabulary — its answers are the persisted universe.
    assert spec.vocabulary == ()
    assert spec.supported_vocabulary is not None


# ── THE PRODUCER REOPENS; IT NEVER ASSEMBLES ────────────────────────────────

@pytest.mark.asyncio
async def test_the_universe_persists_and_reopens_by_kind(db, make_user):
    """Through the REAL repository, on the columns that already existed
    (candidate_kind had default 'quantity' all along)."""
    from core import candidate_repository as repo
    from skills.nutrition.product_variant_clarification import reopen

    user = await make_user()
    cands = (ExactProductCandidate(candidate_id="c1", entity_id="off:70004199",
                                   product_evidence_id=5, label="Salty Peanut"),
             ExactProductCandidate(candidate_id="c2", entity_id="off:70004200",
                                   product_evidence_id=6, label="Cookies & Cream"))
    set_id = await repo.ensure_candidate_set(db, _universe(user.id, cands))
    await db.commit()

    back = await reopen(db, operation_id="op:1", user_id=user.id,
                        candidate_set_id=set_id)
    assert back.candidate_kind == "product"
    assert [c.product_evidence_id for c in back.candidates] == [5, 6]
    assert all(isinstance(c, ExactProductCandidate) for c in back.candidates)


@pytest.mark.asyncio
async def test_no_persisted_universe_means_refuse_not_synthesize(db, make_user):
    """⛔⛔ THE ANSWER TO "WHERE DID THIS EXACT SET COME FROM" IS EITHER A
    PERSISTED SET ID OR A REFUSAL. No candidate_set_id -> NoExactUniverse. A
    quantity set under the same operation -> refused, not coerced."""
    from core import candidate_repository as repo
    from skills.nutrition.product_variant_clarification import (NoExactUniverse,
                                                                reopen)
    user = await make_user()
    with pytest.raises(NoExactUniverse):
        await reopen(db, operation_id="op:none", user_id=user.id)


@pytest.mark.asyncio
async def test_a_stale_option_settles_the_snapshot_it_was_rendered_from(db, make_user):
    """⛔⛔ THE SNAPSHOT-123 RULE. Option rendered from snapshot 123; snapshot
    124 for the same product inserted LATER; the user taps the old option ->
    the stored patch binds 123. Never latest_product_evidence() at answer time
    — that would settle evidence the user never saw."""
    from core import candidate_repository as repo
    from skills.nutrition.product_store import append_product_evidence
    from skills.nutrition.product_variant_clarification import options_for, reopen

    user = await make_user()
    record = {"code": "70004199", "product_name": "Barebell", "serving_size": "55.0g",
              "serving_quantity": 55, "serving_quantity_unit": "g", "rev": 1,
              "last_modified_t": 1, "nutrition_data_per": "100g",
              "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                             "carbohydrates_100g": 18, "fat_100g": 7.3,
                             "energy-kcal_serving": 110, "proteins_serving": 11,
                             "carbohydrates_serving": 9.9, "fat_serving": 4}}
    snap123 = await append_product_evidence(db, record=record, serving_unit="bar")
    cand = ExactProductCandidate(candidate_id="c1", entity_id="off:70004199",
                                 product_evidence_id=snap123.id, label="Salty Peanut")
    set_id = await repo.ensure_candidate_set(db, _universe(user.id, (cand,)))
    await db.commit()
    universe = await reopen(db, operation_id="op:1", user_id=user.id, candidate_set_id=set_id)
    option = options_for(universe, event_id="ev:bar", field_id="product_variant")[0]

    # LATER: the provider edits the record; a NEW snapshot 124 exists.
    edited = dict(record, rev=2)
    edited["nutriments"] = dict(record["nutriments"], **{"energy-kcal_serving": 115})
    snap124 = await append_product_evidence(db, record=edited, serving_unit="bar")
    assert snap124.id != snap123.id

    # The user taps the OLD option. Its stored patch binds 123.
    assert option.patch.product_evidence_id == snap123.id
    assert option.candidate_id == "c1" and option.candidate_set_id == set_id
    # And re-hydrating through the repository yields the same binding.
    again = await reopen(db, operation_id="op:1", user_id=user.id, candidate_set_id=set_id)
    assert again.candidates[0].product_evidence_id == snap123.id


# ── THE HARD FAILURES *(Danny)*: refuse, never coerce, never trust ──────────

async def _snap(db, code="70004199", rev=1, kcal=110):
    from skills.nutrition.product_store import append_product_evidence
    return await append_product_evidence(db, record={
        "code": code, "product_name": "x", "serving_size": "55.0g",
        "serving_quantity": 55, "serving_quantity_unit": "g", "rev": rev,
        "last_modified_t": rev, "nutrition_data_per": "100g",
        "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 20,
                       "carbohydrates_100g": 18, "fat_100g": 7.3,
                       "energy-kcal_serving": kcal, "proteins_serving": 11,
                       "carbohydrates_serving": 9.9, "fat_serving": 4}},
        serving_unit="bar")


@pytest.mark.asyncio
async def test_wrong_user_and_wrong_operation_refuse(db, make_user):
    from core import candidate_repository as repo
    from skills.nutrition.product_variant_clarification import (NoExactUniverse,
                                                                reopen)
    owner, other = await make_user("u-owner"), await make_user("u-other")
    snap = await _snap(db)
    cand = ExactProductCandidate(candidate_id="c1", entity_id="off:70004199",
                                 product_evidence_id=snap.id)
    set_id = await repo.ensure_candidate_set(db, _universe(owner.id, (cand,)))
    await db.commit()
    with pytest.raises(NoExactUniverse):                       # wrong user
        await reopen(db, operation_id="op:1", user_id=other.id,
                     candidate_set_id=set_id)
    with pytest.raises(NoExactUniverse, match="not transferable"):  # wrong op
        await reopen(db, operation_id="op:OTHER", user_id=owner.id,
                     candidate_set_id=set_id)


@pytest.mark.asyncio
async def test_a_quantity_universe_is_refused_not_coerced(db, make_user):
    """A quantity set persisted under this operation is NOT this field's
    universe. Refused, never coerced."""
    from core import candidate_repository as repo
    from db.models import CandidateSetRow
    from skills.nutrition.product_variant_clarification import (NoExactUniverse,
                                                                reopen)
    user = await make_user()
    # write a quantity-kind set directly (its rows say kind=quantity)
    db.add(CandidateSetRow(candidate_set_id=f"cs:q:{user.id}", domain="food",
                           operation_id="op:1", user_id=user.id,
                           interaction_revision=0, field_id="quantity",
                           subject_entity_id="egg", generator_version="v",
                           generation_input_fingerprint="fp", rejections=[]))
    await db.commit()
    # An EMPTY set of declared kind quantity: nothing to hydrate, and the
    # discriminator (from the rows, default "quantity") is what reopen judges.
    with pytest.raises(NoExactUniverse, match="not a product universe"):
        await reopen(db, operation_id="op:1", user_id=user.id,
                     candidate_set_id=f"cs:q:{user.id}")


@pytest.mark.asyncio
async def test_a_candidate_whose_snapshot_disagrees_is_refused(db, make_user):
    """⛔⛔ VERIFY, DON'T TRUST — the load-bearing check. Generation writes
    entity_id and product_evidence_id together, but persisted data can be
    corrupt. A candidate claiming off:70004199 whose snapshot is actually about
    off:0049000042566 must be REFUSED before anything prices from it."""
    from skills.nutrition.product_variant_clarification import (
        NoExactUniverse, verify_candidate_binding)
    user = await make_user()
    right = await _snap(db, code="70004199")
    wrong = await _snap(db, code="0049000042566")
    ok = ExactProductCandidate(candidate_id="c1", entity_id="off:70004199",
                               product_evidence_id=right.id)
    await verify_candidate_binding(db, ok)                        # passes
    lying = ExactProductCandidate(candidate_id="c2", entity_id="off:70004199",
                                  product_evidence_id=wrong.id)
    with pytest.raises(NoExactUniverse, match="disagree"):
        await verify_candidate_binding(db, lying)
    gone = ExactProductCandidate(candidate_id="c3", entity_id="off:70004199",
                                 product_evidence_id=999999)
    with pytest.raises(NoExactUniverse, match="does not exist"):
        await verify_candidate_binding(db, gone)


def test_zero_form_equivalence_is_honoured_by_the_binding_check():
    """OFF canonicalizes leading zeros (P17d.0 probe); a candidate saying
    off:0049000042566 against a snapshot stored as 49000042566 is the SAME
    product — verified through canonical_code, not string equality."""
    from skills.nutrition.product_store import canonical_code
    assert canonical_code("0049000042566") == canonical_code("49000042566")
