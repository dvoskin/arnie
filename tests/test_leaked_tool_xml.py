"""Leaked tool-call XML — never ship it, recover the log from it (Denys #7129)."""
from core.platform import _strip_tool_xml, _sanitize_bubble
from core.turn_health import (
    has_leaked_tool_xml, extract_leaked_tool_calls,
)

LEAK = ('Рис отварной logged. <invoke name="log_food"> '
        '<parameter name="food_name">Огурец</parameter> '
        '<parameter name="calories">10</parameter> </invoke>')
TRUNC = 'Рис <invoke name="log_food"> <parameter name="food_name">Огур'


def test_detects_leak():
    assert has_leaked_tool_xml(LEAK)
    assert has_leaked_tool_xml(TRUNC)
    assert not has_leaked_tool_xml("just a normal reply, 300 calories logged")


def test_strip_removes_all_markup():
    out = _strip_tool_xml(LEAK)
    assert "<invoke" not in out and "<parameter" not in out and "</invoke>" not in out
    assert "Рис отварной logged." in out
    # truncated fragment fully removed too
    tout = _strip_tool_xml(TRUNC)
    assert "<invoke" not in tout and "<parameter" not in tout
    assert tout.strip().startswith("Рис")


def test_sanitize_bubble_strips_xml():
    assert "<invoke" not in _sanitize_bubble(LEAK)


def test_recover_tool_calls():
    calls = extract_leaked_tool_calls(LEAK)
    assert len(calls) == 1
    assert calls[0]["name"] == "log_food"
    assert calls[0]["input"]["food_name"] == "Огурец"
    assert calls[0]["input"]["calories"] == 10  # coerced to int


def test_truncated_block_not_parsed():
    # A truncated (unclosed) invoke can't be trusted → no recovered call.
    assert extract_leaked_tool_calls(TRUNC) == []


def test_clean_text_untouched():
    s = "chicken logged, 300 calories. you're at 1,200 / 2,000."
    assert _strip_tool_xml(s) == s
