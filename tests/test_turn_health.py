"""Turn-health detectors — the deterministic signals that flag a bad turn."""
from core.turn_health import (
    looks_like_stall, looks_like_dead_end, detect_frustration, detect_turn_flags,
)


# ── dead-end detection ──────────────────────────────────────────────────────────

def test_dead_end_catches_bare_acknowledgments():
    for txt in ("done", "Done.", "done ✅", "got it", "Got it 👍", "logged",
                "noted", "all set", "ok", "Updated.", "perfect", "nice 🔥"):
        assert looks_like_dead_end(txt), f"should flag dead-end: {txt!r}"


def test_dead_end_allows_substance():
    for txt in (
        "done, you're at 450 for the day.",
        "logged it 👊|||that's 1,840/2,100.",
        "got it, what's the dinner plan?",
        "nice, that's a strong protein hit.",
        "",
    ):
        assert not looks_like_dead_end(txt), f"false positive on: {txt!r}"


# ── stall detection ────────────────────────────────────────────────────────────

def test_stall_catches_colon_and_period_narration():
    for txt in (
        "Now logging everything:",
        "estimating both:",
        "Let me do that now.",
        "On it — clearing today and relogging everything to yesterday.",
        "I need to delete all of today's entries and relog them to yesterday.",
        "Let me handle this — deleting all of today's entries first, then relogging.",
    ):
        assert looks_like_stall(txt), f"should flag stall: {txt!r}"


def test_stall_does_not_flag_legit_conversation():
    for txt in (
        "solid day. let me know what you have for dinner and we'll close it out.",
        "nice work, that's a strong protein hit.",
        "you're at 1,840/2,100. what's the dinner plan?",
        "",
    ):
        assert not looks_like_stall(txt), f"false positive on: {txt!r}"


# ── frustration detection ───────────────────────────────────────────────────────

def test_frustration_detects_user_pushback():
    for txt in (
        "wtf are you talking about",
        "you missed half the items",
        "I already told you that",
        "that's not what I said",
        "are you dumb",
        "still wrong",
    ):
        assert detect_frustration(txt), f"should detect frustration: {txt!r}"


def test_frustration_no_false_positive_on_normal_text():
    for txt in ("had a chicken wrap and a shake", "log my breakfast", "thanks man"):
        assert not detect_frustration(txt), f"false positive: {txt!r}"


# ── combined flag computation ────────────────────────────────────────────────────

def test_clean_turn_has_no_flags():
    flags = detect_turn_flags(
        user_text="had a chicken wrap", response_text="logged it, you're at 450.",
        has_tool_calls=True, stop_reason="end_turn", retried=False, tool_error=False,
    )
    assert flags == []


def test_flags_accumulate_for_a_bad_turn():
    flags = detect_turn_flags(
        user_text="wtf you missed everything",
        response_text="Let me do that now.",
        has_tool_calls=False, stop_reason="max_tokens", retried=True, tool_error=True,
    )
    assert set(flags) == {"truncated", "retried", "tool_error", "stall_shipped", "user_frustrated"}


def test_stall_only_flags_when_no_tool_calls():
    # Same stall-ish text, but a tool DID run → not a stall.
    flags = detect_turn_flags(
        user_text="move it to yesterday", response_text="On it — moving everything.",
        has_tool_calls=True, stop_reason="end_turn", retried=False, tool_error=False,
    )
    assert "stall_shipped" not in flags
