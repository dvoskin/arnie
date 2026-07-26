"""The food-pipeline block of /api/v1/debug/me.

The block exists to answer one question that repo state cannot: which pipeline
is the DEPLOYED process actually running. Every flag it reports has a code
default that differs from what render.yaml declares, so "the config file says
live" and "the process is running live" are independent facts.

The tests that matter are therefore about the distinction between a flag that
is UNSET and one deliberately SET to its own default — identical behaviour,
opposite fixes — and about the effective value being resolved through the real
accessor rather than re-read here.
"""
from api.diagnostics import _food_pipeline, public_pipeline_summary


def test_unset_flags_report_the_code_default_as_effective(monkeypatch):
    """Nothing set: the block must show what the process really does, which is
    NOT what render.yaml declares."""
    monkeypatch.delenv("TURN_COORDINATOR_MODE", raising=False)
    monkeypatch.delenv("NUTRITION_RESOLVER_MODE", raising=False)
    monkeypatch.delenv("NUTRITION_RESOLVER_SHADOW", raising=False)
    monkeypatch.delenv("FOOD_COMPOSER", raising=False)

    block = _food_pipeline()

    assert block["TURN_COORDINATOR_MODE"]["effective"] == "legacy_only"
    assert block["NUTRITION_RESOLVER_MODE"]["effective"] == "shadow"
    assert block["FOOD_COMPOSER"]["effective"] is False


def test_unset_is_distinguishable_from_set_to_the_same_value(monkeypatch):
    """The whole point of the block. `shadow` by default and `shadow` because
    someone typed it behave identically and need opposite fixes: one is a
    broken deploy, the other is a deliberate setting."""
    monkeypatch.delenv("NUTRITION_RESOLVER_MODE", raising=False)
    monkeypatch.delenv("NUTRITION_RESOLVER_SHADOW", raising=False)
    unset = _food_pipeline()["NUTRITION_RESOLVER_MODE"]

    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "shadow")
    explicit = _food_pipeline()["NUTRITION_RESOLVER_MODE"]

    assert unset["effective"] == explicit["effective"] == "shadow"
    assert unset["env_set"] is False and unset["env_raw"] is None
    assert explicit["env_set"] is True and explicit["env_raw"] == "shadow"


def test_effective_tracks_the_real_accessor(monkeypatch):
    """Resolved through the runtime's own accessors, so the diagnostic cannot
    drift from the behaviour it describes."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "live")
    monkeypatch.setenv("FOOD_COMPOSER", "true")

    block = _food_pipeline()

    assert block["TURN_COORDINATOR_MODE"]["effective"] == "new_observe"
    assert block["NUTRITION_RESOLVER_MODE"]["effective"] == "live"
    assert block["FOOD_COMPOSER"]["effective"] is True


def test_an_unrecognised_mode_reports_what_the_code_falls_back_to(monkeypatch):
    """A typo'd value is the failure this block is most likely to catch: the
    accessor silently falls back, and only `env_raw` shows why."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observ")  # typo

    entry = _food_pipeline()["TURN_COORDINATOR_MODE"]

    assert entry["effective"] == "legacy_only"   # the silent fallback
    assert entry["env_raw"] == "new_observ"      # ...and the reason


def test_resolver_authority_is_reported_not_inferred_from_mode(monkeypatch):
    """Live mode is necessary but not sufficient — the canary cohort decides.
    This is also what gates `event=nutrition_promotion`, so a turn that emits
    no resolution telemetry is explained here rather than guessed at."""
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "shadow")
    assert _food_pipeline(user_id=1)["resolver_owns_committed_values"] is False


# ── the public (unauthenticated) summary on /health ───────────────────────────

def test_public_summary_keeps_effective_and_env_set(monkeypatch):
    """/health is the only check a deploy can run without a user token, so it
    has to answer the same question the authenticated block answers."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.delenv("FOOD_COMPOSER", raising=False)

    pub = public_pipeline_summary()

    assert pub["TURN_COORDINATOR_MODE"]["effective"] == "new_observe"
    assert pub["TURN_COORDINATOR_MODE"]["env_set"] is True
    assert pub["FOOD_COMPOSER"]["env_set"] is False


def test_public_summary_never_echoes_raw_env(monkeypatch):
    """A public endpoint must not reflect whatever was actually typed into an
    env var back to an unauthenticated caller."""
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "definitely-not-a-mode")

    pub = public_pipeline_summary()

    assert "env_raw" not in pub["TURN_COORDINATOR_MODE"]
    assert "definitely-not-a-mode" not in repr(pub)
    # ...while still reporting the silent fallback the container is running.
    assert pub["TURN_COORDINATOR_MODE"]["effective"] == "legacy_only"
