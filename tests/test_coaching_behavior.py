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
async def test_workout_for_yesterday_logs_with_date():
    """Workouts get the same date-flexibility as food: 'yesterday I benched and squatted'
    → log_exercise(date='yesterday') per exercise, not today."""
    from core.llm import chat
    messages = [{"role": "user", "content": "yesterday I benched 185 5x5 and squatted 225 3x5"}]
    result = await chat(messages, _coach_system(), tools=True, max_tokens=4096)
    ex = [tc for tc in result["tool_calls"] if tc["name"] == "log_exercise"]
    dated = [tc for tc in ex if "yester" in str(tc["input"].get("date", "")).lower()]
    assert len(ex) >= 2, f"should log both lifts; got {[tc['name'] for tc in result['tool_calls']]}"
    assert len(dated) >= 2, f"both should carry date=yesterday; got dates {[tc['input'].get('date') for tc in ex]}"


@pytest.mark.asyncio
async def test_closed_day_does_not_narrate_reopening():
    """Logging to a closed day must NOT explain reopening or steps — just do it + confirm."""
    from core.llm import chat
    from core.prompts import build_arnie_system
    system = build_arnie_system("imessage") + (
        "\n\n[TODAY]\nStatus: CLOSED (day was wrapped up). 1,800 cal logged.\n"
        "User: Danny, goal cut."
    )
    messages = [{"role": "user", "content": "oh wait i also had a protein bar after"}]
    result = await chat(messages, system, tools=True, max_tokens=2048)
    txt = (result.get("text") or "").lower()
    assert "reopen" not in txt and "closed" not in txt, \
        f"must not narrate reopening the day: {txt[:200]!r}"
    assert any(tc["name"] == "log_food" for tc in result["tool_calls"]), \
        "should just log the bar"


@pytest.mark.asyncio
async def test_dashboard_handoff_line_does_not_greet_by_name():
    """The dashboard hand-off line should continue the conversation, not open with a
    fresh greeting or the user's name ('yo Danny') — that reads as out-of-context."""
    import re
    from core.blurbs import dashboard_line
    line = (await dashboard_line("Danny")).strip()
    low = line.lower()
    assert not re.match(r"^(yo|hey|hi|sup|hello|howdy)\b", low), f"greeting opener: {line!r}"
    assert "danny" not in low, f"used the name mid-convo: {line!r}"
    assert "http" not in low


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
