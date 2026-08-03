"""A serving panel prices a correction the other two arms cannot reach.

PROD 2026-08-03, le#936 on fe#2721. The user corrected "1 small snack bag" of
Sour Gummy Mini Burgers to "1 burger". The changes dict carried

    {"quantity": "1 burger", "parsed_food_name": "Sour Gummy Mini Burgers"}

and no calorie key at all. `apply_portion` needs a mass and the panel — "15
PIECES" — names no grams; `apply_count_correction` needs compatible units and
"bag" and "burger" are not. Both declined, `_apply_portion_correction` returned
without touching `changes`, and the row kept the 15-piece bag's 140 cal and
32.2 g of carbs against ONE gummy burger.

Two signals landed that make the arithmetic derivable, and neither was usable
before: `_serving_count` can now read an uppercase USDA panel at all, and
`unit_counts_the_pieces` knows the burger IS this product's own piece. The
panel says one serving is 15 of them and the row was one serving, so one burger
is a fifteenth of it — from numbers already on the row, no lookup.

Every value below is verbatim from the ledger: `committed` is le#934's payload,
the panel is its `resolution.serving_text`, and `_PER100_LOGGED` is its
`resolution.per100`. `_PER100_HANDOFF` is the slightly different row quoted in
the handoff for this fix; both must price identically, because the arm counts
pieces and never reads the basis to do it.
"""
import pytest

from skills.nutrition.correction_application import (
    apply_count_correction, apply_portion, apply_serving_count_correction)

#: le#934's payload, exactly.
COMMITTED = {"calories": 140.0, "protein": 1.4, "carbs": 32.2, "fats": 0.0,
             "fiber": None, "sugar": None, "sodium": None}
PANEL = "15 PIECES"
FOOD = "Sour Gummy Mini Burgers"

#: le#934's `resolution.per100`.
_PER100_LOGGED = {"protein": 3.33, "fat": 0.0, "carbs": 76.7, "calories": 333,
                  "sugar": 43.3, "sodium": 100}
#: The same basis as quoted in the handoff.
_PER100_HANDOFF = {"calories": 350.0, "protein": 3.33, "carbs": 80.0,
                   "fat": 0.0}


def _correct(old="1 small snack bag", new="1 burger", committed=None,
             panel=PANEL, per100=None, food=FOOD):
    return apply_serving_count_correction(
        food_name=food, old_quantity=old, new_quantity=new,
        committed=COMMITTED if committed is None else committed,
        serving_text=panel, per100=per100)


# ── the row prod got wrong ────────────────────────────────────────────────────
def test_one_gummy_burger_is_a_fifteenth_of_the_bag():
    """THE REGRESSION. 140 cal over 15 pieces is 9.3, not 140."""
    scaled = _correct(per100=_PER100_LOGGED)
    assert scaled is not None, (
        "the arm that exists for fe#2721 declined the row it was written for")
    assert scaled["calories"] == pytest.approx(9.3, abs=0.1)
    assert scaled["carbs"] == pytest.approx(2.1, abs=0.1)
    assert scaled["protein"] == pytest.approx(0.1, abs=0.05)
    assert scaled["fats"] == pytest.approx(0.0, abs=0.05)


def test_the_basis_is_not_what_prices_it():
    """The two arms above price off a per-100g row; this one counts. So the
    exact basis cannot move the answer, and a row that stored none at all —
    the whole `basis: regular` population — is priced the same."""
    assert (_correct(per100=_PER100_LOGGED)["calories"]
            == _correct(per100=_PER100_HANDOFF)["calories"]
            == _correct(per100=None)["calories"]
            == pytest.approx(9.3, abs=0.1))


def test_a_nutrient_the_row_never_knew_stays_unknown():
    """The row carried no fiber, sugar or sodium. A rescale that filled them
    with zeros would put three numbers on the board that no source produced."""
    scaled = _correct(per100=_PER100_LOGGED)
    assert "fiber" not in scaled and "sugar" not in scaled
    assert "sodium" not in scaled


