"""The composer has to be reachable before an env var can turn it on.

`compose_async` was built, validated, tested — and called from nowhere.
`composer_enabled()` had no reference outside its own definition and the test
that asserts the env var parses. Setting FOOD_COMPOSER=true did nothing at all,
which is why "the openers are repetitive, maybe it needs the LLM" had no switch
to flip.
"""
import inspect
import re

import core.conversation as C
import core.food_response as FR


def test_the_commit_render_can_reach_the_composer():
    src = inspect.getsource(C)
    assert "compose_async" in src, (
        "the composer must be called from the render path, not just defined")
    assert "composer_enabled()" in src, "and gated on the switch"


def test_a_composer_failure_falls_back_to_the_deterministic_text():
    """The floor is the previous behaviour. Every path out of compose_async
    that is not `ok` returns `fallback(plan)`."""
    src = inspect.getsource(FR.compose_async)
    assert "return fallback(plan), last.reason" in src


def test_the_composer_output_is_validated_before_it_ships():
    src = inspect.getsource(FR.compose_async)
    assert "validate(text, plan)" in src
    assert "attempts" in src, "and retried once with the failure reason"


def test_the_switch_still_defaults_off(monkeypatch):
    monkeypatch.delenv("FOOD_COMPOSER", raising=False)
    assert not FR.composer_enabled()
    monkeypatch.setenv("FOOD_COMPOSER", "true")
    assert FR.composer_enabled()


# ── formatting: three surfaces that disagree ─────────────────────────────────
def test_the_voice_contract_forbids_markdown():
    """Telegram sends HTML and escapes stray asterisks into literal text;
    iMessage strips them; only iOS renders them. A composer free to emit
    markdown produces a different bug on each surface, so it emits none and the
    caller supplies bullets."""
    assert "No markdown syntax" in FR.ARNIE_VOICE
    assert "asterisks" in FR.ARNIE_VOICE


def test_the_deterministic_list_uses_the_shared_bullet():
    """The one list character that survives all three adapters untouched."""
    from core.food_response import FoodItemSummary, format_items
    out = format_items([FoodItemSummary(name="toast", portion="1 slice")])
    assert out.startswith("• ")
    assert "*" not in out and "#" not in out
