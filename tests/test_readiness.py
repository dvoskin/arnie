"""Live readiness gates (directive 29).

The shadows are running and emitting structured lines. This reads them back and
answers whether the new path is actually better.

The property under test throughout: the report must never report agreement as
correctness, and must never report an unmeasured gate as a pass. Both would
make a rollout decision on evidence that does not exist.
"""
import pytest

from skills.nutrition.readiness import (GATES, Metric, Stage, build_report,
                                        clarification_rate,
                                        coordinator_agreement, format_report,
                                        gold_ambiguity_recall,
                                        gold_identity_accuracy, large_move_rate,
                                        macro_delta, micronutrient_rejection_rate,
                                        nutrition_agreement, parse_line,
                                        parse_log, resolver_crash_rate,
                                        unresolved_rate, agreement_by_source,
                                        wrong_item_binding)

OBSERVE = ("INFO event=turn_observe turn=imessage:G-1 predicted_lane={p} "
           "actual_lane={a} predicted_disposition=- actual_disposition=- "
           "agree={agree}")
SHADOW = ("INFO event=nutrition_shadow turn=t1 food='{food}' "
          "legacy_source={ls} new_source={ns} legacy_cal={lc} new_cal={nc} "
          "grade=exact unknown=sodium rejected={rej} agree={agree}")
TRACE = ("INFO event=item_trace turn=t1 item=i1 class=branded text='x' "
         "candidates=4→2 top='y' score=0.71 second=0.66 ambiguities=- "
         "materiality=0.10 mode={mode} decision={decision} question=-")


def _observe(p, a):
    return OBSERVE.format(p=p, a=a, agree=("yes" if p == a else "NO"))


def _shadow(ls="usda", ns="off", lc=290, nc=80, agree="NO", rej=0,
            food="Royo Plain Bagel"):
    return SHADOW.format(ls=ls, ns=ns, lc=lc, nc=nc, agree=agree, rej=rej,
                         food=food)


def _trace(mode="moderate", decision="commit"):
    return TRACE.format(mode=mode, decision=decision)


# ── parsing ───────────────────────────────────────────────────────────────────
def test_our_events_parse_and_everything_else_is_ignored():
    """A mixed application log can be piped in whole."""
    assert parse_line(_observe("general", "general"))["event"] == "turn_observe"
    assert parse_line("INFO some unrelated line") is None
    assert parse_line("INFO event=turn_trace route=legacy") is None
    assert parse_line("") is None


def test_quoted_values_survive_parsing():
    rec = parse_line(_shadow(food="Royo Plain Bagel"))
    assert rec["food"] == "Royo Plain Bagel"
    assert rec["legacy_cal"] == "290"


def test_a_whole_log_parses():
    lines = [_observe("general", "general"), "noise", _shadow(),
             _trace(), ""]
    assert len(parse_log(lines)) == 3


# ── agreement is not correctness ──────────────────────────────────────────────
def test_coordinator_agreement_counts_only_comparable_turns():
    records = parse_log([_observe("structured_food", "structured_food"),
                         _observe("general", "general"),
                         _observe("general", "structured_food")])
    m = coordinator_agreement(records)
    assert m.value == pytest.approx(2 / 3)
    assert m.sample == 3
    assert "structured_food→general" in m.detail


def test_disagreements_are_broken_down_so_they_can_be_diagnosed():
    records = parse_log([_observe("general", "structured_food"),
                         _observe("general", "structured_food"),
                         _observe("general", "ledger_undo")])
    detail = coordinator_agreement(records).detail
    assert detail["structured_food→general"] == 2
    assert detail["ledger_undo→general"] == 1


def test_nutrition_agreement_is_labelled_as_agreement_not_accuracy():
    """The gate names accuracy; this metric is agreement. They are different
    claims, and agreement with a system you are replacing is not evidence the
    replacement is right — so this metric is deliberately NOT gated."""
    records = parse_log([_shadow(agree="yes"), _shadow(agree="NO")])
    m = nutrition_agreement(records)
    assert m.value == 0.5
    assert m.name not in GATES


def test_disagreement_is_broken_down_by_source():
    """A high branded disagreement rate is the resolver doing its job. A high
    generic one is a reason to look harder before promoting."""
    records = parse_log([_shadow(ns="off", agree="NO"),
                         _shadow(ns="off", agree="NO"),
                         _shadow(ns="usda", agree="yes"),
                         _shadow(ns="usda", agree="yes")])
    detail = agreement_by_source(records).detail
    assert detail["off"]["rate"] == 1.0
    assert detail["usda"]["rate"] == 0.0


