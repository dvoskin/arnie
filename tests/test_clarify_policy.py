"""The clarification policy engine (build order 7, 8, 15, 25).

The behaviours these pin, in order of how badly they hurt when broken:

  1. a clear food is never re-questioned because a neighbour was ambiguous;
  2. strictness changes the threshold and the transaction policy, never the
     truth;
  3. one bundled question beats three narrow ones, and questions are ranked
     across the whole meal by what they resolve per unit of user effort;
  4. clarification loops are bounded — a fourth re-ask is interrogation.
"""
import pytest

from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                        build_ambiguity)
from skills.nutrition.clarify_policy import (MAX_ROUNDS, ResponseSchema,
                                             TransactionPolicy,
                                             build_questions_for_item, decide)
from skills.nutrition.staging import (FoodClass, FoodIdentity, QuantityIntent,
                                      ResolutionStatus, StagedFoodItem)


def _item(item_id, text="a Fairlife", ambiguities=(), status=None,
          identity=None):
    return StagedFoodItem(
        staged_item_id=item_id, original_text=text,
        food_class=FoodClass.BRANDED,
        identity=identity or FoodIdentity(brand="Fairlife"),
        quantity=QuantityIntent(descriptor="some"),
        ambiguities=tuple(ambiguities),
        resolution_status=status or ResolutionStatus.UNRESOLVED)


def _product_line_amb(item_id, mode="moderate", lead=0.51, second=0.31):
    return build_ambiguity(
        staged_item_id=item_id, ambiguity_type=AmbiguityType.PRODUCT_LINE,
        field_name="product_line", mode=mode,
        calorie_span=190, protein_span=16, item_calories=170,
        options=(AmbiguityOption("Core Power · 26g", lead,
                                 candidate_id="c1"),
                 AmbiguityOption("Elite · 42g", second, candidate_id="c2")))


def _size_amb(item_id, mode="moderate"):
    return build_ambiguity(
        staged_item_id=item_id, ambiguity_type=AmbiguityType.PACKAGE_SIZE,
        field_name="package_size", mode=mode, calorie_span=60, item_calories=140,
        options=(AmbiguityOption("14 oz", 0.6), AmbiguityOption("11.5 oz", 0.4)))


def _quantity_amb(item_id, mode="moderate", span=120):
    return build_ambiguity(
        staged_item_id=item_id,
        ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="consumed_fraction", mode=mode, calorie_span=span,
        item_calories=200,
        options=(AmbiguityOption("the whole thing", 0.5, payload=1.0),
                 AmbiguityOption("about half", 0.5, payload=0.5)))


# ── 1. a clear item is never dragged into a neighbour's ambiguity ─────────────
def test_a_clear_food_is_not_re_questioned_because_a_neighbour_is_vague():
    """"Fairlife, some turkey and 200g of chicken" — the chicken is certain.
    Nothing about the Fairlife should generate a question about it."""
    vague = _item("item_1", "a Fairlife",
                  [_product_line_amb("item_1"), _quantity_amb("item_1")])
    clear = _item("item_2", "200g chicken breast")
    out = decide([vague, clear], mode="moderate")
    assert "item_2" in out.ready_item_ids
    assert all(q.staged_item_id == "item_1" for q in out.questions)


def test_a_rejected_item_is_neither_asked_about_nor_committed():
    rejected = _item("item_3", status=ResolutionStatus.REJECTED,
                     ambiguities=[_product_line_amb("item_3")])
    out = decide([rejected], mode="moderate")
    assert out.ready_item_ids == () and out.held_item_ids == ()
    assert out.questions == ()


def test_an_immaterial_ambiguity_does_not_hold_an_item():
    """Royo Plain vs Royo Everything is ~10 calories. Uncertainty existing is
    not a reason to ask."""
    trivial = build_ambiguity(
        staged_item_id="item_1", ambiguity_type=AmbiguityType.PRODUCT_VARIANT,
        field_name="variant", mode="moderate", calorie_span=10,
        options=(AmbiguityOption("plain", 0.5), AmbiguityOption("sesame", 0.5)))
    out = decide([_item("item_1", ambiguities=[trivial])], mode="moderate")
    assert out.ready_item_ids == ("item_1",)
    assert not out.asks


# ── 2. mode changes policy, not truth ─────────────────────────────────────────
def test_mode_maps_to_transaction_policy():
    items = [_item("item_1", ambiguities=[_product_line_amb("item_1")])]
    assert decide(items, mode="quick").transaction_policy is \
        TransactionPolicy.COMMIT_WITH_ASSUMPTIONS
    assert decide(items, mode="moderate").transaction_policy is \
        TransactionPolicy.PARTIAL_COMMIT
    assert decide(items, mode="strict").transaction_policy is \
        TransactionPolicy.ATOMIC_HOLD


def test_quick_commits_with_a_disclosed_assumption():
    out = decide([_item("item_1",
                        ambiguities=[_product_line_amb("item_1", "quick",
                                                       lead=0.8, second=0.2)])],
                 mode="quick")
    assert out.ready_item_ids == ("item_1",)
    assert len(out.assumptions) == 1
    a = out.assumptions[0]
    assert a.field_name == "product_line"
    assert a.alternatives == ("Elite · 42g",)      # what it could have been
    assert a.nutrition_impact.calories == 190      # and what that would cost
    assert "say the word" in a.user_visible_text


def test_quick_still_asks_when_the_leading_option_is_a_coin_toss():
    """Committing a 0.51/0.49 guess is not low friction, it is wrong."""
    out = decide([_item("item_1",
                        ambiguities=[_product_line_amb("item_1", "quick",
                                                       lead=0.51,
                                                       second=0.49)])],
                 mode="quick")
    assert out.asks and out.ready_item_ids == ()


