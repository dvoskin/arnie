"""
LLM behavioral tests for onboarding.

These tests actually call the LLM (using Haiku for cost) and assert on response
behavior — not just prompt content. Run them when:
  • the onboarding prompts change
  • a behavioral regression is suspected
  • before a deploy after onboarding edits

They are slow (~2-3s each, real API call) and cost money, so they are NOT run in
the default pytest suite. Run explicitly:

    .venv/bin/python -m pytest tests/test_onboarding_behavior.py -v -s

Each test encodes a specific behavioral guarantee that was once broken in prod.
When a new bug ships, add a test here so it can't regress silently.
"""
import asyncio
import os
import pytest
from types import SimpleNamespace
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — LLM behavioral tests require live API",
)

# Use Haiku for all behavioral tests — fast and cheap, still catches prompt deviations.
_EVAL_MODEL = "claude-haiku-4-5"


def _user(**kw):
    base = dict(
        name=None, primary_goal=None, current_weight_kg=None,
        goal_weight_kg=None, training_experience=None, city=None,
        height_cm=None, age=None, sex=None, onboarding_completed=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def _llm(system: str, messages: list) -> str:
    """Call the LLM with no tools, return plain text response."""
    from core.llm import chat
    result = await chat(messages, system, tools=False, max_tokens=512, model=_EVAL_MODEL)
    return (result.get("text") or "").lower()


def _has_any(text: str, *phrases) -> bool:
    return any(p.lower() in text for p in phrases)


def _has_none(text: str, *phrases) -> bool:
    return not any(p.lower() in text for p in phrases)


# ── Stage: GET NAME ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_after_name_invites_brain_dump_not_food():
    """
    REGRESSION: Arnie used to respond to a name with "send me what you ate today"
    instead of inviting the brain dump.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user())  # no name yet → GET_NAME stage
    # Simulate: user just replied with their name
    messages = [
        {"role": "user", "content": "Daniel Voskin"},
    ]
    response = await _llm(system, messages)
    assert _has_any(response, "voice note", "messy paragraph", "dump", "paragraph"), \
        f"Expected brain dump invite, got: {response[:200]}"
    assert _has_none(response, "what did you eat", "what have you eaten", "log your food"), \
        f"Should not ask for food before brain dump: {response[:200]}"


@pytest.mark.asyncio
async def test_after_name_does_not_ask_goal_separately():
    """
    Goal should come from the brain dump, not asked as a standalone question
    before the dump is invited.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user())
    messages = [{"role": "user", "content": "Hey I'm Marcus"}]
    response = await _llm(system, messages)
    # Should invite the dump — goal can be in there. Should NOT ask goal before dump.
    assert _has_none(response, "what are we chasing", "leaning out or building",
                     "lose weight or gain"), \
        f"Should not ask goal before dump invite: {response[:200]}"


# ── Stage: DUMP PENDING — Case A (invite) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_dump_stage_invites_when_no_dump_in_history():
    """
    When we're in dump_pending and no dump has been sent, Arnie invites it.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user(name="Sarah"))
    # History: name was given, Arnie reacted — no dump invitation yet
    messages = [
        {"role": "user", "content": "Sarah"},
        {"role": "assistant", "content": "Good to meet you, Sarah."},
        {"role": "user", "content": "ok cool"},
    ]
    response = await _llm(system, messages)
    assert _has_any(response, "voice note", "messy paragraph", "paragraph"), \
        f"Should invite brain dump: {response[:200]}"


@pytest.mark.asyncio
async def test_dump_stage_does_not_ask_weight_directly():
    """
    REGRESSION: Arnie used to skip the brain dump and ask "what do you weigh?"
    directly after getting name + goal.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user(name="Jake"))
    messages = [
        {"role": "user", "content": "Jake"},
        {"role": "assistant", "content": "Good to meet you, Jake."},
        {"role": "user", "content": "ready"},
    ]
    response = await _llm(system, messages)
    assert _has_none(response, "what do you weigh", "how much do you weigh",
                     "current weight"), \
        f"Should not ask weight before dump: {response[:200]}"


# ── Stage: DUMP PENDING — Case B (process) ────────────────────────────────────