def test_the_size_of_the_correction_is_reported_not_just_its_frequency():
    records = parse_log([_shadow(lc=290, nc=80, agree="NO"),
                         _shadow(lc=200, nc=150, agree="NO"),
                         _shadow(lc=100, nc=100, agree="yes")])
    m = macro_delta(records)
    assert m.sample == 2                    # agreeing turns contribute nothing
    # This assertion used to accept either middle value, hedging around a real
    # median bug rather than pinning the answer. 50 and 210 is 130.
    assert m.value == 130.0
    assert m.detail["max"] == 210.0


def test_unresolved_turns_are_tracked():
    """A rising number means promotion hands MORE turns back to the cascade."""
    records = parse_log([_shadow(ns="unresolved"), _shadow(ns="off")])
    assert unresolved_rate(records).value == 0.5


def test_micronutrient_rejection_is_a_safety_metric():
    """A high number is good news about the validators, not bad news about the
    data."""
    records = parse_log([_shadow(rej=2), _shadow(rej=0), _shadow(rej=1)])
    assert micronutrient_rejection_rate(records).value == pytest.approx(2 / 3)


def test_large_moves_are_rated_against_promotions():
    lines = ["INFO event=nutrition_promotion turn=t outcome=promoted "
             "legacy_cal=290 new_cal=80",
             "INFO event=nutrition_promotion turn=t outcome=promoted "
             "legacy_cal=100 new_cal=95",
             "WARNING event=nutrition_promotion_large_move turn=t "
             "legacy_cal=290 new_cal=80 x=3.6"]
    m = large_move_rate(parse_log(lines))
    assert m.value == 0.5 and m.detail["largest"] == 3.6


def test_a_declined_promotion_is_not_counted_as_one():
    lines = ["INFO event=nutrition_promotion turn=t outcome=declined "
             "reason=unresolved"]
    assert large_move_rate(parse_log(lines)).value is None


# ── proxies are labelled as proxies ───────────────────────────────────────────
def test_the_clarification_rate_says_it_is_a_proxy():
    """The gate is named "unnecessary clarification", but from logs alone this
    is the clarification RATE — only a correction or an abandonment says a given
    question was unnecessary."""
    records = parse_log([_trace("quick", "ask"), _trace("quick", "commit"),
                         _trace("quick", "commit"), _trace("quick", "commit")])
    m = clarification_rate(records, "quick")
    assert m.value == 0.25
    assert m.name == "clarification_rate_quick"     # named for what it measures
    assert "note" in m.detail


def test_clarification_rates_are_per_mode():
    records = parse_log([_trace("quick", "ask"), _trace("moderate", "ask"),
                         _trace("moderate", "commit")])
    assert clarification_rate(records, "quick").value == 1.0
    assert clarification_rate(records, "moderate").value == 0.5


def test_wrong_item_binding_is_absolute_not_a_rate():
    """The failure the whole staged-item model exists to prevent. One
    occurrence is a defect, so the gate is zero rather than a percentage."""
    assert GATES["wrong_item_binding"]["absolute"] is True
    assert GATES["wrong_item_binding"]["max"] == 0
    lines = ["INFO event=food_correction user=7 turn=t field=entry_id "
             "text='x' chose='a' meant='b' alias=- mode=moderate ranked=2"]
    assert wrong_item_binding(parse_log(lines)).value == 1.0


def test_no_data_means_unmeasured_not_a_demonstrated_zero():
    """Zero correction rows is "nobody has complained yet", not "we bound every
    answer correctly". Reporting 0.0 there would clear a canary gate on the
    absence of evidence."""
    m = wrong_item_binding([])
    assert m.value is None
    assert m.verdict() == "unmeasured"


def test_the_denominator_is_applied_answers_not_corrections():
    """Measuring wrong bindings against corrections asks "of the times the user
    told us we were wrong, how often were we wrong" — 100% by construction."""
    lines = [TRACE.format(mode="moderate", decision="commit").replace(
                 "question=-", "question=q1") for _ in range(20)]
    lines.append("INFO event=food_correction user=7 turn=t field=entry_id "
                 "text='x' chose='a' meant='b' alias=- mode=moderate ranked=2")
    m = wrong_item_binding(parse_log(lines))
    assert m.sample == 20
    assert m.value == 1.0


# ── verdicts ──────────────────────────────────────────────────────────────────
def test_an_unmeasured_gate_is_never_a_pass():
    """The property that keeps this honest: a report cannot green-light a
    promotion on evidence it does not have."""
    assert Metric("branded_top1_accuracy").verdict() == "unmeasured"