def test_the_first_two_arms_still_decline_it():
    """This arm is an addition, not a replacement — the reason it had to exist
    is that neither of the others can reach this shape, and that stays true."""
    both = dict(food_name=FOOD, old_quantity="1 small snack bag",
                new_quantity="1 burger", committed=COMMITTED)
    assert apply_portion(**both, per100=_PER100_HANDOFF,
                         serving_text=PANEL) is None
    assert apply_count_correction(**both) is None


# ── it counts in both directions ──────────────────────────────────────────────
def test_more_than_one_piece_scales_up():
    assert _correct(new="3 burgers")["calories"] == pytest.approx(28.0, abs=0.1)


def test_the_panels_own_word_answers_too():
    """"2 pieces" needs no food-name reading — the panel counts pieces."""
    assert _correct(new="2 pieces")["calories"] == pytest.approx(18.7, abs=0.1)


def test_two_bags_hold_thirty_pieces():
    """The premise is `old` WHOLE servings, not always one."""
    assert _correct(old="2 bags")["calories"] == pytest.approx(4.7, abs=0.1)


# ── the premise is fenced ─────────────────────────────────────────────────────
@pytest.mark.parametrize("old,why", [
    ("1 piece", "already a piece — dividing again makes it a 225th"),
    ("2 burgers", "the product's own noun counts pieces, not servings"),
    ("1.5 bags", "not a whole number of servings"),
    ("half a bag", "half a serving is not a count of servings"),
    ("2 handfuls", "a helping is not one of the label's servings"),
    ("whatever was left", "amount=1.0 is the parser's default, not a claim"),
    ("40 g", "a mass is not a count"),
])
def test_an_old_quantity_that_is_not_whole_servings_declines(old, why):
    """A WRONG STRIP CHANGES WHAT THE ROW MEANS, so every way the premise can
    fail is a decline and the seam guard stays the floor."""
    assert _correct(old=old) is None, why


@pytest.mark.parametrize("new,why", [
    ("2 handfuls", "a handful is not one of the panel's pieces"),
    ("1 bottle", "a different object entirely"),
    ("40 g", "a mass has no count to divide"),
    ("0 burgers", "nothing is not a portion"),
])
def test_a_new_quantity_that_is_not_a_piece_declines(new, why):
    assert _correct(new=new) is None, why


@pytest.mark.parametrize("panel", ["", "42 g", "one serving"])
def test_a_panel_that_enumerates_nothing_declines(panel):
    """Without a count on the panel there is no denominator to divide by."""
    assert _correct(panel=panel) is None


def test_a_unit_that_names_a_different_food_is_not_this_ones_piece():
    """`unit_counts_the_pieces` reads the FOOD's name. "1 burger" against a bag
    of gummy worms counts nothing the panel enumerates."""
    assert _correct(food="Sour Gummy Worms", new="1 burger") is None


# ── where the premise is checkable, it is checked ─────────────────────────────
def test_a_bag_that_is_not_one_serving_is_refuted_by_its_own_mass():
    """Sun Chips: the panel says 28 g is about 15 chips, and a 210-cal bag at
    536 cal/100 g is 39.2 g — 1.4 servings, so the bag holds ~21 chips, not 15.
    Reading "1 bag" as one serving would price 9 chips at 126 instead of 90.

    The row's real serving multiple is arithmetic on stored numbers and the
    count is only wording, so a disagreement is never resolved in favour of the
    wording. (That correction is priced correctly by mass one arm up — what
    this protects is the case where it would not be.)
    """
    assert apply_serving_count_correction(
        food_name="Sun Chips Harvest Cheddar", old_quantity="1 bag",
        new_quantity="9 chips",
        committed={"calories": 210.0, "protein": 3.0},
        per100={"calories": 536, "protein": 7.1},
        serving_text="28 g (about 15 chips)") is None


