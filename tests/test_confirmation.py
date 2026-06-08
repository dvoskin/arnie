"""deterministic_confirmation must report the EXACT totals from the log row and
never anything else — this is what prevents the LLM from inventing running totals
(the '1,601/1,800, 192g' bug)."""
from types import SimpleNamespace
from handlers.tool_executor import deterministic_confirmation


def _log(cal, pro):
    return SimpleNamespace(total_calories=cal, total_protein=pro)


def _prefs(cal_t=1800, pro_t=200):
    return SimpleNamespace(calorie_target=cal_t, protein_target=pro_t)


def test_food_confirmation_uses_exact_log_totals():
    # protein well above the low-protein threshold so we hit the "what's next?" path
    tc = [{"name": "log_food", "input": {"food_name": "Royo Bagel"}}]
    out = deterministic_confirmation(tc, _log(435, 190), _prefs())
    # the real numbers must appear; the hallucinated 1601/192 must not
    assert "435/1800 cal" in out
    assert "190/200" in out
    assert "1,601" not in out and "1601" not in out
    # names the food, multi-bubble, ends with a hook
    assert out.lower().startswith("royo bagel logged")
    assert "|||" in out
    assert out.rstrip().endswith("?")


def test_food_confirmation_low_protein_path_uses_real_totals():
    # the screenshot scenario: 435 cal / 60g protein, target 1800 / 200
    tc = [{"name": "log_food", "input": {"food_name": "Royo Bagel"}}]
    out = deterministic_confirmation(tc, _log(435, 60), _prefs())
    assert "435/1800 cal" in out and "60/200g" in out
    assert "1,601" not in out and "1601" not in out and "192g" not in out
    assert out.lower().startswith("royo bagel logged")


def test_no_protein_target_still_states_calories():
    tc = [{"name": "log_food", "input": {"food_name": "eggs"}}]
    out = deterministic_confirmation(tc, _log(140, 12), _prefs(cal_t=None, pro_t=None))
    assert "140 cal" in out


def test_low_protein_nudge():
    tc = [{"name": "log_food", "input": {"food_name": "toast"}}]
    out = deterministic_confirmation(tc, _log(300, 40), _prefs())  # 40 << 200*0.85
    assert "40/200g" in out and "keep it coming" in out


def test_delete_reports_new_total_not_blank():
    tc = [{"name": "delete_food_entry", "input": {}}]
    out = deterministic_confirmation(tc, _log(200, 20), _prefs())
    assert "removed it" in out and "200/1800 cal now" in out


def test_no_bare_got_it_fallback():
    # Use update_profile as a representative non-logging tool that falls through
    # the priority chain to the generic confirmation. Same intent as before
    # (was close_day, deleted in T1.1): the catch-all should never be a bare "got it."
    out = deterministic_confirmation([{"name": "update_profile", "input": {}}], _log(0, 0), _prefs())
    assert out and "got it." != out.strip().lower()


def test_water_uses_water_emoji():
    out = deterministic_confirmation([{"name": "log_water", "input": {}}], _log(0, 0), _prefs())
    assert "💧" in out