def test_a_small_sample_is_reported_as_insufficient_not_pass():
    """100% agreement over four turns is not the same claim as over four
    thousand."""
    assert Metric("branded_top1_accuracy", 1.0, 4).verdict() == "insufficient"
    assert Metric("branded_top1_accuracy", 1.0, 200).verdict() == "pass"


def test_a_zero_tolerance_gate_needs_no_sample_size():
    """One wrong-item binding is a defect regardless of how many turns ran."""
    assert Metric("wrong_item_binding", 0.0, 1).verdict() == "pass"
    assert Metric("wrong_item_binding", 1.0, 1).verdict() == "fail"


def test_min_and_max_gates_both_evaluate():
    assert Metric("branded_top1_accuracy", 0.90, 100).verdict() == "fail"
    assert Metric("branded_top1_accuracy", 0.98, 100).verdict() == "pass"
    assert Metric("clarification_rate_quick", 0.20, 100).verdict() == "fail"
    assert Metric("clarification_rate_quick", 0.05, 100).verdict() == "pass"


def test_an_ungated_metric_has_no_verdict():
    assert Metric("median_calorie_delta", 120.0, 50).verdict() == "unmeasured"


# ── the gold-backed metrics ───────────────────────────────────────────────────
def test_identity_accuracy_comes_from_labelled_data():
    """Labels are what make this accuracy rather than agreement, and the gold
    set is where labels live."""
    top1, top3 = gold_identity_accuracy()
    assert top1.source == "gold" and top3.source == "gold"
    assert top1.sample > 0
    assert 0.0 <= top1.value <= 1.0
    assert top3.value >= top1.value          # top-3 recall cannot be lower


def test_ambiguity_recall_measures_against_expected_asks():
    m = gold_ambiguity_recall()
    assert m.source == "gold"
    assert m.sample > 0
    assert 0.0 <= m.value <= 1.0


# ── the report ────────────────────────────────────────────────────────────────
def test_an_empty_log_clears_no_stage():
    report = build_report([], include_gold=False)
    assert report["cleared"] == []
    assert report["stages"]["shadow_ready"]["clear"] is False


def test_a_report_over_real_lines_measures_what_it_can():
    records = parse_log([_observe("general", "general"), _shadow(),
                         _trace("quick", "commit")])
    report = build_report(records, include_gold=False)
    assert report["records"] == 3
    assert report["metrics"]["nutrition_agreement"]["sample"] == 1
    assert report["metrics"]["coordinator_route_agreement"]["value"] == 1.0


def test_the_report_formats_readably():
    report = build_report(parse_log([_shadow()]), include_gold=False)
    text = format_report(report)
    assert "nutrition readiness" in text
    assert "shadow_ready" in text and "canary_safe" in text
    assert "next:" in text
    assert "is a gate you cannot yet answer" in text


def test_gold_metrics_join_the_report_when_asked():
    report = build_report([], include_gold=True)
    assert "branded_top1_accuracy" in report["metrics"]
    assert report["metrics"]["branded_top1_accuracy"]["source"] == "gold"


def test_every_gate_name_is_produced_by_some_metric():
    """A gate nothing computes is a gate that silently never fails."""
    report = build_report(parse_log([_shadow(), _trace()]), include_gold=True)
    produced = set(report["metrics"])
    missing = set(GATES) - produced
    # These four need production signals that only exist post-promotion; they
    # are declared so they cannot be forgotten, and are reported as unmeasured
    # rather than quietly absent.
    assert missing <= {"duplicate_commit", "stale_clarification_mutation",
                       "snapshot_card_mismatch",
                       "package_vs_consumed_confusion",
                       "strict_unresolved_after_3_rounds"}


# ── gates are staged, because they are not all answerable at once ─────────────
def test_every_gate_declares_the_stage_it_becomes_answerable():
    """The original flat gate set made "all pass before promotion" unreachable:
    a duplicate-commit rate cannot exist before anything commits natively, yet
    the overall verdict required it to pass."""
    for name, gate in GATES.items():
        assert "stage" in gate, name
        assert isinstance(gate["stage"], Stage), name


def test_post_promotion_gates_are_not_in_the_shadow_stage():
    """These need a native write to have happened. Holding shadow readiness on
    them is asking a question nothing can answer yet."""
    for name in ("duplicate_commit", "stale_clarification_mutation",
                 "snapshot_card_mismatch", "package_vs_consumed_confusion",
                 "wrong_item_binding"):
        assert GATES[name]["stage"] is Stage.CANARY, name


def test_shadow_gates_are_all_answerable_from_logs_or_the_gold_suite():
    for name in ("branded_top1_accuracy", "branded_top3_recall",
                 "material_ambiguity_recall", "coordinator_route_agreement",
                 "resolution_unresolved_rate", "resolver_crash_rate"):
        assert GATES[name]["stage"] is Stage.SHADOW, name


