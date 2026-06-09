"""
Regression tests for the food-logging hardening pass.

These lock in the fixes from Phases 1-4 of the cohesive plan:
  • Phase 1 — turn-scoped logging + brand-variant guard + don't-restore-deleted
  • Phase 2 — item-scoped clarification resolve (no silent cross-item close)
  • Phase 3 — photo/voice/quick-mode accommodations
  • Phase 4 — multi-item batch confirmation coaching swap

Each test pins a single, narrowly-scoped behavior so a future prompt rewrite
that drops one of these guardrails fails loudly here instead of in production.
"""
import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta


# ── Phase 1: prompt rules ────────────────────────────────────────────────────


def test_prompt_has_turn_scoped_logging_rule():
    """The system prompt must instruct the model to log ONLY foods in this
    turn's user message — the bug we just shipped was re-logging a deleted
    banana because chat history showed it. Lock that rule in."""
    from core.prompts.arnie import build_arnie_system
    s = build_arnie_system("telegram")
    assert "LOGGING SCOPE" in s
    assert "THIS turn" in s or "this turn's user message" in s
    assert "never re-log" in s.lower() or "do not restore" in s.lower() \
        or "do NOT restore" in s


def test_prompt_warns_against_re_logging_dashboard_deleted_items():
    """When a food vanishes from [TODAY] between turns, the user deleted it from
    the dashboard. The model must not 'helpfully' restore it on the next log."""
    from core.prompts.arnie import build_arnie_system
    s = build_arnie_system("telegram")
    assert "removed it on purpose" in s or "removed it from the dashboard" in s
    assert "do NOT restore" in s or "do NOT re-log" in s.lower() \
        or "never re-log a food the user deleted" in s.lower()


def test_prompt_has_brand_variant_guard():
    """'Royo bagel' must NOT inherit macros from 'royo challah roll' just
    because the brand matches. The prompt must teach this explicitly."""
    from core.prompts.arnie import build_arnie_system
    s = build_arnie_system("telegram")
    assert "BRAND VARIANT GUARD" in s
    assert "brand match is NOT product match" in s.lower() \
        or "same brand ≠ same product" in s
    assert "royo" in s.lower()  # the canonical example is preserved


# ── Phase 1: PENDING CLARIFICATION branches on answer vs new-food ────────────


def _stub_row(kind="food_clarification", question="grilled or fried?",
              item="chicken sandwich", asked_minutes_ago=5, answered=False):
    return SimpleNamespace(
        kind=kind, question=question, item_referenced=item,
        asked_at=datetime.utcnow() - timedelta(minutes=asked_minutes_ago),
        answered_at=datetime.utcnow() if answered else None,
    )


def test_pending_block_branches_on_answer_vs_new_food():
    """The PENDING CLARIFICATION block must explain BOTH branches to the model:
      • answer → log all the original turn's foods
      • new food → log only the new food, leave the question open
    Without both branches the model defaults to 'log everything' and re-logs
    deleted siblings (the bug we just saw)."""
    from core.context_builder import render_pending_clarification_block
    block = render_pending_clarification_block([_stub_row(asked_minutes_ago=5)])
    assert "IF this turn answers" in block
    assert "IF this turn is a NEW food" in block
    assert "log ONLY the new food" in block
    # The legacy "log ALL the foods" instruction must still be present for the
    # answer branch — it's the multi-item batch fix from earlier work.
    assert "log ALL the foods" in block or "all the foods from that " in block.lower()


# ── Phase 2: item-scoped clarification resolve ───────────────────────────────


