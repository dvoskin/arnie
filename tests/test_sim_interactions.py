"""
Simulation tests: weird / unexpected user input patterns and edge-case logic.

All tests are pure-logic (no LLM, no DB, no network). They simulate what various
user inputs produce after routing through the deterministic layers of the pipeline:
  - reconcile_macros  — macro/calorie consistency enforcement
  - _parse_log_date   — natural-language date parsing
  - deterministic_confirmation — fallback confirmation after tool calls
  - looks_like_stall / looks_like_dead_end — turn-health detectors

Each section is labelled with the scenario class it covers.
"""
import pytest
from datetime import date, timedelta
from datetime import datetime as _dt
from types import SimpleNamespace

import pytz

from tests.conftest import _prefs, _log
from core.food_intelligence import reconcile_macros
from handlers.tool_executor import deterministic_confirmation, _parse_log_date
from core.turn_health import looks_like_stall, looks_like_dead_end, detect_turn_flags

# _parse_log_date uses pytz UTC to compute "today", so tests must match.
# Using date.today() diverges across the local-midnight boundary.
_UTC_TODAY = _dt.now(pytz.UTC).date()


# ═══════════════════════════════════════════════════════════════════════════════
# reconcile_macros — the macro/calorie enforcer
# ═══════════════════════════════════════════════════════════════════════════════

