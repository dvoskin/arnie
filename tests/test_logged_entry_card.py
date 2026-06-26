"""Inline log card (macro_card / workout_card) must mirror a REAL DB row.

Bug (Danny 2026-06-26): "what is 84.9kg in lbs" — a pure unit-conversion message —
spuriously fired log_food with the coffee from earlier in context. The executor
deduped it (coffee already on the board → no new row, _entry_id unset), but a
macro_card was emitted anyway, leaking the stale coffee card (entry_id=null) onto a
reply that logged nothing. The fix: emit the card only when the dispatcher stashed
an _entry_id (a real created/rolled-up row).
"""
from core.conversation import _logged_entry_card


def test_real_food_log_emits_macro_card():
    card = _logged_entry_card("log_food", {
        "food_name": "Coffee", "calories": 25, "protein": 0,
        "_entry_id": 1296,
    })
    assert card is not None
    assert card["type"] == "macro_card"
    assert card["payload"]["entry_id"] == 1296
    assert card["payload"]["calories"] == 25


def test_deduped_food_log_emits_no_card():
    # No _entry_id → deduped / no-op → must NOT leak a card.
    assert _logged_entry_card("log_food", {"food_name": "Coffee", "calories": 25}) is None
    assert _logged_entry_card("log_food", {"food_name": "Coffee", "_entry_id": None}) is None
    assert _logged_entry_card("log_food", {"food_name": "Coffee", "_entry_id": 0}) is None


def test_real_exercise_log_emits_workout_card():
    card = _logged_entry_card("log_exercise", {
        "exercise_name": "Bench", "sets": 3, "reps": "8,8,7",
        "weight": 135, "_entry_id": 500,
    })
    assert card is not None
    assert card["type"] == "workout_card"
    assert card["payload"]["entry_id"] == 500
    assert card["payload"]["is_cardio"] is False


def test_deduped_exercise_log_emits_no_card():
    assert _logged_entry_card("log_exercise", {"exercise_name": "Bench", "sets": 3}) is None


def test_non_logging_tools_return_none():
    # suggest_meals / show_day_recap etc. are handled by their own branches,
    # never by this helper — even with an _entry_id present.
    assert _logged_entry_card("suggest_meals", {"meals": [1], "_entry_id": 9}) is None
    assert _logged_entry_card("show_day_recap", {"_recap_payload": {}}) is None
    assert _logged_entry_card("update_food_entry", {"_entry_id": 5}) is None


def test_cardio_flag_inferred_from_cardio_type():
    card = _logged_entry_card("log_exercise", {
        "exercise_name": "Run", "cardio_type": "treadmill", "_entry_id": 7,
    })
    assert card["payload"]["is_cardio"] is True
