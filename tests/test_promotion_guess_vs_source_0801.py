"""A guess does not beat a lookup (prod 0801, resolver live).

Prod evidence: a chicken shawarma bowl web-enriched to 950 cal, then the resolver
promotion overwrote it back to the model's own guess (550) because a `provisional`
resolution — the guess wearing a resolver label — counted as `promotable`. With
NUTRITION_RESOLVER_MODE=live the resolver owns the committed number, so this
silently discarded every web/USDA/OFF hit whenever the resolver only reached a
provisional.

The rule: a provisional resolution may still promote over a bare estimate (both
are guesses), but it must NEVER override a legacy that carries a real source. A
real resolution (usda/off/exact) still wins as before — only the guess defers.

These tests exercise the DECISION, so `to_food_analysis` (which routes through
analyze()) is stubbed to a sentinel: promote() either returns the legacy (declined)
or the sentinel (promoted). No network, no LLM.
"""
from types import SimpleNamespace

import pytest

import skills.nutrition.promotion as P


class _Nutrients:
    def __init__(self, **kw):
        self._d = kw

    def amount(self, key):
        return self._d.get(key)

    def unknown(self):
        return [k for k in ("fiber", "sugar", "sodium") if self._d.get(k) is None]


def _resolution(source, cal=550, grade="category"):
    return SimpleNamespace(
        source=source, match_grade=grade,
        nutrients=_Nutrients(calories=cal, protein=1, carbs=1, fat=1),
        tier=None, confidence=0.5, is_estimate=(source in ("provisional", "estimate")),
        source_id=None)


def _legacy(source, cal=950):
    return SimpleNamespace(
        source=source, enrichment_source=source, calories=cal,
        provenance=None, micros=None, micros_estimated=False,
        fiber=None, sugar=None, sodium=None)


@pytest.fixture(autouse=True)
def _owns_and_sentinel(monkeypatch):
    # Resolver owns the committed number (live + in cohort) — isolate the promote
    # decision from canary rollout.
    monkeypatch.setattr(P, "owns_committed_values", lambda uid=None: True)
    # Stub the builder: a PROMOTE returns this sentinel; a DECLINE returns legacy.
    sentinel = SimpleNamespace(calories=-1, source="__promoted__")
    monkeypatch.setattr(P, "to_food_analysis",
                        lambda *a, **k: sentinel)
    return sentinel


def _promote(resolution, legacy):
    return P.promote(resolution, food_name="chicken shawarma bowl",
                     quantity="1 bowl", legacy=legacy, user_id=26)


@pytest.mark.parametrize("legacy_source", ["web_label", "web", "usda", "off",
                                           "memory", "user_label"])
def test_provisional_never_overrides_a_sourced_legacy(legacy_source):
    """The prod bug: provisional (guess) must not clobber real source data."""
    leg = _legacy(legacy_source, cal=950)
    out = _promote(_resolution("provisional", cal=550), leg)
    assert out is leg and out.calories == 950


def test_provisional_defers_to_the_interpreter_estimate():
    """OWNERSHIP (root fix 0802): a provisional guess has not verified identity, so
    it does NOT override even a bare interpreter estimate — the estimate is the
    committed baseline. (Was: provisional promoted over estimate. New rule: a
    lookup earns the override only by proving identity.)"""
    leg = _legacy("estimate", 400)
    out = _promote(_resolution("provisional", cal=550), leg)
    assert out is leg


def test_category_grade_lookup_defers_to_the_baseline():
    """The shrimp/eggplant class: a real source (usda) but a WEAK CATEGORY match is
    not a verified identity, so it must not override the interpreter's baseline."""
    leg = _legacy("estimate", 150)
    out = _promote(_resolution("usda", cal=2450, grade="category"), leg)
    assert out is leg


def test_close_grade_lookup_still_promotes(_owns_and_sentinel):
    """A CLOSE identity match is verified — it overrides as before (no regression
    to the cases the resolver was built for)."""
    out = _promote(_resolution("off", cal=210, grade="close"), _legacy("estimate", 150))
    assert out is _owns_and_sentinel


def test_users_own_data_promotes_regardless_of_grade(_owns_and_sentinel):
    """The user's confirmed memory is trusted even without an EXACT/CLOSE grade."""
    out = _promote(_resolution("memory", cal=300, grade="category"), _legacy("estimate", 250))
    assert out is _owns_and_sentinel


def test_real_resolution_still_wins_over_web_label(_owns_and_sentinel):
    """A sourced resolution (usda/off/exact) is not a guess — it promotes as before."""
    out = _promote(_resolution("usda", cal=610, grade="exact"),
                   _legacy("web_label", 950))
    assert out is _owns_and_sentinel


def test_unpromotable_resolution_falls_back_to_legacy():
    """Unchanged guard: no calories → keep legacy regardless of source."""
    leg = _legacy("web_label", 950)
    out = _promote(_resolution("provisional", cal=0), leg)
    assert out is leg