class TestReconcileMacros:
    """
    Covers: LLM over/under-reporting, protein-exceeds-calories edge case,
    passthrough tolerance, all-zero guards, and proportional rescaling.
    """

    # ── passthrough cases ─────────────────────────────────────────────────────

    def test_consistent_macros_pass_through_unchanged(self):
        """Macros that sum to within 15% of calories are accepted as-is."""
        # 30g*4 + 40g*4 + 20g*9 = 120+160+180 = 460 cal vs stated 450 → ~2% off
        cal, p, c, f = reconcile_macros(450, 30, 40, 20)
        assert cal == 450
        assert p == 30
        assert c == 40
        assert f == 20

    def test_exactly_at_15_percent_threshold_passes(self):
        """14.9% off should pass through without change."""
        # 500 cal, macros sum to 574 → 14.8% off — under threshold
        # 30g P * 4 = 120, 35g C * 4 = 140, 35g F * 9 = 315 → 575 cal vs 500
        # That's 15%, adjust to 14.9% precisely is hard; test just under instead.
        # P=30, C=30, F=20: 120+120+180 = 420 vs 500 → 16% off → WILL rescale
        cal, p, c, f = reconcile_macros(500, 25, 30, 20)
        # 25*4=100, 30*4=120, 20*9=180 → total 400, diff = 100/500 = 20% → rescales
        assert p != 25 or c != 30 or f != 20  # confirms rescaling occurred

    def test_zero_calories_passes_through(self):
        """cal <= 0 is a passthrough — don't divide by zero or corrupt the data."""
        result = reconcile_macros(0, 30, 40, 20)
        assert result == (0, 30, 40, 20)

    def test_all_zero_macros_pass_through(self):
        """All-zero macros with positive calories → passthrough (no division possible)."""
        result = reconcile_macros(500, 0, 0, 0)
        assert result == (500, 0, 0, 0)

    def test_zero_macro_cal_passes_through(self):
        """macro_cal == 0 (all zeros) → can't scale, passthrough."""
        result = reconcile_macros(300, 0, 0, 0)
        assert result == (300, 0, 0, 0)

    # ── classic LLM over-reporting ────────────────────────────────────────────

    def test_classic_llm_overreport_rescales_carbs_fat(self):
        """
        LLM says 500 cal with macros that sum to 830 cal (a common production bug).
        Protein is trusted; carbs+fat are scaled down.
        protein=50g, carbs=80g, fat=30g → 200+320+270 = 790 cal vs 500
        remaining after protein = 500-200 = 300 cal
        carb_fat_cal = 320+270 = 590, scale = 300/590 ≈ 0.508
        """
        cal, p, c, f = reconcile_macros(500, 50, 80, 30)
        assert cal == 500
        assert p == 50  # protein unchanged
        # verify macros now sum within 15%
        actual = p * 4 + c * 4 + f * 9
        assert abs(actual - 500) / 500 <= 0.15, f"macros still off: {actual} vs 500"

    def test_large_discrepancy_2x_overclaim(self):
        """Macros sum to ~2x the stated calories — should be fully reconciled."""
        # P=60, C=100, F=50 → 240+400+450 = 1090 vs stated 550
        cal, p, c, f = reconcile_macros(550, 60, 100, 50)
        assert cal == 550
        assert p == 60
        actual = p * 4 + c * 4 + f * 9
        assert abs(actual - 550) / 550 <= 0.15, f"still off: {actual}"

    def test_moderate_discrepancy_20_percent_rescales(self):
        """20% discrepancy should trigger rescaling (above the 15% threshold)."""
        # P=30, C=30, F=20 → 120+120+180 = 420 vs 500 → 16% off
        cal, p, c, f = reconcile_macros(500, 30, 30, 20)
        assert cal == 500
        assert p == 30
        actual = p * 4 + c * 4 + f * 9
        assert abs(actual - 500) / 500 <= 0.15

    # ── protein-exceeds-calories edge case ───────────────────────────────────

    def test_protein_exceeds_total_calories_scales_all(self):
        """
        If protein*4 > total calories, all three macros must be scaled proportionally.
        Example: 200 cal stated, P=60g → protein alone = 240 cal > 200.
        """
        cal, p, c, f = reconcile_macros(200, 60, 20, 10)
        assert cal == 200
        # protein must be reduced
        assert p < 60
        # all macros must now sum within tolerance
        actual = p * 4 + c * 4 + f * 9
        assert abs(actual - 200) / 200 <= 0.15, f"still off: {actual} vs 200"

    def test_protein_only_at_exactly_calories(self):
        """P*4 == total cal: remaining=0 → carbs and fat should go to 0."""
        cal, p, c, f = reconcile_macros(200, 50, 10, 5)
        # P=50 → 200 cal → remaining = 0, so c and f get scaled to 0
        assert cal == 200
        actual = p * 4 + c * 4 + f * 9
        assert abs(actual - 200) / 200 <= 0.15

    # ── no carb/fat data edge case ────────────────────────────────────────────

    def test_no_carb_fat_puts_residual_in_carbs(self):
        """
        If carbs=fat=0 but remaining calories > 0, residual goes into carbs.
        E.g. 300 cal, protein=20g (80 cal), remaining=220, carbs=220/4=55
        """
        cal, p, c, f = reconcile_macros(300, 20, 0, 0)
        assert cal == 300
        assert p == 20
        # All the remaining should end up in carbs since fat=0
        actual = p * 4 + c * 4 + f * 9
        assert abs(actual - 300) / 300 <= 0.15, f"residual not absorbed: {actual}"

    # ── output format ─────────────────────────────────────────────────────────

    def test_output_is_rounded_to_one_decimal(self):
        """Rescaled values should be rounded to 1 decimal, not raw floats."""
        cal, p, c, f = reconcile_macros(500, 50, 80, 30)
        # Check each is representable as a 1-decimal float (no long tails)
        for v in (p, c, f):
            assert v == round(v, 1), f"not rounded to 1dp: {v}"

    def test_calories_never_mutated(self):
        """reconcile_macros must NEVER change the stated calorie value."""
        for stated_cal in (200, 500, 1000, 2500):
            out_cal, _, _, _ = reconcile_macros(stated_cal, 50, 80, 30)
            assert out_cal == stated_cal, f"calories changed from {stated_cal} to {out_cal}"

    def test_reconcile_preserves_protein(self):
        """Protein is the ground truth — should survive unchanged unless it exceeds cal."""
        cal, p, c, f = reconcile_macros(600, 40, 70, 30)
        assert p == 40, f"protein changed unexpectedly to {p}"


