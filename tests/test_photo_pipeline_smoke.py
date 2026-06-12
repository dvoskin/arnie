"""
Smoke test for the photo intelligence toolkit.

50 scenarios across preprocessor classification, type-specific extraction,
classifier robustness, error handling, coach_on_photo dispatcher, legacy
wrappers, and system-prompt routing rules.

Mocks the vision layer (analyze_image) so we test the plumbing — classifier
routing, extractor selection, max_tokens lookup, dispatcher behavior, tagged-
block format guarantees — without burning API spend. Vision accuracy itself
is validated post-launch via real photos (task #10).
"""
import asyncio
import logging
from unittest.mock import patch, AsyncMock
import pytest


# ─── Test fixtures ──────────────────────────────────────────────────────────


def _fake_vision(label_response: str, extractor_response: str):
    """
    Build a mock analyze_image that returns the classifier label on the first
    call (max_tokens=20) and the extractor response on subsequent calls.
    """
    call_state = {"n": 0}

    async def _mock(image_data, prompt, mime_type="image/jpeg", max_tokens=512):
        call_state["n"] += 1
        # First call is always the classifier (max_tokens=20).
        if call_state["n"] == 1 and max_tokens == 20:
            return label_response
        return extractor_response

    return _mock


def run(coro):
    """Sync wrapper for async test bodies. Uses asyncio.run for a fresh
    event loop each call — works on Python 3.10+ including 3.14 where
    get_event_loop() raises when no loop is current."""
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def silence_loggers():
    logging.getLogger("multimodal.image_handler").setLevel(logging.CRITICAL)
    logging.getLogger("handlers.tool_executor").setLevel(logging.CRITICAL)


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 1 — Preprocessor routing per photo type (12 tests, 1 per type)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("label,expected_tag", [
    ("PREPARED_MEAL", "[FOOD_LOG]"),
    ("PACKAGED_PRODUCT", "[FOOD_LOG]"),
    ("MENU", "[MENU_DECISION]"),
    ("FRIDGE", "[FRIDGE]"),
    ("GROCERY", "[GROCERY]"),
    ("DELIVERY_APP", "[DELIVERY_APP]"),
    ("WORKOUT_LOG", "[WORKOUT_LOG]"),
    ("BLOOD_TEST", "[METRICS]"),
    ("WEARABLE", "[METRICS]"),
    ("FOOD_DIARY", "[FOOD_DIARY]"),
    ("BODY_PROGRESS", "[BODY_PROGRESS]"),
    ("UNKNOWN", "[UNKNOWN]"),
])
def test_01_classifier_routes_to_right_extractor(label, expected_tag):
    """The classifier label routes to the correct type-specific extractor."""
    from multimodal.image_handler import process_photo

    fake = _fake_vision(label, f"{expected_tag}\nCONFIDENCE: 0.9\n{expected_tag.replace('[', '[/')}")
    with patch("multimodal.image_handler.analyze_image", new=fake):
        result = run(process_photo(b"fake_image_bytes", "test caption"))
    assert expected_tag in result, f"Label {label} did not produce {expected_tag}; got: {result[:100]}"


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 2 — Classifier robustness (5 tests)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("raw_label,expected_normalized", [
    ("MENU", "MENU"),
    ("menu", "MENU"),
    ("MENU.", "MENU"),
    ("  MENU  ", "MENU"),
    ('"MENU"', "MENU"),
])
def test_02_classifier_normalizes_label(raw_label, expected_normalized):
    """Classifier strips whitespace, punctuation, quotes; uppercases."""
    from multimodal.image_handler import classify_image

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        return raw_label
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        label = run(classify_image(b"fake"))
    assert label == expected_normalized


def test_03_classifier_handles_verbose_response():
    """If classifier adds prose, take the first token or fall back."""
    from multimodal.image_handler import classify_image

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        return "MENU is what I see here"
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        label = run(classify_image(b"fake"))
    assert label == "MENU"


def test_04_classifier_falls_back_unknown_label():
    """Unrecognized labels become UNKNOWN."""
    from multimodal.image_handler import classify_image

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        return "RANDOM_GARBAGE_LABEL"
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        label = run(classify_image(b"fake"))
    assert label == "UNKNOWN"


