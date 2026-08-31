"""ONE config-pinning guard, shared by every measurement harness.

⛔⛔⛔ EXTRACTED 2026-08-27 AFTER BUILDING THE SECOND HARNESS WITHOUT IT.
`sweep_case_stability.py` refuses to run under an unpinned configuration and
writes the resolved config as its output's first line. `characterise_ask_
producer.py` was then written from scratch WITHOUT the guard, and four
experiments ran through it — including one whose baseline failed to reproduce,
which cannot now be attributed to variance rather than configuration because
no run recorded its own config.

Having spent the same day proving that unpinned configuration silently reverses
conclusions, a second harness was built without the protection. **The guard has
to live in ONE place that every harness imports, or the next harness will be
written without it too.**
"""

import json
import os
import pathlib


# ⛔⛔⛔ THE 2026-08-27 SWEEP WAS RUN UNDER THE WRONG CONFIGURATION AND FROZEN
# AS A BASELINE. It recorded the tree SHA (`834924b`) and asserted a
# self-tested reader, and both were true. It never recorded the FLAGS. All
# EIGHTEEN behaviour flags `render.yaml` declares were unset in that shell:
#
#     FOOD_GATE_MODEL         prod true  -> sweep unset : the structured food
#                                           lane admitted 2 of 25 corpus cases
#                                           instead of 25 of 25. 23 cases FLIP.
#     NUTRITION_RESOLVER_MODE prod live  -> sweep unset : traces recorded
#                                           `resolver_source='off'`.
#     DEFAULT_MODEL           prod sonnet-4-6 -> sweep unset : A DIFFERENT MODEL.
#
# A tree SHA does not pin a configuration. So this harness now REFUSES to run
# when a declared flag differs without a written reason, rather than producing
# a clean-looking number from the wrong product.
_ALLOWED_DEVIATIONS = {
    "PROACTIVE_MESSAGING_ENABLED":
        "false — the harness must never emit outbound messages on behalf of "
        "synthetic identities",
    "TELEGRAM_BOT_USERNAME": "unused — no Telegram channel in this harness",
    "DASHBOARD_BASE_URL": "unused — no links are rendered",
    "TRUST_PROXY_HEADERS": "unused — no HTTP layer in this harness",
    "DEV_AUTH_ENABLED": "unused — no auth layer in this harness",
    "LINKING_ENABLED": "unused — no account linking in this harness",
    "BRAIN_TAB_ENABLED": "unused — UI surface only",
    # Danny, 2026-08-27: ~1/3 of run cost for zero measurement value here.
    #
    # ⭐ THE JUSTIFICATION IS A CONTRACT, NOT AN ASSUMPTION. In `new_observe`
    # the coordinator OBSERVES and legacy EXECUTES; `deep_observing()` only
    # controls whether the planning stages additionally run in observe mode,
    # and those stages "never execute tools, write rows or send messages"
    # (render.yaml, and `core/turns/observe.py`). What it buys in production is
    # a disposition-agreement number for the promotion decision — a metric this
    # harness does not read. What it costs is a SECOND interpreter pass on
    # every food turn.
    #
    # ⚠ RESIDUAL RISK, WRITTEN DOWN RATHER THAN WAVED AWAY: this is a declared
    # deviation from production, and the last invalid baseline came from an
    # UNdeclared one. If a future run produces an anomaly that the product
    # cannot explain, re-run one case with this restored to `true` before
    # blaming the product.
    "TURN_COORDINATOR_OBSERVE_DEEP":
        "false — read-only second interpreter pass; cannot change the decision "
        "(observe stages never execute tools, write rows or send messages, and "
        "legacy executes in new_observe). Cost, not fidelity. Danny 2026-08-27",
}
_SECRETS = ("DATABASE_URL", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN",
            "ARNIE_USERS_DIR")


class ConfigDrift(Exception):
    """A declared production flag differs and nobody wrote down why."""