def test_a_bag_that_is_one_serving_survives_the_same_check():
    """The check refutes a mismatch; it does not refuse everything it can
    measure. 150 cal at 536 cal/100 g is 28 g — exactly the panel's serving —
    so 9 of its 15 chips is 90."""
    scaled = apply_serving_count_correction(
        food_name="Sun Chips Harvest Cheddar", old_quantity="1 bag",
        new_quantity="9 chips",
        committed={"calories": 150.0, "protein": 2.0},
        per100={"calories": 536, "protein": 7.1},
        serving_text="28 g (about 15 chips)")
    assert scaled is not None
    assert scaled["calories"] == pytest.approx(90.0, abs=0.5)


# ── through the seam that actually shipped the bug ────────────────────────────
class _Gummies:
    """What the ladder returned for le#934, field for field."""
    calories = 140.0
    protein = 1.4
    carbs = 32.2
    fat = 0.0
    fiber = None
    sugar = None
    sodium = None
    fdc_id = "2524698"
    confidence = "likely"
    source = "usda"
    protein_density = None
    satiety = None
    quality = None
    per100 = dict(_PER100_LOGGED)
    serving_text = PANEL
    micros: dict = {}
    micros_estimated = False
    coach_note = ""
    enrichment_source = "usda"
    provenance = None


async def _loaded(db, user_id):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from db.models import User
    return (await db.execute(
        select(User).where(User.id == user_id)
        .options(selectinload(User.preferences)))).scalars().one()


async def test_the_row_prod_left_at_140_is_re_derived(db, make_user,
                                                      monkeypatch, caplog):
    """END TO END, through `_apply_portion_correction` itself.

    le#936's changes verbatim — quantity and the unchanged name, NO calorie key
    — which is precisely what the seam guard could only mark estimated. The
    guard is still the floor; this is it having less to do.
    """
    import logging

    from sqlalchemy import select

    from db.models import FoodEntry
    from db.queries import get_or_create_today_log
    from handlers.tool_executor import execute_tool_calls

    async def _analyze(db_, user_, food_name, inp, *a, **k):
        return _Gummies()
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _analyze)

    user = await _loaded(db, (await make_user()).id)
    await execute_tool_calls(
        [{"name": "log_food",
          "input": {"food_name": FOOD, "quantity": "1 small snack bag",
                    "calories": 140, "protein": 1.4, "carbs": 32.2,
                    "fats": 0}}],
        user, await get_or_create_today_log(db, user.id), db)
    row = (await db.execute(select(FoodEntry))).scalars().first()
    assert row is not None and row.calories == pytest.approx(140.0)

    with caplog.at_level(logging.WARNING):
        await execute_tool_calls(
            [{"name": "update_food_entry",
              "input": {"entry_id": row.id, "quantity": "1 burger",
                        "food_name": FOOD}}],
            user, await get_or_create_today_log(db, user.id), db)
    await db.refresh(row)

    assert row.quantity == "1 burger"
    assert row.calories == pytest.approx(9.3, abs=0.5), (
        "the row still carries the whole bag's calories against one gummy")
    assert row.carbs == pytest.approx(2.1, abs=0.3)
    assert "unpriced_portion_change" not in caplog.text, (
        "the seam fell through to the guard on a correction it can now price")


# ── the signals this arm is built on ──────────────────────────────────────────
def test_the_two_signals_that_made_it_derivable():
    """Both landed on this branch and neither was usable before: the panel was
    unreadable in caps, and nothing could tell that a burger is this product's
    own piece."""
    from skills.nutrition.normalize import (_serving_count,
                                            unit_counts_the_pieces)

    assert _serving_count(PANEL) == (15.0, "piece")
    assert unit_counts_the_pieces("burger", FOOD, "piece") is True
    # And it is not a synonym for the compatibility check it composes.
    from skills.nutrition.normalize import count_units_compatible
    assert count_units_compatible("burger", "piece") is False
    # A noun that names no product and matches no panel word counts nothing.
    assert unit_counts_the_pieces("bag", FOOD, "piece") is False