def test_05_classifier_empty_response_unknown():
    """Empty classifier response becomes UNKNOWN."""
    from multimodal.image_handler import classify_image

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        return ""
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        label = run(classify_image(b"fake"))
    assert label == "UNKNOWN"


def test_06_classifier_substring_match_recovers():
    """Substring match recovers labels with extra context."""
    from multimodal.image_handler import classify_image

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        return "WORKOUT_LOG_HANDWRITTEN"
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        label = run(classify_image(b"fake"))
    assert label == "WORKOUT_LOG"


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 3 — Error handling (5 tests)
# ═══════════════════════════════════════════════════════════════════════════


def test_07_classifier_exception_returns_unknown():
    """Vision raises → classifier returns UNKNOWN, doesn't crash."""
    from multimodal.image_handler import classify_image

    async def _broken(img, prompt, mime_type="image/jpeg", max_tokens=512):
        raise RuntimeError("vision API down")
    with patch("multimodal.image_handler.analyze_image", new=_broken):
        label = run(classify_image(b"fake"))
    assert label == "UNKNOWN"


def test_08_extractor_exception_emits_unknown_block():
    """Extractor exception → process_photo returns an [UNKNOWN] block."""
    from multimodal.image_handler import process_photo

    call_state = {"n": 0}

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        call_state["n"] += 1
        if call_state["n"] == 1:
            return "MENU"
        raise RuntimeError("extractor exploded")
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        out = run(process_photo(b"fake", ""))
    assert "[UNKNOWN]" in out
    assert "MENU" in out  # records what was classified before extractor died


def test_09_extractor_empty_response_emits_unknown_block():
    """Extractor returns empty → process_photo emits [UNKNOWN] fallback."""
    from multimodal.image_handler import process_photo

    call_state = {"n": 0}

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        call_state["n"] += 1
        if call_state["n"] == 1:
            return "FRIDGE"
        return ""
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        out = run(process_photo(b"fake", ""))
    assert "[UNKNOWN]" in out


def test_10_unknown_label_emits_unknown_block_with_ask_text():
    """UNKNOWN classification produces a block with an ASK_USER prompt."""
    from multimodal.image_handler import process_photo

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        return "UNKNOWN" if max_tokens == 20 else "[UNKNOWN]\nVISIBLE: a blurry thing\nASK_USER: \"what am I looking at?\"\n[/UNKNOWN]"
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        out = run(process_photo(b"fake", ""))
    assert "[UNKNOWN]" in out
    assert "ASK_USER" in out


def test_11_classify_image_called_with_low_max_tokens():
    """Classifier uses tiny max_tokens (~20) to keep cost down."""
    from multimodal.image_handler import process_photo

    seen = {"max_tokens_seen": []}

    async def _vision(img, prompt, mime_type="image/jpeg", max_tokens=512):
        seen["max_tokens_seen"].append(max_tokens)
        if max_tokens == 20:
            return "MENU"
        return "[MENU_DECISION]\nCONFIDENCE: 0.8\n[/MENU_DECISION]"
    with patch("multimodal.image_handler.analyze_image", new=_vision):
        run(process_photo(b"fake", ""))
    assert 20 in seen["max_tokens_seen"], "Classifier should use max_tokens=20"
    assert any(t >= 384 for t in seen["max_tokens_seen"]), "Extractor should use larger budget"


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 4 — Per-type max_tokens budgets (5 tests)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("label,expected_min_budget", [
    ("MENU", 1024),       # dense menus
    ("WORKOUT_LOG", 1024),
    ("BLOOD_TEST", 1024),
    ("FOOD_DIARY", 1024),
    ("GROCERY", 1024),
])
def test_12_dense_extractor_budgets_at_least_1024(label, expected_min_budget):
    """Types with long structured output (menus, panels, diaries) get >= 1024 tokens."""
    from multimodal.image_handler import _EXTRACTOR_MAX_TOKENS
    assert _EXTRACTOR_MAX_TOKENS[label] >= expected_min_budget


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 5 — Legacy wrappers (3 tests)
# ═══════════════════════════════════════════════════════════════════════════