@pytest.mark.asyncio
async def test_dump_stage_processes_dump_not_reinvites():
    """
    REGRESSION: After the brain dump was sent, Arnie kept re-inviting it instead
    of processing it. The stage stayed 'dump_pending' so the invite prompt fired again.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user(name="Daniel"))
    dump_invite = (
        "Good to meet you, Daniel. "
        "Fastest way to set me up: voice note or a messy paragraph. "
        "Weight, training, food habits, injuries, deadline — whatever's relevant."
    )
    dump_response = (
        "I'm 190 lbs, 28 years old, I train 4 times a week mostly lifting. "
        "Want to cut down to about 175 before summer. "
        "I eat pretty well but I snack a lot at night. No injuries."
    )
    messages = [
        {"role": "user", "content": "Daniel"},
        {"role": "assistant", "content": dump_invite},
        {"role": "user", "content": dump_response},
    ]
    response = await _llm(system, messages)
    # Must NOT re-invite the dump
    assert _has_none(response, "voice note", "messy paragraph",
                     "send me a paragraph"), \
        f"Should not re-invite dump after dump was received: {response[:200]}"
    # Must reflect something back
    assert _has_any(response, "190", "175", "summer", "lifting", "snack", "cut"), \
        f"Should reflect back what was heard: {response[:200]}"


@pytest.mark.asyncio
async def test_dump_processing_gives_intelligent_reflection():
    """
    After the dump, Arnie should give a 2-4 bubble analysis that shows he understood
    the user — not just echo facts back. This improves retention.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user(name="Mia"))
    dump_invite = "Fastest way to set me up: voice note or a messy paragraph."
    dump = (
        "Ok so I'm 145 lbs, 5'4, I want to lose weight for my wedding in June. "
        "I don't really exercise but I walk a lot. I eat healthy during the day "
        "but dinner is usually big. No injuries. I'm 31."
    )
    messages = [
        {"role": "user", "content": "Mia"},
        {"role": "assistant", "content": dump_invite},
        {"role": "user", "content": dump},
    ]
    response = await _llm(system, messages)
    # Reflection should reference real details, not generic coach-speak
    assert _has_any(response, "wedding", "june", "dinner", "walk"), \
        f"Reflection should reference their specific situation: {response[:200]}"
    assert _has_none(response, "great job", "amazing", "you've got this",
                     "sounds good"), \
        f"Should not use empty praise: {response[:200]}"


@pytest.mark.asyncio
async def test_dump_asks_weight_if_missing_after_processing():
    """
    If weight wasn't in the dump, Arnie should ask for it — but ONLY weight,
    not height, age, sex, or anything else.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user(name="Tom"))
    dump_invite = "Fastest way to set me up: voice note or a messy paragraph."
    dump_without_weight = (
        "I want to build muscle, been lifting for 2 years. "
        "I eat a lot of protein already. No injuries. Based in NYC."
    )
    messages = [
        {"role": "user", "content": "Tom"},
        {"role": "assistant", "content": dump_invite},
        {"role": "user", "content": dump_without_weight},
    ]
    response = await _llm(system, messages)
    assert _has_any(response, "weigh", "weight"), \
        f"Should ask for weight after dump if missing: {response[:200]}"
    assert _has_none(response, "how tall", "your age", "how old", "sex", "gender"), \
        f"Should ONLY ask for weight, not height/age/sex: {response[:200]}"


# ── Stage: COMPLETE ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_stage_drives_to_first_log():
    """
    Once all essentials are in, Arnie drives to the first log — not more questions.
    """
    from handlers.onboarding import build_onboarding_system
    system = build_onboarding_system(_user(
        name="Alex", primary_goal="cut", current_weight_kg=85.0
    ))
    messages = [{"role": "user", "content": "190"}]
    response = await _llm(system, messages)
    assert _has_any(response, "ate today", "eaten today", "first log",
                    "what you eat", "send me"), \
        f"Should drive to first log: {response[:200]}"
    assert _has_none(response, "what's your height", "how old", "training style",
                     "anything else"), \
        f"Should not ask more setup questions: {response[:200]}"


# ── Voice rules ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_responses_use_bubble_separator():
    """
    All onboarding responses should use ||| bubble separators, not walls of text.
    """
    from handlers.onboarding import build_onboarding_system
    # Use the dump stage which generates the most complex responses
    system = build_onboarding_system(_user(name="Chris"))
    dump_invite = "Fastest way to set me up: voice note or a messy paragraph."
    dump = "I'm 200 lbs want to get to 180, I run 3x a week, eat pretty bad, 35 years old."
    messages = [
        {"role": "user", "content": "Chris"},
        {"role": "assistant", "content": dump_invite},
        {"role": "user", "content": dump},
    ]
    # Need raw response (not lowercased) for this check
    from core.llm import chat
    result = await chat(messages, system, tools=False, max_tokens=512, model=_EVAL_MODEL)
    response = result.get("text") or ""
    assert "|||" in response, \
        f"Response should use ||| bubble separators: {response[:200]}"
