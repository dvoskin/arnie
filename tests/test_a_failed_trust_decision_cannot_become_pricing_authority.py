"""⛔⛔⛔ CF24: A FAILED TRUST DECISION MUST NOT BECOME PRICING AUTHORITY.

**The historical bypass, reproduced 2026-08-31** on tree `a7549d7` under
production-equivalent runtime (`new_execute`, `consume`, subject literally 26):

```
predicate  {'seq': 1, 'is_row936': True, 'trusted': False}   ← the guard RAN
seq 2-7    authority.select[branded_exact]  seated_is_row936=True
committed  525.0 kcal · P10.6 C76.6 F19.4 · sugar 4.6 · sodium 1874.4
```

Every macro is row 936's per-100g x 1.2. Entry 3050 committed exactly 525 in
production on 2026-08-25. **The trust decision existed, returned False, and was
not authoritative downstream** — that is the whole defect, and for three weeks
it was recorded as "a consumer reached that nutrition and no evidence says
which".

⭐ THE INVARIANT IS ABOUT PROVENANCE OF AUTHORITY, NOT ABOUT A FOOD:

    If memory nutrition is untrusted, no representation derived from it may
    appear in an authoritative pricing candidate map.

⛔ WHY THE GUARD IS AT `candidate_map` AND NOT AT THE READER. Guarding
`fetch_candidates` protects one route, and CF24's entire cost was not knowing
which route had been used — another reader can always exist. `candidate_map` is
the one thing every pricing consumer reads, so the refusal there covers readers
nobody has written yet. A caller that forgets the door now gets its candidate
DROPPED, rather than silently trusted.

⛔ AND IT IS NOT `if branded_exact`, not a food name, and not "CF25's
qualification happens to reject this shape". Those would fix the instance.
"""
from __future__ import annotations

import pytest

from skills.nutrition import authority
from skills.nutrition.authority import FoodClass, candidate_map

#: Row 936 verbatim — `branded_exact` is its own `origin_tier`, which is what
#: earned it the rung it was seated at.
ROW936 = {
    "fdc_id": None, "user_confirmed": False, "confidence": "exact",
    "origin_tier": "branded_exact", "serving_text": "80 g",
    "per100g": {"calories": 437.5, "protein": 8.8, "carbs": 63.8,
                "fat": 16.2, "sugar": 3.8, "sodium": 1562.0},
}


def _untrusted():
    return dict(ROW936)


def _trusted():
    return {**ROW936, "_trusted_memory": True}


@pytest.mark.parametrize("food_class", list(FoodClass))
def test_untrusted_memory_never_enters_the_candidate_map(food_class):
    """⭐ EVERY CLASS. The bypass seated at `branded_exact`, but a guard that
    only covered that rung would leave the same hole on the others — and
    `candidate_map` routes memory to four different rungs depending on class
    and origin."""
    out = candidate_map(food_class=food_class, memory_match=_untrusted())
    assert not any(c is not None and c.get("per100g", {}).get("calories") == 437.5
                   for c in out.values()), (
        f"untrusted memory nutrition was seated for {food_class}: {sorted(out)}")


@pytest.mark.parametrize("food_class", list(FoodClass))
def test_trusted_memory_STILL_seats(food_class):
    """⛔ THE ANTI-VACUITY HALF. A guard that refused everything would pass the
    test above and silently destroy the memory rung — which is a worse defect
    than the one being fixed, and invisible to a one-directional test."""
    out = candidate_map(food_class=food_class, memory_match=_trusted())
    assert any(c is not None and c.get("per100g", {}).get("calories") == 437.5
               for c in out.values()), (
        f"trusted memory was refused for {food_class} — the rung is dead")


def test_the_exact_3050_SHAPE_cannot_be_seated_or_selected():
    """The incident, end to end through the ladder that produced it."""
    out = candidate_map(food_class=FoodClass.MANUFACTURED,
                        memory_match=_untrusted())
    assert "branded_exact" not in out, (
        "row 936 is seated at branded_exact again — this is entry 3050")
    rung, src = authority.select(out, FoodClass.MANUFACTURED)
    assert src is None or src.get("per100g", {}).get("calories") != 437.5, (
        "authority.select returned the poisoned payload; a 120 g portion of it "
        "prices at 525 kcal, which is what production committed")


def test_the_proof_cannot_be_forged_by_ABSENCE(monkeypatch):
    """⛔ FAIL CLOSED. The refusal must trigger on a MISSING marker, not only on
    an explicitly false one — a candidate assembled by a future reader that
    never heard of the door has no key at all, and that is the realistic
    shape."""
    for missing in ({k: v for k, v in ROW936.items()},
                    {**ROW936, "_trusted_memory": False},
                    {**ROW936, "_trusted_memory": None},
                    {**ROW936, "_trusted_memory": 0}):
        out = candidate_map(food_class=FoodClass.MANUFACTURED,
                            memory_match=missing)
        assert "branded_exact" not in out, f"seated with marker {missing.get('_trusted_memory')!r}"


def test_only_the_door_side_sets_the_proof():
    """⭐ ONE PRODUCER. If any other site could stamp `_trusted_memory`, the
    marker would be a convention rather than a proof — and conventions are what
    CF24 already proved insufficient."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    setters = []
    for folder in ("core", "handlers", "skills", "db", "api"):
        for path in (root / folder).rglob("*.py"):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if '"_trusted_memory"' in line and ":" in line and "get(" not in line:
                    setters.append(f"{path.relative_to(root)}:{i}")
    assert len(setters) == 1, (
        f"`_trusted_memory` is set in {len(setters)} places: {setters}. It must "
        "have exactly ONE producer, immediately after "
        "`memory_nutrition_evidence` returns non-None.")
