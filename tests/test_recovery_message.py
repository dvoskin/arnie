"""
Recovery messages — short user-facing fallback lines for failure / dead-end
paths. Pin the contract so a future refactor can't silently drop the safety
net (the user staring at silent dead-air is the failure mode this prevents).

Coverage:
  • every kind returns a non-empty multi-bubble line
  • every variant contains a concrete recovery action ("resend"/"again"/"send")
  • no em dashes (no-em-dash voice rule)
  • no banned helpdesk phrases ("one moment", "please try again later")
  • deterministic — same (kind, seed) always returns the same line
  • variance across seeds — different seeds sometimes pick different variants
  • unknown kind falls back to 'stall' (typo-safe)
  • run_turn LLM-exception path uses recovery_message("llm_error")
  • run_turn no-text/no-tool-calls fallback uses recovery_message("stall")
"""
import pytest

from handlers.tool_executor import recovery_message, _RECOVERY_BUBBLES


_ALL_KINDS = list(_RECOVERY_BUBBLES.keys())


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_every_kind_returns_nonempty_multibubble(kind):
    """Each recovery line is 2+ bubbles (|||-split) — the first acknowledges
    the snag, the second tells the user what to send. Single-bubble would
    skip the recovery action and feel like a dead-end."""
    line = recovery_message(kind, seed="some user text")
    assert line and line.strip(), f"{kind}: empty line"
    assert "|||" in line, f"{kind}: missing |||-split (needs ack + recovery action)"


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_every_variant_contains_recovery_action(kind):
    """Every variant of every kind MUST tell the user what to send. Without
    a concrete action ("resend", "send it again", "try one more time"), the
    user is left guessing — the retention failure this is supposed to fix."""
    for variant in _RECOVERY_BUBBLES[kind]:
        lower = variant.lower()
        has_action = any(
            kw in lower for kw in ("resend", "send it", "send that", "try", "say it")
        )
        assert has_action, (
            f"{kind} variant missing a recovery action: {variant!r}. "
            f"Must tell user what to send ('resend', 'try again', 'say it again')."
        )


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_no_em_dashes_in_any_variant(kind):
    """Em dashes are banned in Arnie's voice. Recovery messages are still
    voice-bound — use period/comma instead."""
    for variant in _RECOVERY_BUBBLES[kind]:
        assert "—" not in variant, (
            f"{kind} variant contains em dash: {variant!r} — use comma/period"
        )


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_no_banned_helpdesk_phrases(kind):
    """Recovery messages must NOT read as a help-desk script. Specific
    bans: 'please', 'one moment', 'try again later', 'we apologize',
    'sorry for the inconvenience'. The voice is a coach saying 'send it
    again', not a customer-service bot."""
    banned = (
        "please",
        "one moment",
        "try again later",
        "we apologize",
        "sorry for the inconvenience",
        "kindly",
    )
    for variant in _RECOVERY_BUBBLES[kind]:
        lower = variant.lower()
        for phrase in banned:
            assert phrase not in lower, (
                f"{kind} variant contains helpdesk phrase {phrase!r}: {variant!r}"
            )


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_deterministic_for_same_seed(kind):
    """Same (kind, seed) must always return the same line — resume-safe,
    cache-friendly, and prevents flaky tests."""
    a = recovery_message(kind, seed="user msg A")
    b = recovery_message(kind, seed="user msg A")
    assert a == b


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_variance_across_seeds(kind):
    """Different seeds should at least sometimes land on different variants
    (so two consecutive failures with different user input don't always emit
    the same line). Walk a span of seed lengths and confirm the pool gets
    hit more than once."""
    seen = set()
    for n in range(0, 30):
        seen.add(recovery_message(kind, seed="x" * n))
    assert len(seen) >= 2, (
        f"{kind}: same line for all seed lengths — index isn't spreading "
        f"across variants. Pool: {_RECOVERY_BUBBLES[kind]}"
    )


def test_unknown_kind_falls_back_to_stall():
    """Defensive: a typo'd kind ('stalll', 'llm-error') must NOT return
    empty — fall back to the 'stall' pool so the user always gets a real
    line."""
    line = recovery_message("not_a_real_kind", seed="x")
    assert line and "|||" in line
    # Specifically should be one of the stall variants (not silently empty
    # or generic).
    assert line in _RECOVERY_BUBBLES["stall"]


def test_empty_seed_does_not_crash():
    """Empty / None seed must still return a real line — None-safe."""
    assert recovery_message("stall", seed="") in _RECOVERY_BUBBLES["stall"]
    assert recovery_message("stall", seed=None) in _RECOVERY_BUBBLES["stall"]


def test_every_kind_has_at_least_three_variants():
    """Variance only helps if the pool is big enough. Pin >=3 per kind so
    a refactor can't silently shrink the pool to a single line."""
    for kind, pool in _RECOVERY_BUBBLES.items():
        assert len(pool) >= 3, f"{kind}: pool shrunk to {len(pool)} variants"


# ── Pipeline integration: the failure paths actually USE recovery_message ──


@pytest.mark.asyncio
async def test_llm_exception_path_uses_recovery_message(monkeypatch, make_user, db):
    """run_turn's chat() exception handler must return a recovery_message
    line, not a hardcoded 'try again later' string. Pin so a refactor can't
    silently regress to dead-air."""
    import core.conversation as C

    user = await make_user(telegram_id="recov-llm")

    async def _boom(messages, system, tools=True, max_tokens=4096, model=None,
                    stream_handler=None):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(C, "chat", _boom)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "had a banana"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
    )

    body = " ".join(result.response.bubbles)
    # Must be one of the llm_error variants — not an old hardcoded string.
    assert body in [v.replace("|||", " ") for v in _RECOVERY_BUBBLES["llm_error"]] \
        or any(part in body for part in
               sum([v.split("|||") for v in _RECOVERY_BUBBLES["llm_error"]], [])), (
        f"LLM-exception path didn't return a recovery_message variant: {body!r}"
    )
    # Must contain a recovery action keyword (defense in depth).
    assert any(kw in body.lower() for kw in ("resend", "send it", "again", "back")), (
        f"LLM-exception reply missing recovery action: {body!r}"
    )


@pytest.mark.asyncio
async def test_stall_fallback_uses_recovery_message(monkeypatch, make_user, db):
    """When the model produces NO text AND NO tool calls, run_turn's
    terminal fallback must return a recovery_message('stall') line, not
    the legacy 'Still here. What's the move?' generic keep-alive. The
    user needs to know Arnie's confused and what to send."""
    import core.conversation as C

    user = await make_user(telegram_id="recov-stall")

    async def _empty_chat(messages, system, tools=True, max_tokens=4096, model=None,
                           stream_handler=None):
        return {
            "text": "",
            "tool_calls": [],
            "raw_content": [],
            "stop_reason": "end_turn",
        }

    monkeypatch.setattr(C, "chat", _empty_chat)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "asdfqwerty"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
    )

    body = " ".join(result.response.bubbles)
    # Must contain a recovery action keyword.
    assert any(kw in body.lower() for kw in ("resend", "send it", "say it", "try")), (
        f"Stall fallback missing recovery action: {body!r}"
    )
    # Must NOT be the legacy generic keep-alive.
    assert "What's the move" not in body, (
        f"Stall fallback regressed to legacy 'Still here. What's the move?': {body!r}"
    )