def test_moderate_commits_the_clear_and_holds_the_ambiguous():
    vague = _item("item_1", ambiguities=[_product_line_amb("item_1")])
    clear = _item("item_2", "200g chicken")
    out = decide([vague, clear], mode="moderate")
    assert out.ready_item_ids == ("item_2",)
    assert out.held_item_ids == ("item_1",)
    assert out.transaction_policy is TransactionPolicy.PARTIAL_COMMIT


def test_strict_holds_the_whole_meal_but_still_only_asks_about_the_unclear():
    """Atomic means the clear item waits — not that it gets questioned."""
    vague = _item("item_1", ambiguities=[_product_line_amb("item_1", "strict")])
    clear = _item("item_2", "200g chicken")
    out = decide([vague, clear], mode="strict")
    assert set(out.held_item_ids) == {"item_1", "item_2"}
    assert out.ready_item_ids == ()
    assert all(q.staged_item_id == "item_1" for q in out.questions)


# ── 3. bundling and global ranking ────────────────────────────────────────────
def test_naturally_paired_ambiguities_become_one_question():
    """Three turns to establish which bottle, what size and how much is worse
    than one sentence — and the sentence's answer is unambiguous because we
    asked for all three."""
    item = _item("item_1", ambiguities=[
        _product_line_amb("item_1"), _size_amb("item_1"),
        _quantity_amb("item_1")])
    questions = build_questions_for_item(item, item.ambiguities)
    assert len(questions) == 1
    q = questions[0]
    assert q.response_schema is ResponseSchema.PRODUCT_AND_FRACTION
    assert set(q.requested_fields) == {"product_line", "package_size",
                                       "consumed_fraction"}
    assert "whole thing" in q.prompt


def test_an_unbundleable_ambiguity_gets_its_own_question():
    item = _item("item_1", "some blueberries",
                 ambiguities=[_quantity_amb("item_1")])
    questions = build_questions_for_item(item, item.ambiguities)
    assert len(questions) == 1
    assert questions[0].response_schema is ResponseSchema.QUANTITY
    assert questions[0].requested_fields == ("consumed_fraction",)


def test_questions_are_ranked_across_the_whole_meal_by_value():
    """Resolved materiality per unit of user effort — the expensive-to-answer
    small question loses to the cheap high-impact one."""
    big = _item("item_1", "a Fairlife",
                ambiguities=[_product_line_amb("item_1"), _size_amb("item_1")])
    small = _item("item_2", "some blueberries",
                  ambiguities=[_quantity_amb("item_2", span=70)])
    out = decide([small, big], mode="moderate", max_questions=2)
    assert out.questions[0].staged_item_id == "item_1"
    assert out.questions[0].value > out.questions[1].value


def test_only_the_top_questions_are_asked():
    """Dumping one question per ambiguity onto the user is the failure mode
    ranking exists to prevent."""
    items = [_item(f"item_{i}", ambiguities=[_quantity_amb(f"item_{i}")])
             for i in range(5)]
    out = decide(items, mode="moderate", max_questions=2)
    assert len(out.questions) == 2
    assert len(out.held_item_ids) == 5      # all still held, only 2 asked


def test_a_question_names_the_exact_fields_it_will_fill():
    """This is what lets the answer be applied without re-interpreting the
    meal."""
    item = _item("item_1", ambiguities=[_product_line_amb("item_1"),
                                        _size_amb("item_1")])
    q = build_questions_for_item(item, item.ambiguities)[0]
    assert q.requested_fields
    assert q.staged_item_id == "item_1"
    assert q.ambiguity_ids


def test_options_are_carried_for_ui_rendering():
    item = _item("item_1", ambiguities=[_product_line_amb("item_1")])
    q = build_questions_for_item(item, item.ambiguities)[0]
    labels = [o.label for o in q.options]
    assert "Core Power · 26g" in labels and "Elite · 42g" in labels
    assert q.options[0].candidate_id == "c1"
    assert q.allows_free_text


# ── 4. bounded loops ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode,limit", sorted(MAX_ROUNDS.items()))
def test_each_mode_stops_asking_after_its_limit(mode, limit):
    # A coin toss, so every mode asks in the first place — quick commits a
    # clear leader outright, which is a different behaviour tested above.
    item = _item("item_1", ambiguities=[
        _product_line_amb("item_1", mode, lead=0.51, second=0.49)])
    assert decide([item], mode=mode, round_number=limit - 1).asks
    spent = decide([item], mode=mode, round_number=limit)
    assert not spent.asks and spent.exhausted


def test_when_rounds_run_out_the_assumption_is_recorded_not_hidden():
    """Stopping the questions must not mean silently guessing. The leading
    option is taken AND disclosed."""
    item = _item("item_1", ambiguities=[
        _product_line_amb("item_1", "quick", lead=0.51, second=0.49)])
    out = decide([item], mode="quick", round_number=MAX_ROUNDS["quick"])
    assert out.exhausted and not out.asks
    assert len(out.assumptions) == 1
    assert out.assumptions[0].alternatives


# ── the decision table is honoured ────────────────────────────────────────────
def test_the_decision_table_rows_match_the_engine():
    """The table is data so every row is testable; the engine must agree with
    it rather than drift from it."""
    from skills.nutrition.clarify_policy import ACTIONS, DECISION_TABLE
    assert DECISION_TABLE
    for mode, _identity_exact, _qty_vague, band, action in DECISION_TABLE:
        assert mode in MAX_ROUNDS
        assert action in ACTIONS
        assert band in ("low", "medium", "high")


def test_an_empty_meal_decides_nothing():
    out = decide([], mode="moderate")
    assert not out.asks and out.ready_item_ids == () and out.held_item_ids == ()
