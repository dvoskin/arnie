"""
LLM-judge eval scaffold — opt-in compliance check for the prompt rules we
locked in across the hardening pass.

These tests are SKIPPED by default. They make real Anthropic API calls and
cost money/latency, so they only run when LLM_JUDGE_EVAL=true is set in env.

Each scenario:
  1. Constructs a minimal user message + context that should trigger a
     specific prompt rule
  2. Runs Arnie's actual `chat` against the real system prompt
  3. Passes the response to a smaller "judge" model with a yes/no
     compliance question
  4. Asserts the judge says yes

This is NOT a regression-test pass-rate target — it's a smoke test that
confirms the prompt rules HAVE the influence we designed them to have.
Run periodically (pre-deploy, post-prompt-edit) to catch silent drift.

Usage:
  LLM_JUDGE_EVAL=true ANTHROPIC_API_KEY=... \\
      .venv/bin/python3 -m pytest tests/test_llm_judge_eval.py -v
"""
import os
import json
import pytest

from core.prompts.arnie import build_arnie_system


pytestmark = pytest.mark.skipif(
    os.environ.get("LLM_JUDGE_EVAL", "").lower() != "true",
    reason="LLM-judge eval is opt-in (set LLM_JUDGE_EVAL=true to run).",
)


# ── infrastructure ───────────────────────────────────────────────────────────


JUDGE_MODEL = "claude-haiku-4-5-20251001"
ARNIE_MODEL = "claude-sonnet-4-6"  # match prod default


async def _run_arnie(user_msg: str, today_context: str = "") -> str:
    """One-shot Arnie call. Returns the assistant's final text (no tools)."""
    from core.llm import chat
    system = build_arnie_system("telegram")
    if today_context:
        system += f"\n\n--- CONTEXT ---\n{today_context}"
    result = await chat(
        messages=[{"role": "user", "content": user_msg}],
        system=system,
        tools=False,
        max_tokens=600,
    )
    return (result.get("text") or "").strip()


async def _judge(criterion: str, arnie_response: str) -> tuple[bool, str]:
    """Ask a smaller model to judge whether the response satisfies a criterion.
    Returns (passes, reason)."""
    from core.llm import chat
    judge_system = (
        "You are an impartial judge. Given a coaching assistant's response and "
        "a single yes/no criterion, decide whether the response satisfies the "
        "criterion. Reply with JSON only: {\"passes\": true|false, \"reason\": "
        "\"brief one-sentence justification\"}."
    )
    judge_prompt = (
        f"CRITERION: {criterion}\n\n"
        f"RESPONSE:\n{arnie_response}\n\n"
        "Reply with JSON only."
    )
    result = await chat(
        messages=[{"role": "user", "content": judge_prompt}],
        system=judge_system,
        tools=False,
        max_tokens=200,
        model=JUDGE_MODEL,
    )
    txt = (result.get("text") or "").strip()
    # Strip code fences if present
    if txt.startswith("```"):
        txt = txt.split("```")[1].lstrip("json\n").rstrip("`\n")
    try:
        data = json.loads(txt)
        return bool(data.get("passes", False)), data.get("reason", "")
    except Exception as e:
        return False, f"judge parse error: {e}; raw={txt[:200]!r}"


# ── canonical scenarios — one per prompt rule we shipped ─────────────────────


@pytest.mark.asyncio
async def test_eval_no_tool_narration_happy_wolf():
    """Replays the Happy Wolf bug. The model must NOT say 'Hmm, that match
    doesn't look right' or any equivalent narration of the lookup pipeline."""
    user_msg = "I had a happy wolf chocolate chip bar, the kids one"
    response = await _run_arnie(user_msg)
    passes, reason = await _judge(
        "Does the response avoid ANY narration of internal database lookups, "
        "match quality, USDA confidence, or retry attempts? Specifically, "
        "phrases like 'Hmm, that match doesn't look right', 'the USDA match is "
        "off', 'couldn't find a great match', 'let me double-check', or any "
        "equivalent tool-internals leak should NOT appear.",
        response,
    )
    assert passes, f"tool-narration leak: {reason}\nresponse: {response!r}"


