"""The receipt may not claim evidence we do not have.

Prod 2026-08-03, a bakery challah: "Logged Challah bread, 140 cal — From the
product label", for a food that has no label anywhere. Two separate causes, and
the transcript needed only one of them to lie.

  1. `_web_lookup_meal` asks Haiku to read Tavily snippets for a dish's TOTAL
     and then reported as `web_label` — the source belonging to
     `_web_lookup_packaged`, which anchors on a real published per-100g panel.
     A search result is not a label.

  2. `_food_line` — the CONDENSED step a multi-item meal renders, which is
     exactly what a challah sandwich is — took `src["detail"]` unconditionally.
     That is `authority.display_detail`, keyed by RUNG, while `_SOURCE_DETAIL`
     is keyed by LANE. An Open Food Facts answer is lane `off` and rung
     `branded_exact`, whose sentence is "From the product label". `_food_detailed`
     had been narrowed for precisely this; this path had not.

The rule both now follow: a rung sentence may ADD to the receipt, never
overrule the lane about which lane answered.
"""
import core.reasoning as R


def _detail(source, detail="", name="Food", cal=100):
    step = R._food_line(
        {"food_name": name,
         "_sourcing": {"source": source, "detail": detail, "calories": cal}},
        "")
    return step.get("detail", "")


def test_an_off_answer_says_off_not_label():
    """The challah. Lane `off`, rung `branded_exact` — the rung's sentence must
    not overrule the lane."""
    assert _detail("off", "From the product label",
                   name="Challah bread", cal=140) == "From the Open Food Facts label"


def test_a_web_search_is_not_a_product_label():
    """The meal-enrich lane's own words, not the packaged lane's."""
    assert _detail("web_estimate", "", name="Cali Roll",
                   cal=400) == "Typical numbers found online"


def test_a_real_published_label_still_says_so():
    """The honest case must keep its honest sentence — this is a narrowing of
    an overclaim, not a retreat from claiming anything."""
    assert _detail("web_label", "From the product label",
                   name="Quest bar") == "From the product label"


def test_a_rung_sentence_that_adds_something_survives():
    """"supplemented" says something no lane label can — that the portion was
    estimated and only the profile came from the database. That is additive,
    so it wins."""
    d = _detail("usda",
                "Portion estimated · nutrition profile supplemented with USDA data",
                name="Corn", cal=90)
    assert "supplemented" in d


def test_the_meal_enrich_source_is_labelled_everywhere_it_is_read():
    """A new source that any map forgets falls through to "estimate" and reads
    back as a guess — the exact bug `_SOURCE_LABELS` documents for `off`."""
    assert "web_estimate" in R._SOURCE_DETAIL
    assert "web_estimate" in R._SOURCE_LABELS
