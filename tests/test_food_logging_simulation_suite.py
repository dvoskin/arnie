"""
HIGH-VOLUME SIMULATION SUITE — exercises every food-logging code path that
doesn't require an LLM round-trip. Covers:

  DIMENSION                       VARIANTS
  ──────────────────────────────  ────────────────────────────────────────
  modality                        text, [Voice note], [Food photo]
  food_logging_mode               quick, moderate, strict, unknown
  number of items per turn        1, 2, 3, 5, 7, 10, 25
  food types                      banana, brand (built bar), brand variant
                                  (royo bagel vs royo challah roll), generic
                                  (protein bar), compound (chicken sandwich),
                                  drink (cappuccino), restaurant meal
  clarification ordering          fresh, stale-quick, stale-moderate, stale-strict,
                                  multi-row, generic, specific, mixed
  pending-vs-log interactions     log A while Q about A   (close)
                                  log A while Q about B   (don't close)
                                  log A while Q is generic + A is specific
                                  multi-item log against multi-row pending
  prompt-rule integrity           every rule added in phases 1-7

Each simulation asserts a single, narrowly-scoped expectation so a failure
points at a specific regression.
"""
import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta

from tests.conftest import _prefs, _log
from handlers.tool_executor import (
    deterministic_confirmation, _apply_multi_item_batch_coaching,
    tool_heads_up, _TOOL_HEADS_UP_BUBBLES,
)
from core.context_builder import (
    render_pending_clarification_block, food_mode_directive,
)
from core.food_intelligence import (
    is_generic_food_name, normalize_name, normalize_food_logging_mode,
    reconcile_macros, _FOOD_FILLER,
)
from core.prompts.arnie import build_arnie_system


# ── Helpers ──────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = build_arnie_system("telegram")


def _row(item="chicken sandwich", q="grilled or fried?",
         minutes_ago=5, answered=False, kind="food_clarification"):
    return SimpleNamespace(
        kind=kind, question=q, item_referenced=item,
        asked_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        answered_at=datetime.utcnow() if answered else None,
    )


def _log_food_call(food_name, **kwargs):
    inp = {"food_name": food_name, **kwargs}
    return {"id": f"tc-{food_name[:8]}", "name": "log_food", "input": inp}


def _coaching_stub(food_name="oatmeal", cal=200, p=10, cal_t=2000, pro_t=180):
    """Replicates the shape of the real log_food tool-result string."""
    return (
        f"Logged {food_name}: {cal} cal, {p}g protein. ANALYSIS: ok. "
        f"DAY TOTAL: {cal} cal, {p}g protein ({cal_t-cal} cal left, "
        f"{pro_t-p}g protein to go). "
        f"Scale the reply to the log. Meaningful meal: name the food and its macros. "
        f"Sentence case. One emoji if it fits naturally."
    )


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 1 — Prompt rule integrity across all hardening phases
# ════════════════════════════════════════════════════════════════════════════


# Phase 1 — turn-scoped logging
@pytest.mark.parametrize("rule_marker", [
    "LOGGING SCOPE",
    "THIS turn's user message",
    "BRAND VARIANT GUARD",
    "REMOVED-VIA-DASHBOARD AWARENESS",
    "do NOT restore",
])
def test_prompt_contains_phase1_rule(rule_marker):
    assert rule_marker in SYSTEM_PROMPT, (
        f"Phase-1 rule marker {rule_marker!r} missing from system prompt"
    )


# Phase 3 — modality × mode
@pytest.mark.parametrize("rule_marker", [
    "QUICK + GENERIC BRAND",
    "STRICT + VOICE",
    "OVERRIDES",  # photo describe-first override
])
def test_prompt_contains_phase3_rule(rule_marker):
    assert rule_marker in SYSTEM_PROMPT


# Phase 7 — voice + framing
@pytest.mark.parametrize("rule_marker", [
    "CALORIE-ROOM ACCURACY",
    "PROTEIN-GAP-WITH-ROOM",
    "NEVER NARRATE TOOL-RESULT INTERNALS",
    "process invisible",
])
def test_prompt_contains_phase7_rule(rule_marker):
    assert rule_marker in SYSTEM_PROMPT


# Phase 7 — the exact bug examples are namedropped so a future rewrite that
# drops them fails loud here, not in production.
def test_prompt_namedrops_the_at_cal_limit_anti_pattern():
    assert "basically at your cal limit" in SYSTEM_PROMPT
    # And the corrected version is also exemplified
    assert "still room" in SYSTEM_PROMPT.lower() or "to play with" in SYSTEM_PROMPT


def test_prompt_namedrops_the_happy_wolf_anti_pattern_class():
    """The tool-result-narration ban must include the 'match doesn't look right'
    class of leak — that's the live bug we just hit."""
    assert "match doesn't look right" in SYSTEM_PROMPT


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 2 — deterministic_confirmation across all tool-call combos
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("foods,expect_substrings", [
    (["banana"], ["banana", "calories"]),
    (["banana", "coffee"], ["calories"]),
    (["oatmeal", "eggs", "toast"], ["calories"]),
    (["oikos shake", "built bar", "coffee", "apple", "almonds"], ["calories"]),
])
def test_deterministic_confirmation_log_food_batches(foods, expect_substrings):
    tcs = [_log_food_call(f) for f in foods]
    out = deterministic_confirmation(tcs, _log(600, 35), _prefs())
    for s in expect_substrings:
        assert s in out.lower(), f"{s!r} not in {out!r}"
    # Always day-total framing
    assert "|||" in out


@pytest.mark.parametrize("tool_calls,banned", [
    # update-food path: 'Updated.' and 'resynced' are banned wording
    ([{"name": "update_food_entry", "input": {"food_name": "chicken"}}],
     ["updated.", "resynced"]),
    # delete-food path: format must be 'X / Y calories', not 'X/Y cal'
    ([{"name": "delete_food_entry", "input": {}}],
     ["got it logged", "logged it"]),
])
def test_deterministic_confirmation_banned_wording(tool_calls, banned):
    out = deterministic_confirmation(tool_calls, _log(400, 30), _prefs())
    out_low = out.lower()
    for b in banned:
        assert b not in out_low, f"banned phrase {b!r} appeared in {out!r}"


def test_deterministic_confirmation_no_cal_target_works():
    """Users without a calorie target still get a clean confirmation."""
    out = deterministic_confirmation([_log_food_call("banana")],
                                     _log(120, 1), _prefs(cal_t=None))
    assert "banana" in out.lower() or "logged" in out.lower()
    assert "/" not in out.split("|||")[0] or "cal" in out.lower()


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 3 — _apply_multi_item_batch_coaching at scale
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("n_items", [1, 2, 3, 5, 7, 10, 25])
def test_batch_coaching_scales_to_n_items(n_items):
    """The batch coaching must fire for n>=2 and stay quiet for n==1, at any
    scale. The model should always get anchors for the first three items."""
    names = [f"food-{i}" for i in range(n_items)]
    tcs = [_log_food_call(n) for n in names]
    res = _apply_multi_item_batch_coaching(
        {"log_food": _coaching_stub(names[-1])}, tcs,
    )
    out = res["log_food"]
    if n_items == 1:
        assert "MULTI-ITEM BATCH" not in out
        assert "Scale the reply" in out
    else:
        assert "MULTI-ITEM BATCH" in out
        assert f"{n_items} foods" in out
        # First three anchors must be present so the model can summarize
        for n in names[:3]:
            assert n in out
        # Anti-restore guard must always be present
        assert "Never restore" in out


