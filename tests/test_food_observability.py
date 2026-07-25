"""Tracing, dashboards and canary controls (PR #29).

What these pin, in order of how badly it hurts when it breaks:

    the tracer never changes behaviour   an observer that alters the thing it
                                         observes is worse than no observer
    a halt actually halts                including for allowlisted users
    a cohort is stable                   a user who flaps between systems makes
                                         every report irreproducible
    funnels count one kind of thing      a funnel that grows partway down
                                         reports fiction as conversion
    percentiles are real values          an interpolated p99 is a number you
                                         cannot find in the logs
"""
import logging

import pytest

from core import food_trace
from core.food_trace import FoodTurnTrace, Outcome, Stage
from skills.nutrition import canary, dashboards


@pytest.fixture(autouse=True)
def _clean_trace():
    """Every test starts with no ambient trace. A leaked one turns an
    unrelated failure into a confusing one."""
    food_trace.CURRENT_TRACE.set(None)
    yield
    food_trace.CURRENT_TRACE.set(None)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_MODE", "live")
    monkeypatch.delenv("NUTRITION_RESOLVER_ALLOWLIST", raising=False)
    monkeypatch.delenv("NUTRITION_RESOLVER_CANARY_PCT", raising=False)
    monkeypatch.delenv("NUTRITION_RESOLVER_HALT", raising=False)


# ── the tracer must never change behaviour ────────────────────────────────────
def test_the_tracer_is_inert_when_disabled(monkeypatch):
    monkeypatch.setenv("FOOD_TRACE", "off")
    assert food_trace.begin(turn_id="t") is None
    assert food_trace.current() is None
    # Every entry point must tolerate there being no trace.
    food_trace.note(mode="quick")
    food_trace.record(Stage.RESOLVE, duration_ms=5)
    assert food_trace.finish() is None


def test_a_stage_reraises_rather_than_swallowing(monkeypatch):
    """The one thing an observer must never do is change control flow. A
    swallowed exception here would hide exactly the failures the tracer was
    added to surface."""
    monkeypatch.setenv("FOOD_TRACE", "true")
    trace = food_trace.begin(turn_id="t")
    with pytest.raises(ValueError):
        with food_trace.stage(Stage.RESOLVE):
            raise ValueError("boom")
    assert trace.stages[-1].outcome == Outcome.FAILED.value
    assert "ValueError" in trace.stages[-1].detail
    assert trace.error == "resolve:ValueError"


def test_note_ignores_fields_it_does_not_have(monkeypatch):
    """A caller passing a field the trace does not carry must not fail the
    turn — the tracer is the least important thing in the request."""
    monkeypatch.setenv("FOOD_TRACE", "true")
    trace = food_trace.begin(turn_id="t")
    food_trace.note(no_such_field="x", mode="strict")
    assert trace.mode == "strict"


def test_finish_is_idempotent(monkeypatch):
    monkeypatch.setenv("FOOD_TRACE", "true")
    trace = food_trace.begin(turn_id="t")
    assert food_trace.finish(trace) is trace
    assert food_trace.finish() is None


# ── where a turn stopped ──────────────────────────────────────────────────────
def test_stopped_at_is_where_the_turn_ended_not_the_last_stage_run():
    """A turn that asks stops at CLARIFY even though RENDER runs afterwards to
    produce the question. Reporting RENDER would put every clarification at the
    bottom of the funnel and hide that nothing committed."""
    trace = FoodTurnTrace(turn_id="t")
    trace.record(Stage.STAGE)
    trace.record(Stage.CLARIFY, outcome=Outcome.ASKED)
    trace.record(Stage.RENDER)
    assert trace.stopped_at == "clarify"


def test_a_clean_turn_stops_at_its_last_stage():
    trace = FoodTurnTrace(turn_id="t")
    trace.record(Stage.STAGE)
    trace.record(Stage.EXECUTE)
    trace.record(Stage.RENDER)
    assert trace.stopped_at == "render"


