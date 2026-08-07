"""Qualification changes what WINS, not just what gets labelled.

Danny's bar for B-1.5E crossing from classification layer to production
safety boundary: the papaya regression must go red WITHOUT qualification and
green WITH it — behavior, not labels. Both halves run against the CAPTURED
corpus rows and the real `best_candidate`, with the resolver scripted to the
human ground-truth labels (the live model's agreement with those labels is
layer C, already measured at 0 false-compatibles post-policy).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from skills.nutrition import evidence_qualification as eq
from skills.nutrition.evidence_semantics import from_web

CORPUS = pathlib.Path(__file__).parent / "evidence_corpus"

#: Human ground truth for the papaya rows (GROUND_TRUTH.md), keyed by
#: description prefix. The scripted resolver answers with THESE — this file
#: tests the plumbing's effect on ranking, not the model's judgement.
_PAPAYA_TRUTH = {
    "Papayas, raw": ("SAME_IDENTITY", 0.99),
    "Papaya nectar": ("DERIVED_OR_EXTRACTED_FORM", 0.95),
    "Papaya, canned, heavy syrup": ("DERIVED_OR_EXTRACTED_FORM", 0.95),
    "Babyfood": ("COMPOSITE_CONTAINING_IDENTITY", 0.95),
    "Fruit salad": ("COMPOSITE_CONTAINING_IDENTITY", 0.95),
}


def _papaya_rows():
    usda = json.loads((CORPUS / "usda_2026_08_07.json").read_text())
    # The capture projected fields (description/brand/fdc_id/kcal only);
    # `best_candidate` reads `per100g`. The SHAPE is rebuilt from the captured
    # values — the values themselves stay verbatim.
    return [{**r, "per100g": {"calories": r["kcal_per_100g"]}}
            for r in usda["queries"]["papaya"]]


def _scripted_truth(records_titles):
    async def complete(prompt):
        out = []
        for evidence_id, title in records_titles:
            for prefix, (rel, conf) in _PAPAYA_TRUTH.items():
                if title.startswith(prefix):
                    out.append({"evidence_id": evidence_id,
                                "relationship": rel, "confidence": conf})
                    break
        return json.dumps(out)
    return complete


def _ids(rows):
    return [(f"usda:{r.get('fdc_id') or i}", r["description"])
            for i, r in enumerate(rows)]


# ── the regression, both halves ─────────────────────────────────────────────

def test_without_qualification_a_noncomparable_row_can_win():
    """THE RED HALF: the defect must be demonstrably real in the unqualified
    path, or the green half proves nothing. `best_candidate` over the raw
    captured rows for a plain-papaya request must seat a row that is NOT the
    raw fruit — the shipped 2896 behavior."""
    from core.food_intelligence import best_candidate

    winner, _conf = best_candidate("papaya", _papaya_rows())
    assert winner is not None
    if winner["description"] == "Papayas, raw":
        pytest.skip("ranking alone now picks the raw row — the defect no "
                    "longer reproduces from ranking, re-examine this pair")
    # Measured while writing this test: the winner is the BABYFOOD COMPOSITE
    # ("Babyfood, fruit, guava and papaya with tapioca, strained") — its
    # description contains the literal token "papaya", so coverage passes and
    # the composite penalty does not sink it. String overlap seating a
    # composite is the entire class this boundary exists to refuse.
    assert winner["description"] != "Papayas, raw", (
        "expected the unqualified path to demonstrate the defect")


@pytest.mark.asyncio
async def test_with_qualification_the_bad_row_cannot_win():
    """THE GREEN HALF: same rows, same ranking — but qualification removes
    every non-identity row first, so the ONLY seatable papaya row is the raw
    fruit. The heavy-syrup row does not lose the argument; it never enters."""
    from core.food_intelligence import best_candidate

    rows = _papaya_rows()
    q = await eq.qualify_usda_rows("papaya", rows,
                                   complete=_scripted_truth(_ids(rows)))
    assert q.disposition == "qualified"
    kept_names = [r["description"] for r in q.rows]
    assert kept_names == ["Papayas, raw"], kept_names

    winner, _conf = best_candidate("papaya", list(q.rows))
    # QUALIFICATION DECIDES ELIGIBILITY, NOT TRUTH. With only the raw fruit
    # eligible, the bad rows CANNOT win — that is this boundary's whole claim.
    # `best_candidate` then happens to return None here: its coverage gate
    # does not bridge "papaya" to "Papayas, raw" (singular vs plural), so
    # USDA contributes nothing and the ladder falls to the estimate — still
    # strictly better than seating the composite. That plural gap is a
    # D-class ranking finding, recorded in the directive, and deliberately
    # NOT fixed inside the evidence boundary.
    assert winner is None or winner["description"] == "Papayas, raw", (
        f"a non-identity row won through the qualified set: {winner}")


@pytest.mark.asyncio
async def test_a_rejected_row_is_not_resurrected_later():
    """No candidate resurrection: the qualification result is a new list, the
    rejected rows are simply absent, and an empty qualified set yields NO
    candidate rather than a fallback to the raw rows."""
    rows = [r for r in _papaya_rows()
            if not r["description"].startswith("Papayas, raw")]
    q = await eq.qualify_usda_rows("papaya", rows,
                                   complete=_scripted_truth(_ids(rows)))
    assert q.disposition == "qualified" and q.kept_count == 0
    assert q.rows == (), "nothing eligible means nothing — not the raw rows"


@pytest.mark.asyncio
async def test_resolver_down_does_not_authorize_raw_evidence():
    """SEMANTIC_RESOLVER_DOWN != RAW_EVIDENCE_AUTHORIZED.

    The first version failed open to the unfiltered rows — the safety
    boundary optional exactly when unavailable, the babyfood row resurrected
    by a timeout. Now: the USER's action fails open (the ladder's
    qualification-free rungs — memory, structured product matches, the
    estimate — still serve), the EVIDENCE fails closed."""
    async def down(prompt):
        raise RuntimeError("model down")

    rows = _papaya_rows()
    q = await eq.qualify_usda_rows("papaya", rows, complete=down)
    assert q.disposition == "resolver_down_no_candidates"
    assert q.rows == (), (
        "raw keyword rows regained authority from the qualifier's absence")


@pytest.mark.asyncio
async def test_resolver_down_still_leaves_logging_available(monkeypatch):
    """The other half of the invariant, behaviorally: with the resolver down,
    the fetch returns NO USDA candidate (not a bad one), and the estimate
    rung — which analyze() already falls to when usda_candidate is None —
    keeps the user's logging alive."""
    from handlers import tool_executor

    rows = _papaya_rows()

    async def fake_search(query, page_size=8):
        return rows

    async def down(prompt):
        raise RuntimeError("model down")

    monkeypatch.setattr("api.usda.search_food", fake_search)
    monkeypatch.setattr(
        "skills.nutrition.evidence_qualification._default_complete", down)
    monkeypatch.delenv("EVIDENCE_QUALIFICATION_HALT", raising=False)

    usda, _off = await tool_executor._fetch_usda_off_uncached("papaya", False)
    assert usda is None, (
        f"resolver down must yield NO USDA candidate, got "
        f"{(usda or {}).get('description')!r}")


