"""Onboarding completion gate."""
from types import SimpleNamespace
from handlers.onboarding import is_onboarding_complete, _ESSENTIAL


def _user(**kw):
    base = {f: "x" for f in _ESSENTIAL}
    base["current_weight_kg"] = 80
    base.update(kw)
    return SimpleNamespace(**base)


def test_complete_when_all_essentials_present():
    assert is_onboarding_complete(_user()) is True


def test_incomplete_when_any_missing():
    for field in _ESSENTIAL:
        u = _user(**{field: None})
        assert is_onboarding_complete(u) is False, f"missing {field} should be incomplete"


def test_city_is_an_essential():
    # this session made city required for the timezone/reminder flow
    assert "city" in _ESSENTIAL
