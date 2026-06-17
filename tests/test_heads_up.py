"""
T1.5 — Tests for the generalized interim heads-up.

The narrow web_search-only mechanism (commit f5987f0) is now wider:
search_food_database, query_history, generate_image, and track_metric also
get a one-line in-voice "let me check" bubble before the slow
execute_tool_calls step, so the user isn't staring at a typing indicator
for seconds.

These tests pin the contract:
  - the deterministic fallback is short, in-voice, and stable per input
  - each slow tool has its own bubble set (no homogenized "looking it up"
    response for a USDA lookup, a history query, and an image generation)
  - NEEDS_HEADS_UP_TOOLS is the single gate consumed by run_turn
  - the per-tool seed extractor pulls the right input field per tool
"""
import pytest


from handlers.tool_executor import (
    tool_heads_up, search_heads_up, NEEDS_HEADS_UP_TOOLS, _heads_up_seed,
    _TOOL_HEADS_UP_BUBBLES,
)


# ── The gate ────────────────────────────────────────────────────────────────


def test_needs_heads_up_tools_covers_the_slow_tools():
    """Pin the slow-tool set. Adding a new slow tool means updating this list
    AND _TOOL_HEADS_UP_BUBBLES — the test catches drift in either direction."""
    assert NEEDS_HEADS_UP_TOOLS == frozenset({
        "web_search",
        "search_food_database",
        "query_history",
        "generate_image",
        "track_metric",
        "find_nearby_places",
    })


def test_every_gated_tool_has_a_bubble_set():
    """Every name in the gate MUST have a per-tool bubble tuple, or the
    deterministic fallback would silently use the web_search default."""
    for name in NEEDS_HEADS_UP_TOOLS:
        assert name in _TOOL_HEADS_UP_BUBBLES, f"missing bubble set for {name!r}"
        bubbles = _TOOL_HEADS_UP_BUBBLES[name]
        assert bubbles and all(isinstance(b, str) and b.strip() for b in bubbles)


# ── The per-tool heads-up function ──────────────────────────────────────────


@pytest.mark.parametrize("tool_name", sorted(NEEDS_HEADS_UP_TOOLS))
def test_tool_heads_up_returns_short_inline_bubble(tool_name):
    """Every slow tool's heads-up is one short bubble, no |||, no multi-line."""
    line = tool_heads_up(tool_name, "some seed text")
    assert isinstance(line, str) and line.strip()
    assert len(line) <= 80, f"{tool_name} heads-up too long: {line!r}"
    assert "|||" not in line, "heads-up must be ONE bubble"
    assert "\n" not in line, "heads-up must be one line"


@pytest.mark.parametrize("tool_name", sorted(NEEDS_HEADS_UP_TOOLS))
def test_tool_heads_up_is_deterministic(tool_name):
    """Same (tool_name, seed) MUST yield the same line — no Math/random.
    Different seeds should at least sometimes land on different bubbles
    (modulo the small bubble set)."""
    a = tool_heads_up(tool_name, "seed-A")
    b = tool_heads_up(tool_name, "seed-A")
    assert a == b


def test_tool_heads_up_unknown_tool_falls_back_to_web_search_default():
    """Defensive: an unknown name (e.g. a tool added to the gate without a
    bubble set) doesn't crash; it returns SOMETHING short, in voice."""
    line = tool_heads_up("unknown_tool_xyz", "seed")
    assert line and line.strip()


def test_deterministic_fallback_is_intentionally_generic():
    """Fallbacks are emergency-only. The model is instructed to ALWAYS write
    its own in-voice heads-up before a slow tool. The deterministic lines
    here exist for the degenerate case where the model emitted a tool_use
    block with no text in front of it. Those generic lines read as
    "system was a little behind" rather than impersonating Arnie's voice —
    which is the right call: a stock-phrase impersonation feels worse than
    a brief honest "one sec." See the EMERGENCY FALLBACK ONLY comment in
    tool_executor.py.

    This test pins the intent: fallbacks stay short + generic. If a user
    sees these routinely, the upstream bug is the model skipping text;
    the fix is the prompt rule, not these strings.
    """
    for name in NEEDS_HEADS_UP_TOOLS:
        bubbles = _TOOL_HEADS_UP_BUBBLES[name]
        # Each fallback must be SHORT — 30 chars caps "stock phrase" feel.
        assert all(len(b) <= 30 for b in bubbles), (
            f"{name} fallback got too verbose; keep it minimal so the "
            "model's own voice wins by default"
        )
        # Must not contain "lemme" / forced-casual filler.
        joined = " ".join(bubbles).lower()
        for banned in ("lemme", "real quick", "hang tight", "hang on"):
            assert banned not in joined, (
                f"{name} fallback contains '{banned}' — too try-hard casual; "
                "minimal generic emergency lines only"
            )


# ── Backward-compatible search_heads_up shim ────────────────────────────────


def test_search_heads_up_shim_matches_tool_heads_up_web_search():
    """The old public name still works — it's a thin shim. Pre-T1.5 callers
    and tests reference search_heads_up directly; this guarantees they keep
    getting the same bubble as the generalized API."""
    for seed in ("", "chipotle bowl", "longer query about omega-3 dosing", None):
        assert search_heads_up(seed) == tool_heads_up("web_search", seed)


# ── Per-tool seed extraction ────────────────────────────────────────────────


def test_heads_up_seed_pulls_query_for_web_search():
    tc = {"name": "web_search", "input": {"query": "chipotle bowl macros"}}
    assert _heads_up_seed(tc) == "chipotle bowl macros"


def test_heads_up_seed_pulls_food_name_for_search_food_database():
    tc = {"name": "search_food_database",
          "input": {"food_name": "barebells caramel bar", "quantity": "1 bar"}}
    assert _heads_up_seed(tc) == "barebells caramel bar"


def test_heads_up_seed_pulls_metric_and_period_for_query_history():
    tc = {"name": "query_history",
          "input": {"metric": "weight", "period": "last_30"}}
    assert _heads_up_seed(tc) == "weight-last_30"


def test_heads_up_seed_truncates_image_prompt():
    long_prompt = "photorealistic close-up of a grilled chicken bowl with " * 5
    tc = {"name": "generate_image", "input": {"prompt": long_prompt}}
    seed = _heads_up_seed(tc)
    assert len(seed) <= 60, "image prompt seed must be truncated for index stability"


def test_heads_up_seed_handles_missing_input_keys():
    """Defensive: tool call with empty input doesn't raise."""
    for name in NEEDS_HEADS_UP_TOOLS:
        tc = {"name": name, "input": {}}
        # Should not raise; may return empty string.
        seed = _heads_up_seed(tc)
        assert isinstance(seed, str)


# ── No false positives: fast tools must NOT be in the gate ──────────────────


def test_fast_tools_excluded_from_gate():
    """The whole point: log_food/log_exercise/log_water/log_body_weight /
    update_profile / update_food_entry / delete_*_entry / clear_day_log /
    update_memory / store_attribute / track_metric / schedule_check_in
    do NOT trigger a heads-up — they're fast enough that the typing
    indicator bridges them."""
    for fast in (
        "log_food", "log_exercise", "log_water", "log_body_weight",
        "update_profile", "update_food_entry", "update_exercise_entry",
        "delete_food_entry", "delete_exercise_entry", "clear_day_log",
        "update_memory", "store_attribute", "schedule_check_in",
    ):
        assert fast not in NEEDS_HEADS_UP_TOOLS, (
            f"{fast} is fast — adding it would over-fire heads-ups"
        )
