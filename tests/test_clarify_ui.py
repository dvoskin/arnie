"""UI payloads and per-item traces (directive 26, 27).

A clarification rendered as prose forces the user to type an answer we already
know the shape of. The structured payload lets iOS render chips and a fraction
control — and a tapped chip returns a candidate id, which is unambiguous in a
way free text never is.

The trace is the other half: one line per item saying what was found, what was
chosen and what was decided. Without it a wrong question is reproducible only by
guessing at the conversation that produced it.
"""
import pytest

from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                        build_ambiguity)
from skills.nutrition.candidate_sets import ProductCandidate
from skills.nutrition.clarify_policy import ResponseSchema, decide
from skills.nutrition.clarify_ui import (ExitAction, FRACTION_CHOICES,
                                         build_item_trace, build_traces,
                                         build_ui_model, build_ui_models)
from skills.nutrition.models import profile_from_values
from skills.nutrition.provenance import SourceTier
from skills.nutrition.staging import (FoodClass, FoodIdentity, Quantity,
                                      QuantityIntent, StagedFoodItem)


def _bottle_options():
    return (AmbiguityOption("Core Power · 26g", 0.51, payload="Core Power",
                            candidate_id="c1"),
            AmbiguityOption("Elite · 42g", 0.31, payload="Core Power Elite",
                            candidate_id="c2"),
            AmbiguityOption("Nutrition Plan · 30g", 0.18,
                            payload="Nutrition Plan", candidate_id="c3"))


def _item(*, ambiguities=(), candidates=(), text="a Fairlife"):
    return StagedFoodItem(
        staged_item_id="i1", original_text=text,
        food_class=FoodClass.BRANDED,
        identity=FoodIdentity(brand="Fairlife"),
        quantity=QuantityIntent(container_count=1),
        candidate_products=tuple(candidates),
        ambiguities=tuple(ambiguities), meal_group_id="meal_1")


def _line_ambiguity(mode="moderate"):
    return build_ambiguity(
        staged_item_id="i1", ambiguity_type=AmbiguityType.PRODUCT_LINE,
        field_name="product_line", mode=mode, calorie_span=190,
        impact_basis_cal=170,   # a Fairlife — the doubt exceeds the whole drink
        options=_bottle_options())


def _fraction_ambiguity(mode="moderate"):
    return build_ambiguity(
        staged_item_id="i1", ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="consumed_fraction", mode=mode, calorie_span=115,
        impact_basis_cal=160,   # a bowl of berries
        options=(AmbiguityOption("the whole bottle", 0.5, payload=1.0),
                 AmbiguityOption("about half", 0.5, payload=0.5)))


# ── the UI model ──────────────────────────────────────────────────────────────
def test_a_product_question_renders_as_selectable_chips():
    item = _item(ambiguities=[_line_ambiguity()])
    question = decide([item], mode="moderate").questions[0]
    ui = build_ui_model(question, item)

    assert ui.title == question.prompt
    assert ui.schema == ResponseSchema.PRODUCT_SELECTION.value
    assert [o.label for o in ui.options] == ["Core Power · 26g",
                                             "Elite · 42g",
                                             "Nutrition Plan · 30g"]
    # A tapped chip returns an id — unambiguous in a way free text is not.
    assert [o.candidate_id for o in ui.options] == ["c1", "c2", "c3"]


def test_the_subtitle_says_why_we_are_asking():
    """A user who understands the stakes answers faster and resents it less
    than one being quizzed for no stated reason."""
    item = _item(ambiguities=[_line_ambiguity()])
    ui = build_ui_model(decide([item], mode="moderate").questions[0], item)
    assert "different nutrition" in ui.subtitle


def test_a_portion_question_offers_a_fraction_control():
    item = _item(ambiguities=[_fraction_ambiguity()])
    ui = build_ui_model(decide([item], mode="moderate").questions[0], item)
    assert ui.fraction_control == FRACTION_CHOICES
    assert any(label == "Half" for _, label in ui.fraction_control)