@pytest.mark.asyncio
async def test_resolve_closes_only_matching_item(make_user, db):
    """Two open clarification rows (one for chicken sandwich, one for salad).
    Log the chicken sandwich. Only that row should close. The salad question
    stays open — the cross-item resolve collision is the bug we're fixing."""
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-scoped-1")

    pq_a = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="grilled or fried?", tier="cook_method", hook_style="question",
    )
    pq_a.item_referenced = "chicken sandwich"
    # record_pending_question reuses existing rows for the same kind, so we
    # add a second row via the raw model to get two food_clarification rows.
    await db.commit()
    from db.models import PendingQuestion
    pq_b = PendingQuestion(
        user_id=user.id, kind="food_clarification",
        question="what dressing?", item_referenced="salad",
        tier="ingredient", hook_style="question",
    )
    db.add(pq_b)
    await db.commit()

    opens = await get_open_pending_questions(db, user.id)
    assert sum(1 for p in opens if p.kind == "food_clarification") == 2

    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["chicken sandwich"]
    )
    assert closed == 1

    opens = await get_open_pending_questions(db, user.id)
    open_items = sorted(p.item_referenced for p in opens
                        if p.kind == "food_clarification" and p.answered_at is None)
    assert open_items == ["salad"], f"salad question must remain open, got {open_items}"


@pytest.mark.asyncio
async def test_resolve_closes_generic_question_on_matching_brand_log(make_user, db):
    """A pending question about a generic-name item ('protein bar') must close
    when the user logs a same-category specific item ('built bar') — they
    overlap on the content token 'bar' which is the resolved answer."""
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-scoped-2")

    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="which bar? built, barebells, quest?", tier="brand",
        hook_style="question",
    )
    pq.item_referenced = "protein bar"
    await db.commit()

    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["built bar"]
    )
    assert closed == 1

    opens = await get_open_pending_questions(db, user.id)
    assert not [p for p in opens
                if p.kind == "food_clarification" and p.answered_at is None]


@pytest.mark.asyncio
async def test_resolve_skips_unrelated_log(make_user, db):
    """Log item A while an open question is about item B with no name overlap.
    Question stays open. This is the canonical bug: 'I had a royo bagel' must
    NOT silently close an open question about 'banana with honey'."""
    from db.queries import (
        record_pending_question, get_open_pending_questions,
        resolve_pending_questions_for_logged_items,
    )
    user = await make_user(telegram_id="t-scoped-3")

    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="how much honey?", tier="portion", hook_style="question",
    )
    pq.item_referenced = "banana with honey"
    await db.commit()

    closed = await resolve_pending_questions_for_logged_items(
        db, user.id, ["royo bagel"]
    )
    assert closed == 0

    opens = await get_open_pending_questions(db, user.id)
    still_open = [p for p in opens
                  if p.kind == "food_clarification" and p.answered_at is None]
    assert len(still_open) == 1
    assert still_open[0].item_referenced == "banana with honey"


# ── Phase 3: modality × accuracy mode prompt rules ───────────────────────────


def test_prompt_photo_overrides_quick_mode():
    """Photo describe-first must EXPLICITLY override quick mode in the prompt.
    Otherwise quick-mode users get auto-logged photos with no review step —
    visual estimates carry too much uncertainty for that."""
    from core.prompts.arnie import build_arnie_system
    s = build_arnie_system("telegram")
    # The PHOTO LOGGING rule must reference the mode override
    assert "OVERRIDES" in s and "FOOD LOGGING MODE" in s
    assert "quick mode" in s.lower() and (
        "described first" in s.lower() or "describe first" in s.lower()
        or "ALWAYS get described" in s
    )


def test_prompt_voice_softens_strict_mode():
    """Voice notes in strict mode should fall back to moderate behavior —
    making someone re-record to clarify cook method defeats the speed point
    of voice. Rule must be present."""
    from core.prompts.arnie import build_arnie_system
    s = build_arnie_system("telegram")
    assert "STRICT + VOICE" in s or "voice note" in s.lower()
    assert "MODERATE" in s or "moderate behavior" in s.lower()


def test_prompt_quick_mode_handles_generic_brand_from_history():
    """Quick mode + generic brand ('protein bar') should pull from FOOD HISTORY
    rather than ask — that preserves the flow promise. The exception must be
    documented in the prompt."""
    from core.prompts.arnie import build_arnie_system
    s = build_arnie_system("telegram")
    assert "QUICK + GENERIC BRAND" in s
    assert "FOOD HISTORY" in s
    assert "confidence: estimated" in s or "estimated" in s.lower()


# ── Phase 4: multi-item batch confirmation coaching swap ─────────────────────


