"""⛔⛔ A FALLBACK THAT SUCCEEDED IS AN ANSWER, NOT AN OUTAGE.

`_InfraWatch` was added so a refused API call stops being scored as a flaky
behaviour. It watches the log, because `core/llm.py` swallows the model failure
on purpose — a dead turn must still reply — so the signature never reaches the
case as an exception.

The hole that leaves: **`core/llm.py` logs the primary failure BEFORE it
retries.** On the Anthropic path that is

    core/llm.py:205   model call FAILED model=<primary> err=...        <- marker
    core/llm.py:214   model fallback: retrying on <fallback>
    core/llm.py:217   model fallback OK on <fallback>                  <- ANSWERED

so a rep the fallback rescued still carried the marker and was thrown away as
unmeasured. That is the same error the watcher exists to correct, pointing the
other way: the first version could not tell an outage from a behaviour, and
this version could not tell a recovery from an outage. Both discard a real
measurement.

The rule the sequence has to express:

    primary fails, fallback succeeds  -> the model answered  -> SCORE it
    primary fails, fallback fails     -> nothing answered    -> UNMEASURED
"""
from __future__ import annotations

import importlib.util
import logging
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "evalmx",
    pathlib.Path(__file__).resolve().parent.parent / "scripts"
    / "eval_food_matrix.py")
evalmx = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(evalmx)

#: The exact lines `core/llm.py` writes, kept verbatim so a rename of either
#: message shows up here as a failure rather than as silence.
PRIMARY_FAILED = (
    "model call FAILED model=claude-sonnet-5 err=BadRequestError: Error code: "
    "400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API.'}}")
RETRYING = "model fallback: retrying on claude-sonnet-4-6 (primary claude-sonnet-5 failed)"
FALLBACK_OK = "model fallback OK on claude-sonnet-4-6"
FALLBACK_FAILED = (
    "model fallback ALSO failed model=claude-sonnet-4-6 err=BadRequestError: "
    "Error code: 400 - {'type': 'error', 'error': {'type': "
    "'invalid_request_error', 'message': 'Your credit balance is too low to "
    "access the Anthropic API.'}}")
OPENAI_HANDOFF = (
    "Anthropic chat failed (Your credit balance is too low to access the "
    "Anthropic API.); falling back to OpenAI.")


@pytest.fixture()
def watch():
    w = evalmx._InfraWatch()
    root = logging.getLogger()
    root.addHandler(w)
    try:
        yield w
    finally:
        root.removeHandler(w)


def _emit(*lines):
    log = logging.getLogger("core.llm")
    for line in lines:
        log.error(line)


def test_a_rescued_rep_is_scored_not_discarded(watch):
    """⛔⛔ THE BLOCKER. The primary's error is logged before the retry, so a
    rep the fallback answered still carried the marker."""
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_OK)
    assert watch.hits == [], (
        "a rep the fallback rescued was thrown away as unmeasured — the model "
        "answered, and its answer is exactly what the battery exists to score")


def test_both_models_failing_is_still_unmeasured(watch):
    """The case the watcher was built for has to survive the fix."""
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_FAILED)
    assert watch.hits, "a call refused by every model was scored as behaviour"


def test_a_primary_failure_with_no_fallback_is_unmeasured():
    """`MODEL_FALLBACK=false`, or no distinct fallback configured: the primary
    error is the whole story and nothing recovered it."""
    w = evalmx._InfraWatch()
    logging.getLogger().addHandler(w)
    try:
        _emit(PRIMARY_FAILED)
        assert w.hits
    finally:
        logging.getLogger().removeHandler(w)


def test_the_openai_net_also_counts_as_an_answer(watch):
    """The second safety net had no success line at all, so a turn OpenAI
    rescued looked identical to a dead one. `core/llm.py` now says so, and the
    watcher reads it the same way it reads the Anthropic recovery."""
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_FAILED, OPENAI_HANDOFF,
          "openai fallback OK")
    assert watch.hits == [], "a turn the OpenAI net answered was discarded"


def test_a_recovery_does_not_forgive_a_LATER_outage(watch):
    """⛔ THE GUARD ON THE FIX. Clearing on recovery must clear only the call
    that recovered. A rep makes several model calls; if the first is rescued
    and a later one dies outright, the rep is still unmeasured."""
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_OK)      # call 1: rescued
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_FAILED)  # call 2: dead
    assert watch.hits, (
        "an earlier recovery swallowed a later outage — the rep would be "
        "scored on a turn that never got an answer")


