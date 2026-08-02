"""Web-enrich candidate gate (2026-08-02): broadened beyond meal-words to any
non-beverage food on the estimate path (web fails safe; beverages stay out —
the one class it fabricates a label for). Fires only on estimate, so trusted
DB seats are never overridden."""
from handlers.tool_executor import _web_enrich_candidate as ok


def test_solid_foods_now_qualify():
    assert ok("burger bun")
    assert ok("turkey deli slices")
    assert ok("grilled chicken thigh")


def test_meal_words_still_qualify():
    assert ok("CAVA bowl")
    assert ok("chicken burrito")


def test_beverages_excluded():
    for b in ("coffee", "latte", "iced tea", "orange juice", "whiskey",
              "protein shake", "coke", "red wine"):
        assert not ok(b), b


def test_trivial_excluded():
    assert not ok("ab")
    assert not ok("")