def _single_item_coaching_stub(food_name="oatmeal"):
    """Mirrors the shape of the real log_food tool-result string up to the
    'Scale the reply' inflection point. Lets us unit-test the batch-coaching
    swap without spinning up a DB / USDA pipeline."""
    return (
        f"Logged {food_name}: 200 cal, 10g protein. ANALYSIS: ok. "
        f"DAY TOTAL: 600 cal, 30g protein. "
        f"Scale the reply to the log. Meaningful meal: name the food and its macros. "
        f"Sentence case. One emoji if it fits naturally."
    )


def test_multi_item_batch_swaps_coaching_in_tool_result():
    """When 3+ log_food calls fire in one turn, the log_food tool result must
    swap its single-item coaching ('Scale the reply...') for batch coaching
    ('MULTI-ITEM BATCH ... confirm the WHOLE batch in 1-2 bubbles'). Otherwise
    the model recaps the last item only and ignores the rest."""
    from handlers.tool_executor import _apply_multi_item_batch_coaching

    tool_calls = [
        {"id": f"tc{i}", "name": "log_food",
         "input": {"food_name": name}}
        for i, name in enumerate(["oatmeal", "banana", "coffee with milk"])
    ]
    # The real executor only keeps the LAST log_food's coaching string in the
    # results dict (one name-key, last-write-wins). Simulate that here.
    results = {"log_food": _single_item_coaching_stub("coffee with milk")}

    swapped = _apply_multi_item_batch_coaching(results, tool_calls)
    out = swapped["log_food"]
    assert "MULTI-ITEM BATCH" in out
    assert "3 foods" in out
    # All three names should be referenced so the model has anchors.
    assert "oatmeal" in out.lower()
    assert "banana" in out.lower()
    assert "coffee with milk" in out.lower()
    # Single-item coaching must be gone.
    assert "Scale the reply" not in out


def test_single_item_log_keeps_single_item_coaching():
    """One log_food call → keep the original single-item coaching. The batch
    swap MUST NOT fire when only one item is logged."""
    from handlers.tool_executor import _apply_multi_item_batch_coaching

    tool_calls = [
        {"id": "tc1", "name": "log_food", "input": {"food_name": "banana"}}
    ]
    results = {"log_food": _single_item_coaching_stub("banana")}

    swapped = _apply_multi_item_batch_coaching(results, tool_calls)
    out = swapped["log_food"]
    assert "MULTI-ITEM BATCH" not in out
    assert "Scale the reply" in out


def test_batch_coaching_warns_against_restoring_deleted_items():
    """The swapped coaching must explicitly tell the model: never echo items
    the user deleted from the dashboard. This is the live bug we hit when
    Arnie 'helpfully' re-logged a deleted banana after a new bagel."""
    from handlers.tool_executor import _apply_multi_item_batch_coaching

    tool_calls = [
        {"id": "tc1", "name": "log_food", "input": {"food_name": "bagel"}},
        {"id": "tc2", "name": "log_food", "input": {"food_name": "coffee"}},
    ]
    results = {"log_food": _single_item_coaching_stub("coffee")}
    out = _apply_multi_item_batch_coaching(results, tool_calls)["log_food"]
    assert "Never restore" in out or "deleted" in out.lower()
    assert "Never mention items NOT in this turn" in out


def test_batch_coaching_does_not_double_apply():
    """If a tool-result string was already swapped to batch coaching (no
    'Scale the reply' marker remains), a second call must be a no-op rather
    than mangling the text further."""
    from handlers.tool_executor import _apply_multi_item_batch_coaching

    tool_calls = [
        {"id": "tc1", "name": "log_food", "input": {"food_name": "bagel"}},
        {"id": "tc2", "name": "log_food", "input": {"food_name": "coffee"}},
    ]
    results = {"log_food": _single_item_coaching_stub("coffee")}
    first = _apply_multi_item_batch_coaching(results, tool_calls)["log_food"]
    # Apply again — should not change the string (idempotent).
    second = _apply_multi_item_batch_coaching({"log_food": first}, tool_calls)["log_food"]
    assert first == second
