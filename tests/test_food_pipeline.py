"""The one food-resolution path (review 2026-07-25, P0).

The staged-item architecture was built, tested, and never put in the way of a
real turn — the live path kept using the interpreter's JSON and the calorie-only
`food_ledger.material_ambiguities()`. Two architectures, one unreachable.

These tests pin the seam that ends that, and the properties that make it safe to
put in the live path: it never writes, it never raises, and any failure returns
None so the caller keeps its existing behaviour.
"""
import pytest

import core.food_pipeline as FP
from skills.nutrition.clarify_policy import TransactionPolicy
from skills.nutrition.staging import FoodClass

TURN = "imessage:G-1"


def _data(items=None, ambiguities=None, calls=None):
    return {"action": "log", "items": items or [], "say": "",
            "ambiguities": ambiguities or [], "_calls": calls or []}


def _item(food, amount=None, unit=None, brand=None, **kw):
    return {"food": food, "amount": amount, "unit": unit, "brand": brand, **kw}


# ── staging ───────────────────────────────────────────────────────────────────
def test_every_interpreted_item_becomes_a_staged_item():
    items, meal = FP.stage_items(
        _data([_item("toast", 1, "slice"), _item("gooseberry jam", 1, "tbsp")]),
        turn_id=TURN, message="I had gooseberry jam on a piece of toast")
    assert len(items) == 2
    assert all(i.meal_group_id == meal for i in items)
    assert len({i.staged_item_id for i in items}) == 2       # distinct rows


def test_identity_stops_being_a_bare_string():
    items, _ = FP.stage_items(_data([_item("Core Power", 1, "bottle",
                                           brand="Fairlife")]),
                              turn_id=TURN, message="a Fairlife")
    assert items[0].identity.brand == "Fairlife"
    assert items[0].food_class is FoodClass.BRANDED


def test_a_stated_amount_is_distinguished_from_an_inferred_one():
    """The distinction the old path collapsed and then could not ask about."""
    stated, _ = FP.stage_items(_data([_item("rice", 200, "g")]),
                               turn_id=TURN, message="200g of rice")
    assert stated[0].quantity.is_stated

    inferred, _ = FP.stage_items(_data([_item("rice", 1, "bowl")]),
                                 turn_id=TURN, message="a bowl of rice")
    assert inferred[0].quantity.stated_amount == 1


def test_an_item_with_no_food_name_is_dropped_not_staged_blank():
    items, _ = FP.stage_items(_data([_item(""), _item("toast", 1, "slice")]),
                              turn_id=TURN)
    assert len(items) == 1 and items[0].original_text == "toast"


def test_staged_ids_are_stable_within_a_turn():
    a, _ = FP.stage_items(_data([_item("toast")]), turn_id=TURN)
    b, _ = FP.stage_items(_data([_item("toast")]), turn_id=TURN)
    assert a[0].staged_item_id == b[0].staged_item_id


# ── ambiguities land on the right item ────────────────────────────────────────
def test_an_ambiguity_binds_to_the_item_it_names():
    items, _ = FP.stage_items(_data([_item("toast", 1, "slice"),
                                     _item("poke bowl", 1, "bowl")]),
                              turn_id=TURN)
    items = FP.attach_ambiguities(
        items, _data(ambiguities=[{"item": "poke bowl", "field": "consumed",
                                   "impact_cal": 250}]), mode="moderate")
    by_name = {i.original_text: i for i in items}
    assert by_name["poke bowl"].ambiguities
    assert not by_name["toast"].ambiguities


def test_an_unmatched_ambiguity_is_dropped_not_applied_to_the_first_item():
    """A question about the wrong food is worse than no question."""
    items, _ = FP.stage_items(_data([_item("toast"), _item("rice")]),
                              turn_id=TURN)
    items = FP.attach_ambiguities(
        items, _data(ambiguities=[{"item": "shawarma", "field": "consumed",
                                   "impact_cal": 400}]), mode="moderate")
    assert not any(i.ambiguities for i in items)


def test_a_single_item_turn_takes_an_unnamed_ambiguity():
    items, _ = FP.stage_items(_data([_item("poke bowl")]), turn_id=TURN)
    items = FP.attach_ambiguities(
        items, _data(ambiguities=[{"field": "consumed", "impact_cal": 300}]),
        mode="moderate")
    assert items[0].ambiguities


