"""⛔⛔⛔ CF25 — A SNACK PRODUCT PRICED A PLAIN COOKED FOOD, IN PRODUCTION.

2026-08-25, entry 3050: `Shrimp, grilled` @ 120 g committed **525 kcal** —
437.5 per 100g against a truth of ~99. The macros reconstructed perfectly
(`4·10.6 + 4·76.6 + 9·19.4 = 523 ≈ 525`) and 76.6 g of carbs on shrimp is not
a scaled shrimp, it is a DIFFERENT FOOD. USDA `173160`, `Snacks, shrimp
cracker`, is 426 kcal/100g at P7.14 C59.1 F17.9.

⭐⭐⭐ WRONG IDENTITY, RIGHT SOURCE. The candidate was real, the arithmetic
coherent, the binding wrong. So the repair belongs at the IDENTITY boundary
and nowhere else:

    ⛔ no calorie thresholds
    ⛔ no macro sanity checks
    ⛔ no shrimp-specific exception

⭐⭐ AND THE SEAM ALREADY EXISTED. `qualify_usda_rows` filters the USDA lane in
`_enrich`; the OFF lane one function below it called `_off_mod.search()` and
returned the product with NO qualification at all — straight to `branded_exact`
authority. `from_off` was written for exactly this and had no production
caller; its own docstring says `_match` "said 'exact' about a pizza".

A boundary the live path can walk around is not a boundary.
"""
from __future__ import annotations

import pytest

#: The shape OFF returned. `_match` is the provider's own confidence — trusted
#: for nothing, which is the point.
SHRIMP_CRACKER = {
    "code": "shrimpcracker001", "name": "Shrimp Crackers", "brand": "SnackCo",
    "_match": "exact",
    "per100g": {"calories": 437.5, "protein": 8.8, "carbs": 63.8, "fat": 16.2},
}
#: A real branded product for a genuinely branded query.
PROTEIN_BAR = {
    "code": "bar001", "name": "Barebells Caramel Cashew", "brand": "Barebells",
    "_match": "exact",
    "per100g": {"calories": 385.0, "protein": 32.0, "carbs": 35.0, "fat": 14.0},
}
#: ⭐ CORRECT AND VERY HIGH. If anything in the repair reasons about calorie
#: magnitude, this row is the one it wrongly refuses.
OLIVE_OIL = {
    "code": "oil001", "name": "Extra Virgin Olive Oil", "brand": "Filippo",
    "_match": "exact",
    "per100g": {"calories": 800.0, "protein": 0.0, "carbs": 0.0, "fat": 91.0},
}


def _resolver(verdict: str, confidence: float = 0.95):
    """A stand-in semantic resolver returning one verdict for every record."""
    async def _complete(_prompt: str) -> str:
        import json
        # a BARE ARRAY — `core.semantic_evidence` asks for
        # `[{"evidence_id": ..., "relationship": ..., "confidence": ...}]`.
        return json.dumps([
            {"evidence_id": f"off:{code}", "relationship": verdict,
             "confidence": confidence, "reasoning": "test"}
            for code in ("shrimpcracker001", "bar001", "oil001")])
    return _complete


@pytest.mark.asyncio
async def test_a_shrimp_cracker_cannot_price_grilled_shrimp():
    """⛔⛔⛔ ENTRY 3050, PREVENTED. The exact row, the exact query."""
    from skills.nutrition.evidence_qualification import qualify_off_product

    q = await qualify_off_product("Shrimp, grilled", SHRIMP_CRACKER,
                                  complete=_resolver("DIFFERENT_IDENTITY"))
    assert q.rows == (), (
        "a shrimp CRACKER was admitted as authority for plain grilled shrimp "
        f"— this is entry 3050 again: {q.rows!r}")
    # ⛔ AND FOR THE RIGHT REASON. An outage refuses everything too, so
    # `rows == ()` alone would pass against a resolver that never answered —
    # which is exactly how the first draft of this test passed.
    assert q.disposition == "qualified", (
        f"refused, but as an outage rather than on identity: {q.disposition!r}")
    assert q.kept_count == 0 and q.raw_count == 1


