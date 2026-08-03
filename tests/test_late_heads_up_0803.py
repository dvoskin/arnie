"""Second-tier heads-up (P1 felt-latency): the "still on it, here's what's taking
the time" line a turn adds when it is still running ~6s in — like Claude narrating
a long step. These cover the pure pieces: message selection, variety, honesty
(no invented numbers), the enable/delay config, and that it never echoes tier-1.

The timer WIRING (schedule on first heads-up, self-guard on `_reply_ready`) lives
inside run_turn and is exercised by the food-turn suite; here we pin the contract
of what it would say and when it is allowed to.
"""
import re
import pytest

import handlers.tool_executor as T
from handlers.tool_executor import (
    deep_food_heads_up, late_heads_up_enabled, late_heads_up_delay_s,
    tool_heads_up, FOOD_LOOKUP_HEADS_UP,
    _FOOD_DEEP_TEMPLATES, _FOOD_DEEP_TEMPLATES_BRANDED, _FOOD_DEEP_BUBBLES,
)
from core.voice import check_voice, render_bubble, V


def test_names_the_food_when_it_has_one():
    line = deep_food_heads_up("skirt steak", seed="had a skirt steak")
    assert "skirt steak" in line.lower()
    assert line.strip()


def test_branded_uses_label_wording_and_keeps_case():
    line = deep_food_heads_up("Barebells bar", seed="ate a barebells")
    assert "Barebells" in line  # brand case preserved, not lowercased


def test_neutral_pool_when_no_usable_subject():
    line = deep_food_heads_up(None, seed="big lunch plate")
    assert line.strip() and "{food}" not in line


def test_never_echoes_the_first_tier_line():
    """Same food+seed must not draw an identical line 1 and line 2 — a repeat
    reads as the lane stuttering, not as progress."""
    for msg, food in [("had a skirt steak", "skirt steak"),
                      ("2 eggs and rice", "eggs"),
                      ("chocolate croissant", "chocolate croissant")]:
        first = tool_heads_up(FOOD_LOOKUP_HEADS_UP, msg, subject=food)
        second = deep_food_heads_up(food, seed=msg)
        assert first != second, (first, second)


def test_deterministic():
    assert deep_food_heads_up("oatmeal", "x") == deep_food_heads_up("oatmeal", "x")


def test_enough_variety_to_go_unnoticed():
    """Danny's bar: a user who logs often must not see the same line twice in a
    row. >=8 per pool, >=24 distinct lines across pools."""
    assert len(_FOOD_DEEP_TEMPLATES) >= 8
    assert len(_FOOD_DEEP_TEMPLATES_BRANDED) >= 8
    assert len(_FOOD_DEEP_BUBBLES) >= 8
    allpools = set(_FOOD_DEEP_TEMPLATES) | set(_FOOD_DEEP_TEMPLATES_BRANDED) | set(_FOOD_DEEP_BUBBLES)
    assert len(allpools) >= 24


def test_no_em_dash_at_source():
    """Danny 2026-08-03: the em dash is off-voice. Author the pool without it —
    the seam would fix it, but the corpus itself must read as Arnie."""
    for tpl in (_FOOD_DEEP_TEMPLATES + _FOOD_DEEP_TEMPLATES_BRANDED + _FOOD_DEEP_BUBBLES):
        assert "—" not in tpl and "–" not in tpl, tpl


def test_wire_output_is_fully_in_voice():
    """What the client actually receives (after the send seam) has zero voice
    violations for any food, branded or not, subject or none."""
    for food in ("skirt steak", "Barebells bar", "chicken shawarma bowl", None):
        line = render_bubble(deep_food_heads_up(food, seed="lunch"))
        assert check_voice(line) == [], (food, line, [str(v) for v in check_voice(line)])


def test_no_invented_numbers():
    """A progress line must never state a macro or a digit — it has no committed
    number yet, and a guessed one would read as the answer."""
    for tpl in (_FOOD_DEEP_TEMPLATES + _FOOD_DEEP_TEMPLATES_BRANDED + _FOOD_DEEP_BUBBLES):
        assert not re.search(r"\d", tpl), tpl


def test_reads_as_a_sentence_not_a_fragment():
    for tpl in (_FOOD_DEEP_TEMPLATES + _FOOD_DEEP_TEMPLATES_BRANDED + _FOOD_DEEP_BUBBLES):
        words = len(tpl.split())
        assert 5 <= words <= 22, (words, tpl)
        assert tpl.rstrip().endswith((".", "!"))


def test_enabled_default_and_kill_switch(monkeypatch):
    monkeypatch.delenv("FOOD_LATE_HEADSUP", raising=False)
    assert late_heads_up_enabled() is True
    monkeypatch.setenv("FOOD_LATE_HEADSUP", "false")
    assert late_heads_up_enabled() is False
    monkeypatch.setenv("FOOD_LATE_HEADSUP", "on")
    assert late_heads_up_enabled() is True


def test_delay_default_and_override(monkeypatch):
    monkeypatch.delenv("FOOD_LATE_HEADSUP_DELAY_S", raising=False)
    assert late_heads_up_delay_s() == pytest.approx(3.5)
    monkeypatch.setenv("FOOD_LATE_HEADSUP_DELAY_S", "5")
    assert late_heads_up_delay_s() == pytest.approx(5.0)
    # A garbage value falls back rather than crashing the reply path.
    monkeypatch.setenv("FOOD_LATE_HEADSUP_DELAY_S", "nonsense")
    assert late_heads_up_delay_s() == pytest.approx(3.5)
    # Never fires instantly on top of the first line.
    monkeypatch.setenv("FOOD_LATE_HEADSUP_DELAY_S", "0")
    assert late_heads_up_delay_s() >= 0.5