def test_protein_risk_is_scored_not_just_calories():
    """The old policy read one number against a calorie-only threshold, so an
    item that was calorie-tight and protein-wild sailed through."""
    items, _ = FP.stage_items(_data([_item("protein shake")]), turn_id=TURN)
    items = FP.attach_ambiguities(
        items, _data(ambiguities=[{"field": "product", "impact_cal": 30,
                                   "impact_protein": 25}]), mode="moderate")
    amb = items[0].ambiguities[0]
    assert amb.protein_span == 25
    assert amb.is_material          # calories alone would not have fired


# ── the decision ──────────────────────────────────────────────────────────────
def test_a_clear_meal_produces_no_question():
    decision = FP.plan_turn(_data([_item("rice", 200, "g")]), turn_id=TURN,
                            message="200g rice", mode="moderate")
    assert decision is not None
    assert not decision.asks


def test_a_material_ambiguity_produces_one_bound_question():
    decision = FP.plan_turn(
        _data([_item("poke bowl")],
              ambiguities=[{"item": "poke bowl", "field": "consumed",
                            "impact_cal": 400}]),
        turn_id=TURN, message="a poke bowl", mode="moderate")
    assert decision.asks
    question = decision.question
    # The binding that makes a later answer land on one row.
    assert question.staged_item_id == decision.staged_items[0].staged_item_id
    assert question.question_id and question.requested_fields


def test_mode_changes_the_transaction_policy_not_the_items():
    args = dict(items=[_item("poke bowl")],
                ambiguities=[{"item": "poke bowl", "field": "consumed",
                              "impact_cal": 400}])
    policies = {}
    for mode in ("quick", "moderate", "strict"):
        d = FP.plan_turn(_data(**args), turn_id=TURN, message="a poke bowl",
                         mode=mode)
        policies[mode] = d.clarification.transaction_policy
    assert policies["quick"] is TransactionPolicy.COMMIT_WITH_ASSUMPTIONS
    assert policies["moderate"] is TransactionPolicy.PARTIAL_COMMIT
    assert policies["strict"] is TransactionPolicy.ATOMIC_HOLD


def test_only_cleared_items_reach_approved_operations():
    """The veto. The interpreter's calls are FILTERED, not rebuilt — unit, id
    and provenance construction stays in one place."""
    calls = [{"name": "log_food", "input": {"food_name": "toast"}},
             {"name": "log_food", "input": {"food_name": "poke bowl"}}]
    decision = FP.plan_turn(
        _data([_item("toast", 1, "slice"), _item("poke bowl")],
              ambiguities=[{"item": "poke bowl", "field": "consumed",
                            "impact_cal": 400}],
              calls=calls),
        turn_id=TURN, message="toast and a poke bowl", mode="moderate")
    approved = [c["input"]["food_name"] for c in decision.approved_operations]
    assert approved == ["toast"]


def test_strict_approves_nothing_until_the_meal_resolves():
    calls = [{"name": "log_food", "input": {"food_name": "toast"}},
             {"name": "log_food", "input": {"food_name": "poke bowl"}}]
    decision = FP.plan_turn(
        _data([_item("toast", 1, "slice"), _item("poke bowl")],
              ambiguities=[{"item": "poke bowl", "field": "consumed",
                            "impact_cal": 400}], calls=calls),
        turn_id=TURN, message="toast and a poke bowl", mode="strict")
    assert decision.approved_operations == ()
    assert decision.holds_everything


# ── it never takes the turn down ──────────────────────────────────────────────
def test_malformed_interpreter_output_returns_none():
    """None means "keep doing what you were doing", which is what makes this
    safe to put in the live path."""
    assert FP.plan_turn({"items": "not a list"}, turn_id=TURN) is None
    assert FP.plan_turn({}, turn_id=TURN) is None


def test_a_crash_inside_the_policy_returns_none(monkeypatch):
    import skills.nutrition.clarify_policy as CP
    monkeypatch.setattr(FP, "decide", None, raising=False)

    def _boom(*a, **k):
        raise RuntimeError("policy exploded")
    monkeypatch.setattr(CP, "decide", _boom)
    assert FP.plan_turn(_data([_item("toast")]), turn_id=TURN) is None