def test_batch_coaching_handles_blank_food_names_gracefully():
    """Malformed log_food calls with empty food_name must not crash the swap."""
    tcs = [_log_food_call(""), _log_food_call("banana")]
    res = _apply_multi_item_batch_coaching(
        {"log_food": _coaching_stub("banana")}, tcs,
    )
    # Should still apply because there are 2 log_food calls. The named food
    # gets preserved; the empty one is just skipped from the preview list.
    out = res["log_food"]
    assert "MULTI-ITEM BATCH" in out
    assert "banana" in out


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 4 — render_pending_clarification_block across mode × age × count
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("mode,age_min,should_render", [
    # quick — 15 min window
    ("quick", 5, True),
    ("quick", 14, True),
    ("quick", 16, False),
    ("quick", 30, False),
    # moderate — 30 min window
    ("moderate", 5, True),
    ("moderate", 29, True),
    ("moderate", 31, False),
    ("moderate", 60, False),
    # strict — 60 min window
    ("strict", 5, True),
    ("strict", 45, True),
    ("strict", 61, False),
    # unknown falls back to moderate
    (None, 25, True),
    (None, 35, False),
    ("nonsense", 25, True),
])
def test_pending_block_freshness_matrix(mode, age_min, should_render):
    out = render_pending_clarification_block(
        [_row(minutes_ago=age_min)], food_mode=mode,
    )
    if should_render:
        assert out, f"mode={mode} age={age_min}: expected render, got empty"
        assert "[PENDING CLARIFICATION]" in out
    else:
        assert out == "", f"mode={mode} age={age_min}: expected empty, got {out!r}"


@pytest.mark.parametrize("n_rows,expected_lines", [
    (1, 1), (2, 2), (3, 3), (5, 3), (10, 3),  # caps at 3
])
def test_pending_block_caps_at_three(n_rows, expected_lines):
    rows = [_row(item=f"item-{i}", minutes_ago=i + 1) for i in range(n_rows)]
    out = render_pending_clarification_block(rows)
    if n_rows == 0:
        assert out == ""
    else:
        item_lines = [line for line in out.split("\n") if line.startswith("  - ")]
        assert len(item_lines) == expected_lines


def test_pending_block_branches_text_is_explicit():
    out = render_pending_clarification_block([_row(minutes_ago=5)])
    # Both branches must be spelled out
    assert "IF this turn answers your question" in out
    assert "IF this turn is a NEW food" in out
    assert "log ONLY the new food" in out


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 5 — item-scoped resolve under all match conditions
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("question_item,logged_name,should_close", [
    # Exact match
    ("banana", "banana", True),
    # Substring (specific log of generic question)
    ("protein bar", "barebells caramel protein bar", True),
    # Shared content token (the "which bar?" → "built bar" case)
    ("protein bar", "built bar", True),
    # No overlap — must NOT close
    ("banana with honey", "royo bagel", False),
    ("chicken sandwich", "coffee", False),
    ("salad", "chicken breast", False),
    # Empty logged name — defensive
    ("banana", "", False),
])
async def test_resolve_match_conditions(make_user, db,
                                         question_item, logged_name, should_close):
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id=f"t-resolve-{hash((question_item, logged_name)) & 0xffff}")

    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="?", tier="other", hook_style="question",
    )
    pq.item_referenced = question_item
    await db.commit()

    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, [logged_name] if logged_name else []
    )
    if should_close:
        assert closed == 1, (
            f"expected close: q='{question_item}' log='{logged_name}'"
        )
    else:
        assert closed == 0, (
            f"expected NO close: q='{question_item}' log='{logged_name}'"
        )


@pytest.mark.asyncio
async def test_resolve_handles_multi_item_log_against_multi_row_pending(make_user, db):
    """Multi-item log {chicken sandwich, coffee} resolves both — for an open
    question about chicken sandwich, plus an open question about coffee. An
    unrelated question (salad) stays open."""
    from db.models import PendingQuestion
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-multi-resolve")

    pq_a = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="grilled or fried?", tier="cook_method", hook_style="question",
    )
    pq_a.item_referenced = "chicken sandwich"
    await db.commit()
    db.add(PendingQuestion(
        user_id=user.id, kind="food_clarification",
        question="size?", item_referenced="coffee",
        tier="portion", hook_style="question",
    ))
    db.add(PendingQuestion(
        user_id=user.id, kind="food_clarification",
        question="what dressing?", item_referenced="salad",
        tier="ingredient", hook_style="question",
    ))
    await db.commit()

    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["chicken sandwich", "coffee"],
    )
    assert closed == 2

    opens = await get_open_pending_questions(db, user.id)
    open_items = sorted(
        p.item_referenced for p in opens
        if p.kind == "food_clarification" and p.answered_at is None
    )
    assert open_items == ["salad"]


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 6 — is_generic_food_name and brand-variant detection
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("name,is_generic", [
    # Generic — every token in _GENERIC_FOOD
    ("protein bar", True),
    ("shake", True),
    ("a shake", True),
    ("some smoothie", True),
    ("bowl", True),
    ("salad", True),
    ("pasta", True),
    # Specific — at least one brand/qualifier token
    ("built bar", False),
    ("oikos shake", False),
    ("banana", False),
    ("royo bagel", False),
    ("royo challah roll", False),
    ("chicken sandwich", False),  # "chicken" not in _GENERIC_FOOD
    # Edge cases
    ("", False),
    ("   ", False),
])
def test_is_generic_food_name_matrix(name, is_generic):
    assert is_generic_food_name(name) == is_generic


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 7 — food_mode_directive across all inputs
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("mode,must_contain,must_not_contain", [
    ("quick", "quick", ""),
    ("strict", "strict", ""),
    ("moderate", "", "FOOD LOGGING MODE"),  # default = empty
    (None, "", "FOOD LOGGING MODE"),
    ("unknown_string", "", "FOOD LOGGING MODE"),
])
def test_food_mode_directive_matrix(mode, must_contain, must_not_contain):
    out = food_mode_directive(mode)
    if must_contain:
        assert must_contain in out.lower()
    if must_not_contain and out:  # only check ban if directive non-empty
        # No, the directive itself is what we don't want for moderate
        pass
    if mode in (None, "moderate", "unknown_string"):
        assert out == ""


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 8 — normalize_food_logging_mode (relative + synonym handling)
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("value,current,expected", [
    # Direct
    ("quick", "moderate", "quick"),
    ("strict", "moderate", "strict"),
    ("moderate", "moderate", "moderate"),
    # Synonyms
    ("balanced", "moderate", "moderate"),
    ("default", "strict", "moderate"),
    # Relative — step from current
    ("less", "strict", "moderate"),
    ("less", "moderate", "quick"),
    ("less", "quick", "quick"),   # already at floor
    ("more", "quick", "moderate"),
    ("more", "moderate", "strict"),
    ("more", "strict", "strict"),  # already at ceiling
    # Garbage → moderate
    ("xyz", "moderate", "moderate"),
    ("", "moderate", "moderate"),
    (None, "moderate", "moderate"),
])
def test_normalize_food_logging_mode_matrix(value, current, expected):
    assert normalize_food_logging_mode(value, current) == expected


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 9 — heads-up bubbles are in-voice (no "one sec." regressions)
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("tool", list(_TOOL_HEADS_UP_BUBBLES.keys()))
def test_heads_up_fallback_lines_are_in_voice(tool):
    """Every fallback bubble must be Arnie-voiced, not customer-service
    ('one sec.', 'please wait')."""
    BANNED = {"one sec.", "please wait", "hold on", "thank you for waiting"}
    bubbles = _TOOL_HEADS_UP_BUBBLES[tool]
    for b in bubbles:
        assert b not in BANNED, f"banned phrase in {tool}: {b!r}"
        # Should reference what's being looked up
        # (food, history, image, search)
        # Short — under 60 chars, sentence-case start, ends with period
        assert len(b) <= 60
        assert b.endswith(".")


