"""⛔⛔⛔ CF23b — THE PRODUCING TURN, NOT JUST THE NEXT ONE.

The read guard (`memory_nutrition_is_trusted`) rejects a fabricated row when it
is READ BACK. But `_web_lookup_packaged` hands its result to the CURRENT turn:

    return FoodCandidates(usda=usda, off=off, web=web, memory=memory, ...)

So the turn that MINTS the fabrication still prices and commits from it, and
only later turns are protected. A read-only guard is not containment.

THE FABRICATION, verbatim from the "no serving found" branch:

    per100 = {"calories": 200.0,
              "protein": (pro / cal) * 200.0 if cal else None, ...}

Not a measurement — an assumed 200 kcal/100 g density for any packaged food,
with the macros rescaled to that fiction. 163 rows fleet-wide, 154 live to the
legacy pricer, 13 users.

⭐ THE RULE: a missing defensible serving basis yields NO NUTRITION RESULT.
Not a guess with the honest parts kept — the label's numbers are real, but
without a serving MASS they cannot be scaled to an arbitrary quantity, and
"density assumed" is precisely the invented conversion this project refuses
everywhere else.
"""
from __future__ import annotations

import pytest

import handlers.tool_executor as TE


class _Result:
    """⛔ THE SHAPE `_best_matching_snippet` ACTUALLY READS — `.answer` and
    `.results`, ATTRIBUTES not dict keys, and the food's own words must appear
    in the text or the snippet is refused before any parsing happens.

    My first fixture returned a plain dict. Every case then produced None and
    the two containment tests PASSED — for the wrong reason. A guard that
    passes because the harness fed it nothing has proven nothing, which is the
    same silence this repository keeps cataloguing."""
    def __init__(self, text):
        self.answer = text
        self.results = []


def _snippet(text):
    async def _search(_q):
        return _Result(text)
    return _search


@pytest.mark.asyncio
async def test_no_serving_size_means_NO_nutrition_result(monkeypatch):
    """⛔⛔⛔ THE CONTAINMENT PROOF. A label whose serving size cannot be read
    must produce nothing — never a 200 kcal/100 g density."""
    monkeypatch.setattr("core.search.search",
                        _snippet("Quest Chips Sweet Chili nutrition: 140 calories, "
                                 "19 g protein, 5 g carbohydrate, 4 g fat."))
    got = await TE._web_lookup_packaged("Quest Chips Sweet Chili", "1 bag")

    assert got is None, (
        "the web lookup returned a candidate with no defensible serving "
        f"basis: {got!r} — this is the shape that minted 163 fleet rows")


@pytest.mark.asyncio
async def test_the_fabricated_200_density_is_unreachable(monkeypatch):
    """⭐ ASSERTED ON THE VALUE, NOT ONLY ON None. If the branch ever returns
    a candidate again, this says what was wrong with it — a 200.0 that no
    label stated."""
    monkeypatch.setattr("core.search.search",
                        _snippet("Sabra Hummus classic 70 calories 2 g protein "
                                 "4 g carbohydrate 5 g fat"))
    got = await TE._web_lookup_packaged("Sabra Hummus", "2 tbsp")
    if got is not None:
        per100 = got.get("per100g") or {}
        assert per100.get("calories") != 200.0, (
            "the assumed-density branch is reachable again")
        pytest.fail(f"expected no candidate without a serving basis: {got!r}")


@pytest.mark.asyncio
async def test_even_a_perfectly_readable_label_yields_nothing(monkeypatch):
    """⛔⛔ THE CONTROL THAT CANNOT EXIST, AND WHY THAT IS THE POINT.

    An earlier version of this test asserted the opposite — that a stated
    serving size must STILL produce a candidate — as a guard against "fix by
    deleting the feature". That guard was right for the placeholder branch
    alone, and wrong once the second defect class was understood.

    A "correct product still works" control needs a signal that proves the
    page describes the food being logged. This lane has none: no fdc_id, no
    barcode, no structured record, only token overlap. Writing the control
    anyway would assert that snippet ranking works — which is the defect.

    ⭐ SO THE FEATURE IS DISABLED RATHER THAN DEFENDED BY THE MECHANISM THAT
    FAILED, and this test pins that: even a flawless label yields nothing,
    because flawless arithmetic on an unidentified product is what produced
    582 kcal/100 g of milk."""
    monkeypatch.setattr(
        "core.search.search",
        _snippet("Quest Chips label. Serving size 28 g. 140 calories, "
                 "19 g protein, 5 g carbohydrate, 4 g fat."))

    assert await TE._web_lookup_packaged("Quest Chips", "1 bag") is None, (
        "the packaged-web lane returned nutrition while it still cannot name "
        "the product it priced")


# ══════════════════════════════════════════════════════════════════════════
# THE SECOND CLASS — A SUCCESSFUL DENSITY FOR THE WRONG PRODUCT
#
# Removing the "no serving found" branch closes the PLACEHOLDER class. It does
# nothing for this one: a snippet about a DIFFERENT product with a perfectly
# readable serving computes a perfectly correct density — for the wrong food —
# and hands it to the producing turn.
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a_wrong_product_snippet_cannot_price_the_food(monkeypatch):
    """⛔⛔⛔ THIS IS ROW 582, REPRODUCED.

    Production holds `Milk, whole` cached at 582 kcal/100 g — against a true
    61 — carrying `serving_text = "4 pieces (16.7 g)"`. A *pieces* serving on
    a liquid. It got there because `_best_matching_snippet` is pure TOKEN
    OVERLAP: `"Milk, whole"` yields the tokens `milk` and `whole`, and a page
    about WHOLE MILK CHOCOLATE contains both. The serving regex then read
    16.7 g, the arithmetic was flawless, and 97/16.7*100 = 581.

    ⭐ NOTHING IN THIS PATH BINDS IDENTITY. There is no fdc_id, no barcode, no
    structured record — only how many of the food's words appear in some
    prose. Snippet ranking is not an identity binding, and a density computed
    from the wrong label is wrong however correct its arithmetic."""
    monkeypatch.setattr(
        "core.search.search",
        _snippet("Whole Milk Chocolate pieces. Serving size 16.7 g "
                 "(4 pieces): 97 calories, 1 g protein, 11 g carbohydrate, "
                 "5 g fat."))

    got = await TE._web_lookup_packaged("Milk, whole", "250 ml")

    assert got is None, (
        "a snippet about a different product produced a nutrition candidate "
        f"for 'Milk, whole': {got!r} — this is exactly how the 582 kcal/100g "
        "row was created")