def test_13_legacy_process_food_image_still_works():
    """process_food_image must still be importable and delegate to process_photo."""
    from multimodal.image_handler import process_food_image

    fake = _fake_vision("PREPARED_MEAL", "[FOOD_LOG]\nINTENT: log\nCONFIDENCE: 0.85\n[/FOOD_LOG]")
    with patch("multimodal.image_handler.analyze_image", new=fake):
        out = run(process_food_image(b"fake"))
    assert "[FOOD_LOG]" in out


def test_14_legacy_process_general_image_still_works():
    """process_general_image still importable, delegates to process_photo."""
    from multimodal.image_handler import process_general_image

    fake = _fake_vision("MENU", "[MENU_DECISION]\nCONFIDENCE: 0.8\n[/MENU_DECISION]")
    with patch("multimodal.image_handler.analyze_image", new=fake):
        out = run(process_general_image(b"fake", "what's on this?"))
    assert "[MENU_DECISION]" in out


def test_15_legacy_wrappers_accept_old_signatures():
    """Both legacy wrappers accept their original call signatures."""
    import inspect
    from multimodal.image_handler import process_food_image, process_general_image

    food_sig = inspect.signature(process_food_image)
    assert list(food_sig.parameters.keys()) == ["image_data"]

    general_sig = inspect.signature(process_general_image)
    params = list(general_sig.parameters.keys())
    assert "image_data" in params and "caption" in params


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 6 — coach_on_photo dispatcher (10 tests)
# ═══════════════════════════════════════════════════════════════════════════


class _MockUser:
    id = 42
    timezone = "UTC"


class _MockLog:
    id = 1
    total_calories = 1200
    total_protein = 80
    food_entries = []
    exercise_entries = []


async def _call_coach(inp):
    """Helper to invoke _dispatch for the coach_on_photo branch."""
    from handlers.tool_executor import _dispatch
    return await _dispatch(
        "coach_on_photo", inp, _MockUser(), _MockLog(), db=None, source_type="text",
        pre_existing_exercise_ids=set(),
        pre_existing_food_ids=set(),
    )


@pytest.mark.parametrize("photo_type", [
    "menu", "fridge", "grocery", "delivery_app", "prepared_meal", "body_progress",
])
def test_16_coach_on_photo_accepts_all_photo_types(photo_type):
    """Each valid photo_type returns a structured photo_coaching result."""
    result = run(_call_coach({
        "photo_type": photo_type,
        "decision": "Eat the salmon, sub veg for rice.",
        "reasoning": "You're at 1200/2000.",
        "confidence": 0.8,
    }))
    assert isinstance(result, dict)
    assert result["_type"] == "photo_coaching"
    assert result["photo_type"] == photo_type
    assert result["decision"] == "Eat the salmon, sub veg for rice."


def test_22_coach_on_photo_caps_confidence_at_085_for_non_body():
    """Confidence is capped at 0.85 for non-body photo types."""
    result = run(_call_coach({
        "photo_type": "menu",
        "decision": "Get the salmon.",
        "reasoning": "Fits targets.",
        "confidence": 0.99,
    }))
    assert result["confidence"] == 0.85


def test_23_coach_on_photo_caps_confidence_at_075_for_body():
    """Body progress confidence is capped tighter at 0.75."""
    result = run(_call_coach({
        "photo_type": "body_progress",
        "decision": "Midsection tighter than last shot.",
        "reasoning": "Visible delt cap.",
        "confidence": 0.99,
    }))
    assert result["confidence"] == 0.75


def test_24_coach_on_photo_preserves_bf_range_for_body():
    """bf_range field flows through for body_progress."""
    result = run(_call_coach({
        "photo_type": "body_progress",
        "decision": "Looking lean — 14-17% range.",
        "reasoning": "Abs visible.",
        "confidence": 0.7,
        "bf_range": {"low": 14, "high": 17},
    }))
    assert result["bf_range"]["low"] == 14
    assert result["bf_range"]["high"] == 17


