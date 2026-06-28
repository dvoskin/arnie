"""
Regression tests for the multi-wave fix shipped against the screenshot cascade:
  - Bubble cap on proactive follow-ups (Change 4) — no more 3:19 PM dinner triple.
  - Hook extraction guards (Change 3) — stall-prefix and logging-turn closures
    don't queue 30-min re-asks.
  - Body weight unit sanity (Change 12) — 14kg-vs-140lb typo gets caught.
  - Sarcasm detector (Change 14) — short praise after a known-bad reply flags.
  - Packaged-product branded heuristic (Change 6) — safety-net catches branded
    text mentions the model forgot to flag.
"""
from types import SimpleNamespace

import pytest


# ── Change 4 ────────────────────────────────────────────────────────────────
def test_cap_bubbles_keeps_first_two_drops_rest():
    from scheduler.proactive_scheduler import _cap_bubbles
    text = ("Still need that dinner intel whenever you get a sec.|||"
            "Still waiting to hear what's happening for dinner tonight.|||"
            "128g protein to play with, what're you thinking?")
    capped = _cap_bubbles(text, 2)
    parts = [b for b in capped.split("|||") if b.strip()]
    assert len(parts) == 2
    assert "Still need that dinner" in parts[0]


def test_cap_bubbles_passes_short_text_unchanged():
    from scheduler.proactive_scheduler import _cap_bubbles
    assert _cap_bubbles("one bubble", 2) == "one bubble"
    assert _cap_bubbles("a|||b", 2) == "a|||b"


# ── Change 3 ────────────────────────────────────────────────────────────────
def test_extract_hook_rejects_short_coaching_tag_question():
    from reminders.lifecycle import _extract_hook
    # Below the 25-char floor — short coaching tag doesn't queue a re-ask.
    assert _extract_hook("clean log today.|||what's next?") is None


def test_extract_hook_rejects_stall_prefix_bubble():
    from reminders.lifecycle import _extract_hook
    # The exact stall from the screenshot — must NOT open a hook.
    assert _extract_hook(
        "Checking exact macros on the Elmhurst sea salt chocolate flavor real quick?"
    ) is None
    assert _extract_hook(
        "Let me grab the exact macros on that shake before logging it?"
    ) is None


def test_extract_hook_accepts_genuine_long_question():
    from reminders.lifecycle import _extract_hook
    # A real abandoned-loop question still opens a hook.
    result = _extract_hook(
        "515 / 2,126 calories today.|||"
        "Big gap still to fill — what's your plan for dinner tonight?"
    )
    assert result is not None
    assert result[1] == "question"


# ── Change 12 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_body_weight_unit_mixup_caught(monkeypatch):
    """Logging 14 kg when current is 80 kg returns a clarifying tool result
    instead of writing the bogus entry."""
    from handlers import tool_executor as TE

    user = SimpleNamespace(id=1, current_weight_kg=80.0)
    today_log = SimpleNamespace(id=1, total_water_ml=0)

    # Stub the DB write so test doesn't need a real session — verifies the guard
    # NEVER reaches it.
    write_count = {"n": 0}

    async def _no_write(*a, **kw):
        write_count["n"] += 1

    monkeypatch.setattr(TE, "add_body_metric", _no_write)

    result = await TE._dispatch(
        "log_body_weight",
        {"weight": 14, "unit": "kg"},
        user, today_log, db=None, source_type="text",
    )
    assert "Skipped weight log" in result
    assert write_count["n"] == 0


@pytest.mark.asyncio
async def test_body_weight_normal_passes_guard(monkeypatch):
    """A normal weight reading near current_weight_kg writes through.

    The remote commit c356842 expanded log_body_weight's tool result with
    delta/trend/goal/context coaching context, which requires a real DB call
    to get_recent_weights — stub it here so this guard test stays pure."""
    from handlers import tool_executor as TE

    user = SimpleNamespace(id=1, current_weight_kg=80.0, goal_weight_kg=75.0)
    today_log = SimpleNamespace(id=1)

    written = []

    async def _capture(db, uid, kg, context=None, when=None):
        written.append((uid, kg, context))
        return SimpleNamespace(id=42, weight_kg=kg)

    async def _no_recent(db, uid, days=14):
        return []

    monkeypatch.setattr(TE, "add_body_metric", _capture)
    monkeypatch.setattr(TE, "get_recent_weights", _no_recent)

    result = await TE._dispatch(
        "log_body_weight",
        {"weight": 79.2, "unit": "kg"},
        user, today_log, db=None, source_type="text",
    )
    # The expanded tool result begins with "Logged body weight: …" — verify
    # the sane reading made it through the guard and got the new coaching wrap.
    assert "Logged body weight" in result
    assert len(written) == 1


# ── Change 14 ───────────────────────────────────────────────────────────────
def test_sarcastic_ack_after_mechanics_leak():
    from core.turn_health import detect_sarcastic_ack
    assert detect_sarcastic_ack(
        "Great",
        "Updated totals are resynced for you."
    ) is True


def test_sarcastic_ack_after_generic_net_fallback():
    from core.turn_health import detect_sarcastic_ack
    # The "Got that. / You're at 200 / 2126 calories today." screenshot pattern.
    assert detect_sarcastic_ack(
        "Great",
        "Got that.|||You're at 200 / 2126 calories today."
    ) is True


def test_sarcastic_ack_genuine_praise_does_not_match():
    from core.turn_health import detect_sarcastic_ack
    # Same word, but the prior reply was real coaching — not sarcasm.
    assert detect_sarcastic_ack(
        "Great",
        "Solid macro split. Protein landed at 165g — keep that anchor tomorrow."
    ) is False
    # Long enthusiastic message — clearly not sarcastic frustration either.
    assert detect_sarcastic_ack(
        "Great, thanks so much for the breakdown!",
        "Got that.|||You're at 200 / 2126 calories today."
    ) is False


def test_sarcastic_ack_handles_empty_inputs():
    from core.turn_health import detect_sarcastic_ack
    assert detect_sarcastic_ack("", "anything") is False
    assert detect_sarcastic_ack("Great", "") is False


# ── Change 6 ────────────────────────────────────────────────────────────────
def test_looks_branded_catches_real_brand_text_mentions():
    from handlers.tool_executor import _looks_branded
    # The exact screenshot brand — ProperNoun cluster + package noun
    assert _looks_branded("Elmhurst Clean Protein Sea Salt Chocolate shake") is True
    assert _looks_branded("Quest Birthday Cake bar") is True
    assert _looks_branded("Oikos Triple Zero yogurt") is True


def test_looks_branded_ignores_generic_foods():
    from handlers.tool_executor import _looks_branded
    assert _looks_branded("chicken breast") is False
    assert _looks_branded("white rice") is False
    assert _looks_branded("scrambled eggs") is False
    assert _looks_branded("grilled salmon") is False


def test_looks_branded_ignores_empty_or_short():
    from handlers.tool_executor import _looks_branded
    assert _looks_branded("") is False
    assert _looks_branded(None) is False
    assert _looks_branded("rice") is False