def test_fraction_options_do_not_double_as_product_chips():
    """A bundle offers both kinds. Rendering "about half" as a product chip is
    the same confusion that put it in product_line."""
    item = _item(ambiguities=[_line_ambiguity(), _fraction_ambiguity()])
    question = decide([item], mode="moderate").questions[0]
    assert question.response_schema is ResponseSchema.PRODUCT_AND_FRACTION
    ui = build_ui_model(question, item)
    assert all(o.field_name != "consumed_fraction" for o in ui.options)
    assert ui.fraction_control == FRACTION_CHOICES


def test_every_question_offers_a_way_out():
    """A question the user cannot escape is an interrogation. The exits exist
    BEFORE the rounds run out, not only after."""
    for ambiguities in ([_line_ambiguity()], [_fraction_ambiguity()],
                        [_line_ambiguity(), _fraction_ambiguity()]):
        item = _item(ambiguities=ambiguities)
        ui = build_ui_model(decide([item], mode="moderate").questions[0], item)
        assert ui.exits
        assert ExitAction.SKIP_ITEM in ui.exits


def test_label_values_is_offered_only_where_reading_a_label_answers_it():
    """"Use label values" is an answer to "which product". It is not an answer
    to "how much of it did you drink"."""
    product = build_ui_model(
        decide([_item(ambiguities=[_line_ambiguity()])],
               mode="moderate").questions[0])
    portion = build_ui_model(
        decide([_item(ambiguities=[_fraction_ambiguity()])],
               mode="moderate").questions[0])
    assert ExitAction.LABEL_VALUES in product.exits
    assert ExitAction.LABEL_VALUES not in portion.exits


def test_free_text_stays_available():
    """Chat remains fully functional — the payload is additive."""
    item = _item(ambiguities=[_line_ambiguity()])
    ui = build_ui_model(decide([item], mode="moderate").questions[0], item)
    assert ui.allows_free_text


def test_the_payload_serializes_for_a_client():
    item = _item(ambiguities=[_line_ambiguity(), _fraction_ambiguity()])
    payload = build_ui_model(
        decide([item], mode="moderate").questions[0], item).as_dict()
    assert payload["version"] == "clarify_ui_v1"
    assert payload["staged_item_id"] == "i1"
    assert payload["options"][0]["candidate_id"] == "c1"
    assert {e["action"] for e in payload["exits"]}
    assert all(e["label"] for e in payload["exits"])
    assert payload["fraction_control"][0]["label"] == "All of it"


def test_the_payload_binds_to_the_question_and_item():
    """A client answering must name what it answered — anything less and the
    server is back to guessing which row a reply belongs to."""
    item = _item(ambiguities=[_line_ambiguity()])
    question = decide([item], mode="moderate").questions[0]
    ui = build_ui_model(question, item)
    assert ui.question_id == question.question_id
    assert ui.staged_item_id == item.staged_item_id
    assert ui.requested_fields == question.requested_fields


def test_one_model_per_question_asked():
    item = _item(ambiguities=[_line_ambiguity()])
    decision = decide([item], mode="moderate")
    assert len(build_ui_models(decision)) == len(decision.questions)


def test_no_questions_means_no_models():
    """A quick-mode commit renders nothing to tap."""
    item = _item()
    assert build_ui_models(decide([item], mode="quick")) == ()


# ── per-item traces ───────────────────────────────────────────────────────────
def _candidate(name, score, cal):
    return ProductCandidate(
        candidate_id=name, canonical_name=name, brand="Fairlife",
        product_line=name, package_size=Quantity(14, "oz"),
        tier=SourceTier.BRANDED_EXACT, overall_score=score,
        nutrient_profile=profile_from_values("off", calories=cal))


