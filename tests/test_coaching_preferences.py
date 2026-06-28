"""The user-chosen coaching preferences must actually shape the prompt, not sit
as inert labels. Covers coaching_style / accountability_level / response_length
rendering as behavioral directives, and the pacing_enabled toggle gating the
[PACING] nudge."""
from types import SimpleNamespace

from core.context_builder import fmt_profile, pacing_note


def _prefs(**kw):
    base = dict(
        coaching_style="balanced", accountability_level="medium",
        preferred_response_length="medium", pacing_enabled=True,
        calorie_target=2200, protein_target=180, carb_target=200, fat_target=70,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _user():
    return SimpleNamespace(
        name="Danny", age=33, sex="M", height_cm=180, current_weight_kg=85,
        goal_weight_kg=80, primary_goal="recomp", training_experience="advanced",
        dietary_preferences="high protein", injuries=None,
    )


def test_prefs_render_as_behavioral_directives_not_bare_labels():
    s = fmt_profile(_user(), _prefs(coaching_style="strict",
                                    accountability_level="high",
                                    preferred_response_length="short"))
    # each pref turns into an actionable directive the model can follow
    assert "Coaching style STRICT" in s and "direct and demanding" in s
    assert "Accountability HIGH" in s and "hold them to it" in s
    assert "Response length SHORT" in s and "1-2 tight sentences" in s
    assert "honor them every reply" in s


def test_supportive_and_long_variants():
    s = fmt_profile(_user(), _prefs(coaching_style="supportive",
                                    preferred_response_length="long"))
    assert "Coaching style SUPPORTIVE" in s and "gentle" in s
    assert "Response length LONG" in s


def test_unknown_pref_value_falls_back_to_balanced_default():
    s = fmt_profile(_user(), _prefs(coaching_style="banana"))
    assert "Coaching style BALANCED" in s


def test_pacing_note_suppressed_when_pacing_disabled():
    log = SimpleNamespace(total_calories=1200, total_protein=90)
    # enabled → a pacing note is produced
    assert pacing_note(log, _prefs(pacing_enabled=True), "UTC") != ""
    # disabled → no pacing nudge injected at all
    assert pacing_note(log, _prefs(pacing_enabled=False), "UTC") == ""