def test_timings_survive_a_round_trip_through_the_log_line():
    """The bug this pins: a space-separated timings list is truncated to its
    first pair by the key=value parser, so every stage but one vanished from
    the latency report."""
    trace = FoodTurnTrace(turn_id="t")
    for stage, ms in ((Stage.INTERPRET, 3), (Stage.STAGE, 1),
                      (Stage.RESOLVE, 180), (Stage.EXECUTE, 42)):
        trace.record(stage, duration_ms=ms)

    record = dashboards.parse_log([trace.log_line()])[0]
    timings = dashboards._timings(record)
    assert timings == {"interpret": 3.0, "stage": 1.0, "resolve": 180.0,
                       "execute": 42.0}


# ── canary cohorts ────────────────────────────────────────────────────────────
def test_a_users_bucket_is_stable(live):
    """A user who flaps between the old and new system makes every report
    irreproducible and their own history internally inconsistent."""
    assert all(canary.bucket_for(4242) == canary.bucket_for(4242)
               for _ in range(10))


def test_widening_the_canary_only_adds_users(live, monkeypatch):
    """The property that makes a rollout safe to widen: a user in the 10%
    cohort is still in the 25% cohort, because the bucket belongs to the id
    rather than to the percentage."""
    ids = list(range(500))

    monkeypatch.setenv("NUTRITION_RESOLVER_CANARY_PCT", "10")
    at_ten = {i for i in ids if canary.in_canary(i)}
    monkeypatch.setenv("NUTRITION_RESOLVER_CANARY_PCT", "25")
    at_twenty_five = {i for i in ids if canary.in_canary(i)}

    assert at_ten and at_ten < at_twenty_five