@pytest.mark.asyncio
async def test_a_matching_product_is_still_admitted():
    """⭐ THE NEGATIVE INVARIANT. Fail-closed must not mean fail-always, or the
    branded lane is simply deleted and every packaged food loses its label."""
    from skills.nutrition.evidence_qualification import qualify_off_product

    q = await qualify_off_product("Barebells caramel cashew", PROTEIN_BAR,
                                  complete=_resolver("SAME_IDENTITY"))
    assert len(q.rows) == 1 and q.rows[0]["code"] == "bar001", (
        "a genuine branded match for a branded query was refused — the repair "
        "removed the lane instead of qualifying it")


@pytest.mark.asyncio
async def test_a_correct_but_very_high_calorie_product_is_admitted():
    """⛔⛔ NO CALORIE THRESHOLD, NO MACRO SANITY CHECK. Olive oil at 800
    kcal/100g is CORRECT. A plausibility band would refuse it while still
    admitting the shrimp cracker at 437.5, which sits comfortably inside any
    band anyone would draw. Magnitude was never the signal — identity was."""
    from skills.nutrition.evidence_qualification import qualify_off_product

    q = await qualify_off_product("olive oil", OLIVE_OIL,
                                  complete=_resolver("SAME_IDENTITY"))
    assert len(q.rows) == 1, (
        "a correct 800 kcal/100g product was refused — something in the "
        "repair is reasoning about calorie magnitude instead of identity")


@pytest.mark.asyncio
async def test_a_low_confidence_identity_is_refused():
    """⛔ THE THRESHOLD IS THE SAME ONE THE USDA LANE USES. The papaya defect
    reproduced at 0.95 on one model and 0.75 on another; precision over recall
    is the settled trade."""
    from skills.nutrition.evidence_qualification import qualify_off_product

    q = await qualify_off_product("Shrimp, grilled", SHRIMP_CRACKER,
                                  complete=_resolver("SAME_IDENTITY", 0.4))
    assert q.rows == (), "an unconfident identity claim was treated as one"
    assert q.disposition == "qualified", q.disposition


@pytest.mark.asyncio
async def test_the_resolver_being_down_admits_nothing():
    """⛔⛔ SEMANTIC_RESOLVER_DOWN != RAW_EVIDENCE_AUTHORIZED. Branded evidence
    is here BECAUSE it needs qualification; the qualifier's absence cannot
    hand it authority. Same contract as `qualify_usda_rows`."""
    from skills.nutrition.evidence_qualification import qualify_off_product

    async def _down(_prompt: str) -> str:
        raise RuntimeError("resolver unavailable")

    q = await qualify_off_product("Shrimp, grilled", SHRIMP_CRACKER,
                                  complete=_down)
    assert q.rows == ()
    assert "resolver_down" in q.disposition, q.disposition


@pytest.mark.asyncio
async def test_a_resolver_EXCEPTION_also_admits_nothing(monkeypatch):
    """⛔⛔ THE OTHER FAIL-CLOSED PATH, AND MUTATION X4 IS WHY IT EXISTS.

    `test_the_resolver_being_down_admits_nothing` raises inside `complete`,
    but `resolve()` catches that and returns ABSTENTIONS — so it exercises the
    all-abstain branch and leaves the `except` branch unobserved. Mutation X4
    made that branch return the raw products and every test stayed GREEN.

    Two branches, both of which must fail closed, and only one of them was
    being watched."""
    import skills.nutrition.evidence_qualification as EQ

    async def _explode(*_a, **_k):
        raise RuntimeError("resolver blew up below the abstention layer")

    monkeypatch.setattr(EQ, "resolve", _explode)
    q = await EQ.qualify_off_product("Shrimp, grilled", SHRIMP_CRACKER)

    assert q.rows == (), (
        "a resolver EXCEPTION handed the raw branded product authority — "
        "SEMANTIC_RESOLVER_DOWN is not RAW_EVIDENCE_AUTHORIZED")
    assert q.disposition == "resolver_down_no_candidates", q.disposition


