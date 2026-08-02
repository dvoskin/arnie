"""Per-user gate for NUTRITION_ACCURACY_V2 (canary, 0802).

Global flag => everyone (evals unchanged); allowlist => named users only, scoped
to the ambient turn user; nothing set => off. Outside a turn only the global flag
applies.
"""
import pytest

from skills.nutrition import v2_gate


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("NUTRITION_ACCURACY_V2", raising=False)
    monkeypatch.delenv("NUTRITION_ACCURACY_V2_ALLOWLIST", raising=False)


def test_off_by_default():
    assert v2_gate.v2_active() is False
    assert v2_gate.cohort_label() == "off"


def test_global_flag_is_on_for_everyone(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "true")
    assert v2_gate.v2_active() is True            # no user bound -> still on
    with v2_gate.for_user(999):
        assert v2_gate.v2_active() is True
    assert v2_gate.cohort_label() == "global"


def test_allowlisted_user_is_on_only_inside_their_turn(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")
    assert v2_gate.cohort_label() == "allowlist"
    assert v2_gate.v2_active() is False           # no user bound (e.g. eval)
    with v2_gate.for_user(26):
        assert v2_gate.v2_active() is True
    with v2_gate.for_user(99):
        assert v2_gate.v2_active() is False
    assert v2_gate.v2_active() is False           # reset after the turn


def test_global_flag_wins_over_an_empty_or_present_allowlist(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2", "1")
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")
    with v2_gate.for_user(99):
        assert v2_gate.v2_active() is True        # global on -> everyone


def test_allowlist_parses_a_csv_and_ignores_junk(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", " 26 , 40 ,x, ")
    with v2_gate.for_user(40):
        assert v2_gate.v2_active() is True
    with v2_gate.for_user(7):
        assert v2_gate.v2_active() is False


def test_for_user_handles_none_and_bad_values(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")
    with v2_gate.for_user(None):
        assert v2_gate.v2_active() is False
    with v2_gate.for_user("not-an-int"):
        assert v2_gate.v2_active() is False


def test_nested_for_user_restores_the_outer_binding(monkeypatch):
    monkeypatch.setenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "26")
    with v2_gate.for_user(26):
        assert v2_gate.v2_active() is True
        with v2_gate.for_user(99):
            assert v2_gate.v2_active() is False
        assert v2_gate.v2_active() is True        # outer 26 restored