def test_25_coach_on_photo_preserves_macros_for_menu():
    """macros_estimate flows through for menu/delivery/prepared_meal."""
    result = run(_call_coach({
        "photo_type": "menu",
        "decision": "Get the salmon.",
        "reasoning": "Lean pick.",
        "confidence": 0.8,
        "macros_estimate": {"calories": 450, "protein": 35, "carbs": 20, "fats": 18},
    }))
    assert result["macros_estimate"]["calories"] == 450
    assert result["macros_estimate"]["protein"] == 35


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 7 — Tool registration (3 tests)
# ═══════════════════════════════════════════════════════════════════════════


def test_26_coach_on_photo_is_registered():
    """coach_on_photo must appear in build_tools()."""
    from core.tools import build_tools
    names = [t["name"] for t in build_tools()]
    assert "coach_on_photo" in names


def test_27_existing_tools_still_registered():
    """Sanity: existing tools are still present (nothing accidentally removed)."""
    from core.tools import build_tools
    names = set(t["name"] for t in build_tools())
    for required in ["log_food", "log_exercise", "log_water", "log_body_weight",
                     "track_metric", "update_food_entry", "delete_food_entry"]:
        assert required in names, f"existing tool {required} disappeared"


def test_28_coach_on_photo_has_required_schema_fields():
    """coach_on_photo schema declares the right required fields."""
    from core.tools import build_tools
    tool = next(t for t in build_tools() if t["name"] == "coach_on_photo")
    required = tool["input_schema"]["required"]
    for must_have in ["photo_type", "decision", "reasoning", "confidence"]:
        assert must_have in required


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 8 — System prompt routing rules (15 tests)
# ═══════════════════════════════════════════════════════════════════════════


def _prompt():
    from core.prompts.arnie import TOOL_RULES
    return TOOL_RULES


def test_29_prompt_has_photo_pipeline_section():
    assert "PHOTO PIPELINE" in _prompt()


def test_30_prompt_routes_FOOD_LOG_to_log_food():
    p = _prompt()
    food_log_section = p[p.index("[FOOD_LOG]"):p.index("[FOOD_LOG]") + 600]
    assert "log_food" in food_log_section


def test_31_prompt_routes_PREPARED_MEAL_DECISION_to_coach():
    p = _prompt()
    sec = p[p.index("[PREPARED_MEAL_DECISION]"):p.index("[PREPARED_MEAL_DECISION]") + 500]
    assert "coach_on_photo" in sec


def test_32_prompt_routes_PREPARED_MEAL_AMBIGUOUS_to_ask():
    p = _prompt()
    sec = p[p.index("[PREPARED_MEAL_AMBIGUOUS]"):p.index("[PREPARED_MEAL_AMBIGUOUS]") + 400]
    assert "ASK" in sec.upper() and "do not call any tool" in sec.lower()


def test_33_prompt_routes_MENU_DECISION_to_coach():
    p = _prompt()
    sec = p[p.index("[MENU_DECISION]"):p.index("[MENU_DECISION]") + 500]
    assert "coach_on_photo" in sec


def test_34_prompt_routes_FRIDGE_with_sparse_split():
    p = _prompt()
    sec = p[p.index("[FRIDGE]"):p.index("[FRIDGE]") + 700]
    assert "SPARSE: no" in sec and "SPARSE: yes" in sec
    assert "coach_on_photo" in sec


def test_35_prompt_routes_GROCERY_to_coach():
    p = _prompt()
    sec = p[p.index("[GROCERY]"):p.index("[GROCERY]") + 400]
    assert "coach_on_photo" in sec


def test_36_prompt_routes_DELIVERY_APP_to_coach():
    p = _prompt()
    sec = p[p.index("[DELIVERY_APP]"):p.index("[DELIVERY_APP]") + 400]
    assert "coach_on_photo" in sec


def test_37_prompt_routes_WORKOUT_LOG_to_log_exercise():
    p = _prompt()
    sec = p[p.index("[WORKOUT_LOG]"):p.index("[WORKOUT_LOG]") + 1500]
    assert "log_exercise" in sec
    assert "0.7" in sec  # auto-log threshold mentioned


