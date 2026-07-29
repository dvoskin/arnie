"""One line per food turn that can answer "where did the time go, and who paid".

The trace already recorded what a turn DECIDED — stages reached, items staged,
committed, held, where it stopped. It could not answer any latency question
asked of it. Time-to-first-byte, token counts, which signal owned the routing,
whether enrichment actually overlapped, which renderer spoke, how many retries
were paid for, and when the user first saw anything were recorded nowhere, and
`legacy_escape_reason` lived in a different log line — so "which escapes are
the slow ones" needed two greps and a join nobody wrote.

The rules this file pins are the ones that make the aggregate honest:

  * A stage that runs per item is SUMMED. `resolve` runs once per food, and
    last-wins would score a four-item meal as a one-item meal that got
    unlucky.
  * A moment is stamped once. `first_visible` means "when did the user stop
    waiting"; a later bubble overwriting it answers a question `complete_ms`
    already answers.
  * A moment that never happened prints `-`, never `0`. Zero is a real and
    very different reading, and a report that conflates them scores every turn
    that showed the user nothing as instantaneous.
  * Per-stage millisecond figures are DERIVED from the stage records, never
    stored beside them, so the two cannot disagree.
"""
import re

import pytest

from core.food_trace import FoodTurnTrace, Outcome, Stage


def _trace(**kw) -> FoodTurnTrace:
    return FoodTurnTrace(turn_id="t1", user_id=7, mode="moderate",
                         channel="ios", **kw)


# ── stage arithmetic ─────────────────────────────────────────────────────────
def test_a_per_item_stage_is_summed_not_last_wins():
    t = _trace()
    t.record(Stage.RESOLVE, duration_ms=1200)
    t.record(Stage.RESOLVE, duration_ms=900)
    assert t.stage_ms(Stage.RESOLVE) == 2100


def test_a_stage_that_never_ran_costs_nothing():
    assert _trace().stage_ms(Stage.EXECUTE) == 0


def test_stage_ms_takes_the_enum_or_its_value():
    t = _trace()
    t.record(Stage.INTERPRET, duration_ms=3900)
    assert t.stage_ms(Stage.INTERPRET) == t.stage_ms("interpret") == 3900


def test_the_reported_stage_time_is_derived_from_the_records():
    """Not a second field somebody has to remember to update."""
    t = _trace()
    t.record(Stage.INTERPRET, duration_ms=1000)
    assert t.as_dict()["interpreter_total_ms"] == 1000
    t.record(Stage.INTERPRET, duration_ms=500)
    assert t.as_dict()["interpreter_total_ms"] == 1500


def test_no_stage_millis_are_reported_for_stages_nobody_stamps():
    """A figure arrives with the code that records it.

    `route_ms` and `context_load_ms` were absent here until ROUTE and CONTEXT
    were actually stamped, and they are asserted present in
    `test_the_trace_says_who_routed_the_turn`. `snapshot_ms` and
    `validation_ms` are the remaining two the latency report asks for and
    nothing writes: an enum member nothing stamps reports every turn as
    validating in 0 ms, which is worse than reporting nothing at all.
    """
    d = _trace().as_dict()
    assert "snapshot_ms" not in d and "validation_ms" not in d


# ── moments ──────────────────────────────────────────────────────────────────
def test_a_moment_is_stamped_once():
    t = _trace()
    t.mark("first_visible")
    first = t.marks["first_visible"]
    for _ in range(3):
        t.mark("first_visible")
    assert t.marks["first_visible"] == first


def test_a_moment_that_never_happened_is_not_zero():
    t = _trace()
    assert t._mark_str("first_visible") == "-"
    assert "first_visible_ms=-" in t.log_line()


def test_a_real_zero_still_reads_as_zero():
    t = _trace()
    t.mark("first_visible")
    assert t._mark_str("first_visible") != "-"
    assert re.search(r"first_visible_ms=\d", t.log_line())


def test_marks_ride_in_the_dict_too():
    t = _trace()
    t.mark("commit_visible")
    assert "commit_visible" in t.as_dict()["marks"]


# ── the fields the latency report asks for ───────────────────────────────────
LATENCY_FIELDS = ("route_owner", "legacy_escape_reason", "interpreter_model",
                  "interpreter_ttfb_ms", "interpreter_input_tokens",
                  "interpreter_output_tokens", "interpreter_cached_tokens",
                  "enrichment_overlap_ms", "voice_profile", "voice_model",
                  "voice_ttfb_ms", "retry_count", "fallback_path")


@pytest.mark.parametrize("field", LATENCY_FIELDS)
def test_every_latency_field_survives_note_and_reaches_the_dict(field):
    t = _trace()
    value = 1 if field.endswith(("_ms", "_tokens", "_count")) else "x"
    t.note(**{field: value})
    assert t.as_dict()[field] == value


def test_note_still_ignores_a_field_that_does_not_exist():
    """A tracer must never fail a turn because a caller passed a name it does
    not have."""
    t = _trace()
    t.note(not_a_field="boom")
    assert not hasattr(t, "not_a_field")


def test_a_retry_count_of_zero_is_recordable():
    """`note` skips None, not falsy — "no retries" has to be sayable."""
    t = _trace()
    t.note(retry_count=0)
    assert t.as_dict()["retry_count"] == 0


# ── the line stays greppable ─────────────────────────────────────────────────
def _tokens(line: str) -> dict:
    assert line.startswith("event=food_trace ")
    return dict(p.split("=", 1) for p in line.split(" ") if "=" in p)


def test_the_line_is_one_token_per_field():
    """Whole-line integrity: a value containing a space silently truncates the
    field when read back, which is how every stage but the first once vanished
    from the latency report."""
    t = _trace()
    t.record(Stage.INTERPRET, duration_ms=3900)
    t.note(route_owner="thread", interpreter_model="claude-sonnet-5",
           fallback_path="deterministic", legacy_escape_reason="-")
    line = t.log_line()
    assert line.count("  ") == 0
    for pair in line.split(" "):
        assert "=" in pair, f"stray token {pair!r} — a value contained a space"


@pytest.mark.parametrize("key", [
    "route_owner", "legacy_escape", "interp_model", "interp_ttfb_ms",
    "interp_in", "interp_out", "interp_cached", "enrich_overlap_ms",
    "voice_profile", "voice_model", "voice_ttfb_ms", "retries", "fallback",
    "first_visible_ms", "commit_visible_ms", "complete_ms"])
def test_the_latency_half_is_present(key):
    assert f"{key}=" in _trace().log_line()


@pytest.mark.parametrize("key", [
    "turn", "user", "mode", "channel", "cohort", "stopped_at", "total_ms",
    "staged", "ready", "attempted", "committed", "failed", "held", "asked",
    "assumed", "source", "promoted", "error", "meal", "timings"])
def test_the_decision_half_is_unchanged(key):
    """Additive only — the existing report and every grep against it keep
    working."""
    assert f"{key}=" in _trace().log_line()


def test_an_empty_string_field_prints_a_dash_not_nothing():
    line = _trace().log_line()
    assert "route_owner=- " in line and "fallback=- " in line


def test_the_funnel_still_reports_where_the_turn_stopped():
    t = _trace()
    t.record(Stage.INTERPRET, duration_ms=10)
    t.record(Stage.CLARIFY, duration_ms=5, outcome=Outcome.ASKED)
    t.record(Stage.RENDER, duration_ms=900)
    assert t.stopped_at == "clarify"