def test_the_kill_switch_is_honoured(monkeypatch):
    monkeypatch.setenv("FOOD_PIPELINE", "false")
    assert not FP.pipeline_enabled()
    monkeypatch.setenv("FOOD_PIPELINE", "true")
    assert FP.pipeline_enabled()
    monkeypatch.delenv("FOOD_PIPELINE", raising=False)
    assert FP.pipeline_enabled()          # on by default


def test_the_pipeline_never_writes():
    """It decides what MAY be written. A pipeline that writes would be a second
    executor to keep in step."""
    import inspect
    source = inspect.getsource(FP)
    for forbidden in ("db.commit", "db.add", "session.add", "execute_tool_calls"):
        assert forbidden not in source


# ── learned preferences arrive as assumptions ─────────────────────────────────
class _Pref:
    trigger_term = "fairlife"
    brand = "Fairlife"
    product_line = "Core Power Elite"
    variant = None
    canonical_name = None
    confidence = 0.9

    def describe(self):
        return "Fairlife Core Power Elite"


def test_a_promoted_preference_fills_the_gap_and_says_so():
    """Applied as an ASSUMPTION, never silently — a correction needs something
    to contradict."""
    from datetime import datetime
    from skills.nutrition.preferences import UserFoodPreference

    now = datetime(2026, 7, 25, 12, 0)
    pref = UserFoodPreference(trigger_term="fairlife", brand="Fairlife",
                              product_line="Core Power Elite", confirmations=3,
                              promoted_at=now, confidence=0.9)
    items, _ = FP.stage_items(_data([_item("Fairlife")]), turn_id=TURN)
    out = FP.apply_preferences(items, [pref], now=now, mode="moderate")
    assert out[0].identity.product_line == "Core Power Elite"
    assert out[0].assumptions
    assert "usual" in out[0].assumptions[0].user_visible_text


def test_an_unpromoted_preference_changes_nothing():
    from datetime import datetime
    from skills.nutrition.preferences import UserFoodPreference
    now = datetime(2026, 7, 25, 12, 0)
    pref = UserFoodPreference(trigger_term="fairlife", brand="Fairlife",
                              product_line="Core Power Elite", confirmations=1)
    items, _ = FP.stage_items(_data([_item("Fairlife")]), turn_id=TURN)
    out = FP.apply_preferences(items, [pref], now=now, mode="moderate")
    assert out[0].identity.product_line is None
    assert not out[0].assumptions


def test_no_preferences_is_a_no_op():
    items, _ = FP.stage_items(_data([_item("toast")]), turn_id=TURN)
    assert FP.apply_preferences(items, None) == items


# ── the live path uses it ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_live_interpreter_asks_through_the_pipeline(monkeypatch):
    """The point of the exercise: run() no longer decides with the calorie-only
    policy. The ask it returns carries the bindings a narrow parser needs."""
    import core.food_turn as FT
    from tests.test_food_turn import _fake_chat

    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "poke bowl", "amount": 1, "unit": "bowl",
                   "calories": 700, "basis": "estimate"}],
        "ambiguities": [{"item": "poke bowl", "field": "consumed",
                         "impact_cal": 400}],
        "say": "Bowl logged, {batch_cal} cal."}))

    class _Prefs:
        food_logging_mode = "moderate"

    class _User:
        id = 7
        preferences = _Prefs()

    out = await FT.run("had a poke bowl", _User())
    assert out["action"] == "ask"
    # These three are what bind an answer to one row and one field set.
    assert out.get("question_id")
    assert out.get("staged_item_id")
    assert out.get("requested_fields")


@pytest.mark.asyncio
async def test_the_kill_switch_restores_the_old_policy(monkeypatch):
    import core.food_turn as FT
    from tests.test_food_turn import _fake_chat
    monkeypatch.setenv("FOOD_PIPELINE", "false")
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "poke bowl", "amount": 1, "unit": "bowl",
                   "calories": 700, "basis": "estimate"}],
        "ambiguities": [{"item": "poke bowl", "field": "consumed",
                         "impact_cal": 400}],
        "say": "Bowl logged, {batch_cal} cal."}))

    class _Prefs:
        food_logging_mode = "moderate"

    class _User:
        id = 7
        preferences = _Prefs()

    out = await FT.run("had a poke bowl", _User())
    assert out["action"] == "ask"
    assert out.get("question_id") is None       # legacy shape
