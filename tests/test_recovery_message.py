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
  • the RENDER floor (Response.from_text with nothing to render) uses the pool
    too, instead of its own legacy line
  • the replay guard's signatures are DERIVED from the pool, so a reworded
    bubble cannot silently stop being recognized as an error reply
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


# ── The render floor: one stall reply in the product, not two ────────────────
#
# `Response.from_text` is the last thing between a turn and the user, and it had
# its own fallback for an empty reply: `"still here. what's the move?"`. Every
# net above it (core/conversation, core/turns) already answers a stall from the
# approved pool, so that line only ever shipped when all of them were missed —
# from the render layer, below every check that reads a reply, in lowercase, in
# words no one had approved.


def test_the_render_floor_uses_the_approved_pool():
    """A Response with nothing to render still answers, in the approved words."""
    from core.platform import Response

    for empty in ("", None, "|||", "   |||  "):
        bubbles = Response.from_text(empty).bubbles
        assert bubbles, f"render floor produced no bubbles for {empty!r}"
        assert " ".join(bubbles) in [v.replace("|||", " ")
                                     for v in _RECOVERY_BUBBLES["stall"]], (
            f"render floor invented its own line for {empty!r}: {bubbles!r}")


def test_the_render_floor_is_not_the_legacy_line():
    """The specific regression: the lowercase keep-alive is gone for good."""
    from core.platform import Response

    body = " ".join(Response.from_text("").bubbles)
    assert "still here" not in body.lower(), (
        f"render floor regressed to the legacy keep-alive: {body!r}")
    # It was the last in-code lowercase leak the foundation audit listed. A
    # recovery line is sentence case like every other thing Arnie says.
    assert body[:1] == body[:1].upper(), f"render floor line is lowercase: {body!r}"


def test_a_turn_with_no_response_at_all_lands_on_the_floor():
    """The coordinator's own path to it: a native turn that produced no
    response is rendered through `from_text("")` (core/turns/entrypoint), which
    is exactly the case the floor exists for."""
    from core.platform import Response

    assert Response.from_text("").bubbles == Response.from_text(None).bubbles


# ── The replay guard reads the same pool it is guarding ──────────────────────
#
# `core/chat_service` must never collapse an idempotent resend onto an errored
# turn — a resend-after-error has to actually retry. It decided that by matching
# a hand-copied fragment of each bubble, which is a copy that drifts: it carried
# the render floor's private line, which was never a recovery bubble at all.


@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_every_bubble_is_recognized_as_an_error_reply(kind):
    """Every line the pool can emit must be recognized when it comes back as a
    stored reply. This is the property the hand-copied list only happened to
    have."""
    from core.recovery import is_recovery_text

    for variant in _RECOVERY_BUBBLES[kind]:
        # Stored exactly as chat_service persists it: the sanitized bubbles,
        # |||-joined. Nothing in the pool is altered by sanitizing.
        from core.platform import Response
        stored = "|||".join(Response.from_text(variant).bubbles)
        assert is_recovery_text(stored), (
            f"{kind} variant not recognized as an error reply: {stored!r}")


def test_an_ordinary_reply_is_not_an_error_reply():
    """The other half: a real coaching reply must stay replayable, or a
    double-tap re-runs the turn and double-writes the log."""
    from core.recovery import is_recovery_text

    for ordinary in ("Here's the deep dive.",
                     "Shrugs 3×14,14,15 logged.|||What weight on rows?",
                     "Lunch logged, 620 cal.|||Nice work.",
                     "You're at 1,240/2,165 cal.|||Protein's the gap."):
        assert not is_recovery_text(ordinary), (
            f"ordinary reply misread as a recovery bubble: {ordinary!r}")


def test_the_signatures_are_derived_not_transcribed():
    """The guarantee itself: every signature traces to a bubble in the pool,
    and every bubble contributes one. A transcribed list can hold a string no
    bubble produces (it did) and can miss one that a bubble does."""
    from core.recovery import RECOVERY_SIGNATURES

    heads = {v.split("|||", 1)[0].strip().lower()
             for pool in _RECOVERY_BUBBLES.values() for v in pool}
    assert RECOVERY_SIGNATURES == heads
    assert "still here. what's the move" not in RECOVERY_SIGNATURES