@pytest.mark.asyncio
async def test_the_OFF_LANE_ITSELF_qualifies_before_returning(monkeypatch):
    """⛔⛔⛔ THE WIRE, AND IT IS THE HALF THAT WAS MISSING.

    `from_off` and the whole semantic layer already existed and had NO
    production caller. Proving `qualify_off_product` in isolation would repeat
    that exact mistake, so this drives `_enrich`'s OFF lane and asserts the
    branded candidate never comes back when identity is refused."""
    import handlers.tool_executor as TE

    # ⛔⛔ THE SUITE HALTS THIS BOUNDARY BY DEFAULT.
    # `tests/conftest.py` sets `EVIDENCE_QUALIFICATION_HALT=1`, so every test
    # runs with semantic qualification switched OFF — including the USDA half
    # that has been shipped since B-1.5E. A test that forgets this asserts
    # against a lane whose guard is not running, which is how the first draft
    # of THIS test "proved" the wire while the kill switch was doing the
    # deciding. Production has the halt off; the turn that committed entry
    # 3050 logged a real `pricing.qualification` stage.
    monkeypatch.delenv("EVIDENCE_QUALIFICATION_HALT", raising=False)

    async def _fake_off_search(name, page_size=8):
        return dict(SHRIMP_CRACKER)

    async def _no_usda(*_a, **_k):
        return []

    async def _refuse(_food_name, best, variants=(), complete=None,
                      context=None):
        from skills.nutrition.evidence_qualification import Qualification
        return Qualification(rows=(), disposition="different_identity",
                             raw_count=1, kept_count=0)

    import api.usda as USDA
    import skills.nutrition.evidence_qualification as EQ
    import skills.nutrition.off as OFF
    orig_search, orig_qual, orig_usda = (OFF.search, EQ.qualify_off_product,
                                         USDA.search_food)
    OFF.search, EQ.qualify_off_product = _fake_off_search, _refuse
    USDA.search_food = _no_usda
    try:
        _usda, off = await TE._fetch_usda_off_uncached("Shrimp, grilled",
                                                       is_packaged=True)
    finally:
        OFF.search, EQ.qualify_off_product = orig_search, orig_qual
        USDA.search_food = orig_usda

    assert off is None, (
        "the OFF lane returned a product the identity boundary refused — the "
        f"qualification is not wired into the live path: {off!r}")


# ══ THE PRODUCING TURN — DELIBERATELY ABSENT ════════════════════════════════
#
# ⛔⛔⛔ A VACUOUS E2E WAS WRITTEN HERE AND REMOVED. It drove `/api/v1/chat`
# with OFF serving the cracker, asserted the committed row was under 300 kcal,
# and PASSED WITH THE ENTIRE BOUNDARY DELETED — because `_looks_branded(
# "Shrimp, grilled")` is False and entry 3050's item carried no
# `is_packaged`, so the OFF lane is never consulted for this food and the row
# was priced from the plan either way.
#
# ⭐⭐⭐ WHICH MEANS THE OFF LANE DID NOT PRODUCE ENTRY 3050. The proofs above
# close a real hole — an unqualified branded lane reaching `branded_exact`
# authority — but they are NOT the repair for the 2026-08-25 incident, and a
# green E2E here would have asserted otherwise.
#
# What produced it: memory row 936, `grilled shrimp`, created 2026-08-02,
# cal_100=437.5, whose per-100g values reproduce the committed row EXACTLY at
# x1.2 (437.5 -> 525.0, 8.8 -> 10.56, 63.8 -> 76.56, 16.2 -> 19.44). That row
# is `TRUSTED=False` under CF24, executed against production. The turn ran on
# build a7549d72fbfb with CF24 live.
#
# The E2E belongs with the repair for THAT path, once the reader which
# bypassed the guard is identified. Writing it against this one would be
# proving the wrong mechanism.