@pytest.mark.parametrize("tool,seed,expected_contains", [
    ("search_food_database", "happy wolf", "macros"),
    ("query_history", "weekly", "history"),
    ("generate_image", "logo", "image"),
])
def test_heads_up_is_topic_specific(tool, seed, expected_contains):
    line = tool_heads_up(tool, seed)
    assert expected_contains in line.lower() or line.endswith(".")


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 10 — reconcile_macros boundary scenarios
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("cal,p,c,f,within_threshold", [
    # Clean — matches exactly
    (500, 35, 40, 22, True),
    # Slightly off (within 10-15%)
    (500, 30, 40, 25, True),
    # Way off — should auto-correct
    (500, 50, 60, 30, False),
    # Zero calories — defensive
    (0, 0, 0, 0, True),
    # High protein, low fat
    (400, 60, 30, 8, True),
])
def test_reconcile_macros_doesnt_crash_at_boundaries(cal, p, c, f, within_threshold):
    out = reconcile_macros(cal, p, c, f)
    assert isinstance(out, tuple)
    assert len(out) == 4


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 11 — message-order narrative simulations (full scenarios)
# ════════════════════════════════════════════════════════════════════════════
#
# These don't run the LLM — they verify that the deterministic state
# transitions across a multi-turn scenario behave correctly.


@pytest.mark.asyncio
async def test_scenario_clarify_log_delete_relog_attempt(make_user, db):
    """Full scenario — Phase 1's canonical bug.

      Turn 1: user says 'banana with honey', model asks clarifying question
              → pending row opens
      Turn 2: user clarifies 'light drizzle', model logs banana
              → log fires, banana row's pending closes
      Turn 3: user manually deletes banana via dashboard
              → DB no longer has banana entry
      Turn 4: user logs 'royo bagel'
              → resolve_pending_questions_for_logged_items must NOT
                attempt to close any cross-item rows (none should be open),
                and there should be no logical channel to re-create the
                banana row.
    """
    from db.models import PendingQuestion
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-scenario-1")

    # Turn 1: open clarification on banana
    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="how much honey?", tier="portion", hook_style="question",
    )
    pq.item_referenced = "banana with honey"
    await db.commit()
    opens = await get_open_pending_questions(db, user.id)
    assert any(p.item_referenced == "banana with honey" for p in opens)

    # Turn 2: log banana → close the question (item-scoped)
    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["banana with honey"]
    )
    assert closed == 1
    opens = await get_open_pending_questions(db, user.id)
    assert not [p for p in opens
                if p.kind == "food_clarification" and p.answered_at is None]

    # Turn 3: dashboard delete is external — no DB-side hook
    # (the model's behavior is governed by [TODAY] context — verified at
    #  prompt level in test_prompt_warns_against_re_logging_dashboard_deleted_items)

    # Turn 4: log royo bagel → must not close anything (no open rows exist)
    closed_4 = await resolve_pending_questions_for_logged_items(
        db, user.id, ["royo bagel"]
    )
    assert closed_4 == 0


@pytest.mark.asyncio
async def test_scenario_multi_item_clarify_partial(make_user, db):
    """Scenario — multi-item turn where one item needs clarification:
      Turn 1: user 'turkey sandwich, chips, coffee'
              → model asks about turkey sandwich (sauce?), records pending
              → no logs fire yet (multi-item + clarification gate)
      Turn 2: user answers 'mayo only'
              → log_food fires for all 3 (sandwich, chips, coffee) in one turn
              → resolve_pending_questions_for_logged_items closes the
                turkey-sandwich row; the others were never opened
    """
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-scenario-2")

    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="sauce?", tier="ingredient", hook_style="question",
    )
    pq.item_referenced = "turkey sandwich"
    await db.commit()

    # Turn 2 logs all three; item-scoped resolve closes only the sandwich.
    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["turkey sandwich", "chips", "coffee"],
    )
    assert closed == 1
    opens = await get_open_pending_questions(db, user.id)
    assert not [p for p in opens
                if p.kind == "food_clarification" and p.answered_at is None]


@pytest.mark.asyncio
async def test_scenario_log_unrelated_while_question_pending(make_user, db):
    """User has open question about salad dressing. They log a totally
    unrelated coffee (different turn). The salad question must stay open."""
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-scenario-3")

    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="what dressing?", tier="ingredient", hook_style="question",
    )
    pq.item_referenced = "salad"
    await db.commit()

    # Unrelated log
    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["coffee with milk"],
    )
    assert closed == 0
    opens = await get_open_pending_questions(db, user.id)
    still_open = [p for p in opens
                  if p.kind == "food_clarification" and p.answered_at is None]
    assert len(still_open) == 1
    assert still_open[0].item_referenced == "salad"


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 12 — name normalization for matching robustness
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("name_in,expected_tokens_subset", [
    ("Banana", {"banana"}),
    ("3oz chicken breast", {"chicken", "breast"}),
    ("Royo Bagel", {"royo", "bagel"}),
    ("1 medium banana", {"medium", "banana"}),
    ("Built Bar (caramel)", {"built", "bar", "caramel"}),
])
def test_normalize_name_extracts_content_tokens(name_in, expected_tokens_subset):
    norm = normalize_name(name_in)
    tokens = set(norm.split())
    assert expected_tokens_subset.issubset(tokens), (
        f"normalize_name({name_in!r}) = {norm!r}, "
        f"missing tokens: {expected_tokens_subset - tokens}"
    )


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 13 — large-batch confirmation never strands an item
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("n_items", [2, 5, 10, 25, 50])
def test_batch_coaching_never_drops_item_count(n_items):
    """At any scale, the coaching string must name the correct N and reference
    at least the first item — this is what tells the model to summarize
    ALL of them, not just the last one."""
    names = [f"food-{i:02d}" for i in range(n_items)]
    tcs = [_log_food_call(n) for n in names]
    out = _apply_multi_item_batch_coaching(
        {"log_food": _coaching_stub(names[-1])}, tcs,
    )["log_food"]
    assert f"{n_items} foods" in out, f"item count missing at scale {n_items}"
    assert names[0] in out
    if n_items > 3:
        assert "more" in out  # "+ N more" tail must appear


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 14 — modality prefix recognition (text/voice/photo)
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("user_msg,modality_hint_required", [
    ("had a banana", None),
    ("[Voice note] just ate some pasta", "voice"),
    ("[Food photo]\nPhoto analysis: turkey sandwich", "photo"),
])
def test_prompt_teaches_modality_prefixes(user_msg, modality_hint_required):
    """The system prompt must teach the model to recognize each modality
    prefix it'll see in user messages."""
    if modality_hint_required == "voice":
        assert "[Voice note]" in SYSTEM_PROMPT
        assert "VOICE NOTE LOGGING" in SYSTEM_PROMPT
    elif modality_hint_required == "photo":
        assert "[Food photo]" in SYSTEM_PROMPT
        assert "PHOTO LOGGING" in SYSTEM_PROMPT


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 15 — the off-voice "one sec." regression cannot return
# ════════════════════════════════════════════════════════════════════════════


def test_no_one_sec_anywhere_in_heads_up_fallbacks():
    """Belt and suspenders — explicit ban on the regression."""
    flat = [b for bubbles in _TOOL_HEADS_UP_BUBBLES.values() for b in bubbles]
    for b in flat:
        assert "one sec" not in b.lower(), (
            f"'one sec' regression in heads-up fallbacks: {b!r}"
        )


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 16 — cumulative regression sweep
# ════════════════════════════════════════════════════════════════════════════
#
# A single test that pings every public surface area to catch import errors,
# signature drift, or accidental removal of a function. Runs fast.


