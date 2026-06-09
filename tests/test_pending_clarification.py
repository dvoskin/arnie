"""
T2.2 — Tests for PendingClarification (food_clarification kind on PendingQuestion).

When Arnie asks "grilled or fried?" the executor records a pending row. Next
turn the context block surfaces it so the model SEES what's outstanding and
uses the user's answer to log directly — no re-asking. Auto-resolves on
log_food.

The food_clarification kind is invisible to the reminders module (which only
re-asks profile_stats + conversation_hook). It's a pure conversational helper.
"""
import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

from db.queries import (
    record_pending_question, get_open_pending_questions,
    resolve_pending_questions,
)


# ── DB-level: record + auto-resolve ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_food_clarification_records_and_resolves(make_user, db):
    """Happy path: record a question, then resolve_pending_questions(kinds=['food_clarification'])
    closes it (as log_food would do via the executor branch)."""
    user = await make_user(telegram_id="t221")

    pq = await record_pending_question(
        db, user.id, kind="food_clarification",
        question="grilled or fried?", tier="cook_method", hook_style="question",
    )
    pq.item_referenced = "chicken sandwich"
    await db.commit()

    # Confirm it's open.
    opens = await get_open_pending_questions(db, user.id)
    food_clarifs = [p for p in opens if p.kind == "food_clarification"]
    assert len(food_clarifs) == 1
    assert food_clarifs[0].item_referenced == "chicken sandwich"
    assert food_clarifs[0].question == "grilled or fried?"
    assert food_clarifs[0].answered_at is None

    # Auto-resolve (mirrors what the log_food executor does).
    closed = await resolve_pending_questions(db, user.id, kinds=["food_clarification"])
    assert closed == 1

    # No longer in open list.
    opens = await get_open_pending_questions(db, user.id)
    assert all(p.kind != "food_clarification" or p.answered_at for p in opens)


@pytest.mark.asyncio
async def test_food_clarification_invisible_to_other_resolve_kinds(make_user, db):
    """Resolving profile_stats (the reminders module's domain) must NOT touch
    food_clarification rows — they have separate lifecycles."""
    user = await make_user(telegram_id="t222")

    await record_pending_question(
        db, user.id, kind="food_clarification",
        question="what brand?", tier="brand", hook_style="question",
    )
    await record_pending_question(
        db, user.id, kind="profile_stats",
        question="what's your age?", tier="goal_critical", hook_style="question",
    )

    # Resolve profile_stats only.
    closed = await resolve_pending_questions(db, user.id, kinds=["profile_stats"])
    assert closed == 1

    # food_clarification still open.
    opens = await get_open_pending_questions(db, user.id)
    assert any(p.kind == "food_clarification" and p.answered_at is None for p in opens)


# ── render_pending_clarification_block — pure function, no DB ────────────────


def _stub_row(kind="food_clarification", question="grilled or fried?",
              item="chicken sandwich", asked_minutes_ago=5, answered=False):
    """A minimal stand-in for a PendingQuestion row. The block renderer reads
    only `kind`, `asked_at`, `question`, `item_referenced`, `answered_at` —
    no DB, no SQLAlchemy machinery."""
    return SimpleNamespace(
        kind=kind,
        question=question,
        item_referenced=item,
        asked_at=datetime.utcnow() - timedelta(minutes=asked_minutes_ago),
        answered_at=datetime.utcnow() if answered else None,
    )


def test_block_surfaces_fresh_food_clarification():
    """A fresh (< 30 min) food_clarification row renders the block."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(asked_minutes_ago=5)]
    block = render_pending_clarification_block(rows)
    assert "[PENDING CLARIFICATION]" in block
    assert "grilled or fried?" in block
    assert "chicken sandwich" in block
    assert "DON'T re-ask" in block


def test_block_skips_stale_food_clarification():
    """Rows older than 30 minutes don't render — the user has moved on."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(asked_minutes_ago=45)]
    block = render_pending_clarification_block(rows)
    assert block == ""


def test_block_skips_resolved_food_clarification():
    """Resolved rows don't render even if fresh."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(asked_minutes_ago=5, answered=True)]
    block = render_pending_clarification_block(rows)
    assert block == ""


def test_block_skips_non_food_clarification_kinds():
    """profile_stats / goal_check / conversation_hook rows aren't food
    clarifications — they belong to the reminders module's lifecycle."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(kind="profile_stats", asked_minutes_ago=5),
            _stub_row(kind="conversation_hook", asked_minutes_ago=5)]
    block = render_pending_clarification_block(rows)
    assert block == ""


