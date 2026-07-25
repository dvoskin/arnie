"""Mixed commit states and meal grouping (build order 10, 11, 12).

One meal can legitimately contain, at the same moment: an exact item, an
estimated item, a held item and a failed write. Every earlier version
collapsed to one state per turn, and both collapses are wrong — "all
committed" describes the held item as logged, "all held" makes the certain
chicken wait on the uncertain bottle.

The grouping half is what makes partial commit survivable: a held item's later
resolution must join the SAME meal, not appear an hour later as an unrelated
entry with its own card and totals that add up to nothing.
"""
import pytest

from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                        build_ambiguity)
from skills.nutrition.clarify_policy import decide
from skills.nutrition.meal_resolution import (ItemOutcome, attach_to_meal,
                                              build_resolution,
                                              drop_from_meal)
from skills.nutrition.staging import (FoodClass, FoodIdentity, QuantityIntent,
                                      ResolutionStatus, StagedFoodItem,
                                      make_meal_group_id)

MEAL = make_meal_group_id("imessage:G-1")


def _item(item_id, text, *, ambiguities=(), status=None, name=None,
          food_class=FoodClass.GENERIC, quantity=None):
    return StagedFoodItem(
        staged_item_id=item_id, original_text=text, food_class=food_class,
        identity=FoodIdentity(canonical_name=name or text),
        quantity=quantity or QuantityIntent(stated_amount=200,
                                            stated_unit="g"),
        ambiguities=tuple(ambiguities), meal_group_id=MEAL,
        resolution_status=status or ResolutionStatus.UNRESOLVED)


def _material_amb(item_id):
    return build_ambiguity(
        staged_item_id=item_id, ambiguity_type=AmbiguityType.PRODUCT_LINE,
        field_name="product_line", mode="moderate", calorie_span=190,
        options=(AmbiguityOption("Core Power · 26g", 0.51, candidate_id="c1"),
                 AmbiguityOption("Elite · 42g", 0.31, candidate_id="c2")))


def _wrote(entry_id, name, cal=None, protein=None, **kw):
    nutrients = {}
    if cal is not None:
        nutrients["calories"] = cal
    if protein is not None:
        nutrients["protein"] = protein
    return {"entry_id": entry_id, "event_id": entry_id + 100, "name": name,
            "nutrients": nutrients, "source": "usda", **kw}