def pin_config() -> dict:
    """Compare this shell against every flag `render.yaml` declares.

    Returns the resolved configuration, which is written as the FIRST line of
    the output so the run can never again be read without its config.

    ⭐ `MEASUREMENT_ARM` — THE ONE LEGITIMATE REASON TO DIFFER FROM PRODUCTION.
    A causal experiment varies a flag ON PURPOSE, and before this the only ways
    to run one were to edit the tree between arms (which changes `_code_sha`
    and destroys comparability) or to add a permanent entry to
    `_ALLOWED_DEVIATIONS` (which hides the arm inside the list of things nobody
    is measuring). Naming the flag here declares it as the ARM: the run is
    allowed, and the varied flag is written into the output under `_arm` so a
    reader can never mistake an arm for a census. Everything else is still
    pinned exactly as before.
    """
    import re
    txt = pathlib.Path("render.yaml").read_text()
    declared = dict(re.findall(r'- key:\s*(\S+)\s*\n\s*value:\s*"?([^"\n]*)"?', txt))
    arm = {k.strip() for k in (os.getenv("MEASUREMENT_ARM") or "").split(",")
           if k.strip()}
    unknown = sorted(arm - set(declared))
    if unknown:
        raise ConfigDrift(
            f"MEASUREMENT_ARM names flags render.yaml does not declare: "
            f"{unknown}. An arm has to vary something production HAS, or the "
            "experiment is not about production.")
    drift = []
    for key, want in sorted(declared.items()):
        if key in _SECRETS:
            continue
        got = os.environ.get(key)
        if (got or "") != want and key not in _ALLOWED_DEVIATIONS \
                and key not in arm:
            drift.append(f"  {key}: render.yaml={want!r} shell={got!r}")
    if drift:
        raise ConfigDrift(
            "declared production flags differ with no written reason:\n"
            + "\n".join(drift)
            + "\n\nEither export them, or add the flag to _ALLOWED_DEVIATIONS "
              "WITH a reason. A baseline measured under an unpinned "
              "configuration is not a baseline.")
    resolved = {k: os.environ.get(k) for k in declared if k not in _SECRETS}
    resolved["_deviations"] = {k: v for k, v in _ALLOWED_DEVIATIONS.items()
                               if k in declared}
    #: The flags this run varies ON PURPOSE, and what they were set to. `None`
    #: on a census, so "was this an arm?" is answerable from the output alone.
    resolved["_arm"] = ({k: os.environ.get(k) for k in sorted(arm)}
                        if arm else None)
    resolved["_tree_sha"] = _tree_sha()
    resolved["_code_sha"] = _code_sha()
    resolved["_untracked"] = _untracked_code_files()
    return resolved


#: Paths whose contents can change what the PRODUCT does or what the instrument
#: observes. `data/` and `docs/` are excluded on purpose — see `_code_sha`.
_CODE_PATHS = ("core", "skills", "handlers", "db", "scripts", "render.yaml")