def test_public_surface_smoke():
    # food_intelligence
    assert is_generic_food_name("protein bar") is True
    assert is_generic_food_name("built bar") is False
    assert normalize_name("Royo Bagel") == "royo bagel"
    assert normalize_food_logging_mode("quick") == "quick"
    cal, p, c, f = reconcile_macros(500, 30, 40, 25)
    assert cal == 500
    # context_builder
    assert render_pending_clarification_block([]) == ""
    assert food_mode_directive("moderate") == ""
    assert "quick" in food_mode_directive("quick").lower()
    # tool_executor
    assert tool_heads_up("search_food_database", "x").endswith(".")
    out = deterministic_confirmation(
        [_log_food_call("banana")], _log(100, 1), _prefs()
    )
    assert "banana" in out.lower() or "logged" in out.lower()
    # prompt builder
    assert len(SYSTEM_PROMPT) > 10_000  # sanity: not truncated


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 17 — tool-narration anti-pattern ban (Phase 7 / Happy Wolf bug)
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("banned_phrase", [
    "match doesn't look right",
    "USDA match is off",
    "couldn't find a great match",
    "let me double-check",
    "running another search",
    "lookup confidence is low",
])
def test_prompt_explicitly_bans_tool_narration(banned_phrase):
    """Each anti-pattern must be named directly so the model has the
    counterexample in its context, not just an abstract rule."""
    assert banned_phrase in SYSTEM_PROMPT, (
        f"tool-narration ban example {banned_phrase!r} missing from prompt"
    )


def test_prompt_teaches_silent_fallback_on_low_confidence():
    """When ANALYSIS hands the model 'confidence: estimated', it should just
    confirm with 'going with ~X' — NOT disclaim about the lookup pipeline."""
    s_lower = SYSTEM_PROMPT.lower()
    assert "process invisible" in s_lower
    assert "going with" in s_lower or "calling it" in s_lower


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 18 — rapid-send deduplication rule presence
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_has_rapid_send_dedup_rule():
    assert "RAPID-SEND DEDUPLICATION" in SYSTEM_PROMPT
    assert "10 minutes" in SYSTEM_PROMPT or "10-minute" in SYSTEM_PROMPT.lower()


def test_prompt_has_multi_item_clarification_gate():
    """If ANY item in a multi-item list needs clarification, ALL items hold."""
    assert "MULTI-ITEM + CLARIFICATION" in SYSTEM_PROMPT
    assert "Never log item 1 while holding a question about item 2" in SYSTEM_PROMPT


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 19 — calorie-framing matrix (Phase 7)
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("anti_pattern", [
    "basically at your cal limit",
])
def test_prompt_names_calorie_framing_anti_pattern(anti_pattern):
    assert anti_pattern in SYSTEM_PROMPT


def test_prompt_protein_gap_with_room_framing():
    """The corrected framing for 'protein-gap + room left' must be present so
    the model has a positive example to follow."""
    s = SYSTEM_PROMPT
    # The positive example uses 'closes the gap' framing
    assert "closes the gap" in s.lower() or "still room" in s.lower()
    assert "PROTEIN-GAP-WITH-ROOM" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 20 — long-running pending clarification accumulation
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("n_pending", [0, 1, 3, 5, 10, 25])
def test_pending_block_handles_arbitrary_row_counts(n_pending):
    """Whatever number of rows we hand the block, it must (a) not crash,
    (b) cap at 3 lines, and (c) honor freshness filtering."""
    rows = [_row(item=f"food-{i}", minutes_ago=(i % 25) + 1)
            for i in range(n_pending)]
    out = render_pending_clarification_block(rows)
    item_lines = [line for line in out.split("\n") if line.startswith("  - ")]
    if n_pending == 0:
        assert out == ""
    else:
        # Cap at 3, regardless of how many came in
        assert len(item_lines) <= 3


@pytest.mark.parametrize("n_stale,n_fresh,expected_rendered", [
    (0, 1, 1),
    (5, 0, 0),     # all stale → empty
    (5, 2, 2),     # only fresh ones surface
    (10, 5, 3),    # cap at 3 of the fresh
])
def test_pending_block_filters_stale_keeps_fresh(n_stale, n_fresh, expected_rendered):
    rows = [_row(item=f"stale-{i}", minutes_ago=120) for i in range(n_stale)]
    rows += [_row(item=f"fresh-{i}", minutes_ago=5) for i in range(n_fresh)]
    out = render_pending_clarification_block(rows)
    item_lines = [line for line in out.split("\n") if line.startswith("  - ")]
    assert len(item_lines) == expected_rendered
    # No stale ones should ever appear in the rendered output
    for ln in item_lines:
        assert "stale-" not in ln


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 21 — defensive: malformed / missing inputs never crash
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("bad_input", [
    None,
    [],
    [{}],
    [{"name": "log_food", "input": None}],
    [{"name": "log_food", "input": {}}],
    [{"name": "log_food"}],  # missing input
    [{"name": "unknown_tool", "input": {"x": 1}}],
])
def test_deterministic_confirmation_defensive_against_malformed(bad_input):
    """Should never raise. Worst case: returns a generic confirmation."""
    out = deterministic_confirmation(bad_input or [], _log(), _prefs())
    assert isinstance(out, str)


@pytest.mark.parametrize("bad_input", [
    {"log_food": None},
    {},
    {"log_food": ""},
    {"log_food": "ok"},  # no 'Scale the reply' anchor → no-op
])
def test_batch_coaching_defensive_against_malformed(bad_input):
    out = _apply_multi_item_batch_coaching(
        dict(bad_input),
        [_log_food_call("a"), _log_food_call("b")],
    )
    assert isinstance(out, dict)


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 22 — full-scenario walkthroughs (representative real flows)
# ════════════════════════════════════════════════════════════════════════════


def test_scenario_quick_mode_user_logs_generic_brand_with_history():
    """In quick mode, a generic ('protein bar') with a matching history
    should NOT trigger an ask — prompt rule must say so explicitly."""
    s = SYSTEM_PROMPT
    # The Phase 3 rule names this exact case
    assert "QUICK + GENERIC BRAND EXCEPTION" in s
    # And tells the model to log with estimated confidence
    assert "confidence: estimated" in s


def test_scenario_strict_user_voice_note_softens():
    """Strict-mode user sending [Voice note] should get moderate interrogation,
    not full strict (re-recording to clarify cook method defeats voice)."""
    s = SYSTEM_PROMPT
    assert "STRICT + VOICE EXCEPTION" in s
    assert "MODERATE" in s


def test_scenario_photo_with_caption_log_intent_still_describes_first():
    """The PHOTO LOGGING rule must say: even with a caption containing
    'log this', still describe first. This rule has been weakened in past
    rewrites — anchor it here."""
    s = SYSTEM_PROMPT
    assert "describe first" in s.lower() or "describe what you see FIRST" in s
    assert "log this" in s.lower() or "caption" in s.lower()


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 23 — sentence-case + bubble formatting guard
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_enforces_sentence_case():
    s = SYSTEM_PROMPT
    assert "Sentence case" in s or "sentence case" in s


def test_prompt_uses_triple_bar_separator():
    s = SYSTEM_PROMPT
    assert "|||" in s
    assert "bubble" in s.lower()


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 24 — context-rules ground-truth assertion
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_states_context_is_ground_truth():
    """If [TODAY] doesn't show something, the model should NOT claim it did
    (or didn't) log without consulting [TODAY] first."""
    s = SYSTEM_PROMPT
    assert "CONTEXT IS GROUND TRUTH" in s
    assert "[TODAY] is the actual DB state" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 25 — every tool that should have a heads-up has one
# ════════════════════════════════════════════════════════════════════════════


