"""⛔⛔⛔ A DEPLOYMENT MANIFEST IS NOT THE AUTHORITY FOR RUNTIME CONFIGURATION.

`pin_config` compared the shell against `render.yaml`. On 2026-08-31 that was
shown to be structurally insufficient rather than merely stale:

```
render.yaml   TURN_COORDINATOR_MODE = new_observe
PRODUCTION    TURN_COORDINATOR_MODE = new_execute

ENTITY_RESOLUTION_MODE · ENTITY_RESOLUTION_CONSUME_ALLOWLIST ·
TURN_COORDINATOR_ALLOWLIST · NUTRITION_ACCURACY_V2 allowlist
    -> ABSENT FROM THE MANIFEST ENTIRELY
```

The drift check had therefore **never compared them**, and reported a clean pin
while they differed. A guard whose key list comes from a file can only check
what someone remembered to write down, so the same defect recurs under the next
flag.

⭐ AND THE ELIGIBILITY HALF IS THE ONE THAT DECIDES BEHAVIOUR.
`ENTITY_RESOLUTION_MODE=consume` is not "this turn consumes identity" —
`consume` + `allowlist=[26]` means user 26 does and nobody else does. That is
exactly why a local CF24 replay never reached the memory row: the synthetic
user was in no cohort, the identity never resolved, the lookup key never
matched, and the guarded door never ran. The harness looked correct and
measured a different product.

Every case below was executed as a mutation before being written down.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib

import pytest

from scripts.config_pin import (COHORT_KEYS, MEASUREMENT_CRITICAL, RuntimeDrift,
                                pin_runtime)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "production_config_snapshot.json"

#: The exact production runtime, as captured. Kept here so a test that passes
#: cannot be passing because the environment happened to be right.
PROD = {
    "TURN_COORDINATOR_MODE": "new_execute",
    "TURN_COORDINATOR_LANES": "ledger_undo,structured_food",
    "ENTITY_RESOLUTION_MODE": "consume",
    "NUTRITION_ACCURACY_V2": "allowlist",
    "NUTRITION_RESOLVER_MODE": "live",
    "FOOD_COMPOSER": "true",
    "FOOD_COMPOSER_MODEL": "claude-sonnet-5",
    "FOOD_GATE_MODEL": "true",
    "DEFAULT_MODEL": "claude-sonnet-4-6",
    "FOOD_PORTION_PRICING": "true",
    "QUICK_LOG_FOOD_WRITER": "canonical",
}
ENROLLED = 26


@pytest.fixture
def env(monkeypatch):
    for k, v in PROD.items():
        monkeypatch.setenv(k, v)
    return monkeypatch


def test_the_snapshot_supplies_every_measurement_critical_key():
    """⛔ A key with no production value cannot be compared either way."""
    snap = json.loads(SNAP.read_text())
    missing = [k for k in MEASUREMENT_CRITICAL if k not in (snap.get("values") or {})]
    assert not missing, (
        f"the production snapshot does not establish {missing}. Capture them "
        "or attest them — a measurement-critical key with no source is a "
        "refusal, never a None quietly recorded.")
    for k in COHORT_KEYS:
        assert k in (snap.get("cohorts") or {}), f"cohort {k} not captured"


def test_every_snapshot_value_declares_its_provenance():
    """⭐ `/health` does not expose everything. `FOOD_GATE_MODEL` and
    `DEFAULT_MODEL` are human-attested, and that is legitimate — but it must be
    VISIBLE, because an attested value ages differently from a read one."""
    snap = json.loads(SNAP.read_text())
    for key, entry in (snap.get("values") or {}).items():
        assert entry.get("provenance") in ("health", "attested"), (
            f"{key} declares no provenance")


def test_exact_production_config_with_an_enrolled_subject_is_ACCEPTED(env):
    out = pin_runtime(subject_id=ENROLLED)
    assert out["_subject_eligibility"]["TURN_COORDINATOR_ALLOWLIST"]["enrolled"]


def test_a_critical_key_absent_locally_is_REFUSED(env):
    env.delenv("ENTITY_RESOLUTION_MODE")
    with pytest.raises(RuntimeDrift, match="ABSENT LOCALLY"):
        pin_runtime(subject_id=ENROLLED)


def test_new_execute_silently_becoming_new_observe_is_REFUSED(env):
    """⭐ THE EXACT DEFECT. Every census this session ran under `new_observe`
    while production ran `new_execute`, and nothing said so."""
    env.setenv("TURN_COORDINATOR_MODE", "new_observe")
    with pytest.raises(RuntimeDrift, match="TURN_COORDINATOR_MODE"):
        pin_runtime(subject_id=ENROLLED)


def test_a_subject_outside_the_cohort_is_REFUSED(env):
    """⭐⭐⭐ THE LOAD-BEARING CASE, and the one that explains the CF24 local
    VOID: a synthetic user is in no allowlist, so identity never resolves and
    the guarded reader is never reached."""
    with pytest.raises(RuntimeDrift, match="NOT enrolled"):
        pin_runtime(subject_id=999)


def test_a_dashboard_only_key_hidden_from_the_snapshot_is_REFUSED(env, tmp_path):
    """The manifest defect itself, reproduced against the new authority."""
    original = SNAP.read_text()
    snap = json.loads(original)
    del snap["values"]["ENTITY_RESOLUTION_MODE"]
    try:
        SNAP.write_text(json.dumps(snap))
        with pytest.raises(RuntimeDrift, match="ABSENT FROM THE PRODUCTION SNAPSHOT"):
            pin_runtime(subject_id=ENROLLED)
    finally:
        SNAP.write_text(original)


def test_an_undeclared_deviation_is_REFUSED_but_a_DECLARED_one_is_recorded(env):
    """A deviation without a written reason is not declared — it is merely
    known about, which is how the last invalid baseline happened."""
    env.setenv("TURN_COORDINATOR_MODE", "new_observe")
    with pytest.raises(RuntimeDrift):
        pin_runtime(subject_id=ENROLLED)
    out = pin_runtime(subject_id=ENROLLED,
                      declared={"TURN_COORDINATOR_MODE": "arm runs observe deliberately"})
    assert out["_runtime"]["TURN_COORDINATOR_MODE"]["declared_deviation"]


def test_OMITTING_the_subject_is_REFUSED_unless_declared(env):
    """⛔ SKIPPING THE STRONGEST HALF MUST BE AN ACT, NOT AN OMISSION.

    Recording "UNCHECKED" was not enough: a caller who simply forgot
    `subject_id` got a clean pin over the one check that decides behaviour, and
    the record read as a pass with a footnote."""
    with pytest.raises(RuntimeDrift, match="subject eligibility"):
        pin_runtime()
    out = pin_runtime(declared={"subject_eligibility": "no cohort dependence"})
    assert out["_subject_eligibility"]["checked"] is False


def test_the_registry_is_not_derived_from_the_manifest(env):
    """⭐ THE STRUCTURAL FIX, pinned. If MEASUREMENT_CRITICAL were ever rebuilt
    from `render.yaml`, the original defect returns wholesale — the manifest
    omits three of these keys today."""
    manifest = (ROOT / "render.yaml").read_text()
    absent = [k for k in MEASUREMENT_CRITICAL if f"key: {k}" not in manifest]
    assert absent, (
        "every measurement-critical key now appears in render.yaml, which "
        "makes this test vacuous — it exists to prove the registry does NOT "
        "depend on that file")
