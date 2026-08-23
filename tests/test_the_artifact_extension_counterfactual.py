"""⛔⛔⛔ THE AUTHORIZED ARTIFACT-EXTENSION COUNTERFACTUAL.

*(Danny, 2026-08-22)* — a READ-ONLY USDA FDC 15.3 extension over
`NO_LOCAL_EVIDENCE`, using the existing canonical identity, real USDA
candidates, the real ranker, actual sourced portions, the shared selector and
the real `decide()`. Forbidden and absent: translations, restaurant estimates,
recipe decomposition, OFF, aliases, generated evidence.

⭐ **THE MEASUREMENT IS THE DELIVERABLE, SO ITS FAILURE MODES ARE THE PRODUCT.**
"0 recovered" is worth nothing on its own; "0 recovered, and here is which of
six causes stopped each item" is what decides whether a coverage tranche is
worth building. So every bucket is pinned, and a cause that cannot be
distinguished from another is a cause that cannot be acted on.

⛔ NETWORK-FREE HERE. Every provider seam is stubbed: this file proves the
ATTRIBUTION, not USDA's contents.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import measure_settlement_coverage as M  # noqa: E402
from core.general_settlement import ItemFacts  # noqa: E402


def _facts(**kw) -> ItemFacts:
    base = dict(identity="Cucumber", entity="cucumber", preparation="",
                has_identity=True, has_quantity=True, has_mass=False,
                has_memory=False, has_artifact=False,
                selected_rung="", selected_rung_authoritative=False)
    base.update(kw)
    return ItemFacts(**base)


_ROW = {"fdc_id": 168409, "description": "Cucumber, with peel, raw",
        "per100g": {"calories": 15.0, "protein": 0.65, "carbs": 3.63,
                    "fat": 0.11}}


class _Q:
    disposition = "qualified"

    def __init__(self, rows):
        self.rows = tuple(rows)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # ⭐ THE RETRY IS REAL AND MUST NOT BE PAID FOR HERE. Five attempts with a
    # rising backoff is right against a provider that flakes half the time; in
    # a test it is fifteen seconds of sleeping to prove a `raise`. The BEHAVIOUR
    # under test is "a persistent outage reports UNMEASURED", and one attempt
    # proves it exactly as well — the retry COUNT has its own proof below.
    monkeypatch.setattr(M, "_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(M, "_RETRY_BACKOFF", 0)
    monkeypatch.setattr(M, "_PROVIDER_PACE", 0)
    M.EXTENSION_LEDGER.clear()
    M._EXTENSION_CACHE.clear()
    original = M.INTERVENTIONS["NO_LOCAL_EVIDENCE"]
    yield
    M.INTERVENTIONS["NO_LOCAL_EVIDENCE"] = original
    M.EXTENSION_LEDGER.clear()
    M._EXTENSION_CACHE.clear()


def _stub(monkeypatch, *, rows=(_ROW,), qualified=None, portions=(),
          search_raises=False, qualify_raises=False, portions_raises=False):
    import api.usda as USDA
    import skills.nutrition.evidence_qualification as EQ

    async def _search(query, page_size=5, strict=False):
        if search_raises:
            raise RuntimeError("usda down")
        _search.seen.append(query)
        return list(rows)
    _search.seen = []

    async def _qualify(identity, chunk, **kw):
        if qualify_raises:
            raise RuntimeError("resolver down")
        return _Q(chunk if qualified is None else qualified)

    async def _portions(fdc_id, strict=False):
        if portions_raises:
            raise RuntimeError("detail down")
        return [dict(p) for p in portions]

    monkeypatch.setattr(USDA, "search_food", _search)
    monkeypatch.setattr(EQ, "qualify_usda_rows", _qualify)
    monkeypatch.setattr(USDA, "food_portions", _portions)
    return _search


# ── ARMING ────────────────────────────────────────────────────────────────


def test_the_networked_counterfactual_is_OFF_until_armed():
    """⛔⛔ THE ROUTINE INSTRUMENT MUST STAY PURE. Every other intervention is
    deterministic and I/O-free; this one reaches USDA and a resolver. Default-on
    would make the whole ranking depend on two providers being up, and would
    silently change what UNMEASURED means between runs."""
    assert M.INTERVENTIONS["NO_LOCAL_EVIDENCE"] is None
    M.enable_artifact_extension()
    assert M.INTERVENTIONS["NO_LOCAL_EVIDENCE"] is \
        M.artifact_extension_counterfactual


def test_an_unarmed_run_reports_NOTHING_not_an_empty_table():
    """⛔ ZEROS IN EVERY BUCKET WOULD READ AS "tried, recovered nothing".
    `None` says it was not run — the same distinction UNMEASURED draws one
    level up, and the reason that distinction exists at all."""
    assert M._extension_report() is None


# ── THE SIX OUTCOMES ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_recovered_item_is_authoritative_through_the_shared_selector(
        monkeypatch):
    """⭐ THE POSITIVE. A real per-100 g winner plus a stated MASS scales
    through `select_priced_rung` — the function `price()` calls — and the item
    becomes settleable. Nothing here recreates the selector or the predicate."""
    _stub(monkeypatch)
    updated = await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())

    assert updated is not None
    assert updated.selected_rung_authoritative is True
    assert updated.selected_rung == "artifact"
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "RECOVERED"


@pytest.mark.asyncio
async def test_no_usda_match(monkeypatch):
    _stub(monkeypatch, rows=())
    await M.artifact_extension_counterfactual(
        item={"food_name": "Окрошка на айране", "quantity": "300 г"},
        facts=_facts())
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "no USDA match"


@pytest.mark.asyncio
async def test_qualification_keeping_nothing_is_ALSO_no_usda_match(monkeypatch):
    """⭐ A SEARCH HIT THE RESOLVER REJECTED IS NOT EVIDENCE. The artifact
    stores QUALIFIED candidates, so a food whose every hit is judged a
    different identity has no artifact entry — the same end state as no hit at
    all, and honestly the same bucket."""
    _stub(monkeypatch, qualified=())
    await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "no USDA match"


@pytest.mark.asyncio
async def test_no_defensible_winner(monkeypatch):
    """The ranker declines every candidate — `best_candidate` returning None is
    the `ARTIFACT_RANKER_NO_WINNER` state the pricer already names."""
    _stub(monkeypatch, rows=({"fdc_id": 1, "description": "Sausage roll",
                              "per100g": {"calories": 300.0}},))
    await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "no defensible winner"


@pytest.mark.asyncio
async def test_no_nutrition(monkeypatch):
    """⭐ A WINNER WITH NO PER-100 G IS A DIFFERENT REPAIR from no winner at
    all: the ranker did its job and the record is empty. Collapsing the two
    would hide which half of the pipeline to fix."""
    _stub(monkeypatch, rows=({"fdc_id": 168409,
                              "description": "Cucumber, with peel, raw",
                              "per100g": {}},))
    await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "no nutrition"


@pytest.mark.asyncio
async def test_no_required_portion_or_conversion(monkeypatch):
    """⛔⛔ COVERAGE DOES NOT ANSWER A CONVERSION QUESTION. The record prices
    per 100 g and the user counted pieces; with no sourced portion naming that
    unit the resolver falls to a heuristic, which is not canonical authority.
    Extending the artifact would put this food IN the artifact and still not
    settle it — which is exactly the kind of thing a tranche estimate must not
    quietly count as recovered."""
    _stub(monkeypatch)                                   # no portions at all
    updated = await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "2 cucumbers"},
        facts=_facts())
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "no required portion/conversion"
    assert updated is not None and \
        updated.selected_rung_authoritative is False


@pytest.mark.asyncio
async def test_a_sourced_portion_turns_that_count_into_a_recovery(monkeypatch):
    """⭐ THE TWIN THAT MAKES THE BUCKET ABOVE ATTRIBUTABLE. Same food, same
    count, one real `foodPortions` row naming the unit — and it recovers. An
    absence is only attributable when you can show the presence changing the
    answer."""
    _stub(monkeypatch, portions=({"unit_text": "cucumber", "amount": 1.0,
                                  "grams": 301.0, "portion_id": 1},))
    updated = await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "2 cucumbers"},
        facts=_facts())
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "RECOVERED"
    assert updated.selected_rung_authoritative is True


@pytest.mark.parametrize("seam", ["search", "qualify", "portions"])
@pytest.mark.asyncio
async def test_every_provider_outage_is_UNMEASURED_not_a_negative(monkeypatch,
                                                                  seam):
    """⛔⛔⛔ AN OUTAGE IS NOT A VERDICT ABOUT THE FOOD. Any of the three seams
    failing must return None — UNMEASURED — because "we could not ask" and "the
    answer is no" are different facts, and only one of them should stop a
    tranche being built."""
    _stub(monkeypatch, **{f"{seam}_raises": True})
    got = await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())
    assert got is None, f"a {seam} outage produced a verdict"
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "infrastructure UNMEASURED"


# ── THE FORBIDDEN LIST ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_identity_is_searched_EXACTLY_AS_WRITTEN(monkeypatch):
    """⛔⛔ NO TRANSLATION — and the Cyrillic case is the whole reason the rule
    exists. 93 of the 202 addressable items carry a non-Latin surface, so
    translating here would measure a *translation* tranche and report it as
    coverage. The query that goes to USDA is the user's own identity."""
    search = _stub(monkeypatch, rows=())
    await M.artifact_extension_counterfactual(
        item={"food_name": "Творог", "quantity": "150 г"},
        facts=_facts(identity="Творог", entity="творог"))
    assert search.seen == ["Творог"], (
        f"the identity was transformed before the search: {search.seen}")


