"""Execution state reaches the reply, or the disclosure is decorative.

`fc682d5` taught the executor to stash `correction_unpriced` when an identity
changed and no source could price it, and taught the reply to disclose it. The
two halves never met:

  * `stash()` writes to the ambient CALL_CTX and says so — "the command input
    is NEVER written" (executor immutability, P0.3e).
  * `ok_tool_calls()` hands back `{name, input: raw_input}` — the command, with
    none of that context.
  * The reply read `_ci.get("correction_unpriced")` off that raw input.

So the list stayed empty on every turn and the disclosure never fired. Its test
asserted that the executor's SOURCE TEXT contains the string
"correction_unpriced" — which it does — so a grep stood in for the behaviour
and the gap survived a release.

These tests pin the seam itself: the side that carries execution state, and the
join used to reach it.
"""
from core.execution_result import CallResult, from_call_contexts, stash


def _batch():
    inp = {"entry_id": 4, "food_name": "Shrimp, deep fried"}
    return inp, [{"name": "update_food_entry", "input": inp}]


# ── the seam, stated ─────────────────────────────────────────────────────────

def test_stashing_does_not_reach_the_command(monkeypatch):
    """The property the reply relied on and did not have."""
    from core.execution_result import CALL_CTX
    inp = {"entry_id": 4}
    token = CALL_CTX.set({})
    try:
        stash(inp, "correction", {"renamed": True})
        assert "correction" not in inp, (
            "the command is immutable — anything reading execution state off "
            "it reads nothing")
        assert CALL_CTX.get()["correction"] == {"renamed": True}
    finally:
        CALL_CTX.reset(token)


def test_the_outcome_arrives_on_the_typed_call():
    inp, calls = _batch()
    ctx = [{"result": "Updated.",
            "correction": {"renamed": True, "moved_numbers": False}}]
    ex = from_call_contexts(calls, ctx)
    assert ex.calls[0].correction == {"renamed": True, "moved_numbers": False}


def test_the_typed_call_is_joinable_by_the_command_it_ran():
    """The reply joins typed calls to `ok_tool_calls()` dicts by `id(input)`;
    if `raw_input` were a copy the join would silently miss every time."""
    inp, calls = _batch()
    ex = from_call_contexts(calls, [{"result": "Updated.", "correction": {}}])
    assert id(ex.calls[0].raw_input) == id(inp)
    assert id(ex.ok_tool_calls()[0]["input"]) == id(inp)


def test_a_call_with_no_outcome_carries_none_rather_than_an_empty_shape():
    inp, calls = _batch()
    ex = from_call_contexts(calls, [{"result": "Updated."}])
    assert ex.calls[0].correction is None


def test_a_non_dict_outcome_is_refused():
    inp, calls = _batch()
    ex = from_call_contexts(calls, [{"result": "Updated.", "correction": "yes"}])
    assert ex.calls[0].correction is None


# ── what the reply now asks of it ────────────────────────────────────────────

def test_a_rename_that_moved_no_number_is_the_disclosable_shape():
    """Covers both failures the user cannot tell apart: the ladder returned
    nothing, and the ladder returned the same number it already had."""
    unpriced = CallResult(name="update_food_entry", raw_input={}, status="committed",
                          correction={"renamed": True, "moved_numbers": False,
                                      "unpriced": True})
    priced_the_same = CallResult(name="update_food_entry", raw_input={},
                                 status="committed",
                                 correction={"renamed": True,
                                             "moved_numbers": False,
                                             "unpriced": False})
    for call in (unpriced, priced_the_same):
        c = call.correction
        assert c["renamed"] and not c["moved_numbers"]


def test_a_rename_that_did_move_the_number_is_not_disclosed():
    call = CallResult(name="update_food_entry", raw_input={}, status="committed",
                      correction={"renamed": True, "moved_numbers": True,
                                  "unpriced": False})
    c = call.correction
    assert not (c["renamed"] and not c["moved_numbers"])