@pytest.mark.asyncio
async def test_no_packaged_web_candidate_survives_without_identity_binding(
        monkeypatch):
    """⛔ AND THE GENERAL FORM. Since no signal in this path can bind identity,
    the honest containment is that the path yields no nutrition at all — not
    that it yields nutrition when the ranking happens to be right.

    ⚠ THE CONTROL THIS TEST DOES NOT HAVE. A 'correct product still works'
    case would need a real identity-binding signal to be meaningful, and there
    is none here — asserting it against snippet ranking would be asserting the
    defect. The feature is disabled rather than defended by the mechanism that
    failed."""
    monkeypatch.setattr(
        "core.search.search",
        _snippet("Quest Chips label. Serving size 28 g. 140 calories, "
                 "19 g protein, 5 g carbohydrate, 4 g fat."))
    assert await TE._web_lookup_packaged("Quest Chips", "1 bag") is None


# ══════════════════════════════════════════════════════════════════════════
# THE SAME DEFECT IN THE MEAL LANE
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_the_meal_lane_can_price_the_wrong_meal(monkeypatch):
    """⛔⛔⛔ SAME BINDING FAILURE, DIFFERENT LANE.

    `_web_lookup_meal_inner` selects its text with the SAME token-overlap
    snippet picker, then asks a model to read the numbers. The prompt does say
    "NOT a different item" and a low confidence is discarded — but that is a
    SECOND OPINION ON UNBOUND TEXT, not an identity binding. A UPC, an FDC id
    or a structured product record binds; a model's self-assessment of prose it
    was handed does not.

    ⭐ AND THE MITIGATION IS THE THING THAT CAN FAIL. Keeping the lane alive
    because the model usually notices is defending a feature with a mechanism
    whose failure is the defect — the same argument that retired the packaged
    lane's snippet ranking."""
    monkeypatch.setattr(
        "core.search.search",
        _snippet("Chicken shawarma platter with rice at Restaurant B: "
                 "1180 calories, 62 g protein, 120 g carbohydrate, 44 g fat."))

    async def _chat(**kw):
        # The model, confident about a page describing a DIFFERENT platter.
        return {"text": '{"calories":1180,"protein":62,"carbs":120,'
                        '"fat":44,"confidence":"high"}'}
    monkeypatch.setattr("core.llm.chat", _chat)

    got = await TE._web_lookup_meal("chicken shawarma platter", "1 platter")

    assert got is None, (
        "the meal lane priced a food from a snippet it cannot prove describes "
        f"that food: {got!r}")


# ══════════════════════════════════════════════════════════════════════════
# THE STRUCTURAL GUARD — SO A FORGOTTEN CALL SITE CANNOT SURVIVE THE REPAIR
# ══════════════════════════════════════════════════════════════════════════

#: Functions permitted to consume `_best_matching_snippet`, and why. A NEW
#: entry is a decision that must be made deliberately: token overlap cannot
#: bind nutrition evidence to a food identity, so anything producing nutrition
#: from it must fail closed until an independent binding exists (UPC, FDC id,
#: or a structured product record).
_SNIPPET_CONSUMERS = {
    # nutrition producers, DISABLED — each returns None before the call
    "_web_lookup_packaged": "disabled: no identity binding",
    "_web_lookup_meal_inner": "disabled: no identity binding",
}


def test_no_nutrition_path_consumes_the_snippet_without_an_identity_binding():
    """⛔⛔⛔ THE RULE, ENFORCED STRUCTURALLY.

    Two lanes produced wrong nutrition from token overlap and both were found
    one at a time — the packaged lane first, the meal lane only because
    somebody looked for the second caller. A third would have survived the
    repair.

    So the call sites are ENUMERATED. Adding one is a deliberate act that
    fails this test until it is classified, and a nutrition producer may only
    be listed once it fails closed."""
    import ast
    import inspect

    import handlers.tool_executor as TE_mod

    tree = ast.parse(inspect.getsource(TE_mod))
    consumers = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", "") == "_best_matching_snippet"):
                consumers[node.name] = node

    unregistered = sorted(set(consumers) - set(_SNIPPET_CONSUMERS))
    assert not unregistered, (
        f"new consumer(s) of _best_matching_snippet: {unregistered}. Token "
        f"overlap cannot bind nutrition to a food identity — classify each: "
        f"an independent binding (UPC/FDC/structured record) may remain, a "
        f"nutrition producer without one must fail closed.")

    # every registered nutrition producer must return None BEFORE the call
    for name, node in consumers.items():
        if "disabled" not in _SNIPPET_CONSUMERS[name]:
            continue
        first_return = next(
            (n for n in node.body if isinstance(n, ast.Return)), None)
        assert first_return is not None and isinstance(
            first_return.value, ast.Constant) and first_return.value.value is None, (
            f"{name} is registered as disabled but does not return None before "
            f"reaching the snippet — the lane is still live")
