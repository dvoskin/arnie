"""Write-set validator — the justification rules as code, tested against the
incident shapes the corpus documents (tests/corpus/incident_cases.jsonl)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from core.write_set import validate_write_set, summarize


def _entry(name, ago_min=10, id_=100):
    return SimpleNamespace(id=id_, parsed_food_name=name,
                           timestamp=datetime.utcnow() - timedelta(minutes=ago_min))


def _log_food(name):
    return {"name": "log_food", "input": {"food_name": name}}


def test_named_items_justified():
    v = validate_write_set(
        [_log_food("Ground Turkey"), _log_food("White Rice")],
        "Also 150g ground turkey and 100g white rice", [])
    assert [x.verdict for x in v] == ["justified", "justified"]


def test_third_bar_carryover_flagged():
    """The third-Barebells incident: bar dragged into a batch that never
    named it, same bar on the board 57 min ago → carryover shape."""
    board = [_entry("Barebells Salty Peanut Protein Bar", ago_min=57)]
    v = validate_write_set(
        [_log_food("Barebells Salty Peanut Protein Bar"),
         _log_food("Ground Turkey")],
        "Also 150g ground turkey and 100g white rice", board)
    assert v[0].verdict == "suspicious_unnamed"
    assert "carryover" in v[0].reason
    assert v[1].verdict == "justified"


def test_clarify_answer_combined_message_justifies():
    """Cookies-and-caramel: the gate-effective message (prior + 'Yes')
    names the item — justified."""
    v = validate_write_set(
        [_log_food("Barebells Cookies and Caramel Protein Bar")],
        "Also just had a cookies and caramel barbell\nYes", [])
    assert v[0].verdict == "justified"


def test_invention_shape_flagged():
    """Item named nowhere, no cue, nothing on the board → invention."""
    v = validate_write_set(
        [_log_food("Garlic Bread")], "had a slice of pizza", [])
    assert v[0].verdict == "suspicious_unnamed"
    assert "invention" in v[0].reason


def test_add_cue_covers_generic_repeat():
    v = validate_write_set(
        [_log_food("Cottage cheese")], "one more", [])
    assert v[0].verdict == "repeat_cue"


def test_photo_turn_exempt():
    v = validate_write_set(
        [_log_food("Grilled salmon plate")], "", [], from_photo=True)
    assert v[0].verdict == "justified"


def test_edit_with_unknown_id_flagged():
    board = [_entry("Eggs", id_=101)]
    v = validate_write_set(
        [{"name": "update_food_entry", "input": {"entry_id": 999}}],
        "make it 3 eggs", board)
    assert v[0].verdict == "suspicious_unknown_id"


def test_summarize_shape():
    board = [_entry("Barebells Salty Peanut Protein Bar", ago_min=30)]
    s = summarize(validate_write_set(
        [_log_food("Barebells Salty Peanut Protein Bar")],
        "connect apple health", board))
    assert s["counts"] == {"suspicious_unnamed": 1}
    assert s["flagged"][0]["item"].startswith("Barebells")