@pytest.mark.asyncio
async def test_eval_calorie_room_framing():
    """User is 87 cal under target with a 51g protein gap. The model must NOT
    say 'basically at your cal limit' — they have room."""
    context = (
        "[TODAY] 2026-06-08\nCals 1913 / 2000  |  P 149g / 200g\n"
        "Food:\n  • [#1] dinner (1 plate): 800cal 50P\n"
    )
    user_msg = "what should I have tonight to close out the day?"
    response = await _run_arnie(user_msg, today_context=context)
    passes, reason = await _judge(
        "The user is 87 calories UNDER target with a 51g protein gap. The "
        "response must NOT say 'at your cal limit', 'basically there', 'tight "
        "on calories', or any phrasing that overstates how close they are to "
        "their target — they have 87 cal of real room. Framing should be "
        "positive about the room available.",
        response,
    )
    assert passes, f"calorie-room framing: {reason}\nresponse: {response!r}"


@pytest.mark.asyncio
async def test_eval_no_one_sec_fallback():
    """A slow-tool turn should produce an in-voice heads-up, never the
    customer-service 'one sec.' string."""
    user_msg = "how many cals are in a starbucks venti pumpkin spice latte?"
    response = await _run_arnie(user_msg)
    passes, reason = await _judge(
        "Does the response avoid the off-voice phrase 'one sec.' as a "
        "heads-up bubble? It should sound like a coach, not a customer-service "
        "rep — something like 'pulling the macros' or 'checking that' is OK; "
        "literal 'one sec.' is not.",
        response,
    )
    assert passes, f"one sec regression: {reason}\nresponse: {response!r}"


@pytest.mark.asyncio
async def test_eval_brand_variant_does_not_inherit():
    """If [FOOD HISTORY] has 'royo challah roll' and user logs 'royo bagel',
    the model must NOT silently reuse challah macros."""
    context = (
        "[FOOD HISTORY]\n"
        "Royo challah roll (1 piece): 320 cal, 8g protein — logged 5 times\n"
        "[TODAY] 2026-06-08\nCals 1200 / 2000\n"
    )
    user_msg = "I had a royo bagel"
    response = await _run_arnie(user_msg, today_context=context)
    passes, reason = await _judge(
        "The user logged 'royo bagel'. The history has 'royo challah roll' "
        "(a different product). Did the response either (a) ask which Royo "
        "item, or (b) treat the bagel as a separate item with its own "
        "estimate? It must NOT silently inherit the 320 cal / 8g protein "
        "from the challah roll.",
        response,
    )
    assert passes, f"brand-variant inheritance: {reason}\nresponse: {response!r}"


@pytest.mark.asyncio
async def test_eval_does_not_restore_deleted_item():
    """Chat-history shows banana was confirmed earlier; [TODAY] no longer has
    it. New log: 'I had a coffee'. The model must NOT mention or relog the
    banana."""
    context = (
        "[TODAY] 2026-06-08\nCals 1500 / 2000\n"
        "Food:\n  • [#3] dinner (1 plate): 1500cal\n"
    )
    # Simulate prior banana confirmation in chat history (via user message)
    user_msg = (
        "(earlier you logged a banana for me at 105 cal, but I removed it "
        "from the dashboard) I just had a coffee"
    )
    response = await _run_arnie(user_msg, today_context=context)
    passes, reason = await _judge(
        "The user removed the banana from the dashboard and now logs only a "
        "coffee. Does the response (a) confirm only the coffee, and (b) NOT "
        "restore or re-log the banana? Mentioning the banana removal is OK "
        "if natural, but no relogging it.",
        response,
    )
    assert passes, f"dashboard-delete restore: {reason}\nresponse: {response!r}"


# ── opt-in test runner helper ────────────────────────────────────────────────


def test_eval_scaffold_loads():
    """Sanity: the scaffold itself imports without the LLM. Always runs."""
    assert callable(_run_arnie)
    assert callable(_judge)
