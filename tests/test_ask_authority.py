"""WHO DECIDES TO ASK.

The interpreter used to own the ask outright. `action:"ask"` returned from
`_run_untraced` before `plan_turn` was ever reached, so on a clarification the
staging, the calibrated spans, the day-share and item-share dials and the
user's own mode contributed nothing at all. Measured over 110 real production
food messages: 100% of ask turns carried no scored consequence (0/27, 0/23,
0/25 across quick / moderate / strict), and the ask rate was flat across modes
— quick 25%, moderate 21%, strict 23% — because mode only ever reached the log
path.

Three things enforced that, and all three had to go:

  1. the prompt scoped ambiguity reporting to "when you log", so a model that
     had decided to ask correctly reported nothing;
  2. `plan_turn` sat behind `any(k == "log" for k, _ in ops)`;
  3. the `ask` schema had NO SLOT for the contested item's estimate — so even
     with 1 and 2 fixed the system still could not decline to ask, because
     nothing had produced a number to commit instead. That one is why the
     first attempt measured zero demotions in every mode.

Afterwards: 100% of proposals carry consequence and a fallback estimate, and
the rate finally separates by mode (16 / 21 / 24%).

These tests pin the DIRECTION of authority, not the dials — the numbers above
live in skills/nutrition/materiality.py and are swept against production.
"""
from types import SimpleNamespace

import pytest

import core.food_turn as FT
from skills.nutrition.materiality import DAY_SHARE_OVERRIDE

TARGETS = {"calories": 2000.0, "protein": 150.0, "carbs": 200.0, "fat": 60.0}


@pytest.fixture(autouse=True)
def _fixed_targets(monkeypatch):
    """Pin the day's goals. These tests are about WHO decides, so they must not
    also depend on how targets are computed — and without this they silently
    fall through to the scale-blind legacy thresholds and pass for the wrong
    reason."""
    monkeypatch.setattr(FT, "_daily_targets", lambda user: dict(TARGETS))


def _user(mode):
    return SimpleNamespace(preferences=SimpleNamespace(
        food_logging_mode=mode))


def _proposal(span, calories, field="quantity"):
    """A model proposal to ask, carrying both halves the contract now requires:
    a best-estimate row and what the answer would settle."""
    return {"action": "ask",
            "items": [{"food": "Thing", "amount": 1, "unit": "serving",
                       "calories": calories, "protein": 10}],
            "ambiguities": [{"item": "Thing", "field": field,
                             "impact_cal": span}],
            "points": [{"label": "Thing", "qs": ["how much?"]}]}


# ── the inversion ────────────────────────────────────────────────────────────

def test_a_trivial_unknown_does_not_earn_a_question():
    """The model may propose; a 12-calorie spread on a snack does not survive
    it in any mode. Before, this reached the user as a question purely because
    the interpreter felt like asking."""
    for mode in ("quick", "moderate", "strict"):
        assert not FT._proposed_ask_is_material(
            _proposal(span=12, calories=90), mode=mode, user=_user(mode)), mode


def test_a_large_unknown_earns_a_question_in_every_mode():
    """400 calories in doubt on a 500-calorie plate — 18% of the day. Quick
    swallowed this, because quick opts out of the proportion rule and 400/500
    is below its threshold. Absolute size overrides proportion now."""
    for mode in ("quick", "moderate", "strict"):
        assert FT._proposed_ask_is_material(
            _proposal(span=400, calories=500), mode=mode, user=_user(mode)), mode


def test_modes_disagree_in_the_middle():
    """The whole point of modes. A middling unknown is worth a question to
    someone tracking closely and not to someone logging fast — one rule, three
    dials, rather than three different behaviours."""
    p = _proposal(span=60, calories=300)
    assert not FT._proposed_ask_is_material(p, mode="quick", user=_user("quick"))
    assert FT._proposed_ask_is_material(p, mode="strict", user=_user("strict"))


# ── the fail-safe ────────────────────────────────────────────────────────────

def test_an_unweighable_proposal_is_kept_not_committed():
    """Silence is not evidence of no doubt. A proposal reporting no consequence
    gives no grounds to call the question unnecessary, so it stands — reading
    it as "immaterial" commits a number nobody established."""
    bare = {"action": "ask",
            "items": [{"food": "Chicken shish", "amount": 3, "unit": "piece"}],
            "points": [{"label": "Chicken shish",
                        "q": "chunks off the skewer, or whole skewers?"}]}
    for mode in ("quick", "moderate", "strict"):
        assert FT._proposed_ask_is_material(bare, mode=mode,
                                            user=_user(mode)), mode


def test_an_unsized_item_still_scores_on_the_day():
    """No calories on the row yet — the day proportion is still knowable, and
    refusing on the missing denominator would drop every early-stage
    uncertainty."""
    p = {"action": "ask",
         "items": [{"food": "Thing", "amount": 1, "unit": "plate"}],
         "ambiguities": [{"item": "Thing", "field": "identity",
                          "impact_cal": 400}],
         "points": [{"label": "Thing", "qs": ["what was in it?"]}]}
    assert FT._proposed_ask_is_material(p, mode="strict", user=_user("strict"))


# ── the override is about the day, not the item ──────────────────────────────

def test_absolute_size_overrides_proportion():
    """An unknown worth this much of a day is worth a question whatever
    fraction of its own item it happens to be — the case quick had backwards,
    asking about a 10-calorie coffee and writing a 500-calorie plate."""
    span = DAY_SHARE_OVERRIDE * TARGETS["calories"] + 10   # just over the line
    assert FT._proposed_ask_is_material(
        _proposal(span=span, calories=4000), mode="quick", user=_user("quick"))