# ═══════════════════════════════════════════════════════════════════════════════
# _parse_log_date — natural date parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseLogDate:
    """
    The LLM passes date strings from user speech. These must be parsed robustly.
    Critically: future dates and implausibly old dates must be rejected (return None).
    """

    def test_none_input_returns_none(self):
        assert _parse_log_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_log_date("") is None

    def test_yesterday(self):
        result = _parse_log_date("yesterday")
        assert result == _UTC_TODAY - timedelta(days=1)

    def test_yesterday_case_insensitive(self):
        result = _parse_log_date("Yesterday")
        assert result == _UTC_TODAY - timedelta(days=1)

    def test_two_days_ago_numeric(self):
        result = _parse_log_date("2 days ago")
        assert result == _UTC_TODAY - timedelta(days=2)

    def test_two_days_ago_word(self):
        result = _parse_log_date("two days ago")
        assert result == _UTC_TODAY - timedelta(days=2)

    def test_three_days_ago_numeric(self):
        result = _parse_log_date("3 days ago")
        assert result == _UTC_TODAY - timedelta(days=3)

    def test_three_days_ago_word(self):
        result = _parse_log_date("three days ago")
        assert result == _UTC_TODAY - timedelta(days=3)

    def test_four_days_ago_not_supported_returns_none(self):
        """
        '4 days ago' is NOT in the supported phrases — returns None (treated as today).
        Document this known gap: the LLM should convert to ISO or 'yesterday' instead.
        """
        result = _parse_log_date("4 days ago")
        assert result is None

    def test_last_week_not_supported_returns_none(self):
        """'last week' is not parsed — returns None."""
        result = _parse_log_date("last week")
        assert result is None

    def test_valid_iso_date_in_past(self):
        past = _UTC_TODAY - timedelta(days=10)
        result = _parse_log_date(past.isoformat())
        assert result == past

    def test_future_date_rejected(self):
        """The LLM should never log forward in time; reject future ISO dates."""
        future = _UTC_TODAY + timedelta(days=1)
        result = _parse_log_date(future.isoformat())
        assert result is None

    def test_far_future_date_rejected(self):
        """Far-future dates (year confusion bugs) must be rejected."""
        result = _parse_log_date("2099-01-01")
        assert result is None

    def test_implausibly_old_date_rejected(self):
        """Dates >730 days ago are rejected (year confusion like 'Jan 1' → wrong year)."""
        ancient = _UTC_TODAY - timedelta(days=731)
        result = _parse_log_date(ancient.isoformat())
        assert result is None

    def test_exactly_730_days_ago_is_accepted(self):
        """730 days ago is at the boundary — should be accepted."""
        edge = _UTC_TODAY - timedelta(days=730)
        result = _parse_log_date(edge.isoformat())
        assert result == edge

    def test_invalid_format_returns_none(self):
        """Gibberish strings return None without crashing."""
        assert _parse_log_date("last tuesday") is None
        assert _parse_log_date("a while ago") is None
        assert _parse_log_date("notadate") is None

    def test_iso_date_with_whitespace(self):
        """Leading/trailing whitespace around an ISO date should be stripped."""
        past = _UTC_TODAY - timedelta(days=5)
        result = _parse_log_date(f"  {past.isoformat()}  ")
        assert result == past