def test_block_caps_at_three_rows_to_keep_prompt_lean():
    """If 5 clarifications are pending, only 3 land in the prompt — the model
    doesn't need the full backlog."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(item=f"item-{i}", asked_minutes_ago=i + 1) for i in range(5)]
    block = render_pending_clarification_block(rows)
    # Should mention 3 items, NOT all 5.
    item_lines = [line for line in block.split("\n") if line.startswith("  - ")]
    assert len(item_lines) == 3


def test_block_handles_missing_item_referenced_gracefully():
    """Older food_clarification rows may have NULL item_referenced (the column
    is nullable). The block must still render with a placeholder."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(item=None, asked_minutes_ago=5)]
    block = render_pending_clarification_block(rows)
    assert "[PENDING CLARIFICATION]" in block
    assert "the food" in block  # the fallback placeholder


# ── Tool definition is present + active ──────────────────────────────────────


def test_note_food_clarification_tool_in_active_set():
    from core.tools import build_tools
    names = {t["name"] for t in build_tools()}
    assert "note_food_clarification" in names


def test_note_food_clarification_schema_requires_question_and_food_item():
    from core.tools import build_tools
    tool = next(t for t in build_tools() if t["name"] == "note_food_clarification")
    required = set(tool["input_schema"].get("required", []))
    assert {"question", "food_item"} <= required


# ── mode-based freshness window ──────────────────────────────────────────────


def test_quick_mode_expires_after_15_minutes():
    """quick mode users want flow — questions expire after 15 min, not 30."""
    from core.context_builder import render_pending_clarification_block
    # 20 min ago — stale for quick (15), fresh for moderate (30)
    rows = [_stub_row(asked_minutes_ago=20)]
    assert render_pending_clarification_block(rows, food_mode="quick") == ""
    assert render_pending_clarification_block(rows, food_mode="moderate") != ""


def test_quick_mode_still_surfaces_very_fresh_questions():
    """quick mode: a 10-min-old question is still within the 15-min window."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(asked_minutes_ago=10)]
    block = render_pending_clarification_block(rows, food_mode="quick")
    assert "[PENDING CLARIFICATION]" in block


def test_strict_mode_keeps_questions_live_for_60_minutes():
    """strict mode users are deliberate — questions stay live for 60 min."""
    from core.context_builder import render_pending_clarification_block
    # 45 min ago — stale for moderate (30), fresh for strict (60)
    rows = [_stub_row(asked_minutes_ago=45)]
    assert render_pending_clarification_block(rows, food_mode="moderate") == ""
    assert render_pending_clarification_block(rows, food_mode="strict") != ""


def test_strict_mode_expires_after_60_minutes():
    """strict mode questions still expire — 65 min old is gone."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(asked_minutes_ago=65)]
    assert render_pending_clarification_block(rows, food_mode="strict") == ""


def test_unknown_mode_falls_back_to_default_30_minutes():
    """An unrecognised mode string uses the 30-min default — no crash."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(asked_minutes_ago=20)]
    # 20 min — should be fresh under default (30)
    assert render_pending_clarification_block(rows, food_mode="typo_mode") != ""


def test_block_includes_log_all_foods_instruction():
    """After our multi-item fix, the block must tell the LLM to log ALL foods,
    not just the one the question was about."""
    from core.context_builder import render_pending_clarification_block
    rows = [_stub_row(asked_minutes_ago=5)]
    block = render_pending_clarification_block(rows)
    assert "all" in block.lower()


def test_prompt_teaches_clarification_tool_and_context_block():
    """The model must be taught to call note_food_clarification when asking
    AND to consume the [PENDING CLARIFICATION] block next turn. The rule was
    tightened from a verbose 'RECORD YOUR QUESTION' header to a few in-voice
    lines to keep the model from going clinical mid-question."""
    from core.prompts.arnie import build_arnie_system
    s = build_arnie_system("telegram")
    assert "note_food_clarification" in s
    assert "[PENDING CLARIFICATION]" in s
    # Voice-preservation example must be present — this is what prevents
    # the "Need to confirm the calories on that" clinical regression.
    assert "challah" in s.lower() or "in your normal voice" in s.lower()
