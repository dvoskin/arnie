"""The report is scored on percentiles, so its two refusals are the product.

A latency report that guesses is worse than one that abstains, because a
number with a name gets quoted. Two rules, both of which flatter exactly the
turns that failed worst if you get them wrong:

  * `-` means MISSING, never zero. `first_visible_ms=-` is a turn where
    nothing ever reached the user. Scored as 0 ms it becomes the fastest turn
    in the sample and drags the median down — the worst outcome improving the
    metric is how a report starts lying.
  * A tail percentile over too few samples is withheld. p95 of nine turns is
    the second-slowest turn wearing a statistical name; it moves by hundreds
    of milliseconds when one more arrives, and it will be quoted as though it
    were stable.

Parsed from the REAL `FoodTurnTrace.log_line()` rather than hand-written
strings, so a change to the trace's format fails here instead of silently
producing an empty report in production.
"""
import importlib.util
import pathlib

import pytest

from core.food_trace import FoodTurnTrace, Stage

_spec = importlib.util.spec_from_file_location(
    "food_latency_report",
    pathlib.Path(__file__).parent.parent / "scripts" / "food_latency_report.py")
REPORT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(REPORT)


def _line(**kw) -> str:
    """A real trace line, so the parser is tested against the real format."""
    marks = kw.pop("marks", {})
    t = FoodTurnTrace(turn_id="t", user_id=1, mode="moderate", channel="ios")
    t.record(Stage.INTERPRET, duration_ms=3900)
    t.note(**kw)
    t.marks.update(marks)
    return t.log_line()


# ── it reads what the trace actually writes ──────────────────────────────────
def test_it_parses_the_real_trace_format():
    rows = REPORT.parse([_line(route_owner="thread")])
    assert len(rows) == 1 and rows[0]["route_owner"] == "thread"


def test_it_ignores_every_other_log_line():
    noise = ["event=turn_trace route=legacy ms=900",
             "event=food_fast_path_shadow agree=true",
             "INFO some prose that happens to contain route_owner=x"]
    assert REPORT.parse(noise + [_line()]) != []
    assert len(REPORT.parse(noise)) == 0


# ── a dash is missing, not zero ──────────────────────────────────────────────
def test_an_unstamped_moment_is_absent_not_instant():
    row = REPORT.parse([_line()])[0]
    assert row["first_visible_ms"] == "-"
    assert REPORT.num(row, "first_visible_ms") is None


def test_a_silent_turn_does_not_drag_the_median_down():
    """The failure this rule exists to prevent: the turns that showed the user
    nothing becoming the fastest turns in the sample."""
    shown = [_line(marks={"first_visible": 4000.0}) for _ in range(4)]
    silent = [_line() for _ in range(4)]
    rows = REPORT.parse(shown + silent)
    values = REPORT.by(rows, "route_owner", "first_visible_ms")["-"]
    assert values == [4000.0] * 4, "a silent turn was scored as 0 ms"
    assert REPORT.pct(values, 0.50) == 4000.0


def test_a_real_zero_is_still_a_zero():
    row = REPORT.parse([_line(marks={"first_visible": 0.0})])[0]
    assert REPORT.num(row, "first_visible_ms") == 0.0


def test_a_junk_value_is_missing_rather_than_fatal():
    assert REPORT.num({"x": "n/a"}, "x") is None
    assert REPORT.num({}, "x") is None


# ── percentiles ──────────────────────────────────────────────────────────────
def test_a_percentile_is_a_turn_that_actually_happened():
    """Nearest-rank, not interpolation — a quoted p95 should be a real turn."""
    vals = [float(v) for v in range(1, 101)]
    assert REPORT.pct(vals, 0.95) in vals
    assert REPORT.pct(vals, 0.50) in vals


def test_percentiles_are_ordered():
    vals = [float(v) for v in range(1, 101)]
    assert (REPORT.pct(vals, 0.50) <= REPORT.pct(vals, 0.75)
            <= REPORT.pct(vals, 0.95) <= REPORT.pct(vals, 0.99))


def test_no_samples_is_no_answer():
    assert REPORT.pct([], 0.95) is None


def test_a_thin_group_withholds_its_tail(capsys):
    REPORT.table("t", {"sparse": [100.0] * (REPORT.MIN_SAMPLES - 1)})
    out = capsys.readouterr().out
    assert "(thin)" in out
    assert out.count("·") == 3, "p75/p95/p99 must all be withheld"


def test_a_full_group_reports_its_tail(capsys):
    REPORT.table("t", {"dense": [float(v) for v in range(REPORT.MIN_SAMPLES)]})
    out = capsys.readouterr().out
    assert "(thin)" not in out and "·" not in out


# ── the whole thing runs ─────────────────────────────────────────────────────
def test_the_report_runs_on_real_lines(tmp_path, capsys):
    log = tmp_path / "app.log"
    log.write_text("\n".join(
        _line(route_owner="gate_regex" if i % 3 else "gate_model",
              voice_profile="commit", retry_count=i % 7 == 0,
              interpreter_input_tokens=6183,
              interpreter_cached_tokens=5940 if i % 8 else 0,
              marks={"first_visible": 3000.0 + i})
        for i in range(40)))
    assert REPORT.main(["prog", str(log)]) == 0
    out = capsys.readouterr().out
    assert "decision-model gate calls:" in out
    assert "prompt cache:" in out


def test_an_empty_log_is_an_error_not_an_empty_report(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("nothing here\n")
    assert REPORT.main(["prog", str(log)]) == 1