def test_zero_percent_means_allowlist_only(live, monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_ALLOWLIST", "7")
    monkeypatch.setenv("NUTRITION_RESOLVER_CANARY_PCT", "0")
    assert canary.owns_committed_values(7)
    assert not canary.owns_committed_values(8)


def test_an_unset_percentage_is_not_a_full_rollout(live):
    """A misread env var must fail toward the smaller cohort. The opposite
    default turns a typo into a full rollout."""
    assert canary.canary_percent() == 0.0


def test_a_malformed_percentage_is_zero_not_an_exception(live, monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_CANARY_PCT", "twenty")
    assert canary.canary_percent() == 0.0


# ── the halt ──────────────────────────────────────────────────────────────────
def test_a_halt_overrides_the_allowlist(live, monkeypatch):
    """A halt an allowlist could override is not a halt — and the allowlist is
    the team's own accounts, who are the least likely to notice."""
    monkeypatch.setenv("NUTRITION_RESOLVER_ALLOWLIST", "7")
    assert canary.owns_committed_values(7)
    monkeypatch.setenv("NUTRITION_RESOLVER_HALT", "true")
    assert not canary.owns_committed_values(7)


def test_promotion_honours_the_halt(live, monkeypatch):
    """The gate the rest of the system actually calls."""
    from skills.nutrition.promotion import owns_committed_values
    monkeypatch.setenv("NUTRITION_RESOLVER_CANARY_PCT", "100")
    assert owns_committed_values(7)
    monkeypatch.setenv("NUTRITION_RESOLVER_HALT", "1")
    assert not owns_committed_values(7)


def test_a_halt_does_not_stop_shadow_logging(live, monkeypatch):
    """The data explaining why it halted is produced by the thing that
    halted."""
    from skills.nutrition.promotion import shadow_enabled
    monkeypatch.setenv("NUTRITION_RESOLVER_HALT", "true")
    assert shadow_enabled()


def test_the_cohort_label_names_which_mechanism_let_the_user_in(live,
                                                                monkeypatch):
    monkeypatch.setenv("NUTRITION_RESOLVER_ALLOWLIST", "7")
    monkeypatch.setenv("NUTRITION_RESOLVER_CANARY_PCT", "100")
    assert canary.cohort_label(7) == "allowlist"
    assert canary.cohort_label(8) == "canary"
    monkeypatch.setenv("NUTRITION_RESOLVER_HALT", "on")
    assert canary.cohort_label(7) == "halted"


# ── evaluating readiness into a rollout decision ──────────────────────────────
def _report(**verdicts):
    return {"metrics": {name: {"verdict": v} for name, v in verdicts.items()}}


def test_an_empty_report_is_not_a_green_light():
    """An empty report is the shape a broken log pipeline produces. Treating it
    as healthy makes the pipeline failing look like the system passing."""
    decision = canary.evaluate({})
    assert decision.verdict is canary.Verdict.WATCH
    assert "no_metrics" in decision.reasons
    assert not decision.may_widen


def test_a_zero_tolerance_failure_halts():
    decision = canary.evaluate(_report(wrong_item_binding="fail",
                                       branded_top1_accuracy="pass"))
    assert decision.should_halt
    assert decision.reasons == ("wrong_item_binding",)


def test_an_ordinary_failure_watches_rather_than_halting():
    """Not every miss is a correctness violation. Halting on an accuracy dip
    would make the halt meaningless by making it constant."""
    decision = canary.evaluate(_report(branded_top1_accuracy="fail"))
    assert decision.verdict is canary.Verdict.WATCH
    assert not decision.should_halt


def test_insufficient_data_is_not_a_pass():
    decision = canary.evaluate(_report(branded_top1_accuracy="insufficient"))
    assert decision.verdict is canary.Verdict.WATCH
    assert not decision.may_widen


def test_ungated_metrics_do_not_vote():
    """`build_report` puts every metric in one dict and sets verdict None for
    the ungated ones. An agreement rate is deliberately ungated, and letting it
    count as a pass would let a number nobody promised anything about decide
    whether a rollout continues."""
    report = {"metrics": {"nutrition_agreement": {"verdict": None,
                                                  "value": 0.4}}}
    decision = canary.evaluate(report)
    assert decision.checked == 0
    assert "no_metrics" in decision.reasons


def test_halt_gates_are_read_from_readiness_not_restated():
    """Two lists of "which failures are correctness violations" would drift the
    first time a gate was added."""
    from skills.nutrition.readiness import GATES
    absolute = {n for n, spec in GATES.items() if spec.get("absolute")}
    assert absolute and absolute <= canary.halt_gates()


def test_a_real_readiness_report_evaluates_without_error():
    """The contract between the two modules, against the real report shape
    rather than a hand-built dict."""
    from skills.nutrition.readiness import build_report
    decision = canary.evaluate(build_report([], include_gold=False))
    assert decision.verdict in (canary.Verdict.WATCH, canary.Verdict.HALT)
    assert decision.checked > 0


# ── funnels ───────────────────────────────────────────────────────────────────
def _trace_line(turn, meal, *, staged=1, committed=1, held=0, asked=0,
                cohort="control", stages=(("interpret", 2), ("stage", 1))):
    trace = FoodTurnTrace(turn_id=turn, user_id=1, mode="moderate",
                          cohort=cohort, meal_group_id=meal)
    for name, ms in stages:
        trace.record(Stage(name), duration_ms=ms)
    trace.note(items_staged=staged, items_committed=committed,
               items_held=held, questions_asked=asked, resolver_source="off")
    return trace.log_line()


def test_every_funnel_counts_one_kind_of_thing():
    """The invariant every ratio depends on. Mixing turns and items made
    "items staged" exceed "food turns" the moment anyone logged two foods at
    once — and 200% conversion reported as fact is worse than no report."""
    lines = [_trace_line("t1", "m1", staged=4, committed=4),
             _trace_line("t2", "m2", staged=1, committed=0, held=1, asked=1),
             _trace_line("t3", "m2", staged=1, committed=1)]
    report = dashboards.build_dashboards(dashboards.parse_log(lines))

    assert report["counting_warnings"] == []
    for funnel in report["funnels"]:
        counts = [s["count"] for s in funnel["steps"]]
        assert all(a >= b for a, b in zip(counts, counts[1:])), funnel["name"]


def test_the_clarification_funnel_joins_on_the_meal_not_the_turn():
    """The question is asked on one turn and answered on another. A turn-keyed
    join would score every clarification as abandoned."""
    lines = [_trace_line("t1", "m1", staged=1, committed=0, held=1, asked=1),
             _trace_line("t2", "m1", staged=1, committed=1)]
    funnel = dashboards.clarification_funnel(dashboards.parse_log(lines))
    steps = {s.name: s.count for s in funnel.steps}
    assert steps["meals with a question"] == 1
    assert steps["...later committed"] == 1


def test_a_turn_that_commits_without_the_resolver_keeps_the_funnel_honest():
    """With NUTRITION_RESOLVER_MODE=off no turn records a resolve stage and
    turns still commit. An earlier funnel had "reached resolve" above
    "committed something", which went non-monotonic in exactly the
    configuration production runs in today."""
    lines = [_trace_line("t1", "m1", stages=(("interpret", 2), ("stage", 1)))]
    report = dashboards.build_dashboards(dashboards.parse_log(lines))
    assert report["counting_warnings"] == []
    assert report["turns_reaching_resolve"] == 0


def test_the_turn_funnel_separates_committed_from_committed_cleanly():
    """A turn that committed something while holding the rest is a turn the
    user has to come back to, not a finished one."""
    lines = [_trace_line("t1", "m1", staged=2, committed=1, held=1),
             _trace_line("t2", "m2", staged=1, committed=1)]
    steps = {s.name: s.count
             for s in dashboards.turn_funnel(dashboards.parse_log(lines)).steps}
    assert steps["committed something"] == 2
    assert steps["committed cleanly"] == 1


def test_the_correction_funnel_separates_assumptions_from_parse_failures():
    from skills.nutrition.preferences import build_correction
    from skills.nutrition.staging import (FoodAssumption, StagedFoodItem)

    item = StagedFoodItem(staged_item_id="i1", original_text="a fairlife")
    item = item.with_assumption(FoodAssumption(
        staged_item_id="i1", field_name="product_line",
        assumed_value="Core Power", user_visible_text="Went with your usual."))

    on_assumption = build_correction(
        user_id=1, field_name="product_line", chosen="Core Power",
        corrected="Elite", item=item)
    on_a_stated_value = build_correction(
        user_id=1, field_name="stated_amount", chosen="1", corrected="2",
        item=item)

    assert on_assumption.was_assumed
    assert not on_a_stated_value.was_assumed

    funnel = dashboards.correction_funnel(dashboards.parse_log(
        [on_assumption.log_line(), on_a_stated_value.log_line()]))
    steps = {s.name: s.count for s in funnel.steps}
    assert steps["corrections received"] == 2
    assert steps["...to an assumption"] == 1


def test_confused_pairs_need_to_recur():
    """A pair seen once is an unusual pantry. A pair seen repeatedly is a
    ranking bug, and only the second is worth a code change."""
    from skills.nutrition.preferences import build_correction

    lines = [build_correction(user_id=1, field_name="product_line",
                              chosen="Core Power", corrected="Elite").log_line()
             for _ in range(3)]
    lines.append(build_correction(user_id=1, field_name="product_line",
                                  chosen="Oatly", corrected="Alpro").log_line())

    pairs = dashboards.confused_pairs(dashboards.parse_log(lines))
    assert [(p["chosen"], p["corrected"], p["count"]) for p in pairs] == [
        ("Core Power", "Elite", 3)]


def test_a_funnel_that_grows_is_reported_as_a_counting_bug():
    """The guard itself. Reporting 140% conversion as if it were a fact is
    worse than reporting nothing."""
    broken = dashboards.Funnel(name="broken", steps=(
        dashboards.Step("a", 1), dashboards.Step("b", 5)))
    assert not broken.is_monotonic


# ── latency ───────────────────────────────────────────────────────────────────
def test_percentiles_are_values_that_actually_occurred():
    """An interpolated p99 of 812ms when nothing took 812ms is a number you
    cannot go and find in the logs."""
    values = [10, 20, 30, 40, 1000]
    for p in (0.5, 0.9, 0.99):
        assert dashboards.percentile(values, p) in values


def test_percentiles_of_nothing_are_none_not_zero():
    """Zero latency and unmeasured latency are different facts, and a
    dashboard that cannot tell them apart reports an outage as excellent
    performance."""
    assert dashboards.percentile([], 0.5) is None
    assert dashboards.latency_for("x", []).p50 is None


def test_latency_is_reported_per_stage_in_pipeline_order():
    """A food turn is slow for one reason at a time, and a total tells you it
    was slow without telling you which of seven stages to look at."""
    lines = [_trace_line("t1", "m1", stages=(("interpret", 2), ("resolve", 300),
                                             ("execute", 40))),
             _trace_line("t2", "m2", stages=(("interpret", 3), ("resolve", 900),
                                             ("execute", 50)))]
    report = dashboards.latency_report(dashboards.parse_log(lines))
    names = [s["name"] for s in report["stages"]]
    assert names == ["interpret", "resolve", "execute"]
    resolve = next(s for s in report["stages"] if s["name"] == "resolve")
    assert resolve["samples"] == 2 and resolve["max_ms"] == 900.0


# ── the wiring ────────────────────────────────────────────────────────────────
def test_the_pipeline_records_its_stages(monkeypatch, caplog):
    """The end-to-end check that matters: run the real planner and confirm the
    spine came out with the stages on it."""
    monkeypatch.setenv("FOOD_TRACE", "true")
    from core.food_pipeline import plan_turn

    trace = food_trace.begin(turn_id="t1", user_id=1, mode="moderate")
    data = {"items": [{"food": "fairlife", "brand": "Fairlife"}],
            "ambiguities": [{"item": "fairlife", "field": "brand",
                             "options": ["Core Power", "Elite"],
                             "impact_cal": 190, "impact_protein": 16}]}
    decision = plan_turn(data, turn_id="t1", message="a fairlife",
                         mode="moderate")

    assert decision is not None and decision.asks
    assert {s.stage for s in trace.stages} >= {"stage", "clarify"}
    assert trace.items_staged == 1
    assert trace.questions_asked >= 1
    assert trace.stopped_at == "clarify"

    with caplog.at_level(logging.INFO):
        food_trace.finish(trace)
    assert any("event=food_trace" in r.message for r in caplog.records)


def test_the_resolver_records_a_resolve_stage(monkeypatch):
    monkeypatch.setenv("FOOD_TRACE", "true")
    from skills.nutrition.models import FoodResolutionRequest
    from skills.nutrition.resolver import resolve

    trace = food_trace.begin(turn_id="t1")
    out = resolve(FoodResolutionRequest(food_name="nothing",
                                        raw_quantity="100g"), [])
    assert out.source == "unresolved"
    stage = next(s for s in trace.stages if s.stage == "resolve")
    assert stage.outcome == Outcome.HELD.value
    assert stage.counts["candidates"] == 0


def test_resolution_is_identical_with_tracing_on_and_off(monkeypatch):
    """The whole point of an observer: turning it on must not change a single
    number."""
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import (FoodResolutionRequest,
                                         profile_from_values)
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.resolver import resolve
    from skills.nutrition.scaling import Per100g

    def _run():
        candidate = Candidate(
            source="usda", tier=SourceTier.GENERIC_EXACT, name="Banana, raw",
            profile=profile_from_values("usda", basis="per_100g",
                                        confidence=0.8, calories=89,
                                        protein=1.1),
            basis=Per100g(), reported_grade=MatchGrade.EXACT)
        return resolve(FoodResolutionRequest(food_name="Banana, raw",
                                             raw_quantity="118g"), [candidate])

    monkeypatch.setenv("FOOD_TRACE", "off")
    without = _run()
    monkeypatch.setenv("FOOD_TRACE", "true")
    food_trace.begin(turn_id="t")
    with_tracing = _run()

    assert without.nutrients.as_dict() == with_tracing.nutrients.as_dict()
    assert without.source == with_tracing.source
    assert without.assumptions == with_tracing.assumptions
