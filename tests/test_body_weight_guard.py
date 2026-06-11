"""Regression tests for the iMessage duplicate-send + body-weight mis-log fixes."""
from types import SimpleNamespace
from handlers.tool_executor import deterministic_confirmation
from core.turn_health import looks_like_partial_narration, detect_turn_flags


def _prefs(cal_t=1800, pro_t=200):
    return SimpleNamespace(calorie_target=cal_t, protein_target=pro_t)


def _log(cal=0, pro=0):
    return SimpleNamespace(total_calories=cal, total_protein=pro)


# ── deterministic_confirmation guards ────────────────────────────────────────

def test_body_weight_without_number_does_not_claim_weighin():
    # "I'm gonna have a barbells bar" mis-routed to log_body_weight with no weight.
    tc = [{"name": "log_body_weight", "input": {}}]
    out = deterministic_confirmation(tc, _log(), _prefs())
    assert "weight down" not in out.lower()


def test_body_weight_with_number_confirms_weighin():
    """The fallback wording rotates across three "weigh-in logged" variants
    (handlers/tool_executor.py::_weight_fallback). All three are valid
    confirmations; assert the response carries weigh-in language, not the
    specific old "weight down" string."""
    tc = [{"name": "log_body_weight", "input": {"weight": 82.5}}]
    out = deterministic_confirmation(tc, _log(), _prefs()).lower()
    assert any(s in out for s in ("weigh-in", "weight logged", "scale check"))


def test_body_weight_zero_is_not_a_weighin():
    tc = [{"name": "log_body_weight", "input": {"weight": 0}}]
    out = deterministic_confirmation(tc, _log(), _prefs())
    assert "weight down" not in out.lower()


def test_body_weight_with_exercise_in_same_turn_skips_weighin():
    # "squatted 225 lbs" — LLM mis-routes exercise weight to log_body_weight.
    # When log_exercise is also present, the weight message must NOT fire.
    tc = [
        {"name": "log_exercise", "input": {"exercise_name": "squat", "weight": 225}},
        {"name": "log_body_weight", "input": {"weight": 225, "unit": "lbs"}},
    ]
    out = deterministic_confirmation(tc, _log(), _prefs())
    assert "weight down" not in out.lower(), (
        "exercise+body_weight in same turn must not produce the weigh-in message"
    )
    assert "logged" in out.lower(), "should fall through to exercise confirmation"


def test_food_photo_macro_numbers_do_not_produce_weighin():
    # Food photo: LLM logs food correctly but also false-positives log_body_weight
    # on a macro gram number (e.g. "55g protein" → weight=55 kg).
    # log_food check fires first so the weight message must never be returned.
    tc = [
        {"name": "log_food", "input": {"food_name": "steak panini", "calories": 600}},
        {"name": "log_body_weight", "input": {"weight": 55, "unit": "kg"}},
    ]
    out = deterministic_confirmation(tc, _log(cal=600, pro=35), _prefs())
    assert "weight down" not in out.lower(), (
        "food+body_weight in same turn must return food confirmation, not weight message"
    )
    assert "logged" in out.lower() or "cal" in out.lower()


# ── partial narration detection ───────────────────────────────────────────────

def test_partial_narration_fires_on_calorie_text_with_food_calls():
    # LLM logged chicken but narrated "rice ~200cal" in text.
    text = "Got the chicken logged. Also noting rice (~200cal) and broccoli (~50cal)."
    assert looks_like_partial_narration(text, has_food_calls=True)


def test_partial_narration_does_not_fire_without_food_calls():
    # Same text but no log_food was called — this is a full stall, not partial.
    text = "Got the chicken logged. Also noting rice (~200cal) and broccoli (~50cal)."
    assert not looks_like_partial_narration(text, has_food_calls=False)


def test_partial_narration_does_not_fire_on_brief_coaching():
    # "Nice 💪" strips down to "nice" — must not be flagged as partial narration.
    assert not looks_like_partial_narration("Nice 💪", has_food_calls=True)


def test_partial_narration_does_not_fire_on_empty():
    assert not looks_like_partial_narration("", has_food_calls=True)
    assert not looks_like_partial_narration(None, has_food_calls=True)


# ── image_body_weight_misroute health flag ────────────────────────────────────

def test_image_body_weight_misroute_flag_fires():
    # Food photo turn where only log_body_weight was called (no log_food).
    flags = detect_turn_flags(
        user_text="[Food photo]",
        response_text="Got your weight down.",
        has_tool_calls=True,
        stop_reason="end_turn",
        retried=False,
        tool_error=False,
        source_type="image",
        tool_names={"log_body_weight"},
    )
    assert "image_body_weight_misroute" in flags


def test_image_body_weight_misroute_flag_does_not_fire_with_food():
    # Food photo where log_food was also called — not a misroute.
    flags = detect_turn_flags(
        user_text="[Food photo]",
        response_text="Logged the panini.",
        has_tool_calls=True,
        stop_reason="end_turn",
        retried=False,
        tool_error=False,
        source_type="image",
        tool_names={"log_food", "log_body_weight"},
    )
    assert "image_body_weight_misroute" not in flags


def test_image_body_weight_misroute_flag_does_not_fire_on_text_turn():
    # Text turn "I weigh 195 today" — log_body_weight is correct here, no flag.
    flags = detect_turn_flags(
        user_text="I weigh 195 today",
        response_text="Got your weight down.",
        has_tool_calls=True,
        stop_reason="end_turn",
        retried=False,
        tool_error=False,
        source_type="text",
        tool_names={"log_body_weight"},
    )
    assert "image_body_weight_misroute" not in flags