def _code_sha() -> str:
    """The last commit touching BEHAVIOUR-RELEVANT code, plus a dirty marker
    scoped to those paths.

    ⛔⛔ WHY NOT THE FULL TREE SHA. Probe eligibility compares the tree at
    qualification against the tree at run time. Using the whole repo made that
    check self-defeating: **registering eligibility is a commit, which changes
    the SHA, which invalidates the eligibility just registered.** A probe could
    never be qualified and then used. Observed 2026-08-27 — the guard blocked
    its own experiment twice.

    ⭐ THIS IS NOT A RELAXATION. A docs or corpus commit cannot change what the
    model does; flagging it as a behaviour change measured the wrong thing. The
    full `_tree_sha` is still recorded for provenance — this is only what
    eligibility COMPARES on.

    ⛔⛔ 2026-08-31: THE DIRTY MARKER WAS A BOOLEAN OVER A PATH SET THAT MIXES
    PRODUCT CODE WITH INSTRUMENTS, AND IT VOIDED A 150-TURN RUN.

    Writing `scripts/analyse_c_rerun.py` — an UNTRACKED analysis script,
    imported by nothing, that reads the output after the fact — while arms 2
    and 3 were in flight flipped `-dirty` on for those two arms and not the
    first. Three arms of one experiment, byte-identical product code, recorded
    as `0181534`, `0181534-dirty`, `0181534-dirty`, and therefore incomparable.

    The guard was RIGHT to refuse: it could not tell an analysis script from a
    product edit, because "-dirty" throws away the one thing that would
    distinguish them. **A marker that says something changed without saying
    what cannot be adjudicated, only argued with** — and arguing past a
    refusal condition is the failure preregistration exists to prevent.

    So: MODIFIED TRACKED FILES still dirty the sha, because a tracked edit is a
    product edit. UNTRACKED files are recorded SEPARATELY, by name, under
    `_untracked` — present in the record, inspectable by a human, and not
    silently fused into the identity of the code. Nothing tracked can import an
    untracked module without a tracked edit, which would dirty the sha anyway.
    """
    import subprocess
    try:
        sha = subprocess.run(["git", "log", "-1", "--format=%h", "--",
                              *_CODE_PATHS], capture_output=True, text=True,
                             timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain", "--",
                                *_CODE_PATHS], capture_output=True, text=True,
                               timeout=5)
        out = (sha.stdout or "").strip() or "unknown"
        modified = [ln for ln in (dirty.stdout or "").splitlines()
                    if ln[:2].strip() and not ln.startswith("??")]
        return out + ("-dirty" if modified else "")
    except Exception:
        return "unknown"


def _untracked_code_files() -> list:
    """Untracked files sitting in the behaviour-relevant paths, BY NAME.

    Recorded rather than folded into `_code_sha` — see the note there. A reader
    comparing two runs can see exactly which extra files were present and
    decide for themselves; what they can no longer do is mistake an analysis
    script for a product change, or vice versa.
    """
    import subprocess
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--",
                              *_CODE_PATHS], capture_output=True, text=True,
                             timeout=5)
        return sorted(ln[3:].strip() for ln in (out.stdout or "").splitlines()
                      if ln.startswith("??"))
    except Exception:
        return []


def _tree_sha() -> str:
    """HEAD, plus a dirty marker. ⚠ A SHA ALONE PINS NOTHING — that is the
    2026-08-27 lesson and the reason this sits BESIDE the resolved flags rather
    than instead of them. Both are needed: the flags say what product ran, the
    SHA says what code."""
    import subprocess
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5)
        out = (sha.stdout or "").strip() or "unknown"
        return out + ("-dirty" if (dirty.stdout or "").strip() else "")
    except Exception:
        return "unknown"


def comparable(a: dict, b: dict) -> tuple:
    """⛔ CROSS-RUN COMPARISON IS INVALID UNLESS CONFIG **AND** TREE MATCH.

    Returns (ok, [reasons]). Three discrimination rounds were compared against
    a baseline collected from a different tree state through an UNPINNED
    harness; no run recorded enough to notice. Callers must refuse to compare
    rather than quietly reporting a delta.
    """
    reasons = []
    if (a or {}).get("_code_sha") != (b or {}).get("_code_sha"):
        reasons.append(f"code differs: {(a or {}).get('_code_sha')} vs "
                       f"{(b or {}).get('_code_sha')}")
    #: `_untracked` is compared, but as a NAMED difference rather than as part
    #: of the code identity — see `_code_sha`. It is listed last so the reason
    #: reads as what it is: extra files were present, here they are.
    keys = (set(a or {}) | set(b or {})) - {"_deviations", "_tree_sha",
                                            "_code_sha", "_arm"}
    for k in sorted(keys):
        if (a or {}).get(k) != (b or {}).get(k):
            reasons.append(f"{k}: {(a or {}).get(k)!r} vs {(b or {}).get(k)!r}")
    return (not reasons), reasons