def test_a_later_stage_cannot_hold_back_an_earlier_one():
    """The whole point of the split: canary gates being unmeasured must not
    make shadow readiness unreachable."""
    report = build_report([], include_gold=True)
    shadow = report["stages"]["shadow_ready"]
    canary = report["stages"]["canary_safe"]
    assert canary["unmeasured"] > 0
    # Shadow's verdict is decided only by shadow gates.
    assert shadow["fail"] == 0
    assert shadow["insufficient"] + shadow["unmeasured"] > 0


def test_the_report_names_one_next_action():
    report = build_report([], include_gold=False)
    assert "shadow_ready" in report["next_action"]


def test_resolver_crash_rate_is_computed_not_just_declared():
    """A promotion gate nothing computes is a gate that silently never fails."""
    records = parse_log([_shadow(ns="error"), _shadow(ns="off"),
                         _shadow(ns="off"), _shadow(ns="off")])
    assert resolver_crash_rate(records).value == 0.25


def test_every_gate_is_produced_by_some_metric():
    report = build_report(parse_log([_shadow(), _trace()]), include_gold=True)
    produced = set(report["metrics"])
    missing = set(GATES) - produced
    # What remains needs post-promotion signals and is reported as unmeasured
    # rather than quietly absent.
    assert missing <= {"duplicate_commit", "stale_clarification_mutation",
                       "snapshot_card_mismatch",
                       "package_vs_consumed_confusion",
                       "strict_unresolved_after_3_rounds"}


# ── findings from the Codex review on #26 ─────────────────────────────────────
def test_the_median_is_the_middle_of_an_even_sample():
    """50 and 210 is a median of 130, not 210. Picking the upper middle
    overstates the typical disagreement in exactly the direction that makes a
    rollout look riskier than it is."""
    records = parse_log([_shadow(lc=100, nc=150, agree="NO"),
                         _shadow(lc=100, nc=310, agree="NO")])
    assert macro_delta(records).value == 130.0


def test_the_median_still_works_on_an_odd_sample():
    records = parse_log([_shadow(lc=100, nc=150, agree="NO"),
                         _shadow(lc=100, nc=200, agree="NO"),
                         _shadow(lc=100, nc=400, agree="NO")])
    assert macro_delta(records).value == 100.0


def test_an_unresolved_result_never_scores_as_a_correct_identity():
    """resolve() copies canonical_name from the REQUEST when nothing survives
    validation. For any gold case whose request text equals the expected
    identity, a name match alone would score a rejected-everything turn as
    correct — leaving the branded-accuracy gate falsely green after a validator
    regression."""
    from skills.nutrition.readiness import gold_identity_accuracy
    # A case that resolves to nothing, whose request text IS the expected name.
    from skills.nutrition.provenance import MatchGrade, SourceTier
    case = {
        "id": "everything-rejected", "category": "branded",
        "request": {"food_name": "Ghost Product", "raw_quantity": "100g",
                    "brand": "Ghost"},
        "candidates": [{"source": "off", "tier": SourceTier.BRANDED_EXACT,
                        "name": "Totally Different Thing", "basis": "per_100g",
                        "grade": MatchGrade.EXACT, "brand": "Rival",
                        "values": {"calories": 100}}],
        "expect": {"identity": "Ghost Product"},
    }
    top1, _ = gold_identity_accuracy([case])
    assert top1.sample == 1
    assert top1.value == 0.0        # not 1.0


def test_a_declared_gate_with_no_metric_still_counts_as_unmeasured():
    """Otherwise a gate nothing computes is absent from the verdict entirely,
    and a stage reports clear while several of its gates were never answered."""
    report = build_report([], include_gold=False)
    for name in ("duplicate_commit", "snapshot_card_mismatch",
                 "package_vs_consumed_confusion",
                 "stale_clarification_mutation"):
        assert name in report["metrics"], name
        assert report["metrics"][name]["verdict"] == "unmeasured", name
    assert report["stages"]["canary_safe"]["clear"] is False


def test_a_gold_suite_failure_cannot_silently_drop_its_gates():
    """The same hole from the other direction: if the gold metrics never get
    appended, their gates must still be counted as unanswered."""
    report = build_report([], include_gold=False)
    for name in ("branded_top1_accuracy", "branded_top3_recall",
                 "material_ambiguity_recall"):
        assert report["metrics"][name]["verdict"] == "unmeasured", name
    assert report["stages"]["shadow_ready"]["clear"] is False