def test_the_counterfactual_reaches_no_forbidden_source():
    """⛔ OFF, ALIASES, RECIPE DECOMPOSITION AND RESTAURANT ESTIMATES ARE OUT OF
    SCOPE, so the code must not be able to reach them.

    ⛔⛔ THE FIRST VERSION OF THIS TEST SCANNED RAW TEXT AND FAILED ON ITS OWN
    PROSE — the word "translating" inside a comment explaining why translation
    is forbidden. A substring search over source cannot tell an IMPORT from an
    apology, which is the grep trap this repository keeps re-learning. So the
    check is on the AST: what the function IMPORTS and what it CALLS, which is
    what "can reach" actually means.
    """
    import ast
    import inspect

    forbidden_modules = ("off", "unit_alias", "aliases", "recipe",
                         "translate", "translation", "deepl", "googletrans")
    for func in (M.artifact_extension_counterfactual, M._usda_extension):
        tree = ast.parse(inspect.getsource(func).lstrip())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        for name in imported:
            leaf = name.rsplit(".", 1)[-1].lower()
            assert leaf not in forbidden_modules, (
                f"{func.__name__} imports {name!r} — outside the authorized "
                f"scope")
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)}
        assert not (called & set(forbidden_modules)), (
            f"{func.__name__} calls {sorted(called & set(forbidden_modules))}")


