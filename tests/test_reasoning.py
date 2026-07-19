"""Reasoning receipts — deterministic, humanized, honest."""
from core.reasoning import build_reasoning


def test_food_step_with_usda_detail():
    r = build_reasoning(
        [{"name": "log_food", "input": {"food_name": "oatmeal", "calories": 300}}],
        {"log_food": "Logged: oatmeal 300 cal (USDA enriched)"},
        None, 2100)
    assert r["duration_ms"] == 2100
    s = r["steps"][0]
    assert "Logged oatmeal" in s["label"] and "300 cal" in s["label"]
    assert "USDA" in s["detail"]


def test_dedup_block_becomes_duplicate_check():
    r = build_reasoning(
        [{"name": "log_food", "input": {"food_name": "turkey"}}],
        {"log_food": "Already on the board: turkey 250g, logged at 00:32"},
        None, None)
    assert "Duplicate check" in r["steps"][0]["label"]
    assert "unchanged" in r["steps"][0]["detail"]


def test_exercise_scheme_and_silent_tools():
    r = build_reasoning(
        [{"name": "log_exercise", "input": {"exercise_name": "Bench", "sets": 3, "reps": "8"}},
         {"name": "store_attribute", "input": {}},
         {"name": "note_food_clarification", "input": {}}],
        {"log_exercise": "Logged"}, None, None)
    assert len(r["steps"]) == 1
    assert "Bench — 3×8" in r["steps"][0]["label"]


def test_pure_chat_turn_gets_context_receipt_and_cap():
    # Every reply carries a receipt — a no-tool turn shows the honest
    # context-read steps (Danny: thoughts on every reply, like Claude).
    r = build_reasoning([], {}, None, 500)
    assert r["duration_ms"] == 500
    assert len(r["steps"]) == 2
    assert "Read your logs" in r["steps"][0]["label"]
    many = [{"name": "log_food", "input": {"food_name": f"f{i}"}} for i in range(12)]
    r = build_reasoning(many, {}, None, None)
    assert len(r["steps"]) == 8
