"""
LLM behavioral tests for coaching (live API). Gated behind -m behavioral — slow,
costs money, non-deterministic. Run manually / pre-deploy:  pytest -m behavioral

Uses the PRODUCTION model (no model override) because the behaviors here — emitting
one tool call per food item, not truncating a multi-item dump — depend on the model
tier that actually ships. Haiku would under-report and make the test misleading.
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = [
    pytest.mark.behavioral,
    pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set — LLM behavioral tests require live API",
    ),
]


def _coach_system() -> str:
    from core.prompts import build_arnie_system
    # Minimal coaching context: onboarded user, empty day, targets set.
    return build_arnie_system("imessage") + (
        "\n\n[TODAY]\n0 food entries logged. calorie target 2100, protein target 180.\n"
        "User: Danny, goal cut."
    )


@pytest.mark.asyncio
async def test_multi_item_dump_emits_a_call_per_item():
    """
    REGRESSION (the 7-item-dump bug): a single message listing many foods must produce
    a log_food call PER item, not just the first. Run with the production model and the
    real 2048 first-pass budget so truncation can't silently drop the tail.
    """
    from core.llm import chat
    messages = [{"role": "user", "content": (
        "log all this: grilled chicken wrap, half a shnitzel sandwich, "
        "2 chicken poppers, 5 spicy tuna sushi, 6 cookies, half a babka slice, "
        "half a cinnamon roll"
    )}]
    result = await chat(messages, _coach_system(), tools=True, max_tokens=2048)
    food_calls = [tc for tc in result["tool_calls"] if tc["name"] == "log_food"]
    names = [tc["input"].get("food_name", "") for tc in food_calls]
    assert len(food_calls) >= 5, f"expected a call per item (~7), got {len(food_calls)}: {names}"


@pytest.mark.asyncio
async def test_labeled_yesterday_list_logs_to_yesterday():
    """A list labeled 'Yesterday' must carry date='yesterday' on the items, not today."""
    from core.llm import chat
    messages = [{"role": "user", "content": (
        "Yesterday: grilled chicken wrap, shnitzel sandwich, 6 cookies"
    )}]
    result = await chat(messages, _coach_system(), tools=True, max_tokens=2048)
    food_calls = [tc for tc in result["tool_calls"] if tc["name"] == "log_food"]
    assert food_calls, "expected the foods to be logged"
    dated = [tc for tc in food_calls if "yester" in str(tc["input"].get("date", "")).lower()]
    assert len(dated) >= len(food_calls) - 1, (
        f"items should carry date=yesterday, got dates: "
        f"{[tc['input'].get('date') for tc in food_calls]}"
    )


@pytest.mark.asyncio
async def test_redo_today_clears_then_relogs():
    """'redo today as the following: ...' must clear_day_log FIRST, then re-log the
    items — a clean rebuild in one turn, not new items stacked on the old mess."""
    from core.llm import chat
    messages = [{"role": "user", "content": (
        "redo today as the following: grilled chicken wrap, shnitzel sandwich, 6 cookies"
    )}]
    result = await chat(messages, _coach_system(), tools=True, max_tokens=4096)
    names = [tc["name"] for tc in result["tool_calls"]]
    assert "clear_day_log" in names, f"redo must clear first; got {names}"
    assert names.count("log_food") >= 2, f"redo must re-log the new list; got {names}"


def _coach_system_with_entries() -> str:
    """Coaching context with two logged entries (so the model has [#id]s to move)."""
    from core.prompts import build_arnie_system
    return build_arnie_system("imessage") + (
        "\n\n[TODAY]\nLogged so far:\n"
        "  [#11] chicken wrap — 450 cal, 35g protein\n"
        "  [#12] premier shake — 160 cal, 30g protein\n"
        "Totals: 610 cal, 65g protein. User: Danny, goal cut."
    )


@pytest.mark.asyncio
async def test_put_this_for_yesterday_moves_entries_not_narration():
    """'put this log for yesterday instead of today' must MOVE the entries via
    update_food_entry(date=...) — one call per entry — not narrate 'let me delete and
    relog', and not invent a bespoke move tool."""
    from core.llm import chat
    messages = [{"role": "user", "content": (
        "put this log for yesterday instead of today, the whole thing was yesterday"
    )}]
    result = await chat(messages, _coach_system_with_entries(), tools=True, max_tokens=4096)
    names = [tc["name"] for tc in result["tool_calls"]]
    moves = [tc for tc in result["tool_calls"]
             if tc["name"] == "update_food_entry"
             and "yester" in str(tc["input"].get("date", "")).lower()]
    assert len(moves) >= 2, (
        f"should move both entries to yesterday via update_food_entry(date=...). "
        f"tools={names}, text={result['text'][:160]!r}"
    )


@pytest.mark.asyncio
async def test_estimate_request_logs_without_reasking():
    """'guestimate' must produce a log_food call, not another clarifying question."""
    from core.llm import chat
    messages = [
        {"role": "user", "content": "had a cinnamon roll"},
        {"role": "assistant", "content": "what size, roughly?"},
        {"role": "user", "content": "guestimate tht shit"},
    ]
    result = await chat(messages, _coach_system(), tools=True, max_tokens=1024)
    food_calls = [tc for tc in result["tool_calls"] if tc["name"] == "log_food"]
    assert food_calls, f"should estimate and log, not re-ask. text was: {result['text'][:160]!r}"