@pytest.mark.asyncio
async def test_one_usda_round_trip_per_DISTINCT_identity(monkeypatch):
    """⭐ 202 addressable items carry 155 distinct identities. Asking twice
    about the same food would cost twice AND could answer differently between
    two items of the same meal, which would make the meal-level verdict depend
    on ordering."""
    search = _stub(monkeypatch)
    for _ in range(3):
        await M.artifact_extension_counterfactual(
            item={"food_name": "Cucumber", "quantity": "100 g"},
            facts=_facts())
    assert search.seen == ["Cucumber"], (
        f"the same identity was searched {len(search.seen)} times")
    assert len(M.EXTENSION_LEDGER) == 3, "each ITEM must still be attributed"


@pytest.mark.asyncio
async def test_a_transient_provider_flake_is_RETRIED_not_reported(monkeypatch):
    """⛔⛔⛔ THE DEFECT THAT INVALIDATED TWO FULL RUNS.

    Measured 2026-08-22: the IDENTICAL USDA search returns 200 or a 404 HTML
    error page roughly HALF the time, with rate-limit budget untouched (3104 of
    3600) and even paced at one request per second. `_search` logged that and
    returned `[]`, so every flake was filed as "this food is not in USDA" — the
    dominant bucket of the whole measurement, contaminated by an outage.

    Two runs over identical inputs disagreed wildly: 9 recovered vs 2, 132 "no
    USDA match" vs 99. That disagreement is the only reason it was caught, and
    a single run would have been reported as fact.

    ⭐ So a flake that later ANSWERS must not surface at all."""
    monkeypatch.setattr(M, "_RETRY_ATTEMPTS", 4)
    monkeypatch.setattr(M, "_RETRY_BACKOFF", 0)
    monkeypatch.setattr(M, "_PROVIDER_PACE", 0)
    import api.usda as USDA
    import skills.nutrition.evidence_qualification as EQ

    calls = {"n": 0}

    async def _flaky(query, page_size=5, strict=False):
        calls["n"] += 1
        if calls["n"] < 3:                    # answers only on the third try
            raise USDA.UsdaUnavailable("404 html error page")
        return [dict(_ROW)]

    async def _qualify(identity, chunk, **kw):
        return _Q(chunk)

    async def _portions(fdc_id, strict=False):
        return []

    monkeypatch.setattr(USDA, "search_food", _flaky)
    monkeypatch.setattr(EQ, "qualify_usda_rows", _qualify)
    monkeypatch.setattr(USDA, "food_portions", _portions)

    updated = await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())
    assert calls["n"] == 3, f"the flake was not retried ({calls['n']} attempts)"
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "RECOVERED", (
        "a food USDA eventually answered for was filed as a failure")
    assert updated.selected_rung_authoritative is True


