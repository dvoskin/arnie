"""REACHABILITY — a capability that is correct, tested and never called.

⛔ THE DEFECT THIS FILE EXISTS FOR. Phases 0.1, 0.2, 0.3 and 0.5 built
`skills/nutrition/eligibility.py` — a closed veto vocabulary, raw-vs-cooked
conflict, heat-medium conflict, base-food mismatch — and NOTHING IMPORTED IT.
No non-test caller existed anywhere in the runtime. Every veto it can prove
was exercised only by its own tests, which call `el.vetoes(...)` directly and
therefore prove the function WORKS while saying nothing about whether anything
INVOKES it.

That is the same shape this project already recorded once: an enum member that
was present in `main` and constructed exactly once, so a feature shipped,
passed review, and could not fire.

⭐ SO THESE GATES ARE CAUSAL, NOT FUNCTIONAL. They drive the real build
entry point and assert the veto changed what happened — that a mismatched row
never reached the resolver, and that removing the wiring makes that fail.
A test that calls the veto itself can never catch an unwired veto.
"""
from __future__ import annotations

import asyncio

import pytest

from skills.nutrition import eligibility as el


def _row(fdc_id, description, calories=100.0):
    return {"fdc_id": fdc_id, "description": description,
            "data_type": "sr legacy", "per100g": {"calories": calories}}


@pytest.fixture
def build(monkeypatch):
    """The real `build_one`, with retrieval and the resolver observable."""
    import api.usda as usda
    import scripts.build_pricing_artifact as bp
    import skills.nutrition.evidence_qualification as eq

    seen_by_resolver = []

    async def _fake_retrieval(*_args, **_kwargs):
        return [_row(1, "Beef, chuck, cooked, roasted"),
                _row(2, "Mushrooms, portabella, grilled", 29.0),
                _row(3, "Tofu, fried", 270.0)]

    async def _fake_resolver(food_name, rows, *_a, **_k):
        seen_by_resolver.extend(str(r.get("fdc_id")) for r in rows)
        from types import SimpleNamespace
        return SimpleNamespace(rows=tuple(rows), disposition="qualified",
                               resolver_version="test", kept_count=len(rows))

    # ⚠ PATCH WHERE IT IS LOOKED UP, NOT WHERE IT IS DEFINED. `build_one`
    # imports these INSIDE the function, so binding a name on the module
    # object does nothing — the first attempt did exactly that and the real
    # USDA API answered with 403 API_KEY_MISSING, which is a retrieval
    # failure wearing a test failure's clothes.
    monkeypatch.setattr(usda, "_search", _fake_retrieval)
    monkeypatch.setattr(eq, "qualify_usda_rows", _fake_resolver)
    return bp, seen_by_resolver


def test_the_build_refuses_a_mismatched_row_before_the_resolver(build, capsys):
    """⭐ THE CAUSAL PROOF. Mushrooms and tofu never mention beef, so the
    build must drop them WITHOUT the model being asked — the cost saving is
    incidental; the point is that a mechanical fact was decided mechanically."""
    bp, seen_by_resolver = build
    result = asyncio.run(bp.build_one("beef", "roasted"))

    refused = result.get("mechanically_refused") or {}
    assert set(refused) == {"usda:2", "usda:3"}, refused
    assert all(reason == el.BASE_FOOD_MISMATCH
               for reason in refused.values())

    # and the resolver was never shown them
    assert "2" not in seen_by_resolver
    assert "3" not in seen_by_resolver
    assert "1" in seen_by_resolver


def test_the_refusal_is_attributable_on_the_entry(build):
    """A row that left before the model saw it still says why."""
    bp, _seen = build
    result = asyncio.run(bp.build_one("beef", "roasted"))
    assert result["mechanically_refused"]["usda:2"] == el.BASE_FOOD_MISMATCH


def test_a_legitimate_row_is_never_refused(build):
    """The veto must not touch a record that mentions the requested food."""
    bp, seen_by_resolver = build
    result = asyncio.run(bp.build_one("mushrooms", "grilled"))
    refused = result.get("mechanically_refused") or {}
    assert "usda:2" not in refused
    assert "2" in seen_by_resolver


def test_unwiring_the_veto_makes_this_fail(build, monkeypatch):
    """⭐⭐ ANTI-VACUITY, AND THE ONE THAT MATTERS MOST HERE. The original
    defect was not a wrong veto — it was a veto nobody called. So the gate
    must go red when the CALL is removed, not merely when the rule changes."""
    bp, seen_by_resolver = build
    monkeypatch.setattr(el, "vetoes", lambda *_a, **_k: ())

    result = asyncio.run(bp.build_one("beef", "roasted"))
    assert not (result.get("mechanically_refused") or {})
    # the mismatched rows now reach the model — exactly the old behaviour
    assert "2" in seen_by_resolver and "3" in seen_by_resolver


def test_refusing_every_row_is_reported_as_retrieval_not_emptiness(build):
    """Refusing all rows is a RETRIEVAL outcome, not an admission one — the
    same reasoning that stops a rejection emptying an entry."""
    bp, _seen = build
    result = asyncio.run(bp.build_one("kiwi", ""))
    assert result["status"] == bp.EMPTY
    assert el.BASE_FOOD_MISMATCH in result["reason"]
    assert result["mechanically_refused"]


def test_the_eligibility_module_now_has_a_production_caller():
    """⛔ THE ROOT CHECK. Grep-level, deliberately: the defect was structural
    absence, and no behavioural test can see 'nothing imports this'."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    callers = [
        path for path in root.rglob("*.py")
        if "tests/" not in str(path.relative_to(root))
        and "skills/nutrition/eligibility.py" != str(path.relative_to(root))
        and "from skills.nutrition import eligibility" in path.read_text()
    ]
    assert callers, ("skills.nutrition.eligibility has NO production caller — "
                     "the whole mechanical layer is unreachable again")
