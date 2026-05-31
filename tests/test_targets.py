"""Mifflin-St Jeor target calculation."""
from types import SimpleNamespace
from core.targets import calc_targets


def _user(**kw):
    base = dict(current_weight_kg=80, height_cm=180, age=30, sex="male",
                primary_goal="maintain", training_experience="intermediate")
    base.update(kw)
    return SimpleNamespace(**base)


def test_returns_none_when_stats_missing():
    assert calc_targets(_user(height_cm=None)) is None
    assert calc_targets(_user(age=None)) is None
    assert calc_targets(_user(sex=None)) is None


def test_maintain_targets_reasonable():
    t = calc_targets(_user(primary_goal="maintain"))
    assert t is not None
    # BMR ~1780, x1.55 TDEE ~2759 -> maintain calories in a sane band
    assert 2400 <= t["calories"] <= 3100
    assert t["protein"] > 100
    assert t["goal"] == "maintain"


def test_cut_is_below_maintain_and_bulk_above():
    maint = calc_targets(_user(primary_goal="maintain"))["calories"]
    cut = calc_targets(_user(primary_goal="cut"))["calories"]
    bulk = calc_targets(_user(primary_goal="bulk"))["calories"]
    assert cut < maint < bulk
    assert maint - cut == 500  # 500 kcal deficit


def test_sex_changes_bmr():
    m = calc_targets(_user(sex="male"))["calories"]
    f = calc_targets(_user(sex="female"))["calories"]
    assert m > f  # male BMR constant is +5 vs -161
