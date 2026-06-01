"""Onboarding completion gate + derived stage (hybrid brain-dump model)."""
from types import SimpleNamespace
from handlers.onboarding import (
    is_onboarding_complete, onboarding_stage, build_onboarding_system, _ESSENTIAL,
)


def _user(**kw):
    """A user with all three essentials present by default."""
    base = dict(
        name="Danny", primary_goal="cut", current_weight_kg=86.0,
        # bonuses (absent by default) — must NOT affect completion
        goal_weight_kg=None, training_experience=None, city=None,
        height_cm=None, age=None, sex=None, onboarding_completed=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_essentials_are_the_minimal_three():
    assert _ESSENTIAL == ["name", "current_weight_kg", "primary_goal"]


def test_complete_when_three_essentials_present():
    assert is_onboarding_complete(_user()) is True


def test_incomplete_when_any_essential_missing():
    for field in _ESSENTIAL:
        u = _user(**{field: None})
        assert is_onboarding_complete(u) is False, f"missing {field} should be incomplete"


def test_bonuses_do_not_block_completion():
    # No training, city, height, age, or sex — still complete on the three essentials.
    u = _user(training_experience=None, city=None, height_cm=None, age=None, sex=None)
    assert is_onboarding_complete(u) is True


def test_stage_progression():
    assert onboarding_stage(_user(name=None, primary_goal=None, current_weight_kg=None)) == "intro_started"
    assert onboarding_stage(_user(primary_goal=None, current_weight_kg=None)) == "name_collected"
    assert onboarding_stage(_user(current_weight_kg=None)) == "goal_collected"
    assert onboarding_stage(_user()) == "essentials_collected"
    assert onboarding_stage(_user(onboarding_completed=True)) == "onboarding_complete"


# ── build_onboarding_system: no re-asking, brain-dump next move ────────────────

def test_prompt_surfaces_known_fields_so_they_are_not_reasked():
    # name + goal known, weight missing, plus two bonuses already given
    u = _user(current_weight_kg=None, training_experience="intermediate", city="NYC")
    sys = build_onboarding_system(u)
    assert "KNOWN ALREADY" in sys
    assert "Danny" in sys and "cut" in sys
    # bonuses are surfaced as known (so Arnie won't re-ask them) but never block
    assert "intermediate" in sys and "NYC" in sys
    # the one remaining essential is weight, and the next move is the brain dump
    assert "STILL NEEDED (essential): weight" in sys
    assert "brain dump" in sys.lower()


def test_prompt_all_essentials_drives_to_first_log():
    sys = build_onboarding_system(_user())
    assert "ALL ESSENTIALS IN" in sys
    assert "STILL NEEDED" not in sys


def test_prompt_example_bubbles_have_no_em_dash():
    # The few-shot example outputs inside the prompt must model clean copy.
    sys = build_onboarding_system(_user(current_weight_kg=None))
    for line in sys.splitlines():
        if '"' in line and "|||" in line:        # a quoted multi-bubble example
            assert "—" not in line, f"em dash in example bubble: {line}"
