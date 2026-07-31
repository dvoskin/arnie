"""A config value the code does not recognise must be visible.

The six-day gap, exactly: on 2026-07-31 the deployed `NUTRITION_RESOLVER_MODE`
was `true`. The parser accepts `off | shadow | live` and silently returns its
default for anything else, so production ran in SHADOW while `render.yaml`
recorded — in a comment naming a person and a date — that the resolver had
been live for all users since 07-25.

Nothing failed. Nothing logged. `/health` reported `env_set: true`, which was
true and useless: the var WAS set, to a word nothing had ever heard of.

`TURN_COORDINATOR_MODE` has the same `else <default>` shape, so these tests
cover the pattern rather than the one flag that happened to be wrong.
"""
import logging

import pytest

from core import config_guard


# ── the exact production value that caused it ────────────────────────────────


def test_the_value_that_cost_six_days_is_reported_invalid(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "true")

    bad = config_guard.invalid()

    names = [b.name for b in bad]
    assert "NUTRITION_RESOLVER_MODE" in names, (
        "`true` is not one of off|shadow|live — it must be reported as ignored"
    )
    entry = next(b for b in bad if b.name == "NUTRITION_RESOLVER_MODE")
    assert entry.falls_back_to == "shadow", (
        "the report must name what is ACTUALLY running, which is the whole "
        "question the six-day gap could not answer"
    )


def test_it_says_so_out_loud(monkeypatch, caplog):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "true")

    with caplog.at_level(logging.ERROR):
        config_guard.report()

    lines = [r.getMessage() for r in caplog.records
             if "event=config_invalid" in r.getMessage()]
    assert len(lines) == 1
    assert "NUTRITION_RESOLVER_MODE" in lines[0]
    assert "off|shadow|live" in lines[0]
    assert "effective=shadow" in lines[0]


def test_the_raw_value_is_never_echoed(monkeypatch, caplog):
    """Arbitrary environment content does not belong in a log line — a typo
    puts whatever was actually typed into it, and these logs are not private."""
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "sk-secret-looking-thing")

    with caplog.at_level(logging.ERROR):
        config_guard.report()

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "sk-secret-looking-thing" not in joined


# ── the states that are NOT failures ─────────────────────────────────────────


@pytest.mark.parametrize("value", ["off", "shadow", "live", "LIVE", " live "])
def test_a_recognised_value_is_not_reported(monkeypatch, value):
    """Case and whitespace are tolerated by the parser, so they must be
    tolerated here too — a guard stricter than the thing it guards would
    report failures that do not exist."""
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", value)
    assert [b.name for b in config_guard.invalid()] == []


def test_an_unset_flag_is_not_invalid(monkeypatch):
    """Unset is defaulted, which is a deliberate state. The failure being
    caught is the one that LOOKS configured."""
    monkeypatch.delenv("NUTRITION_RESOLVER_MODE", raising=False)
    monkeypatch.delenv("TURN_COORDINATOR_MODE", raising=False)
    assert config_guard.invalid() == []


# ── the same shape, on the other flag ────────────────────────────────────────


def test_the_coordinator_flag_is_covered_too(monkeypatch):
    """`TURN_COORDINATOR_MODE` ends `else MODE_LEGACY_ONLY`. A typo there runs
    the legacy path and the only symptom is an improvement that never
    arrives."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new-observe")   # hyphen, not _

    bad = [b for b in config_guard.invalid()
           if b.name == "TURN_COORDINATOR_MODE"]
    assert bad, "a near-miss typo must not pass silently"
    assert bad[0].falls_back_to == "legacy_only"


def test_every_registered_flag_names_a_reachable_fallback():
    """The registry claims what each flag becomes when ignored. If that claim
    is wrong the report misleads, which is worse than not reporting."""
    for name, flag in config_guard.ENUM_FLAGS.items():
        assert flag.falls_back_to in flag.allowed, (
            f"{name} claims to fall back to {flag.falls_back_to!r}, which is "
            f"not one of its own allowed values {flag.allowed}"
        )


# ── it reaches the outside ───────────────────────────────────────────────────


def test_health_reports_env_valid(monkeypatch):
    """The six-day gap was only ever visible from OUTSIDE the container."""
    from api.diagnostics import public_pipeline_summary

    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "true")
    entry = public_pipeline_summary().get("NUTRITION_RESOLVER_MODE", {})

    assert entry.get("env_set") is True, "the var IS set — that was never in doubt"
    assert entry.get("env_valid") is False, (
        "env_set alone said 'configured' about a value being ignored; "
        "env_valid is the field that tells the truth"
    )


def test_env_valid_is_absent_for_a_non_enum_flag(monkeypatch):
    """`FOOD_COMPOSER` is a boolean, not an enumeration. Reporting it as valid
    would imply a check that is not happening."""
    from api.diagnostics import public_pipeline_summary

    entry = public_pipeline_summary().get("FOOD_COMPOSER", {})
    assert "env_valid" not in entry
