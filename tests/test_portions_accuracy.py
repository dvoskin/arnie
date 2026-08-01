"""Parts 2b/3/4 tables: portion prior, cooking yield, added fat (v2 accuracy).

These are the named, auditable tables that replace three silent failures —
grams from the model's low guess, a raw density for a cooked food, and an added
fat nobody counted. Pure functions, no flag: the flag gates whether analyze()
CONSULTS them, tested by scripts/eval_accuracy.py; here we pin the tables.
"""
from core.portions import portion_prior, cooking_yield, added_fat_calories


def test_portion_prior_covers_bare_whole_foods():
    # The gap that sent skirt steak's grams through the model's guess.
    assert portion_prior("skirt steak") == 200
    assert portion_prior("handful of almonds") == 28      # longest-keyword match
    assert portion_prior("grilled chicken breast") == 170
    assert portion_prior("green salad") == 200


def test_portion_prior_is_none_for_unknown_food():
    # No prior invented for a food we don't have a serving for.
    assert portion_prior("wizzle gizzard surprise") is None


def test_cooking_yield_only_for_cooked_foods():
    assert cooking_yield("skirt steak") == 1.30           # beef family
    assert cooking_yield("chicken thigh") == 1.25
    assert cooking_yield("almonds") == 1.0                # raw food, no yield
    assert cooking_yield("green salad") == 1.0


def test_added_fat_detects_named_additions_longest_wins():
    assert added_fat_calories("sirloin steak cooked in butter") == (100, "in butter")
    assert added_fat_calories("green salad with ranch") == (145, "with ranch")
    assert added_fat_calories("chicken with olive oil")[0] == 120


def test_added_fat_respects_stated_omission():
    # "no dressing" must not add dressing calories.
    assert added_fat_calories("a big green salad, no dressing") == (0, "")
    assert added_fat_calories("plain grilled chicken") == (0, "")


def test_added_fat_absent_when_nothing_named():
    assert added_fat_calories("grilled chicken breast") == (0, "")