def test_a_trace_records_what_was_found_and_what_was_decided():
    item = _item(ambiguities=[_line_ambiguity()],
                 candidates=[_candidate("Core Power", 0.71, 170),
                             _candidate("Elite", 0.66, 230)])
    decision = decide([item], mode="moderate")
    trace = build_item_trace(item, decision=decision, mode="moderate",
                             turn_id="turn_123", raw_candidate_count=4)

    assert trace.turn_id == "turn_123"
    assert trace.staged_item_id == "i1"
    assert trace.food_class == "branded"
    # "four results became two real choices" — not "two were dropped".
    assert trace.candidates_found == 4
    assert trace.candidates_after_collapse == 2
    assert trace.top_score == 0.71 and trace.second_score == 0.66
    assert trace.ambiguities == ("product_line",)
    assert trace.materiality_score > 0
    assert trace.decision == "ask"
    assert trace.question_id == decision.questions[0].question_id


def test_a_committed_item_traces_as_commit_with_its_assumptions():
    item = _item(ambiguities=[], candidates=[_candidate("Core Power", 0.9, 170)])
    decision = decide([item], mode="quick")
    trace = build_item_trace(item, decision=decision, mode="quick")
    assert trace.decision == "commit"
    assert trace.question_id == ""


def test_a_held_item_traces_as_hold_not_ask():
    """Strict holds the clear item without questioning it — the trace must not
    imply a question was asked."""
    clear = StagedFoodItem(
        staged_item_id="i2", original_text="200g chicken",
        food_class=FoodClass.GENERIC,
        identity=FoodIdentity(canonical_name="chicken"),
        quantity=QuantityIntent(stated_amount=200, stated_unit="g"),
        meal_group_id="meal_1")
    vague = _item(ambiguities=[_line_ambiguity("strict")])
    decision = decide([clear, vague], mode="strict")
    trace = build_item_trace(clear, decision=decision, mode="strict")
    assert trace.decision == "hold"
    assert trace.question_id == ""


def test_the_trace_line_is_greppable():
    item = _item(ambiguities=[_line_ambiguity()],
                 candidates=[_candidate("Core Power", 0.71, 170)])
    line = build_item_trace(item, decision=decide([item], mode="moderate"),
                            mode="moderate", turn_id="turn_123").log_line()
    assert line.startswith("event=item_trace ")
    for token in ("turn=turn_123", "item=i1", "class=branded",
                  "decision=ask", "materiality=", "mode=moderate"):
        assert token in line


def test_the_trace_serializes_to_the_shape_the_directive_specified():
    item = _item(ambiguities=[_line_ambiguity()],
                 candidates=[_candidate("Core Power", 0.71, 170)])
    d = build_item_trace(item, decision=decide([item], mode="moderate"),
                         mode="moderate", turn_id="turn_123",
                         raw_candidate_count=4).as_dict()
    for key in ("turn_id", "staged_item_id", "original_text", "food_class",
                "candidates_found", "top_candidate", "top_score",
                "second_score", "ambiguities", "materiality_score", "mode",
                "decision", "question_id"):
        assert key in d, key
    assert d["version"] == "item_trace_v1"


def test_a_trace_per_item_across_a_mixed_meal():
    clear = StagedFoodItem(
        staged_item_id="i2", original_text="200g chicken",
        food_class=FoodClass.GENERIC,
        identity=FoodIdentity(canonical_name="chicken"),
        quantity=QuantityIntent(stated_amount=200, stated_unit="g"),
        meal_group_id="meal_1")
    vague = _item(ambiguities=[_line_ambiguity()])
    decision = decide([clear, vague], mode="moderate")
    traces = build_traces([clear, vague], decision=decision, mode="moderate",
                          turn_id="turn_9", raw_counts={"i1": 4})
    assert len(traces) == 2
    by_item = {t.staged_item_id: t for t in traces}
    assert by_item["i2"].decision == "commit"
    assert by_item["i1"].decision == "ask"
    assert by_item["i1"].candidates_found == 4
    assert all(t.meal_group_id == "meal_1" for t in traces)


def test_an_item_with_no_candidates_still_traces():
    """A lookup that found nothing is exactly the case worth tracing."""
    trace = build_item_trace(_item(), decision=decide([_item()], mode="quick"),
                             mode="quick")
    assert trace.candidates_found == 0
    assert trace.top_candidate == ""
    assert trace.top_score == 0.0
    assert trace.log_line()
