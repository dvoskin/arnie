"""should_run_scribe gate behavior (the live scribe entry point).

The distinct_missing_items reconcile tests moved with the helper to
scripts/stress_completeness.py (2026-07-24 cleanup): production partial-drop
rescue is the count-gated fuzzy unlogged_items path, covered by
tests/test_deterministic_partial_drop.py."""
from core.scribe import should_run_scribe


def test_should_run_scribe_covers_food_turns_skips_chatter():
    assert should_run_scribe("had a turkey sandwich and rice")
    assert should_run_scribe("eggs bacon toast")          # space-separated list
    assert should_run_scribe("175g turkey and 100g rice")
    assert not should_run_scribe("ok")                    # ack
    assert not should_run_scribe("thanks")
    assert not should_run_scribe("how many calories in a bagel?")   # question
    assert not should_run_scribe("")