def differs_only_in(a: dict, b: dict, keys) -> tuple:
    """⭐ THE COMPARISON A CAUSAL PAIR NEEDS: same code, same everything, and
    ONE named variable.

    `comparable()` answers "may these be compared at all" and correctly says NO
    for two arms of an experiment. This answers the different question an
    experiment actually asks — *is the arm the ONLY thing that moved?* — and it
    is deliberately not a relaxation of `comparable`: it still refuses on a
    `_code_sha` mismatch, and it refuses on any difference outside `keys`.
    """
    keys = set(keys)
    ok, reasons = comparable(a, b)
    if ok:
        return False, ["nothing differs — these are the same arm, not a pair"]
    stray = [r for r in reasons
             if not any(r.startswith(f"{k}:") for k in keys)]
    return (not stray), stray


# ═══════════════════════════════════════════════════════════════════════════
# ⛔⛔⛔ A DEPLOYMENT MANIFEST IS NOT THE AUTHORITY FOR RUNTIME CONFIGURATION.
#
# Everything above compares the shell against `render.yaml`. On 2026-08-31 that
# was shown to be structurally insufficient, not merely stale:
#
#     render.yaml   TURN_COORDINATOR_MODE = new_observe
#     PRODUCTION    TURN_COORDINATOR_MODE = new_execute
#
#     ENTITY_RESOLUTION_MODE / ENTITY_RESOLUTION_CONSUME_ALLOWLIST /
#     TURN_COORDINATOR_ALLOWLIST / NUTRITION_ACCURACY_V2 allowlist
#         -> ABSENT FROM THE MANIFEST ENTIRELY, so the drift check had never
#            compared them and reported a CLEAN PIN while they differed.
#
# The manifest can omit dashboard-defined variables. A guard whose key list
# comes from that file can only ever check what someone remembered to write
# down — so the same defect recurs under the next flag.
#
# ⭐ THE CONTRACT IS THEREFORE:
#     measurement-critical registry  (frozen HERE, not derived from a file)
#         -> expected value from a PRODUCTION SNAPSHOT (with provenance)
#         -> actual value in this run
#         -> and SUBJECT ELIGIBILITY, which is the part that decides behaviour
#
# `ENTITY_RESOLUTION_MODE=consume` is not equivalent to "this turn consumes
# identity". `consume` + `allowlist=[26]` means user 26 does and nobody else
# does — and that difference is exactly why a local replay of CF24 never
# reached the memory row: the synthetic user was in no cohort, the identity
# never resolved, the lookup key never matched, and the guarded door never ran.
_SNAPSHOT_PATH = pathlib.Path("data/production_config_snapshot.json")

#: FROZEN. Add a key when a measurement depends on it; never remove one to make
#: a run pass.
MEASUREMENT_CRITICAL = (
    "TURN_COORDINATOR_MODE", "TURN_COORDINATOR_LANES",
    "ENTITY_RESOLUTION_MODE", "NUTRITION_ACCURACY_V2",
    "NUTRITION_RESOLVER_MODE", "FOOD_COMPOSER", "FOOD_COMPOSER_MODEL",
    "FOOD_GATE_MODEL", "DEFAULT_MODEL", "FOOD_PORTION_PRICING",
    "QUICK_LOG_FOOD_WRITER",
)

#: Cohort membership decides BEHAVIOUR, so it is checked as a first-class fact
#: rather than inferred from the mode string.
COHORT_KEYS = ("TURN_COORDINATOR_ALLOWLIST",
               "ENTITY_RESOLUTION_CONSUME_ALLOWLIST",
               "NUTRITION_ACCURACY_V2_allowlist")


class RuntimeDrift(Exception):
    """The run does not match the production runtime it claims to represent."""


def _snapshot() -> dict:
    if not _SNAPSHOT_PATH.exists():
        raise RuntimeDrift(
            f"{_SNAPSHOT_PATH} is missing. A measurement cannot claim "
            "production equivalence with no record of what production runs. "
            "Capture it from /health first.")
    return json.loads(_SNAPSHOT_PATH.read_text())


