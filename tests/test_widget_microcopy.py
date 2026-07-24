"""Widget NEXT-row microcopy: always complete, behavioral, ≤34 chars —
never truncated analytics (Danny 2026-07-24)."""
from types import SimpleNamespace
from api.native_data import _widget_microcopy_ok, _widget_next_microcopy


def test_analytics_style_headlines_rejected():
    assert _widget_microcopy_ok("+1695 cal remaining (21% used) — protein back-load") is None
    assert _widget_microcopy_ok("1,695 left today") is None
    assert _widget_microcopy_ok("A" * 40) is None
    assert _widget_microcopy_ok("Protein first at lunch.") == "Protein first at lunch."


def _log(cal=0, protein=0, workout=False):
    return SimpleNamespace(total_calories=cal, total_protein=protein,
                           workout_completed=workout)


def test_ladder_always_fits_and_never_empty():
    prefs = SimpleNamespace(calorie_target=2165, protein_target=180)
    for log in (_log(), _log(cal=400, protein=20), _log(cal=1900, protein=150),
                _log(cal=900, protein=120, workout=True)):
        for weighed in (True, False):
            out = _widget_next_microcopy(log, prefs, "America/New_York",
                                         weighed_today=weighed)
            assert out and len(out) <= 34 and "%" not in out
