"""⛔⛔ A LEGACY SURFACE KEY MAY NOT IMPERSONATE CANONICAL EVIDENCE.

`user_food_matches` records NO canonical identity: a row is keyed by a lossy
surface normalization, so it is evidence about a STRING, not about the identity
being priced. Measured fleet-wide 2026-08-16: 19 normalized addresses are bound
to more than one source record. `banana` is one — fdc 2012128 at 312 kcal/100g
on FOUR accounts, beside fdc 173944 at 89 — and canonical settlement addressed
the first and committed 368 kcal where legacy priced 105.

⭐ THE TEST IS DISAGREEMENT BETWEEN AUTHORITIES, NEVER PLAUSIBILITY. No calorie
ranges, no food names, no per-user exceptions. Bindings that assert the SAME
numbers are one authority re-cached; bindings that assert DIFFERENT numbers are
competing ones, and a competing address cannot be authoritative for anybody.

⭐⭐ AND THE RUNG ABSTAINS RATHER THAN GUESSING — it does not pick a binding,
average them, or fail the meal. The ladder continues, and for `banana` that is
ARTIFACT at 89 kcal/100g: the correct 105.
"""
from __future__ import annotations

import pytest

from core.canonical_pricing import (ArtifactEvidence, MemoryEvidence,
                                    PricingRefused, Rung, price)
from core.canonical_pricing_inputs import _address_has_one_authority
from skills.nutrition.normalize import normalize_quantity

BANANA_GOOD = {"calories": 89.0, "protein": 1.09, "carbs": 22.8, "fat": 0.33}
BANANA_BAD = {"calories": 312.0, "protein": 12.5, "carbs": 40.6, "fat": 6.25}


class _Rows:
    """The only thing the admissibility check reads: the bindings for one
    address. Shaped as SQLAlchemy returns them."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_a, **_k):
        return self

    def all(self):
        return self._rows


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,unambiguous,why", [
    ([(89.0, 1.09, 22.8, 0.33)], True, "one binding"),
    ([(89.0, 1.09, 22.8, 0.33), (89.0, 1.09, 22.8, 0.33)], True,
     "the same authority re-cached — a history duplicate, not a conflict"),
    ([(800.0, 0.0, 0.0, 100.0), (800.0, 0.0, 0.0, 100.0)], True,
     "two fdc ids carrying IDENTICAL values: characterized as duplicates"),
    ([(89.0, 1.09, 22.8, 0.33), (312.0, 12.5, 40.6, 6.25)], False,
     "banana: competing authorities"),
    ([(30.0, 0.6, 7.6, 0.2), (31.0, 0.8, 7.9, 0.2)], False,
     "watermelon: they disagree, so the address cannot establish authority — "
     "refusing is the safe direction and needs no tolerance knob"),
    ([], True, "no bindings at all is an absence, not an ambiguity"),
])
async def test_the_address_authority_test_is_agreement_not_plausibility(
        rows, unambiguous, why):
    assert await _address_has_one_authority(_Rows(rows), "x") is unambiguous, why


# ══ the ladder, with an inadmissible address ════════════════════════════════

def test_banana_memory_abstains_and_the_artifact_decides():
    """⭐ THE EXACT CANARY, AS A UNIT. Memory abstains (the address is
    ambiguous), so the ladder continues to the artifact and prices 105 — the
    number legacy produced, reached by the canonical path."""
    from skills.nutrition.pricing_artifact import evidence_for

    artifact = evidence_for("banana", "")
    assert artifact is not None, "the artifact must cover banana for this gate"
    priced = price(entity="Banana", memory=None, artifact=artifact,
                   consumed=normalize_quantity("1 banana", "Banana"))
    assert priced.rung is Rung.ARTIFACT
    assert round(priced.calories) == 105
    assert priced.evidence_id == "usda:173944"


def test_an_admissible_memory_still_outranks_the_artifact():
    """⛔ THE GUARD MAY NOT DEMOTE MEMORY GENERALLY. A clean address still wins,
    and still wins OVER a present artifact — rung precedence is untouched."""
    from skills.nutrition.pricing_artifact import evidence_for

    priced = price(entity="Banana",
                   memory=MemoryEvidence(per100g=BANANA_GOOD, source_id="ufm"),
                   artifact=evidence_for("banana", ""),
                   consumed=normalize_quantity("1 banana", "Banana"))
    assert priced.rung is Rung.MEMORY


def test_memory_absent_still_reaches_the_artifact():
    from skills.nutrition.pricing_artifact import evidence_for

    priced = price(entity="Banana", memory=None,
                   artifact=evidence_for("banana", ""),
                   consumed=normalize_quantity("1 banana", "Banana"))
    assert priced.rung is Rung.ARTIFACT


def test_ambiguous_memory_with_no_artifact_refuses_rather_than_guessing():
    """⛔⛔ NEVER AN ARBITRARY BINDING. With the address inadmissible and no
    artifact, the answer is a refusal — not "pick one", not "average them"."""
    with pytest.raises(PricingRefused):
        price(entity="Nothing covered", memory=None,
              artifact=ArtifactEvidence(candidates=()),
              consumed=normalize_quantity("100 g", "Nothing covered"))


def test_the_guard_reads_only_the_bindings_never_the_food():
    """⛔ NO FOOD NAMES, NO RANGES, NO PER-USER EXCEPTIONS. Structural: the
    admissibility function may not consult the identity, the user, or any
    threshold — only whether the bindings agree."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(_address_has_one_authority).lstrip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    banned = {"banana", "cucumber", "calories_range", "PLAUSIBLE", "user_id"}
    assert not (banned & names), f"the guard consults {banned & names}"
    numbers = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
               and n.value not in (0, 1)]
    assert not numbers, (
        f"the guard carries magic numbers {numbers} — a tolerance is a "
        f"threshold, and a threshold is where nutrition judgement is smuggled in")