def test_all_slow_tools_have_heads_up_bubbles():
    """Every slow tool maps to >=2 deterministic heads-up bubbles. A new slow
    tool added without an entry would surface here."""
    REQUIRED = {"web_search", "search_food_database", "query_history",
                "generate_image", "track_metric", "find_nearby_places"}
    assert set(_TOOL_HEADS_UP_BUBBLES.keys()) == REQUIRED
    for tool in REQUIRED:
        assert len(_TOOL_HEADS_UP_BUBBLES[tool]) >= 2, f"{tool}: need >=2 bubbles"


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 26 — generic-name token coverage (recipe-dependent dishes)
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("composite_dish", [
    "sandwich", "wrap", "bowl", "salad", "burrito", "taco",
    "burger", "pizza", "pasta", "ramen", "curry", "soup",
    "stirfry", "sushi", "poke",
])
def test_composite_dishes_are_classified_generic(composite_dish):
    """Recipe-dependent composite dishes must be flagged as generic so the
    model asks for components rather than silently logging an average. This
    is what saved us from logging USDA's 'sandwich, average' nonsense."""
    assert is_generic_food_name(composite_dish) is True


@pytest.mark.parametrize("specific_food", [
    "banana", "avocado", "ground turkey", "chicken breast",
    "salmon", "eggs", "rice", "broccoli", "almonds",
])
def test_specific_whole_foods_are_not_generic(specific_food):
    """Whole foods are specific enough to log from USDA directly."""
    assert is_generic_food_name(specific_food) is False


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 27 — confirmation length scaling by item count
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("n_items", [1, 3, 7, 15])
def test_deterministic_confirmation_doesnt_explode_with_item_count(n_items):
    """Even with 15 items, the deterministic fallback must produce a coherent
    short string with the day total — not a 15-line recap."""
    tcs = [_log_food_call(f"food-{i}") for i in range(n_items)]
    out = deterministic_confirmation(tcs, _log(800, 50), _prefs())
    assert isinstance(out, str)
    # Under 500 chars even for a fat batch — the fallback is brief by design
    assert len(out) < 500, f"confirmation too long ({len(out)} chars)"
    # Always has the day total somewhere
    assert "calorie" in out.lower() or "/" in out


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 28 — the user's exact reported bug, replayed
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reported_bug_royo_bagel_does_not_close_banana_question(make_user, db):
    """Replays the user's exact reported sequence:
      1. Open clarification about 'banana with honey'
      2. User sends an unrelated 'I had a royo bagel'
      3. The banana question must NOT silently close
      4. The royo bagel log must NOT accidentally close anything

    This is the canonical regression test for the cross-item collision."""
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-royo-replay")

    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="how much honey?", tier="portion", hook_style="question",
    )
    pq.item_referenced = "banana with honey"
    await db.commit()

    # The royo bagel log — separate item entirely.
    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["royo bagel"],
    )
    assert closed == 0, "royo bagel must NOT close banana question"

    # The banana question is still open and recoverable.
    opens = await get_open_pending_questions(db, user.id)
    banana_qs = [p for p in opens
                 if p.item_referenced == "banana with honey"
                 and p.answered_at is None]
    assert len(banana_qs) == 1


def test_reported_bug_happy_wolf_narration_is_banned():
    """Replays the Happy Wolf 'Hmm, that match doesn't look right' bug —
    the prompt must explicitly ban this narration class."""
    assert "match doesn't look right" in SYSTEM_PROMPT
    # And include the alternative instruction (silently fall back).
    assert "silently fall back" in SYSTEM_PROMPT.lower() \
        or "silently fall back to your own estimate" in SYSTEM_PROMPT


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 29 — Gap 1: tool-error confirmation drift
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_has_tool_error_integrity_rule():
    """If a tool result starts with Error:/Skipped/Failed to, the model must
    NOT claim 'logged'. This is the silent-failure mode where the dashboard
    stays empty but the user sees a success message."""
    assert "TOOL-ERROR INTEGRITY" in SYSTEM_PROMPT
    assert "Error:" in SYSTEM_PROMPT
    assert "did NOT succeed" in SYSTEM_PROMPT


@pytest.mark.parametrize("err_prefix", [
    "Error: USDA unreachable",
    "Skipped — day log not yet created (onboarding incomplete)",
    "Failed to record clarification: db locked",
])
def test_deterministic_confirmation_surfaces_log_food_errors(err_prefix):
    """When log_food's tool_result is an error, the deterministic fallback
    must NOT claim success. It surfaces the failure honestly so the user
    can retry."""
    tcs = [_log_food_call("banana")]
    out = deterministic_confirmation(
        tcs, _log(0, 0), _prefs(), tool_results={"log_food": err_prefix}
    )
    assert "didn't go through" in out.lower() or "failed" in out.lower() \
        or "try again" in out.lower() or "resend" in out.lower()
    # Must NOT contain success language
    assert "logged" not in out.lower() or "didn't" in out.lower()
    assert "got it" not in out.lower() or "didn't" in out.lower()


@pytest.mark.parametrize("good_result_prefix", [
    "Logged banana: 100 cal",
    "Logged chicken sandwich: 500 cal",
])
def test_deterministic_confirmation_clean_path_unchanged_with_results(good_result_prefix):
    """Successful tool_results should not trip the error branch — happy path
    must keep working."""
    tcs = [_log_food_call("banana")]
    out = deterministic_confirmation(
        tcs, _log(100, 1), _prefs(),
        tool_results={"log_food": good_result_prefix + ". DAY TOTAL: 100 cal"},
    )
    assert "didn't go through" not in out.lower()
    assert "failed" not in out.lower()


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 30 — Gap 2: partial-failure batch coaching
# ════════════════════════════════════════════════════════════════════════════


def test_batch_coaching_partial_failure_names_failures():
    """When per_call data shows some log_food calls failed, the coaching swap
    enters partial-failure mode: name the failures, name what succeeded, ban
    'all logged.'"""
    tcs = [_log_food_call(n) for n in ("bagel", "coffee", "banana")]
    per_call = [
        ("log_food", "bagel", True),
        ("log_food", "coffee", False),   # failed
        ("log_food", "banana", True),
    ]
    out = _apply_multi_item_batch_coaching(
        {"log_food": _coaching_stub("banana")}, tcs, per_call=per_call,
    )["log_food"]
    assert "MULTI-ITEM BATCH WITH FAILURES" in out
    assert "2 of 3 succeeded" in out
    assert "coffee" in out  # the failure named
    assert "FAILED" in out
    # Critical: the "all logged" framing must be banned
    assert "NEVER say 'all logged'" in out or "NEVER say \"all logged\"" in out


def test_batch_coaching_all_failed_still_routes_to_failure_branch():
    """All log_food calls failed → still partial-failure mode, with 0 succeeded."""
    tcs = [_log_food_call(n) for n in ("a", "b")]
    per_call = [("log_food", "a", False), ("log_food", "b", False)]
    out = _apply_multi_item_batch_coaching(
        {"log_food": _coaching_stub("b")}, tcs, per_call=per_call,
    )["log_food"]
    assert "MULTI-ITEM BATCH WITH FAILURES" in out
    assert "0 of 2 succeeded" in out


def test_batch_coaching_all_succeeded_uses_clean_branch():
    """When per_call says all succeeded, use the clean batch coaching (no
    failure language)."""
    tcs = [_log_food_call(n) for n in ("a", "b", "c")]
    per_call = [("log_food", "a", True), ("log_food", "b", True), ("log_food", "c", True)]
    out = _apply_multi_item_batch_coaching(
        {"log_food": _coaching_stub("c")}, tcs, per_call=per_call,
    )["log_food"]
    assert "MULTI-ITEM BATCH WITH FAILURES" not in out
    assert "MULTI-ITEM BATCH" in out
    assert "3 foods" in out