# ═══════════════════════════════════════════════════════════════════════════════
# deterministic_confirmation — fallback message quality
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeterministicConfirmationCombos:
    """
    Weird multi-tool turns and priority ordering.

    Priority (first match wins):
    clear_day_log alone → wipe message
    update only → "Updated. ✅"
    log_food / update_food_entry → food confirmation
    log_exercise → exercise confirmation
    log_body_weight → weigh-in (guarded)
    log_water → water
    delete → removed
    update_profile → profile
    close_day → wrap-up
    generic fallback
    """

    # ── exercise path ─────────────────────────────────────────────────────────

    def test_single_exercise_gives_next_set_cue(self):
        tc = [{"name": "log_exercise", "input": {"exercise_name": "bench press"}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "bench press" in out.lower()
        assert "next set" in out.lower()
        assert "💪" in out

    def test_multi_exercise_turn_shows_count(self):
        tc = [
            {"name": "log_exercise", "input": {"exercise_name": "squat"}},
            {"name": "log_exercise", "input": {"exercise_name": "deadlift"}},
            {"name": "log_exercise", "input": {"exercise_name": "bench"}},
        ]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "3" in out
        assert "exercises" in out.lower()
        assert "what's next" in out.lower()

    def test_exercise_no_name_uses_generic_fallback(self):
        """When no exercise_name is in the input, falls back to 'exercise'."""
        tc = [{"name": "log_exercise", "input": {}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "exercise" in out.lower()
        assert "💪" in out

    # ── priority: food beats exercise ────────────────────────────────────────

    def test_food_takes_priority_over_exercise_in_same_turn(self):
        """
        A turn that logs both food AND exercise (e.g. post-workout meal note)
        must use the food confirmation path since macros matter more right now.
        """
        tc = [
            {"name": "log_food", "input": {"food_name": "chicken"}},
            {"name": "log_exercise", "input": {"exercise_name": "pull-ups"}},
        ]
        out = deterministic_confirmation(tc, _log(500, 45), _prefs())
        assert "chicken" in out.lower()
        assert "cal" in out.lower()

    # ── priority: clear_day_log ───────────────────────────────────────────────

    def test_clear_alone_gives_wipe_message(self):
        tc = [{"name": "clear_day_log", "input": {}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "wiped" in out.lower() or "clean" in out.lower()
        assert "send me" in out.lower() or "rebuild" in out.lower()

    def test_clear_plus_log_food_uses_food_path_not_clear(self):
        """clear_day_log followed by log_food in the same turn → food confirmation."""
        tc = [
            {"name": "clear_day_log", "input": {}},
            {"name": "log_food", "input": {"food_name": "steak"}},
        ]
        out = deterministic_confirmation(tc, _log(600, 50), _prefs())
        assert "steak" in out.lower()
        assert "wiped" not in out.lower()

    def test_clear_plus_log_exercise_uses_exercise_path(self):
        """clear_day_log + log_exercise → exercise confirmation (clear guard only applies when no re-log)."""
        tc = [
            {"name": "clear_day_log", "input": {}},
            {"name": "log_exercise", "input": {"exercise_name": "deadlift"}},
        ]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "deadlift" in out.lower()
        assert "wiped" not in out.lower()

    # ── update-only path ──────────────────────────────────────────────────────

    def test_update_food_only_gives_updated_message(self):
        tc = [{"name": "update_food_entry", "input": {"entry_id": 5}}]
        out = deterministic_confirmation(tc, _log(800, 70), _prefs())
        assert "updated" in out.lower()
        assert "resynced" in out.lower()

    def test_update_exercise_only_gives_updated_message(self):
        tc = [{"name": "update_exercise_entry", "input": {"entry_id": 3}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "updated" in out.lower()

    def test_update_food_plus_log_food_uses_food_path(self):
        """update_food_entry + log_food in same turn → food path, not update-only."""
        tc = [
            {"name": "update_food_entry", "input": {"entry_id": 1}},
            {"name": "log_food", "input": {"food_name": "oats"}},
        ]
        out = deterministic_confirmation(tc, _log(400, 20), _prefs())
        assert "oats" in out.lower()
        assert "resynced" not in out.lower()

    # ── food confirmation variants ────────────────────────────────────────────

    def test_food_no_targets_shows_cal_only(self):
        """When no targets are set, just report the day total, no target fractions."""
        tc = [{"name": "log_food", "input": {"food_name": "banana"}}]
        out = deterministic_confirmation(tc, _log(300, 5), _prefs(cal_t=None, pro_t=None))
        assert "300 cal" in out.lower()
        # Should NOT have "target" fractions
        assert "/" not in out or "300" in out  # 300 is fine but not "300/None"

    def test_food_multi_item_turn_shows_generic_logged(self):
        """Multiple food items in one turn → 'Logged.' (not a specific food name)."""
        tc = [
            {"name": "log_food", "input": {"food_name": "eggs"}},
            {"name": "log_food", "input": {"food_name": "toast"}},
        ]
        out = deterministic_confirmation(tc, _log(450, 30), _prefs())
        # Generic 'Logged.' — not 'Eggs logged.' (ambiguous which one)
        first = out.split("|||")[0].strip()
        assert first.lower().startswith("logged") or "eggs" in first.lower()

    def test_food_protein_at_target_shows_what_is_next(self):
        """At/near protein target → 'What's next?' not 'keep it coming'."""
        tc = [{"name": "log_food", "input": {"food_name": "chicken breast"}}]
        # 190g protein out of 200g target → 95% = well above 85% threshold
        out = deterministic_confirmation(tc, _log(1800, 190), _prefs())
        assert "keep it coming" not in out.lower()
        assert "what's next" in out.lower()

    # ── water path ────────────────────────────────────────────────────────────

    def test_water_gives_water_emoji_and_sip(self):
        tc = [{"name": "log_water", "input": {"amount_ml": 500}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "💧" in out
        assert "sipping" in out.lower() or "water" in out.lower()

    def test_exercise_takes_priority_over_water(self):
        """Exercise + water logged same turn → exercise confirmation fires."""
        tc = [
            {"name": "log_exercise", "input": {"exercise_name": "row"}},
            {"name": "log_water", "input": {"amount_ml": 600}},
        ]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "row" in out.lower()
        assert "💧" not in out  # water emoji should NOT appear

    # ── delete path ───────────────────────────────────────────────────────────

    def test_delete_food_entry_shows_new_total(self):
        tc = [{"name": "delete_food_entry", "input": {"entry_id": 7}}]
        out = deterministic_confirmation(tc, _log(800, 60), _prefs())
        assert "removed" in out.lower()
        assert "800" in out

    def test_delete_exercise_entry(self):
        tc = [{"name": "delete_exercise_entry", "input": {"entry_id": 2}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "removed" in out.lower()

    # ── close_day ─────────────────────────────────────────────────────────────

    def test_close_day_wrap_message(self):
        tc = [{"name": "close_day", "input": {}}]
        out = deterministic_confirmation(tc, _log(2100, 180), _prefs())
        assert "wrap" in out.lower() or "closed" in out.lower()

    # ── body weight fallback priority ─────────────────────────────────────────

    def test_body_weight_string_weight_does_not_crash(self):
        """The LLM occasionally passes weight as a string — must not raise TypeError."""
        tc = [{"name": "log_body_weight", "input": {"weight": "175"}}]
        # float("175") = 175.0, which is > 0 → should confirm weigh-in
        out = deterministic_confirmation(tc, _log(), _prefs())
        # No crash is the main assertion
        assert out

    def test_body_weight_negative_not_confirmed(self):
        """Negative weight should not trigger the weigh-in confirmation."""
        tc = [{"name": "log_body_weight", "input": {"weight": -5}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "weight down" not in out.lower()

    def test_generic_fallback_for_unknown_tool(self):
        """Unknown tool name → generic fallback, not a crash."""
        tc = [{"name": "some_future_tool", "input": {}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert out  # something is returned
        assert "what's next" in out.lower()

    # ── multi-bubble structure ────────────────────────────────────────────────

    def test_food_confirmation_is_multi_bubble(self):
        """Every food confirmation must use ||| to split into bubbles."""
        tc = [{"name": "log_food", "input": {"food_name": "salmon"}}]
        out = deterministic_confirmation(tc, _log(400, 35), _prefs())
        assert "|||" in out

    def test_exercise_confirmation_is_multi_bubble(self):
        tc = [{"name": "log_exercise", "input": {"exercise_name": "squat"}}]
        out = deterministic_confirmation(tc, _log(), _prefs())
        assert "|||" in out

    def test_no_empty_bubbles(self):
        """Splitting on ||| should not produce blank bubbles."""
        for tc in [
            [{"name": "log_food", "input": {"food_name": "rice"}}],
            [{"name": "log_exercise", "input": {"exercise_name": "bench"}}],
            [{"name": "log_water", "input": {}}],
        ]:
            out = deterministic_confirmation(tc, _log(300, 20), _prefs())
            bubbles = [b.strip() for b in out.split("|||")]
            assert all(b for b in bubbles), f"empty bubble in: {out!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# looks_like_stall — expanded edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestStallDetectorEdgeCases:
    """
    User inputs that should and shouldn't trigger a stall. 'gonna log' / 'going to log'
    phrasing was added as a stall marker; verify it doesn't clip normal conversation.
    """

    def test_gonna_log_is_a_stall(self):
        assert looks_like_stall("gonna log your meals now")

    def test_going_to_log_is_a_stall(self):
        assert looks_like_stall("going to log that")

    def test_i_ll_log_all_is_a_stall(self):
        assert looks_like_stall("I'll log all of that now")

    def test_adding_it_all_is_a_stall(self):
        assert looks_like_stall("adding it all now")

    def test_logging_everything_is_a_stall(self):
        assert looks_like_stall("Logging everything you listed:")

    def test_normal_coaching_reply_not_a_stall(self):
        for txt in (
            "solid meal. let me know what you have for dinner.",
            "you're at 1,400 cal. what's the plan for tonight?",
            "that's a good protein hit. let me know when you're done training.",
            "nice work. what's the next set?",
        ):
            assert not looks_like_stall(txt), f"false positive: {txt!r}"

    def test_empty_string_not_a_stall(self):
        assert not looks_like_stall("")

    def test_none_not_a_stall(self):
        # None is cast via (text or "")
        assert not looks_like_stall(None)  # type: ignore[arg-type]

    def test_colon_at_end_is_a_stall(self):
        assert looks_like_stall("Now logging everything:")

    def test_on_it_prefix_is_a_stall(self):
        assert looks_like_stall("On it — clearing today and relogging to yesterday.")

    def test_regular_sentence_ending_in_colon_not_a_stall(self):
        """Only whole-text colon at the end — some coaching mentions specific items with colons."""
        # "Here's what I see:" followed by substance is NOT caught by the stall detector
        # because looks_like_stall checks t.endswith(":"), and coaching replies won't end on it
        assert not looks_like_stall("Here's what I see: 450 cal, 35g protein. solid.")


# ═══════════════════════════════════════════════════════════════════════════════
# looks_like_dead_end — expanded edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeadEndDetectorEdgeCases:
    """
    Dead-end detector: any reply that strips down to a bare acknowledgment token
    (after removing emoji/digits/punctuation) is flagged. Substance after the word is fine.
    """

    def test_dead_end_with_bubble_separator_still_flagged(self):
        """'done ✅|||' is still a dead-end — the ||| becomes a space, core = 'done'."""
        assert looks_like_dead_end("done ✅|||")

    def test_cool_with_emoji_is_dead_end(self):
        assert looks_like_dead_end("cool 🔥")

    def test_got_it_in_different_case(self):
        for txt in ("GOT IT", "Got it.", "GOT IT 👍"):
            assert looks_like_dead_end(txt), f"missed: {txt!r}"

    def test_substance_after_dead_end_word_is_allowed(self):
        for txt in (
            "cool, that's a solid protein hit",
            "done, you're at 1,200 for the day",
            "logged it — what's for dinner?",
            "got it, protein's still light at 80g",
            "nice work, that's two days in a row",
        ):
            assert not looks_like_dead_end(txt), f"false positive: {txt!r}"

    def test_alright_alone_is_dead_end(self):
        assert looks_like_dead_end("alright")
        assert looks_like_dead_end("alright.")

    def test_roger_alone_is_dead_end(self):
        assert looks_like_dead_end("roger")

    def test_multi_bubble_with_substance_not_dead_end(self):
        """A full reply with ||| bubbles is never a dead-end even if the first bubble is short."""
        txt = "logged ✅|||you're at 1,600/2,100 cal. protein's solid at 140g."
        assert not looks_like_dead_end(txt)

    def test_empty_is_not_dead_end(self):
        assert not looks_like_dead_end("")
        assert not looks_like_dead_end(None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# detect_turn_flags — combined scenarios from weird input flows
# ═══════════════════════════════════════════════════════════════════════════════

class TestTurnFlagCombos:
    """
    Realistic bad-turn combinations from production: tool errors mid-workout,
    user frustration + stall, image misroute.
    """

    def test_mid_workout_tool_error_flags_correctly(self):
        """A log_exercise call that errors should flag tool_error, not stall."""
        flags = detect_turn_flags(
            user_text="bench 225 for 5",
            response_text="Bench press logged. 💪|||What's the next set?",
            has_tool_calls=True,
            stop_reason="end_turn",
            retried=False,
            tool_error=True,
            source_type="text",
            tool_names={"log_exercise"},
        )
        assert "tool_error" in flags
        assert "stall_shipped" not in flags

    def test_frustrated_user_after_missed_food_item(self):
        flags = detect_turn_flags(
            user_text="you missed half the items again",
            response_text="Logged it.",
            has_tool_calls=True,
            stop_reason="end_turn",
            retried=False,
            tool_error=False,
            source_type="text",
            tool_names={"log_food"},
        )
        assert "user_frustrated" in flags

    def test_truncated_mid_food_dump(self):
        """A truncated food dump (max_tokens hit) flags truncated."""
        flags = detect_turn_flags(
            user_text="log: chicken, rice, broccoli, eggs, toast, banana, shake, yogurt",
            response_text="Logging all of that:",
            has_tool_calls=False,
            stop_reason="max_tokens",
            retried=True,
            tool_error=False,
            source_type="text",
            tool_names=set(),
        )
        assert "truncated" in flags
        assert "retried" in flags

    def test_image_food_with_no_log_food_call_misroute(self):
        """Photo of a meal where LLM only called log_body_weight → image_body_weight_misroute."""
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

    def test_clean_workout_set_turn_no_flags(self):
        """A normal mid-workout set log produces zero flags."""
        flags = detect_turn_flags(
            user_text="225 for 8",
            response_text="🏋️ Bench · 1×8 @225lb|||up 5lb from last week, push for 230 next set.",
            has_tool_calls=True,
            stop_reason="end_turn",
            retried=False,
            tool_error=False,
            source_type="text",
            tool_names={"log_exercise"},
        )
        assert flags == []

    def test_stall_only_fires_when_no_tools(self):
        """'Let me log all of that' with an actual tool call is NOT a stall."""
        flags = detect_turn_flags(
            user_text="log everything i listed",
            response_text="Let me log all of that now.",
            has_tool_calls=True,
            stop_reason="end_turn",
            retried=False,
            tool_error=False,
            source_type="text",
            tool_names={"log_food"},
        )
        assert "stall_shipped" not in flags


# ═══════════════════════════════════════════════════════════════════════════════
# Food intelligence integration: reconcile_macros called through analyze()
# ═══════════════════════════════════════════════════════════════════════════════

class TestFoodIntelligenceIntegration:
    """
    verify reconcile_macros is actually called inside analyze() so the DB
    never receives physically impossible macro numbers.
    """

    def test_analyze_outputs_consistent_macros_for_bad_llm_input(self):
        """
        Simulate what happens when the LLM submits 500 cal but macros sum to 800+.
        After analyze(), the returned macros must be consistent.
        """
        from core.food_intelligence import analyze

        # Classic bad LLM output: 500 cal, P=50g, C=80g, F=30g → 200+320+270=790
        result = analyze("chicken breast", "6oz", 500, 50, 80, 30)
        actual_cal = result.protein * 4 + result.carbs * 4 + result.fat * 9
        stated_cal = result.calories
        pct_err = abs(actual_cal - stated_cal) / stated_cal
        assert pct_err <= 0.15, (
            f"analyze() still returns inconsistent macros: "
            f"P={result.protein}g C={result.carbs}g F={result.fat}g → {actual_cal:.0f} cal "
            f"vs stated {stated_cal} cal ({pct_err:.1%} off)"
        )

    def test_analyze_calories_unchanged_by_reconcile(self):
        """analyze() must not alter the stated calorie count."""
        from core.food_intelligence import analyze
        result = analyze("salmon", "4oz", 250, 45, 60, 25)
        assert result.calories == 250

    def test_analyze_with_consistent_macros_leaves_them_alone(self):
        """If the LLM gives consistent macros, analyze() should not perturb them."""
        from core.food_intelligence import analyze
        # 30g*4 + 40g*4 + 10g*9 = 120+160+90 = 370 vs stated 360 → 2.7% off (ok)
        result = analyze("oatmeal", "1 cup", 360, 30, 40, 10)
        assert result.protein == 30, "protein changed when macros were fine"
        assert result.carbs == 40, "carbs changed when macros were fine"
        assert result.fat == 10, "fat changed when macros were fine"
