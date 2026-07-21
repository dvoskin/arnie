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


def test_single_food_shows_full_sourcing_trace():
    # A single-item log with the executor's _sourcing stash gets the full trace:
    # searched -> matched source -> serving checked -> logged totals.
    r = build_reasoning(
        [{"name": "log_food", "input": {
            "food_name": "Barebells salty peanut", "quantity": "1 bar",
            "_sourcing": {"name": "Barebells salty peanut", "quantity": "1 bar",
                          "source": "web_label", "confidence": "likely",
                          "calories": 200, "protein": 20}}}],
        {"log_food": "Logged: Barebells 200 cal"}, None, 1500)
    labels = [s["label"] for s in r["steps"]]
    assert any("Searched for Barebells" in l for l in labels)
    assert any("product label" in l for l in labels)          # web_label source
    assert any("Serving checked — 1 bar" in l for l in labels)
    assert any("Logged Barebells" in l and "200 cal" in l and "20g protein" in l
               for l in labels)


def test_estimate_source_is_flagged_in_trace():
    # A low-confidence estimate (no exact match) reads as such — the signal that
    # this item is a web-enrich candidate.
    r = build_reasoning(
        [{"name": "log_food", "input": {
            "food_name": "poke bowl", "quantity": "large",
            "_sourcing": {"name": "poke bowl", "quantity": "large",
                          "source": "estimate", "confidence": "estimated",
                          "calories": 750, "protein": 42}}}],
        {"log_food": "Logged: poke bowl 750 cal"}, None, None)
    labels = [s["label"] for s in r["steps"]]
    assert any("estimated from the description" in l for l in labels)


def test_multi_food_stays_condensed_with_source_detail():
    # Two+ foods share the step budget: one condensed line each, still carrying
    # the source in the detail.
    r = build_reasoning(
        [{"name": "log_food", "input": {
            "food_name": "eggs", "_sourcing": {"source": "usda", "calories": 210}}},
         {"name": "log_food", "input": {
            "food_name": "toast", "_sourcing": {"source": "history", "calories": 120}}}],
        {"log_food": "Logged"}, None, None)
    assert len(r["steps"]) == 2
    assert "Logged eggs" in r["steps"][0]["label"]
    assert "USDA" in r["steps"][0]["detail"]
    assert "earlier log" in r["steps"][1]["detail"]


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