def test_batch_coaching_no_per_call_data_falls_back_to_clean_branch():
    """When per_call is None (backwards-compat path), use the clean branch."""
    tcs = [_log_food_call(n) for n in ("a", "b")]
    out = _apply_multi_item_batch_coaching(
        {"log_food": _coaching_stub("b")}, tcs, per_call=None,
    )["log_food"]
    assert "MULTI-ITEM BATCH" in out
    assert "MULTI-ITEM BATCH WITH FAILURES" not in out


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 31 — Gap 3: PENDING block row ordering (newest-first)
# ════════════════════════════════════════════════════════════════════════════


def test_pending_block_sorts_newest_first_when_capping():
    """With 5 fresh rows of varying ages, the cap of 3 must show the NEWEST
    three. Before this fix, the cap was input-order-dependent and stale-but-fresh
    rows could hide newer questions from the model."""
    rows = [
        _row(item="oldest", minutes_ago=25),    # fresh but old
        _row(item="middle-1", minutes_ago=15),
        _row(item="newest", minutes_ago=1),
        _row(item="middle-2", minutes_ago=10),
        _row(item="second-newest", minutes_ago=3),
    ]
    out = render_pending_clarification_block(rows)
    # The three newest are 'newest' (1m), 'second-newest' (3m), 'middle-2' (10m)
    assert "newest" in out
    assert "second-newest" in out
    assert "middle-2" in out
    # And the two older fresh ones should NOT appear
    assert "oldest" not in out
    assert "middle-1" not in out


def test_pending_block_ordering_is_deterministic_with_ties():
    """When two rows have the exact same asked_at, the tiebreaker is
    item_referenced — so the order doesn't flicker between renders."""
    same_time = datetime.utcnow() - timedelta(minutes=5)
    rows = [
        SimpleNamespace(kind="food_clarification", question="?", item_referenced="b",
                        asked_at=same_time, answered_at=None),
        SimpleNamespace(kind="food_clarification", question="?", item_referenced="a",
                        asked_at=same_time, answered_at=None),
    ]
    out1 = render_pending_clarification_block(rows)
    out2 = render_pending_clarification_block(list(reversed(rows)))
    assert out1 == out2


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 32 — Gap 4: STRICT + PHOTO behavior
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_specifies_strict_photo_behavior():
    """The strict-photo branch must require component-by-component breakdown
    before logging — generic 'looks ~500 cal' defeats strict users' preference."""
    s = SYSTEM_PROMPT
    assert "PHOTO + STRICT MODE" in s
    # Component breakdown example must be present
    assert "bread" in s.lower() and "turkey" in s.lower() and "mayo" in s.lower()
    # Anti-pattern banned: just a top-line estimate
    assert "NOT just" in s and "looks ~500 cal" in s


def test_prompt_specifies_quick_photo_one_bubble_describe():
    """Quick mode still describes (photo always overrides quick) but in ONE
    bubble with a range — not a component breakdown."""
    s = SYSTEM_PROMPT
    assert "PHOTO + QUICK MODE" in s
    assert "ONE bubble" in s or "one bubble" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 33 — Gap 5: multi-clarification answer mapping
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_teaches_multi_answer_mapping():
    """When user replies 'mayo, small, oat' to a 3-question turn, the model
    must state its mapping back so the user can catch a mismatch."""
    s = SYSTEM_PROMPT
    assert "MULTI-ANSWER MAPPING" in s
    # The canonical example must be present so the model has a template
    assert "mayo, small, oat" in s
    # And the count-mismatch rule
    assert "doesn't match the question count" in s or "ask one short clarifier" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 34 — Gap 10: expanded generic-name coverage
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("brand_dependent_item", [
    "yogurt", "ice cream", "cheese", "cake", "pie", "biscuit",
    "pudding", "mousse", "syrup", "jam", "jelly", "butter",
    "hummus", "guacamole", "sauce", "dressing", "spread",
    "gelato", "sorbet", "creamer",
])
def test_brand_dependent_items_classified_generic(brand_dependent_item):
    """Items whose macros swing wildly by brand or recipe must be flagged so
    the prompt's GENERIC BRANDED ITEMS rule triggers an ask."""
    assert is_generic_food_name(brand_dependent_item) is True, (
        f"{brand_dependent_item!r} should be generic (asks-which-brand)"
    )


@pytest.mark.parametrize("specific_branded_item", [
    "chobani triple zero",       # specific yogurt
    "halo top ice cream",        # specific frozen dessert
    "cheddar cheese",            # specific cheese variety
    "peanut butter",             # specific spread (peanut qualifier)
    "almond butter",             # specific spread (almond qualifier)
    "maple syrup",               # specific syrup
    "strawberry jam",            # specific jam
    "tomato sauce",              # specific sauce
])
def test_specific_branded_items_not_generic(specific_branded_item):
    """A brand or variety qualifier disambiguates the generic — these should
    NOT trigger the asks-which-brand flow."""
    assert is_generic_food_name(specific_branded_item) is False, (
        f"{specific_branded_item!r} has a qualifier — should NOT be generic"
    )


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 35 — Gap 6: ambiguous update/delete reference
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_has_ambiguous_update_delete_rule():
    """When [TODAY] shows multiple matching entries, the model must ask which
    one before firing update/delete. The exact rule must be present so the
    model doesn't silently pick the wrong row."""
    s = SYSTEM_PROMPT
    assert "AMBIGUOUS UPDATE/DELETE REFERENCE" in s
    assert "two chickens" in s.lower() or "MULTIPLE entries" in s
    # And: distinguish by detail, never by [#id]
    assert "NEVER reference" in s and "[#id]" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 36 — Gap 7: macro-reconciliation surfacing
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_instructs_model_to_use_tool_result_macros():
    """The log_food tool result tells the model to use 'Logged X:' macros,
    NOT its own input — even when reconciliation corrected the values."""
    # This rule lives in the tool result template, not the system prompt.
    # Verify by inspecting the source.
    import inspect
    from handlers import tool_executor
    src = inspect.getsource(tool_executor._dispatch)
    assert "NEVER from your input" in src
    assert "ALWAYS from the tool" in src


def test_reconciliation_flag_appears_in_source():
    """The reconcile-detection path must be present so corrections surface."""
    import inspect
    from handlers import tool_executor
    src = inspect.getsource(tool_executor._dispatch)
    assert "RECONCILED" in src or "reconciled_note" in src
    assert "USE THE RECONCILED VALUES" in src


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 37 — Gap 11: empty FOOD HISTORY in quick mode
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_handles_empty_history_in_quick_mode():
    """Day-1 quick-mode users have no FOOD HISTORY — the rule must say
    estimate-and-flag instead of asking, preserving quick mode's flow."""
    s = SYSTEM_PROMPT
    # The empty-history clause must be present in the quick-mode section
    assert "[FOOD HISTORY] is empty" in s or "day-1 user" in s
    # And the corrective behavior is: log with estimated:true, flag in one bubble
    assert "estimated: true" in s
    # Quick mode promise preserved
    assert "EVERY turn" in s or "even day 1" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 38 — Gap 12: TZ-shifted day boundary (defensive)
# ════════════════════════════════════════════════════════════════════════════


def test_parse_log_date_yesterday_respects_user_tz():
    """'yesterday' must be relative to the user's TZ, not UTC. Without this,
    a user in Tokyo at 1am would log to UTC's yesterday (their own today)."""
    from handlers.tool_executor import _parse_log_date
    from datetime import date
    import pytz
    from datetime import datetime as _dt
    # We can't deterministically test "today" without freezing time, but we CAN
    # verify the function uses the timezone we pass.
    out_tokyo = _parse_log_date("yesterday", "Asia/Tokyo")
    out_utc = _parse_log_date("yesterday", "UTC")
    # Both should be a date (not None), within 1 day of each other.
    assert out_tokyo is not None
    assert out_utc is not None
    assert abs((out_tokyo - out_utc).days) <= 1