def test_an_ordinary_log_line_is_not_an_outage(watch):
    """The watcher must not widen into a general error detector: a behavioural
    complaint is the battery's business, not the plumbing's."""
    logging.getLogger("core.food_turn").warning(
        "event=off_breaker state=open fails=1 cooldown_s=120")
    logging.getLogger("core.food_turn").warning(
        "interpreter asked: how much grilled chicken breast?")
    assert watch.hits == []


def test_the_per_rep_reset_actually_resets(watch):
    """⛔⛔ THE RESET IS A COMPUTED LIST NOW, AND `hits.clear()` WOULD BE A
    NO-OP. `hits` became a property when the pending/dead split landed, so the
    per-rep reset in `main` had to move from `watch.hits.clear()` to
    `watch.clear()`. The first form still runs, still type-checks, and silently
    leaks every marker into the following reps — one outage would then condemn
    every case after it as unmeasured.

    Pinned here because nothing else would notice: the battery would go from
    "one INFRA case" to "all of them" and still look like a coherent report."""
    _emit(PRIMARY_FAILED)
    assert watch.hits, "precondition: the marker was recorded"
    watch.clear()
    assert watch.hits == [], "the per-rep reset did not reset"
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_OK)
    assert watch.hits == [], (
        "a leaked marker from the previous rep survived the reset and would "
        "condemn a rep the fallback rescued")


def test_a_DEAD_call_is_not_forgiven_by_a_LATER_recovery(watch):
    """⛔⛔ THE ORDER MATTERS, AND ONE ORDER WAS UNTESTED. The existing guard
    runs rescued-then-dead, which passes even if a recovery clears everything
    — the dead call comes afterwards and its markers survive by accident.

    Reverse it and the real requirement appears: call 1 dies outright, call 2
    is rescued. The rep still contains a turn that never got an answer, so it
    is still unmeasured. Two mutations (recovery clearing everything, and
    removing the call-boundary banking) were GREEN against the original order
    and are RED against this one."""
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_FAILED)  # call 1: dead
    _emit(PRIMARY_FAILED, RETRYING, FALLBACK_OK)      # call 2: rescued
    assert watch.hits, (
        "a later recovery forgave an earlier outage — the rep would be scored "
        "on a turn that never got an answer")


def test_main_does_not_leak_markers_between_cases(monkeypatch, capsys, tmp_path):
    """⛔⛔ THE RESET AS `main` ACTUALLY USES IT, AND AN ASSERTION THAT CAN SEE
    THE DIFFERENCE.

    The `watch.clear()` proof above passes even when `main` calls
    `watch.hits.clear()` — which clears a computed temporary and does nothing.
    So this drives `main` itself.

    ⭐ AND THE FIRST VERSION OF THIS TEST WAS ALSO BLIND: it asserted
    `exit == 2`, which is true whether ONE rep was refused or every rep of
    every case was. Mutation R4-9 stayed green against it. One refused rep and
    a total leak are the same exit code and a completely different report.

    The signal that separates them is the per-case verdict. Case 1 has a
    genuinely refused rep and must read INFRA; case 2 is clean and must read
    PASS. Under leakage the marker survives into case 2 and condemns it, so
    the second verdict is what this test is really about."""
    import asyncio

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-this-proof")
    monkeypatch.setenv("EVAL_REPS", "2")
    monkeypatch.setattr(evalmx, "RESULTS_PATH", str(tmp_path / "results.txt"))

    seen = {"n": 0}

    async def fake_case(case):
        seen["n"] += 1
        if case["name"] == "refused once" and seen["n"] == 1:
            _emit(PRIMARY_FAILED, RETRYING, FALLBACK_FAILED)
            return False, "got=None want=ask"
        return True, "got=ask ✓"

    monkeypatch.setattr(evalmx, "run_case", fake_case)
    monkeypatch.setattr(evalmx, "CASES", [
        dict(name="refused once", msg="x", expect="ask"),
        dict(name="entirely clean", msg="y", expect="ask"),
    ])

    with pytest.raises(SystemExit) as exc:
        asyncio.run(evalmx.main())

    out = capsys.readouterr().out
    first = next(l for l in out.splitlines() if "refused once" in l)
    second = next(l for l in out.splitlines() if "entirely clean" in l)

    assert first.startswith("[INFRA]"), first
    assert second.startswith("[PASS]"), (
        "a marker leaked out of the previous case and condemned a clean one — "
        "the run would report every case after the first outage as unmeasured "
        "and still look like a coherent report: " + second)
    assert "UNMEASURED (infrastructure): 1" in out
    assert exc.value.code == 2
