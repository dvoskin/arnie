"""A food turn that has already been slow gets a heads-up; a fast one stays quiet.

`NEEDS_HEADS_UP_TOOLS` gated the interim bubble, and its comment recorded the
rule plainly: "log-only turns NEVER trigger it." That was true of the turn it
was written for — the model picked a tool and the row landed. The structured
lane put an interpreter pass, a shelf lookup and a composer in front of it, and
production food turns now run 9-15 s in silence while `web_search` says
"looking it up." at one second.

The exception is gated on ELAPSED time rather than on a guess about which foods
are slow, which is what keeps it honest in both directions: the wait is a
measured fact by the time tools dispatch, and a turn that got there quickly says
nothing. If the interpreter gets faster, this stops firing without anyone
editing it.

What it must never become is the pre-action narration that `NO TRANSACTION
NARRATION` removed — a bubble claiming a write is underway. It describes a
LOOKUP, which is why it borrows `search_food_database`'s pool.
"""
import core.conversation as C
from handlers.tool_executor import tool_heads_up, NEEDS_HEADS_UP_TOOLS


def test_the_threshold_is_read_where_the_wait_is_already_known():
    """The gate sits after the interpreter pass, so `elapsed` is measured."""
    src = C.__dict__["_run_turn"].__code__.co_consts
    assert C._FOOD_HEADS_UP_AFTER_S > 0
    # The heads-up decision reads the turn clock, not a per-food prediction.
    import inspect
    body = inspect.getsource(C._run_turn)
    assert "_FOOD_HEADS_UP_AFTER_S" in body
    assert "_turn_t0" in body.split("_FOOD_HEADS_UP_AFTER_S")[0][-400:], (
        "the gate must compare against the turn clock, not a food heuristic")


def test_a_log_turn_borrows_the_lookup_wording_not_a_write_claim():
    """The bubble describes checking a source. It may not announce a write."""
    line = tool_heads_up("search_food_database", seed="cheez doodles")
    lowered = line.lower()
    assert lowered.strip(), "a heads-up is never empty"
    for banned in ("logging", "logged", "adding", "saving", "writing"):
        assert banned not in lowered, (
            f"{line!r} claims a write is underway — that is the pre-action "
            f"narration NO TRANSACTION NARRATION removed")


def test_log_food_is_not_in_the_generic_pool():
    """The exception is conditional, in the turn. Adding `log_food` to
    NEEDS_HEADS_UP_TOOLS would fire on every log including instant ones, which
    is the unconditional case the original rule was protecting against."""
    assert "log_food" not in NEEDS_HEADS_UP_TOOLS
    assert "update_food_entry" not in NEEDS_HEADS_UP_TOOLS