# ── the mixed state exists ────────────────────────────────────────────────────
def test_one_meal_holds_exact_estimated_held_and_failed_at_once():
    """The state the whole module exists for."""
    chicken = _item("i1", "200g chicken")
    berries = _item("i2", "a handful of blueberries",
                    status=ResolutionStatus.RESOLVED_ESTIMATED,
                    quantity=QuantityIntent(descriptor="a handful",
                                            estimated_mass_g=45))
    fairlife = _item("i3", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i3")])
    broken = _item("i4", "200g rice")

    decision = decide([chicken, berries, fairlife, broken], mode="moderate")
    out = build_resolution(
        meal_group_id=MEAL, items=[chicken, berries, fairlife, broken],
        decision=decision,
        execution_by_item={
            "i1": _wrote(1, "Chicken breast", cal=330, protein=62),
            "i2": _wrote(2, "Blueberries", cal=26),
            # i4 was ready but the executor refused it.
            "i4": {"entry_id": None, "reason": "duplicate_blocked"},
        })

    outcomes = {c.staged_item_id: c.outcome for c in out.committed}
    assert outcomes["i1"] is ItemOutcome.COMMITTED_EXACT
    assert outcomes["i2"] is ItemOutcome.COMMITTED_ESTIMATED
    assert [p.staged_item_id for p in out.pending] == ["i3"]
    assert [f.staged_item_id for f in out.failed] == ["i4"]
    assert out.is_partial and not out.is_complete
    assert "1 exact, 1 estimated; 1 held; 1 failed" == out.describe_state()


def test_ready_but_unwritten_is_failed_not_committed():
    """The distinction narration depends on. A dedup-blocked write is not a
    log, however ready the policy thought it was."""
    item = _item("i1", "200g chicken")
    out = build_resolution(
        meal_group_id=MEAL, items=[item], decision=decide([item], mode="quick"),
        execution_by_item={"i1": {"entry_id": None, "reason": "dedup"}})
    assert out.committed == ()
    assert out.failed[0].reason == "dedup"
    assert out.committed_nothing


def test_an_item_the_decision_did_not_cover_is_held_not_assumed_written():
    """Held is the safe default. An uncovered item must never be reported as
    logged."""
    item = _item("i1", "200g chicken")

    class _EmptyDecision:
        ready_item_ids = ()
        held_item_ids = ()
        questions = ()
        assumptions = ()

    out = build_resolution(meal_group_id=MEAL, items=[item],
                           decision=_EmptyDecision())
    assert out.committed == ()
    assert out.pending[0].reason == "undecided"


def test_a_rejected_item_is_skipped_not_failed():
    item = _item("i1", "something impossible",
                 status=ResolutionStatus.REJECTED)
    out = build_resolution(meal_group_id=MEAL, items=[item],
                           decision=decide([item], mode="moderate"))
    assert out.skipped[0].outcome is ItemOutcome.SKIPPED
    assert out.failed == () and out.committed == ()


# ── totals count only what is in the day ──────────────────────────────────────
def test_totals_exclude_held_items():
    """A card showing three items and a total matching two of them is the bug
    this prevents. A held item is not in the day, so it contributes nothing."""
    chicken = _item("i1", "200g chicken")
    fairlife = _item("i2", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i2")])
    out = build_resolution(
        meal_group_id=MEAL, items=[chicken, fairlife],
        decision=decide([chicken, fairlife], mode="moderate"),
        execution_by_item={"i1": _wrote(1, "Chicken", cal=330, protein=62)})
    assert out.totals() == {"calories": 330.0, "protein": 62.0}


def test_totals_sum_across_committed_items_only():
    a = _item("i1", "200g chicken")
    b = _item("i2", "100g rice")
    out = build_resolution(
        meal_group_id=MEAL, items=[a, b],
        decision=decide([a, b], mode="quick"),
        execution_by_item={"i1": _wrote(1, "Chicken", cal=330, protein=62),
                           "i2": _wrote(2, "Rice", cal=130, protein=3)})
    assert out.totals() == {"calories": 460.0, "protein": 65.0}


def test_a_none_nutrient_is_not_counted_as_zero():
    a = _item("i1", "200g chicken")
    out = build_resolution(
        meal_group_id=MEAL, items=[a], decision=decide([a], mode="quick"),
        execution_by_item={"i1": {"entry_id": 1, "name": "Chicken",
                                  "nutrients": {"calories": 330,
                                                "sodium": None}}})
    assert out.totals() == {"calories": 330.0}
    assert "sodium" not in out.totals()


# ── grouping across a partial commit ──────────────────────────────────────────
def test_a_resolved_held_item_joins_the_same_meal():
    """The failure this closes: the answer arrives an hour later and becomes
    an unrelated entry with its own card."""
    chicken = _item("i1", "200g chicken")
    fairlife = _item("i2", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i2")])
    out = build_resolution(
        meal_group_id=MEAL, items=[chicken, fairlife],
        decision=decide([chicken, fairlife], mode="moderate"),
        execution_by_item={"i1": _wrote(1, "Chicken", cal=330)})
    assert out.is_partial

    joined = attach_to_meal(out, staged_item_id="i2", entry_id=9, event_id=109,
                            name="Core Power Elite", quantity_text="14 oz",
                            nutrients={"calories": 230, "protein": 42},
                            source="off", confidence=0.9)
    assert joined.is_complete
    assert {c.meal_group_id for c in joined.committed} == {MEAL}
    assert joined.totals() == {"calories": 560.0, "protein": 42.0}
    assert joined.pending == ()


def test_attaching_an_estimated_answer_marks_it_estimated():
    from skills.nutrition.staging import FoodAssumption
    fairlife = _item("i1", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i1")])
    out = build_resolution(meal_group_id=MEAL, items=[fairlife],
                           decision=decide([fairlife], mode="moderate"))
    joined = attach_to_meal(
        out, staged_item_id="i1", entry_id=9, name="Core Power",
        assumptions=(FoodAssumption(staged_item_id="i1",
                                    field_name="product_line",
                                    assumed_value="Core Power"),))
    assert joined.committed[0].outcome is ItemOutcome.COMMITTED_ESTIMATED
    assert joined.assumptions


def test_attaching_an_unknown_item_is_a_no_op():
    """A late answer naming an item this meal never held must not invent one."""
    item = _item("i1", "200g chicken")
    out = build_resolution(meal_group_id=MEAL, items=[item],
                           decision=decide([item], mode="quick"),
                           execution_by_item={"i1": _wrote(1, "Chicken")})
    assert attach_to_meal(out, staged_item_id="nope", entry_id=99) == out


def test_skipping_a_held_item_does_not_cancel_what_committed():
    """"don't log the yogurt" removes one item. It is not "cancel the meal"."""
    chicken = _item("i1", "200g chicken")
    fairlife = _item("i2", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i2")])
    out = build_resolution(
        meal_group_id=MEAL, items=[chicken, fairlife],
        decision=decide([chicken, fairlife], mode="moderate"),
        execution_by_item={"i1": _wrote(1, "Chicken", cal=330)})
    dropped = drop_from_meal(out, "i2")
    assert dropped.is_complete
    assert len(dropped.committed) == 1          # the chicken survives
    assert dropped.skipped[0].reason == "user_skipped"
    assert dropped.totals() == {"calories": 330.0}


def test_the_meal_group_is_shared_by_every_item_regardless_of_state():
    chicken = _item("i1", "200g chicken")
    fairlife = _item("i2", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i2")])
    rejected = _item("i3", "nonsense", status=ResolutionStatus.REJECTED)
    out = build_resolution(
        meal_group_id=MEAL, items=[chicken, fairlife, rejected],
        decision=decide([chicken, fairlife, rejected], mode="moderate"),
        execution_by_item={"i1": _wrote(1, "Chicken")})
    groups = {i.meal_group_id for i in
              (*out.committed, *out.pending, *out.skipped)}
    assert groups == {MEAL}
    assert set(out.item_ids()) == {"i1", "i2", "i3"}


# ── the pending item carries what binds an answer ─────────────────────────────
def test_a_pending_item_names_the_question_and_fields_it_awaits():
    """An incoming answer binds to THIS, never to the meal or the most recent
    food."""
    fairlife = _item("i1", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i1")])
    decision = decide([fairlife], mode="moderate")
    out = build_resolution(meal_group_id=MEAL, items=[fairlife],
                           decision=decision)
    held = out.pending_for("i1")
    assert held.question_id == decision.questions[0].question_id
    assert held.requested_fields == decision.questions[0].requested_fields
    assert held.reason == "product_line"
    assert held.original_text == "a Fairlife"


def test_strict_holds_everything_and_commits_nothing_yet():
    chicken = _item("i1", "200g chicken")
    fairlife = _item("i2", "a Fairlife", food_class=FoodClass.BRANDED,
                     ambiguities=[_material_amb("i2")])
    out = build_resolution(
        meal_group_id=MEAL, items=[chicken, fairlife],
        decision=decide([chicken, fairlife], mode="strict"),
        execution_by_item={})
    assert out.committed == ()
    assert {p.staged_item_id for p in out.pending} == {"i1", "i2"}
    # The clear item is held, not questioned.
    assert out.pending_for("i1").reason == "atomic_hold"
    assert out.pending_for("i1").question_id == ""


def test_an_empty_meal_resolves_to_nothing():
    out = build_resolution(meal_group_id=MEAL, items=[],
                           decision=decide([], mode="moderate"))
    assert out.describe_state() == "nothing"
    assert out.is_complete and out.committed_nothing