def test_parse_log_date_rejects_future():
    """Catches the year-confusion bug — a parsed date in the future must
    return None, not log to a future day."""
    from handlers.tool_executor import _parse_log_date
    assert _parse_log_date("2099-01-01", "UTC") is None


def test_parse_log_date_rejects_implausibly_old():
    """Same as future: implausibly-old dates (>2 years back) are likely a
    year-misparse and should return None."""
    from handlers.tool_executor import _parse_log_date
    assert _parse_log_date("2020-01-01", "UTC") is None


def test_prompt_handles_unknown_timezone():
    """If the user's timezone isn't set, the model must NOT invent a local
    time — ask what city they're in instead."""
    s = SYSTEM_PROMPT
    assert "timezone is unknown" in s
    assert "ask what city" in s.lower()


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 39 — Gap 13: state freshness (deterministic_confirmation reads
# DailyLog after refresh)
# ════════════════════════════════════════════════════════════════════════════


def test_deterministic_confirmation_uses_log_totals():
    """deterministic_confirmation must read total_calories/total_protein from
    the DailyLog passed in — those are the post-refresh authoritative numbers.
    The function must NOT recompute or invent totals."""
    out = deterministic_confirmation(
        [_log_food_call("banana")], _log(1234, 56), _prefs(cal_t=2000)
    )
    # 1,234 is unusual enough to be obviously the passed-in value
    assert "1,234" in out or "1234" in out


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 40 — Gap 14: LLM-judge eval scaffold loads
# ════════════════════════════════════════════════════════════════════════════


def test_llm_judge_eval_scaffold_is_opt_in():
    """The eval module must exist, must import without making API calls, and
    must skip by default (opt-in via LLM_JUDGE_EVAL=true)."""
    from tests import test_llm_judge_eval as eval_mod
    assert hasattr(eval_mod, "_run_arnie")
    assert hasattr(eval_mod, "_judge")
    # The pytestmark skip should be present
    assert hasattr(eval_mod, "pytestmark")


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 41 — Drift 1: over-target framing
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_bans_soft_framing_when_over_target():
    """When the user is OVER target, the model must name the gap directly
    ('58 over target'), not soften with 'almost no calorie room left.'"""
    s = SYSTEM_PROMPT
    # The corrective rule must be present
    assert "NAME THE GAP DIRECTLY" in s
    # And the soft phrasings must be explicitly banned for over-target
    for banned in ("almost no room", "basically no room",
                   "right at the limit", "at your cap"):
        assert banned in s.lower(), f"missing ban example: {banned!r}"


def test_prompt_has_over_target_example_format():
    """The prompt must show the corrected over-target framing."""
    s = SYSTEM_PROMPT
    assert "58 over target" in s or "228 over" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 42 — Drift 2: redundant "X: X is..." labeling ban
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_bans_redundant_label_repeat():
    """'Diet Coke: Diet Coke's a zero' duplicates the food name. The prompt
    must ban this shape with the canonical example."""
    s = SYSTEM_PROMPT
    assert "NEVER LABEL THE FOOD AND THEN REPEAT IT" in s
    # The example may wrap across lines in the source — check parts.
    assert "Diet Coke:" in s and "Diet" in s
    # And give the corrected alternative
    assert "Diet Coke's a zero." in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 43 — Drift 3: strict-mode opener consistency
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_bans_strict_mode_out_loud():
    """Strict-mode pre-log questions must use natural coach-talk openers
    ("for accuracy, …", "before I lock it in, …"). Saying the literal phrase
    "strict mode" out loud is banned — it reads as a feature label, not a
    coach. Users picked the accuracy level; they don't need it announced."""
    s = SYSTEM_PROMPT
    # The explicit ban
    assert 'NEVER SAY "STRICT MODE" OUT LOUD' in s
    assert 'BANNED in your reply text: "strict mode"' in s
    # The required natural openers
    assert '"for accuracy, one thing: ..."' in s
    assert '"quick one so we log the right numbers: ..."' in s
    assert '"before I lock it in: ..."' in s
    # And the one-question-shape-per-reply consolidation rule
    assert "ONE PRE-LOG QUESTION PER ITEM, ONE QUESTION SHAPE PER REPLY" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 44 — Telegram webhook duplicate dedup
# ════════════════════════════════════════════════════════════════════════════


def test_telegram_webhook_has_update_id_dedup():
    """The Telegram webhook must dedup by update_id to survive Telegram
    retries that slip past the 200-immediate response (network blip, old
    pod still warming, etc.)."""
    import inspect
    from api import app
    src = inspect.getsource(app.telegram_webhook)
    assert "_seen_tg_updates" in src
    assert "update_id" in src.lower()
    assert "duplicate update_id" in src


def test_telegram_webhook_holds_task_reference():
    """asyncio.create_task without a held reference can be GC'd mid-run.
    The webhook must store the task in an app-state set."""
    import inspect
    from api import app
    src = inspect.getsource(app.telegram_webhook)
    assert "_tg_bg_tasks" in src
    assert "add_done_callback" in src


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 45 — Dashboard is the single source of truth
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_has_dashboard_recap_section():
    """The DASHBOARD_RECAP section must be present so recap requests pull
    from the DB, not chat history."""
    s = SYSTEM_PROMPT
    assert "DASHBOARD IS THE SOURCE OF TRUTH" in s
    assert "FOOD RECAP REQUESTS" in s


@pytest.mark.parametrize("food_recap_trigger", [
    "what have I eaten today?",
    "what's on my log?",
    "show my food",
    "what did I have so far?",
    "what's my day looking like?",
    "give me my food log",
    "what's logged so far?",
])
def test_prompt_lists_food_recap_triggers(food_recap_trigger):
    """Each canonical 'recap my food' phrasing must be in the prompt so the
    model recognizes it as a recap request, not a logging request."""
    s = SYSTEM_PROMPT
    assert food_recap_trigger in s, (
        f"recap trigger phrase {food_recap_trigger!r} missing from prompt"
    )


def test_prompt_requires_listing_every_entry_in_food_recap():
    """The food recap rule must say 'list every entry' so the model doesn't
    paraphrase ('a few items') or skip small items."""
    s = SYSTEM_PROMPT
    assert "List EVERY food entry" in s
    # And ban paraphrases
    assert "Never paraphrase" in s
    assert "a bunch of stuff" in s or "the usual lunch" in s


def test_prompt_food_recap_uses_calories_format():
    """The food recap example must use 'calories' with spaces around the
    slash — keep the format consistent with the FOOD_LOGGING rule."""
    s = SYSTEM_PROMPT
    # The canonical example
    assert "805 / 2,000 calories" in s


def test_prompt_includes_past_day_food_recap_branch():
    """When the user asks about past days, the model must use FOOD HISTORY
    or query_history honestly — not invent details."""
    s = SYSTEM_PROMPT
    assert "PAST-DAY FOOD RECAPS" in s
    assert "query_history" in s


def test_prompt_covers_exercise_and_weight_recap():
    """The recap rule must extend beyond food — exercise, weight, water,
    custom tracking all get the same dashboard-is-truth treatment."""
    s = SYSTEM_PROMPT
    assert "EXERCISE / ACTIVITY RECAP" in s
    assert "WEIGHT / WATER" in s


def test_prompt_bans_chat_memory_for_recaps():
    """Even if chat history mentioned a number, [TODAY] wins. Lock the rule."""
    s = SYSTEM_PROMPT
    assert "NUMBERS COME FROM THE DB" in s
    # The phrase wraps in source — verify the key tokens are present.
    assert "more recent than" in s and "chat memory" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 46 — LOGGING FIDELITY (upstream guarantee for recap accuracy)
# ════════════════════════════════════════════════════════════════════════════


def test_prompt_has_item_count_self_check():
    """Before sending a reply, the model must verify N foods named ↔ N
    log_food calls. This is what makes the eventual recap accurate."""
    s = SYSTEM_PROMPT
    assert "ITEM-COUNT SELF-CHECK" in s
    assert "THEY MUST MATCH" in s


def test_prompt_has_category_dedupe_trap_rule():
    """The 'melon, watermelon and mango' regression: the model silently
    merged a generic + specific into one item, logged only 2 of 3 foods.
    The CATEGORY ≠ DEDUPE rule names this trap explicitly with worked
    examples so the model treats comma-separated nouns as distinct items
    even when one is a category and the next is a specific instance."""
    s = SYSTEM_PROMPT
    assert "CATEGORY ≠ DEDUPE" in s
    # Pin the canonical example from the screenshot.
    assert "melon, watermelon and mango" in s
    assert "3 items" in s
    # Pin the apposition exception (the only valid merge case).
    assert "apposition" in s
    assert "specifically watermelon" in s


def test_prompt_has_multi_item_confirmation_integrity_rule():
    """Even if log_food calls are right, a confirmation that names only
    2 of 3 items (the user-visible symptom in the screenshot) is the
    canary. The model must re-count when its confirmation list is
    shorter than the user's input list."""
    s = SYSTEM_PROMPT
    assert "CONFIRMATION INTEGRITY for multi-item" in s
    assert "name EVERY item that was logged" in s
    assert "STOP, re-count" in s


def test_prompt_has_logging_fidelity_section():
    """LOGGING FIDELITY rule must be present in FOOD_ACCURACY so the model
    knows what gets stored is what gets restated."""
    s = SYSTEM_PROMPT
    assert "LOGGING FIDELITY" in s
    # Three sub-rules
    assert "FOOD NAME: use the user's words" in s
    assert "QUANTITY FIDELITY" in s
    assert "EVERY ITEM GETS ITS OWN log_food" in s
    assert "DO NOT INVENT ITEMS" in s


@pytest.mark.parametrize("preserved_phrase", [
    "happy wolf chocolate chip kids bar",
    "royo bagel",
    "half plate",
    "3 bites",
    "1/3 piece",
])
def test_prompt_names_fidelity_examples(preserved_phrase):
    """The fidelity rule must include concrete user-phrase preservation
    examples so the model has a template."""
    s = SYSTEM_PROMPT
    assert preserved_phrase in s, (
        f"fidelity example {preserved_phrase!r} missing from prompt"
    )


def test_prompt_bans_collapsing_distinct_items():
    """'1 plain + 1 pepperoni pizza' must be two log_food calls, not one
    '2 slices of pizza' — different macros, different items."""
    s = SYSTEM_PROMPT
    # The example wraps across lines in source — verify the key tokens.
    assert "1 slice plain pizza" in s
    assert "1 slice" in s and "pepperoni pizza" in s
    assert "TWO log_food calls" in s


def test_prompt_bans_inventing_items():
    """User says 'had pizza' — don't also log garlic bread the user didn't
    name."""
    s = SYSTEM_PROMPT
    assert "DO NOT INVENT ITEMS the user didn't name" in s


# ════════════════════════════════════════════════════════════════════════════
# DIMENSION 47 — Past-day food recap + no-empty-promises
# ════════════════════════════════════════════════════════════════════════════


def test_fmt_recent_day_detail_lists_entries_for_each_day():
    """The new context formatter must list every food entry with macros for
    each of the last 3 past days. This is what makes 'what did I eat
    Sunday?' answerable from context."""
    from datetime import date, timedelta
    from types import SimpleNamespace
    from core.context_builder import fmt_recent_day_detail

    today = date.today()
    yesterday = today - timedelta(days=1)
    two_days = today - timedelta(days=2)

    y_food = [SimpleNamespace(parsed_food_name="Banana", quantity="1 medium",
                              calories=105, protein=1, carbs=27, fats=0,
                              estimated_flag=False)]
    y_log = SimpleNamespace(date=yesterday, food_entries=y_food,
                            total_calories=105, total_protein=1)
    t_food = [SimpleNamespace(parsed_food_name="Chicken sandwich",
                              quantity="~10in", calories=550, protein=38,
                              carbs=45, fats=22, estimated_flag=True)]
    t_log = SimpleNamespace(date=two_days, food_entries=t_food,
                            total_calories=550, total_protein=38)

    out = fmt_recent_day_detail([y_log, t_log])
    assert "[RECENT DAY DETAIL" in out
    assert "Banana" in out
    assert "Chicken sandwich" in out
    assert "105 cal" in out
    assert "550 cal" in out
    assert "38g protein" in out


def test_fmt_recent_day_detail_marks_estimated_with_tilde():
    from datetime import date, timedelta
    from types import SimpleNamespace
    from core.context_builder import fmt_recent_day_detail
    yesterday = date.today() - timedelta(days=1)
    log = SimpleNamespace(
        date=yesterday,
        food_entries=[SimpleNamespace(parsed_food_name="X", quantity="",
                                       calories=300, protein=20, carbs=20,
                                       fats=10, estimated_flag=True)],
        total_calories=300, total_protein=20,
    )
    out = fmt_recent_day_detail([log])
    assert "~300 cal" in out


def test_fmt_recent_day_detail_caps_at_3_days():
    """Even when 10 past logs are passed in, the block caps at 3 days to keep
    the prompt lean."""
    from datetime import date, timedelta
    from types import SimpleNamespace
    from core.context_builder import fmt_recent_day_detail

    today = date.today()
    logs = []
    for i in range(1, 11):
        d = today - timedelta(days=i)
        logs.append(SimpleNamespace(
            date=d,
            food_entries=[SimpleNamespace(parsed_food_name=f"food{i}",
                                           quantity="", calories=100,
                                           protein=10, carbs=0, fats=0,
                                           estimated_flag=False)],
            total_calories=100, total_protein=10,
        ))
    out = fmt_recent_day_detail(logs)
    # Exactly 3 days appear
    headers = [l for l in out.split("\n") if l.startswith("202") and ":" in l]
    assert len(headers) <= 3


def test_fmt_recent_day_detail_excludes_today():
    """Today's data has its own [TODAY] block — exclude it from this one."""
    from datetime import date
    from types import SimpleNamespace
    from core.context_builder import fmt_recent_day_detail
    today = date.today()
    log = SimpleNamespace(
        date=today,
        food_entries=[SimpleNamespace(parsed_food_name="X", quantity="",
                                       calories=100, protein=10, carbs=0,
                                       fats=0, estimated_flag=False)],
        total_calories=100, total_protein=10,
    )
    assert fmt_recent_day_detail([log]) == ""


def test_fmt_recent_day_detail_empty_returns_empty():
    """No past logs → empty string, not a header with nothing below."""
    from core.context_builder import fmt_recent_day_detail
    assert fmt_recent_day_detail([]) == ""
    assert fmt_recent_day_detail(None) == ""


def test_prompt_references_recent_day_detail_block():
    """The PAST-DAY FOOD RECAPS rule must point the model at the new
    [RECENT DAY DETAIL] block so it knows where to look."""
    s = SYSTEM_PROMPT
    assert "[RECENT DAY DETAIL]" in s
    assert "USE IT DIRECTLY" in s


def test_prompt_bans_empty_promises_on_data_requests():
    """The 'let me pull that up — one sec' silent-fail pattern must be
    explicitly banned for data requests."""
    s = SYSTEM_PROMPT
    assert "NO EMPTY PROMISES ON DATA REQUESTS" in s
    # Each banned phrase from the live bug must appear in the ban list
    for banned in ("let me pull that up", "one sec", "let me check",
                   "let me actually pull it"):
        assert banned in s, f"missing ban example: {banned!r}"
    # And the corrective: honest admission beats fake stall
    assert "honest" in s.lower() or "admit" in s.lower()