def _norm(v):
    """One scale for shell strings and JSON types, so 'true' == True."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v).strip().lower() if v is not None else None


def pin_runtime(*, subject_id=None, declared: dict = None) -> dict:
    """⛔ REFUSE unless this run matches the production runtime it claims.

    Five fatal conditions, per Danny 2026-08-31:

        required key absent from the production snapshot -> REFUSE
        required key absent locally                      -> REFUSE
        value mismatch                                   -> REFUSE
        subject eligibility mismatch                     -> REFUSE
        undeclared experimental deviation                -> REFUSE

    `declared` is the experiment's OWN deviations: `{KEY: "written reason"}`.
    A deviation without a reason is not declared, it is merely known about.

    `subject_id` is the identity the turn will run as. Omitting it is allowed
    ONLY when the measurement does not depend on cohort behaviour, and the
    result records `subject_eligibility: "UNCHECKED"` so a reader can see that
    the strongest half of this guard was skipped.
    """
    snap = _snapshot()
    declared = dict(declared or {})
    values = snap.get("values") or {}
    problems, resolved = [], {}

    for key in MEASUREMENT_CRITICAL:
        entry = values.get(key)
        if entry is None:
            problems.append(
                f"  {key}: ABSENT FROM THE PRODUCTION SNAPSHOT — nothing "
                f"establishes what production runs, so equivalence cannot be "
                f"claimed either way")
            continue
        want, got = _norm(entry.get("value")), _norm(os.environ.get(key))
        resolved[key] = {"expected": entry.get("value"),
                         "actual": os.environ.get(key),
                         "provenance": entry.get("provenance")}
        if got is None:
            problems.append(f"  {key}: ABSENT LOCALLY (production={want!r})")
        elif got != want:
            if key in declared:
                resolved[key]["declared_deviation"] = declared[key]
            else:
                problems.append(
                    f"  {key}: production={want!r} run={got!r} — undeclared")

    # ── subject eligibility: the half that decides behaviour ────────────────
    cohorts = snap.get("cohorts") or {}
    if subject_id is None:
        # ⛔ SKIPPING THE STRONGEST HALF MUST BE AN ACT, NOT AN OMISSION.
        # Recording "UNCHECKED" in the output is not enough: a caller that
        # simply forgets `subject_id` would get a clean pin over the one check
        # that decides behaviour, and the record would look like a pass with a
        # footnote. Opting out now costs a written reason, exactly like every
        # other deviation.
        if "subject_eligibility" not in declared:
            problems.append(
                "  subject eligibility: NOT CHECKED and not declared. Pass "
                "`subject_id=`, or declare "
                "`{'subject_eligibility': '<why this measurement does not "
                "depend on cohort behaviour>'}`")
        eligibility = {"checked": False,
                       "declared_deviation": declared.get("subject_eligibility")}
    else:
        eligibility = {}
        for ck in COHORT_KEYS:
            members = cohorts.get(ck)
            if members is None:
                problems.append(f"  cohort {ck}: absent from the snapshot")
                continue
            inside = int(subject_id) in [int(m) for m in members]
            eligibility[ck] = {"members": members, "subject": int(subject_id),
                               "enrolled": inside}
            if not inside and ck not in declared:
                problems.append(
                    f"  cohort {ck}: production enrols {members}, this run's "
                    f"subject {subject_id} is NOT enrolled — behaviour differs "
                    f"and no deviation was declared")
            elif not inside:
                eligibility[ck]["declared_deviation"] = declared[ck]

    if problems:
        raise RuntimeDrift(
            "this run does not match the production runtime it claims:\n"
            + "\n".join(problems)
            + "\n\nDeclare each deviation WITH A WRITTEN REASON, or fix the "
              "run. A measurement described as production-equivalent when it "
              "is not is how a valid causal result acquires an invalid "
              "generalisation.")
    return {"_runtime_snapshot_build": snap.get("_build"),
            "_runtime_captured_at": snap.get("_captured_at"),
            "_runtime": resolved,
            "_subject_eligibility": eligibility,
            "_declared_runtime_deviations": declared}