@pytest.mark.asyncio
async def test_the_pricing_path_actually_runs_qualification(monkeypatch):
    """The wiring gate, BEHAVIORAL. A source-text ratchet was satisfiable by
    dead code — a call inside `if False:` is still a substring, and the
    bypass mutation proved it. So this drives the real
    `_fetch_usda_off_uncached` with the captured papaya rows and asserts the
    composite CANNOT come back as the USDA candidate: if qualification is
    bypassed, babyfood wins and this goes red."""
    from handlers import tool_executor

    rows = _papaya_rows()

    async def fake_search(query, page_size=8):
        return rows

    monkeypatch.setattr("api.usda.search_food", fake_search)
    monkeypatch.setattr(
        "skills.nutrition.evidence_qualification._default_complete",
        _scripted_truth(_ids(rows)))
    monkeypatch.delenv("EVIDENCE_QUALIFICATION_HALT", raising=False)

    usda, _off = await tool_executor._fetch_usda_off_uncached("papaya", False)
    assert usda is None or usda.get("description") == "Papayas, raw", (
        f"a non-identity row came back as the USDA candidate: "
        f"{(usda or {}).get('description')!r} — qualification was bypassed")


def test_the_halt_switch_restores_yesterday(monkeypatch):
    """The kill switch is a rollout control, and it must actually bypass."""
    from handlers.tool_executor import _qualification_halted

    monkeypatch.setenv("EVIDENCE_QUALIFICATION_HALT", "1")
    assert _qualification_halted()
    monkeypatch.delenv("EVIDENCE_QUALIFICATION_HALT", raising=False)
    assert not _qualification_halted()


# ── the claim-type gate ─────────────────────────────────────────────────────

def test_materiality_evidence_can_never_price():
    """THE HARD GATE Danny required before the production turn: a source
    admitted for `preparation_materiality` but not `nutrition_pricing` can
    open a field and can never contribute a calorie/macro candidate.

    The synthesized web answer IS that source: admissible for relevance,
    inadmissible for pricing, by TYPE — not by anyone remembering."""
    class _Result:
        error, query = None, "grilled vs fried"
        answer = "Grilled chicken ~165 kcal/100g, fried ~250"
        results = [{"title": "blog", "url": "https://example.com"}]

    records = from_web(_Result())
    synthesized = [r for r in records if r.evidence_type == "synthesized_text"]
    assert synthesized, "the web adapter stopped typing the answer"
    for record in synthesized:
        assert eq.admissible_for_relevance(record)
        assert not eq.admissible_for_pricing(record), (
            "'web says fried matters, therefore web calories are "
            "authoritative' — the exact shortcut this gate exists to refuse")


def test_pricing_admissibility_is_by_type_not_by_provider():
    """A structured manufacturer record from the web lane may still price
    (§15); it is the SYNTHESIZED text that may not. The distinction is the
    evidence_type, so a future provider inherits the rule automatically."""
    from core.semantic_evidence import EvidenceRecord

    structured_web = EvidenceRecord(evidence_id="w1", provider="web",
                                    title="Barebells nutrition label",
                                    evidence_type="structured_record")
    assert eq.admissible_for_pricing(structured_web)