@pytest.mark.asyncio
async def test_an_outage_is_never_CACHED_against_the_food(monkeypatch):
    """⛔⛔ ONE TRANSIENT 404 BECAME A PERMANENT VERDICT. The per-identity cache
    stored the infrastructure outcome, so the first flake for a food poisoned
    every later item carrying it — which is how the same inputs produced 0
    unmeasurable items in one run and 45 in the next.

    An outage is a property of the MOMENT, not of the food, and must never be
    remembered as one."""
    monkeypatch.setattr(M, "_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(M, "_RETRY_BACKOFF", 0)
    monkeypatch.setattr(M, "_PROVIDER_PACE", 0)
    import api.usda as USDA
    import skills.nutrition.evidence_qualification as EQ

    state = {"down": True}

    async def _search(query, page_size=5, strict=False):
        if state["down"]:
            raise USDA.UsdaUnavailable("down")
        return [dict(_ROW)]

    async def _qualify(identity, chunk, **kw):
        return _Q(chunk)

    async def _portions(fdc_id, strict=False):
        return []

    monkeypatch.setattr(USDA, "search_food", _search)
    monkeypatch.setattr(EQ, "qualify_usda_rows", _qualify)
    monkeypatch.setattr(USDA, "food_portions", _portions)

    first = await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())
    assert first is None                                  # UNMEASURED

    state["down"] = False
    second = await M.artifact_extension_counterfactual(
        item={"food_name": "Cucumber", "quantity": "100 g"}, facts=_facts())
    assert second is not None, (
        "the outage was cached against the food — a later item carrying the "
        "same identity inherited a verdict about the network")
    assert M.EXTENSION_LEDGER[-1]["outcome"] == "RECOVERED"
