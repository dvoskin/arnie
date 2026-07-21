"""
Food logging simulation tests — all formats, all clarification scenarios.

No LLM, no DB, no network. Tests exercise the deterministic layers that
govern what gets logged and what gets confirmed:

  deterministic_confirmation — fallback wording for every food-log scenario
  _macros_from_search        — USDA result parsing (what the LLM sees for searches)
  render_pending_clarification_block — what context the LLM reads when questions are open
  Prompt integrity           — verifies the LLM has correct rules for each scenario

Scenarios:
  A  Single-item foods — clear, no clarification needed
  B  Single-item foods — calorie-context thresholds
  C  Single-item foods — protein-state thresholds
  D  Multi-item foods  — all clear, log all
  E  Multi-item foods  — partial/missing food names
  F  Calorie boundary conditions — exact threshold edges
  G  Protein boundary conditions — exact threshold edges
  H  USDA macro parsing — various result string formats
  I  Multi-item pending clarification — two items in one block
  J  Prompt rule integrity — new multi-item and clarification rules
"""
import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from tests.conftest import _prefs, _log
from handlers.tool_executor import deterministic_confirmation, _macros_from_search
from core.context_builder import render_pending_clarification_block


# ── helpers ───────────────────────────────────────────────────────────────────

def _tc(name, food_name=None, exercise_name=None):
    inp = {}
    if food_name is not None:
        inp["food_name"] = food_name
    if exercise_name is not None:
        inp["exercise_name"] = exercise_name
    return {"name": name, "input": inp}


def _food(name):
    return _tc("log_food", food_name=name)


def _update(name):
    return _tc("update_food_entry", food_name=name)


