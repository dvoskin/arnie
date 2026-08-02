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


def test_provisional_still_promotes_over_a_bare_estimate(_owns_and_sentinel):
    """Two guesses — the resolver's provisional may still win over an estimate."""
    out = _promote(_resolution("provisional", cal=550), _legacy("estimate", 400))
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
