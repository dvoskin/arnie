"""The latency report's math and budgets (B5).

`summarize` was extracted from `main` precisely so this can run without a
Postgres: the percentile and pass/fail logic is what a launch gate is scored on,
and it should be tested, not trusted.
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "latency_report", ROOT / "scripts" / "latency_report.py")
LR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LR)


def test_pct_picks_the_right_order_statistic():
    v = list(range(1, 101))          # 1..100, nearest-rank on a 0-indexed sort
    assert LR.pct(v, 50) == 51       # idx round(0.5*99)=50 → v[50]
    assert LR.pct(v, 95) == 95       # idx round(0.95*99)=94 → v[94]
    assert LR.pct(v, 99) == 99       # idx round(0.99*99)=98 → v[98]
    assert LR.pct([], 95) == 0        # empty is 0, never a crash


def _rows(key, totals, outcome="ok", stages='{"llm": 1}'):
    return [(key, outcome, t, stages) for t in totals]


def test_summarize_scores_turn_against_its_budget():
    # p95 over the 6000ms turn budget → FAIL; a fast set → PASS.
    slow = LR.summarize(_rows("turn", [1000, 2000, 3000, 9000] * 6))
    row = {r["key"]: r for r in slow}["turn"]
    assert row["budget"] == 6000 and row["verdict"] == "FAIL"

    fast = LR.summarize(_rows("turn", [800, 900, 1000, 1100] * 6))
    assert {r["key"]: r for r in fast}["turn"]["verdict"] == "PASS"


def test_summarize_counts_errors_and_flags_small_samples():
    rows = _rows("turn", [1000, 2000]) + [("turn", "error:DeadlineExceeded", 6100, "{}")]
    row = {r["key"]: r for r in LR.summarize(rows)}["turn"]
    assert row["err"] == 1
    assert row["indicative"] is True        # n<20


def test_summarize_breaks_down_stage_p95_and_sorts_by_volume():
    busy = _rows("turn", [1000] * 30, stages='{"llm": 700, "tools": 200}')
    rare = _rows("log_food", [300] * 3)
    out = LR.summarize(busy + rare)
    assert out[0]["key"] == "turn"          # busiest route first
    assert out[0]["stage_p95"] == {"llm": 700, "tools": 200}


def test_unbudgeted_key_has_no_verdict():
    row = {r["key"]: r for r in LR.summarize(_rows("chat_misc", [100, 200]))}["chat_misc"]
    assert row["budget"] is None and row["verdict"] == ""