def _pending(item, question, minutes_ago=5, answered=False):
    return SimpleNamespace(
        kind="food_clarification",
        question=question,
        item_referenced=item,
        asked_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        answered_at=datetime.utcnow() if answered else None,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# A  Single-item foods — clear, no clarification needed
# ═══════════════════════════════════════════════════════════════════════════════

class TestSingleItemClear:
    """These foods need no question — the fallback should confirm and move on."""

    def test_banana(self):
        out = deterministic_confirmation([_food("banana")], _log(200, 5), _prefs())
        assert "banana" in out.lower()
        assert "logged" in out.lower()
        assert "|||" in out

    def test_black_coffee(self):
        """Basically zero calories — still confirms."""
        out = deterministic_confirmation([_food("black coffee")], _log(15, 0), _prefs())
        assert "black coffee" in out.lower()
        assert "15" in out

    def test_greek_yogurt(self):
        out = deterministic_confirmation([_food("Greek yogurt")], _log(420, 55), _prefs())
        assert "greek yogurt" in out.lower()
        assert "420" in out
        assert "55 / 200" in out  # above 85% of 200 → at-target path

    def test_protein_shake(self):
        out = deterministic_confirmation([_food("protein shake")], _log(600, 85), _prefs())
        assert "protein shake" in out.lower()
        assert "600" in out

    def test_oatmeal(self):
        out = deterministic_confirmation([_food("oatmeal")], _log(350, 12), _prefs(cal_t=2000))
        assert "oatmeal" in out.lower()
        # 350 / 2000 = 17.5% → good room left
        assert "good room left" in out.lower()

    def test_never_dead_ends(self):
        """Every single-item log must end with some kind of next-step signal."""
        items = ["apple", "rice", "steak", "soda", "hummus"]
        for item in items:
            out = deterministic_confirmation([_food(item)], _log(500, 30), _prefs())
            bubbles = out.split("|||")
            assert len(bubbles) >= 2, f"{item}: only {len(bubbles)} bubble(s)"
            last = bubbles[-1].strip()
            assert last, f"{item}: last bubble is empty"


# ═══════════════════════════════════════════════════════════════════════════════
# B  Single-item foods — calorie-context thresholds
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalorieContext:
    """The calorie tail should reflect where the user stands vs. their target."""

    def test_no_target_spells_out_calories(self):
        out = deterministic_confirmation([_food("eggs")], _log(180, 14), _prefs(cal_t=None, pro_t=None))
        assert "180 calories" in out
        assert "so far today" in out.lower()

    def test_good_room_left_when_well_under_target(self):
        # 400 / 2000 = 20% — clearly "good room left"
        out = deterministic_confirmation([_food("banana")], _log(400, 5), _prefs(cal_t=2000, pro_t=None))
        assert "good room left" in out.lower()

    def test_tight_finish_when_near_target(self):
        # 1800 / 2000 = 90% — "tight finish"
        out = deterministic_confirmation([_food("chicken")], _log(1800, 80), _prefs(cal_t=2000, pro_t=None))
        assert "tight finish" in out.lower()

    def test_keep_controlled_when_at_target(self):
        # 2000 / 2000 = 100% — "keep the rest controlled"
        out = deterministic_confirmation([_food("pasta")], _log(2000, 60), _prefs(cal_t=2000, pro_t=None))
        assert "keep the rest controlled" in out.lower()

    def test_keep_controlled_when_over_target(self):
        # 2400 / 2000 = 120% — still "keep the rest controlled"
        out = deterministic_confirmation([_food("burger")], _log(2400, 90), _prefs(cal_t=2000, pro_t=None))
        assert "keep the rest controlled" in out.lower()

    def test_calorie_format_uses_slash_and_word(self):
        """Must write 'X / Y calories', not 'X/Y cal'."""
        out = deterministic_confirmation([_food("rice")], _log(800, 20), _prefs(cal_t=2000, pro_t=None))
        assert " / " in out
        assert "calories" in out.lower()
        # Must NOT use the old format
        assert "/2000 cal" not in out
        assert "800/2000" not in out


# ═══════════════════════════════════════════════════════════════════════════════
# C  Single-item foods — protein-state thresholds
# ═══════════════════════════════════════════════════════════════════════════════

class TestProteinState:
    """Protein bubble should reflect how close the user is to their target."""

    def test_low_protein_nudge_when_well_below(self):
        # 40g of 200g target = 20% → low protein
        out = deterministic_confirmation([_food("toast")], _log(300, 40), _prefs(pro_t=200))
        assert "40 / 200g" in out
        assert "protein-first" in out.lower()

    def test_at_target_path_when_above_85_pct(self):
        # 170g of 200g = 85% → at/above path
        out = deterministic_confirmation([_food("steak")], _log(900, 170), _prefs(pro_t=200))
        assert "170 / 200" in out
        assert "protein-first" not in out.lower()

    def test_at_target_path_when_over_target(self):
        # 220g of 200g = 110% → still at/above path
        out = deterministic_confirmation([_food("chicken")], _log(1100, 220), _prefs(pro_t=200))
        assert "220 / 200" in out
        assert "protein-first" not in out.lower()

    def test_no_protein_target_ends_with_send_next_meal(self):
        out = deterministic_confirmation([_food("fruit salad")], _log(200, 3), _prefs(pro_t=None))
        assert "send the next meal" in out.lower()

    def test_no_protein_target_no_protein_line(self):
        """When there's no protein target, don't show a protein fraction."""
        out = deterministic_confirmation([_food("watermelon")], _log(80, 2), _prefs(cal_t=2000, pro_t=None))
        assert "/" not in out.split("|||")[-1]  # no X/Y in last bubble


# ═══════════════════════════════════════════════════════════════════════════════
# D  Multi-item foods — all clear, log all
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiItemAllClear:
    """When multiple foods are logged in one turn, the head should name them."""

    def test_two_foods_listed_in_head(self):
        tcs = [_food("chicken"), _food("rice")]
        out = deterministic_confirmation(tcs, _log(700, 55), _prefs())
        assert out.lower().startswith("logged:")
        assert "chicken" in out.lower()
        assert "rice" in out.lower()

    def test_three_foods_all_listed(self):
        tcs = [_food("chicken"), _food("rice"), _food("broccoli")]
        out = deterministic_confirmation(tcs, _log(750, 60), _prefs())
        assert "chicken" in out.lower()
        assert "rice" in out.lower()
        assert "broccoli" in out.lower()

    def test_five_foods_all_listed(self):
        tcs = [_food(f) for f in ["chicken", "rice", "broccoli", "olive oil", "salad dressing"]]
        out = deterministic_confirmation(tcs, _log(900, 65), _prefs())
        head = out.split("|||")[0]
        for food in ["chicken", "rice", "broccoli"]:
            assert food in head.lower()

    def test_multi_item_still_shows_calorie_state(self):
        tcs = [_food("chicken"), _food("rice")]
        out = deterministic_confirmation(tcs, _log(1850, 70), _prefs(cal_t=2000, pro_t=None))
        assert "tight finish" in out.lower()

    def test_multi_item_still_shows_protein_nudge(self):
        tcs = [_food("pasta"), _food("bread")]
        out = deterministic_confirmation(tcs, _log(900, 30), _prefs(pro_t=200))
        assert "protein-first" in out.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# E  Multi-item foods — partial/missing food names
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiItemMissingNames:
    """Edge cases where food_name is absent or empty."""

    def test_update_food_entry_only_returns_fixed_not_logged(self):
        """A pure correction (update only, no new log) → 'Fixed.' path.
        'Updated.' and 'totals are resynced' are banned words — must NOT appear."""
        tcs = [_update("chicken breast")]
        out = deterministic_confirmation(tcs, _log(800, 70), _prefs())
        # Should say "fixed" (the correct, non-banned wording) and name the item
        assert "fixed" in out.lower()
        assert "chicken breast" in out.lower()
        # Banned words must not appear
        assert "updated." not in out.lower()
        assert "resynced" not in out.lower()
        # Should NOT hit the food-logged path
        assert "logged" not in out.lower()

    def test_log_food_with_empty_name_falls_to_meal_logged(self):
        tcs = [_tc("log_food", food_name="")]
        out = deterministic_confirmation(tcs, _log(400, 30), _prefs())
        assert "meal logged" in out.lower()

    def test_log_food_no_name_key_falls_to_meal_logged(self):
        tcs = [{"name": "log_food", "input": {}}]
        out = deterministic_confirmation(tcs, _log(400, 30), _prefs())
        assert "meal logged" in out.lower()

    def test_log_food_plus_update_combines_both_names(self):
        """New food + correction in same turn → names both in head."""
        tcs = [_food("chicken"), _update("eggs")]
        out = deterministic_confirmation(tcs, _log(900, 75), _prefs())
        assert "chicken" in out.lower()
        assert "eggs" in out.lower()

    def test_log_food_name_preserved_when_update_has_no_name(self):
        """update_food_entry with no name doesn't erase the logged food's name."""
        tcs = [_food("salmon"), _tc("update_food_entry", food_name="")]
        out = deterministic_confirmation(tcs, _log(700, 60), _prefs())
        assert "salmon" in out.lower()
        # Only one named food → "Salmon logged." not "Logged: salmon."
        assert out.lower().startswith("salmon logged")


# ═══════════════════════════════════════════════════════════════════════════════
# F  Calorie boundary conditions — exact threshold edges
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalorieBoundaries:
    """The 85% boundary must be exact: at or above → tight finish."""

    def test_just_below_85_pct_is_good_room_left(self):
        # 84% of 2000 = 1680 → "good room left"
        out = deterministic_confirmation([_food("rice")], _log(1680, 50), _prefs(cal_t=2000, pro_t=None))
        assert "good room left" in out.lower()

    def test_exactly_at_85_pct_is_tight_finish(self):
        # 85% of 2000 = 1700 → "tight finish"
        out = deterministic_confirmation([_food("rice")], _log(1700, 50), _prefs(cal_t=2000, pro_t=None))
        assert "tight finish" in out.lower()

    def test_just_above_85_pct_is_tight_finish(self):
        # 86% of 2000 = 1720 → "tight finish"
        out = deterministic_confirmation([_food("rice")], _log(1720, 50), _prefs(cal_t=2000, pro_t=None))
        assert "tight finish" in out.lower()

    def test_exactly_at_100_pct_is_controlled(self):
        # 100% of 2000 = 2000 → "keep the rest controlled"
        out = deterministic_confirmation([_food("rice")], _log(2000, 50), _prefs(cal_t=2000, pro_t=None))
        assert "keep the rest controlled" in out.lower()

    def test_one_calorie_over_is_controlled(self):
        # 2001 / 2000 → "keep the rest controlled"
        out = deterministic_confirmation([_food("rice")], _log(2001, 50), _prefs(cal_t=2000, pro_t=None))
        assert "keep the rest controlled" in out.lower()

    def test_zero_calories_is_good_room_left(self):
        # 0 / 2000 → "good room left"
        out = deterministic_confirmation([_food("water")], _log(0, 0), _prefs(cal_t=2000, pro_t=None))
        assert "good room left" in out.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# G  Protein boundary conditions — exact threshold edges
# ═══════════════════════════════════════════════════════════════════════════════

class TestProteinBoundaries:
    """85% threshold: strictly below → low protein; at or above → at-target."""

    def test_just_below_85_pct_is_low_protein(self):
        # 84% of 200 = 168 → low protein
        out = deterministic_confirmation([_food("pasta")], _log(800, 168), _prefs(pro_t=200))
        assert "protein-first" in out.lower()

    def test_exactly_at_85_pct_is_at_target_path(self):
        # 85% of 200 = 170 → at/above path (NOT low protein)
        out = deterministic_confirmation([_food("chicken")], _log(800, 170), _prefs(pro_t=200))
        assert "protein-first" not in out.lower()
        assert "170 / 200" in out

    def test_just_above_85_pct_is_at_target_path(self):
        # 86% of 200 = 172 → at/above path
        out = deterministic_confirmation([_food("steak")], _log(900, 172), _prefs(pro_t=200))
        assert "protein-first" not in out.lower()

    def test_zero_protein_with_target_is_low_protein(self):
        out = deterministic_confirmation([_food("white rice")], _log(300, 0), _prefs(pro_t=200))
        assert "protein-first" in out.lower()
        assert "0 / 200" in out

    def test_fractional_protein_target_handles_without_crash(self):
        # pro_t=150 → 85% = 127.5; pro=127 → below
        out = deterministic_confirmation([_food("salad")], _log(500, 127), _prefs(pro_t=150))
        assert "protein-first" in out.lower()

    def test_fractional_protein_target_at_boundary(self):
        # pro_t=150, pro=128 → 128 >= 127.5 → at/above
        out = deterministic_confirmation([_food("chicken")], _log(700, 128), _prefs(pro_t=150))
        assert "protein-first" not in out.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# H  USDA macro parsing — _macros_from_search
# ═══════════════════════════════════════════════════════════════════════════════

class TestMacrosFromSearch:
    """The parser must extract macros accurately from various USDA result formats."""

    def test_standard_for_x_format(self):
        result = "For 1 bar (~50g): 180 cal, 20g P, 4g C, 9g F"
        assert _macros_from_search(result) == "180 cal, 20g P, 4g C, 9g F"

    def test_for_x_format_with_decimal_calories(self):
        result = "For 1 cup (240ml): 12.5 cal, 1g P, 2g C, 0g F"
        parsed = _macros_from_search(result)
        assert parsed.startswith("12.5 cal")

    def test_for_x_format_no_space_before_cal(self):
        result = "For 2 tbsp: 30cal, 0g P, 2g C, 3g F"
        parsed = _macros_from_search(result)
        assert "30cal" in parsed

    def test_per_100g_fallback(self):
        result = "Per 100g: 360 cal | 40g protein | 8g carbs | 18g fat"
        parsed = _macros_from_search(result)
        assert "360 cal" in parsed
        assert "per 100g" in parsed.lower()

    def test_prefers_for_x_over_per_100g(self):
        result = (
            "For 1 serving (30g): 120 cal, 10g P, 5g C, 6g F\n"
            "Per 100g: 400 cal | 33g protein | 17g carbs | 20g fat"
        )
        parsed = _macros_from_search(result)
        # Should pick the "For 1 serving" line
        assert parsed.startswith("120 cal")

    def test_empty_string_returns_empty(self):
        assert _macros_from_search("") == ""

    def test_none_equivalent_returns_empty(self):
        assert _macros_from_search(None) == ""

    def test_no_match_returns_empty(self):
        result = "Food not found in database."
        assert _macros_from_search(result) == ""

    def test_error_string_returns_empty(self):
        result = "Error: USDA lookup failed"
        assert _macros_from_search(result) == ""

    def test_partial_match_no_cal_keyword_returns_empty(self):
        # Has "For X:" but no "cal" in the capture group
        result = "For 1 bar: protein 20g, fat 5g, carbs 2g"
        assert _macros_from_search(result) == ""

    def test_search_only_fallback_surfaces_macros(self):
        """When search runs without a log (pure macro question), the fallback
        builds a head from parsed macros. Verify the macro string is usable."""
        result = "For 1 egg (50g): 78 cal, 6g P, 0g C, 5g F"
        macro = _macros_from_search(result)
        assert macro  # non-empty
        assert "78 cal" in macro


# ═══════════════════════════════════════════════════════════════════════════════
# I  Multi-item pending clarification — context block
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiItemPendingBlock:
    """When multiple foods need clarification, the context block must surface
    all of them so the LLM logs everything on the next turn."""

    def test_two_items_both_appear_in_block(self):
        rows = [
            _pending("Caesar salad", "what dressing, and how much?", minutes_ago=3),
            _pending("chicken soup", "homemade or restaurant?", minutes_ago=3),
        ]
        block = render_pending_clarification_block(rows)
        assert "Caesar salad" in block
        assert "chicken soup" in block
        assert "what dressing" in block
        assert "homemade or restaurant" in block

    def test_two_items_both_questions_surfaced(self):
        rows = [
            _pending("pasta", "what sauce?", minutes_ago=2),
            _pending("protein shake", "what brand?", minutes_ago=2),
        ]
        block = render_pending_clarification_block(rows)
        assert "what sauce" in block
        assert "what brand" in block

    def test_block_tells_llm_to_log_all_foods(self):
        """Core multi-item fix: block must instruct logging ALL foods, not just
        the clarified one."""
        rows = [_pending("chicken", "grilled or fried?")]
        block = render_pending_clarification_block(rows)
        assert "all" in block.lower()

    def test_stale_item_not_surfaced_fresh_item_is(self):
        rows = [
            _pending("pasta", "what sauce?", minutes_ago=5),    # fresh
            _pending("chicken", "grilled or fried?", minutes_ago=45),  # stale
        ]
        block = render_pending_clarification_block(rows)
        assert "pasta" in block
        assert "chicken" not in block

    def test_answered_item_not_surfaced(self):
        rows = [
            _pending("salmon", "grilled?", minutes_ago=5, answered=True),
            _pending("rice", "brown or white?", minutes_ago=5, answered=False),
        ]
        block = render_pending_clarification_block(rows)
        assert "rice" in block
        assert "salmon" not in block

    def test_three_items_all_appear(self):
        rows = [
            _pending("chicken soup", "homemade?", minutes_ago=2),
            _pending("Caesar salad", "what dressing?", minutes_ago=2),
            _pending("cantaloupe", "quarter?", minutes_ago=2),
        ]
        block = render_pending_clarification_block(rows)
        item_lines = [l for l in block.split("\n") if l.startswith("  - ")]
        assert len(item_lines) == 3

    def test_four_items_caps_at_three(self):
        """Block caps at 3 to keep prompt lean even with 4 pending."""
        rows = [_pending(f"food-{i}", f"question {i}?", minutes_ago=i + 1) for i in range(4)]
        block = render_pending_clarification_block(rows)
        item_lines = [l for l in block.split("\n") if l.startswith("  - ")]
        assert len(item_lines) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# J  Prompt rule integrity — new multi-item and clarification rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptRuleIntegrity:
    """Verify the LLM has the right instructions for every key scenario.
    These are the rules that drive LLM behavior — if they're missing or wrong,
    the LLM will fail silently in production."""

    @pytest.fixture(scope="class")
    def system(self):
        from core.prompts.arnie import build_arnie_system
        return build_arnie_system("telegram")

    # ── multi-item connectors ──────────────────────────────────────────────────

    def test_conversational_connectors_in_multi_item_rule(self, system):
        """'then', 'after that', 'also' must be recognised as item separators
        so voice-style messages like 'I had X then Y' are parsed correctly."""
        assert '"then"' in system
        assert '"after that"' in system
        assert '"also"' in system

    def test_multi_item_rule_covers_conversational_chaining(self, system):
        assert "conversational chaining" in system

    # ── clarification gate logic ───────────────────────────────────────────────

    def test_clarification_hold_all_items_rule(self, system):
        """When any item needs clarification, NOTHING gets logged yet."""
        assert "not even the items you can already estimate" in system

    def test_note_food_clarification_once_per_item(self, system):
        """Must call note_food_clarification once PER unclear item, not once total."""
        assert "once PER unclear item" in system

    def test_log_everything_after_clarification(self, system):
        """After clarification is answered, ALL items must be logged — not just the
        ones that needed questions."""
        assert "log EVERYTHING" in system

    def test_never_log_item_1_while_holding_question_about_item_2(self, system):
        assert "Never log item 1 while holding a question about item 2" in system

    # ── accuracy mode / persistence ───────────────────────────────────────────

    def test_accuracy_mode_quick_has_15_min_window(self, system):
        assert "15 minutes" in system or "15-min" in system

    def test_accuracy_mode_strict_has_60_min_window(self, system):
        assert "60 minutes" in system or "60-min" in system

    # ── food accuracy rules ────────────────────────────────────────────────────

    def test_decompose_everything_covers_salad(self, system):
        """Salad is the example for hidden dressing calories."""
        assert '"salad"' in system or "'salad'" in system or "salad" in system

    def test_salad_dressing_is_in_hidden_calories(self, system):
        assert "salad dressing" in system.lower()

    def test_ask_question_example_includes_salad_dressing(self, system):
        """'what dressing, and how much?' must be the cue for any salad."""
        assert "what dressing" in system

    def test_multi_item_list_logs_first_then_refines(self, system):
        """The log-all-first rule replaced the old per-item 'pasta → what sauce?'
        ask example: a multi-item list is logged in full, THEN refined — never held
        for a question. Pin the rule so the behavior can't silently regress."""
        assert "LOG THE WHOLE LIST FIRST" in system

    def test_ask_question_example_includes_protein_cook_method(self, system):
        assert "grilled or fried" in system

    def test_hidden_calories_covers_cooking_oil(self, system):
        assert "cooking oil" in system.lower() or "saut" in system.lower()

    # ── numbers / wording rules ───────────────────────────────────────────────

    def test_spell_out_calories_not_cal(self, system):
        """The wording rule must appear in the prompt."""
        assert "'calories' not 'cal'" in system or '"calories" not "cal"' in system

    def test_numbers_are_sacred_rule_present(self, system):
        assert "NUMBERS ARE SACRED" in system

    def test_day_total_verbatim_rule(self, system):
        assert "verbatim" in system and "DAY TOTAL" in system

    # ── quantity rule ──────────────────────────────────────────────────────────

    def test_quantity_is_mandatory_rule_present(self, system):
        assert "QUANTITY IS MANDATORY" in system

    def test_never_log_1_serving(self, system):
        assert '"1 serving"' in system or "1 serving" in system