def test_38_prompt_workout_handles_date_raw():
    # Normalize whitespace so the assertion isn't fragile to line wrapping
    # ("MOST RECENT\n          PAST" inside the system prompt).
    import re
    p = _prompt()
    sec = p[p.index("[WORKOUT_LOG]"):p.index("[WORKOUT_LOG]") + 2000]
    sec_norm = re.sub(r"\s+", " ", sec).upper()
    assert "DATE_RAW" in sec
    assert "MOST RECENT PAST" in sec_norm


def test_39_prompt_workout_handles_bodyweight():
    p = _prompt()
    sec = p[p.index("[WORKOUT_LOG]"):p.index("[WORKOUT_LOG]") + 1500]
    assert "bodyweight" in sec
    assert "OMIT" in sec or "omit" in sec


def test_40_prompt_routes_METRICS_blood_test_to_track_metric():
    p = _prompt()
    sec = p[p.index("[METRICS] (SOURCE: blood_test)"):p.index("[METRICS] (SOURCE: blood_test)") + 500]
    assert "track_metric" in sec


def test_41_prompt_routes_METRICS_wearable_with_context_split():
    p = _prompt()
    sec = p[p.index("[METRICS] (SOURCE: wearable)"):p.index("[METRICS] (SOURCE: wearable)") + 1200]
    assert "CONTEXT: current_reading" in sec
    assert "DON'T track_metric" in sec or "don't track" in sec.lower()
    assert "daily_summary" in sec


def test_42_prompt_routes_FOOD_DIARY_to_log_food_with_date():
    p = _prompt()
    sec = p[p.index("[FOOD_DIARY]"):p.index("[FOOD_DIARY]") + 500]
    assert "log_food" in sec
    assert "date=" in sec


def test_43_prompt_routes_BODY_PROGRESS_to_coach_with_range():
    p = _prompt()
    sec = p[p.index("[BODY_PROGRESS]"):p.index("[BODY_PROGRESS]") + 700]
    assert "coach_on_photo" in sec
    assert "bf_range" in sec
    assert "RANGE" in sec or "range" in sec


def test_44_prompt_has_ask_first_gate():
    p = _prompt()
    assert "ASK-FIRST GATE" in p
    assert "CONFIDENCE < 0.5" in p
    assert "TEMPLATE_OR_STOCK" in p


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 9 — Preprocessor prompt content checks (6 tests)
# ═══════════════════════════════════════════════════════════════════════════


def test_45_menu_extractor_detects_templates():
    from multimodal.image_handler import _MENU_PROMPT
    assert "TEMPLATE_OR_STOCK" in _MENU_PROMPT
    assert "placeholder" in _MENU_PROMPT.lower()


def test_46_menu_extractor_buckets_dense_menus():
    from multimodal.image_handler import _MENU_PROMPT
    assert "LEAN" in _MENU_PROMPT and "MID" in _MENU_PROMPT and "HEAVY" in _MENU_PROMPT
    assert "> 15" in _MENU_PROMPT or ">15" in _MENU_PROMPT or "15 dish" in _MENU_PROMPT


def test_47_workout_extractor_has_future_plan_rule():
    from multimodal.image_handler import _WORKOUT_LOG_PROMPT
    assert "PLANS, not logs" in _WORKOUT_LOG_PROMPT
    assert "bodyweight" in _WORKOUT_LOG_PROMPT
    assert "DATE_RAW" in _WORKOUT_LOG_PROMPT


def test_48_blood_test_extractor_detects_samples():
    from multimodal.image_handler import _BLOOD_TEST_PROMPT
    assert "SAMPLE_OR_DEMO" in _BLOOD_TEST_PROMPT
    assert "GNU Solidario" in _BLOOD_TEST_PROMPT  # specific known demo system


def test_49_wearable_extractor_has_context_field():
    from multimodal.image_handler import _WEARABLE_PROMPT
    assert "CONTEXT:" in _WEARABLE_PROMPT
    assert "current_reading" in _WEARABLE_PROMPT
    assert "daily_summary" in _WEARABLE_PROMPT
    assert "personal_threshold" in _WEARABLE_PROMPT


def test_50_fridge_extractor_has_sparse_flag():
    from multimodal.image_handler import _FRIDGE_PROMPT
    assert "SPARSE: [yes | no]" in _FRIDGE_PROMPT
    assert "STOCKED" in _FRIDGE_PROMPT
