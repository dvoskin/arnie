"""A food on the board is done, not held.

`note_held_items` exists for a real failure — the Dove bar, 2026-07-24: three
foods confirmed, two written, one silently gone. Anything the user saw in
"Locking this in" that is not in the write gets NAMED rather than dropped.

It compared the stash against THIS turn's commits and nothing else. A row
written a turn earlier is in neither list, so it read as missing and was
announced as held. Prod 2026-08-03:

    "Way over target for today, no more coming your way tonight. Holding the
     Challah bread and Honey turkey slices and Jalapenos - tell me which kind
     and it goes on too."

directly under a receipt panel reading "Logged Challah bread, 140 cal / Logged
Honey turkey slices, 68 cal / Logged Jalapenos, 5 cal".

That is worse than saying nothing. It invites the user to answer a question
about a thing already done, and their answer then arrives as a NEW report — a
duplicate the dedup has to catch. The canned tail is the tell that this is a
template and not a judgement: blueberries and fries have no "kind".
"""
from core.food_turn import note_held_items


def _call(name):
    return {"name": "log_food", "input": {"food_name": name}}


def _row(name):
    return {"id": 1, "food": name, "qty": "1", "mins_ago": 3, "cal": 100}


SAY = "Way over target for today, no more coming your way tonight."


def test_a_food_already_on_the_board_is_not_announced_as_held():
    """The transcript, exactly."""
    out = note_held_items(
        SAY,
        [{"food": "Challah bread"}, {"food": "Honey turkey slices"},
         {"food": "Jalapenos"}, {"food": "Mayo"}],
        [_call("Mayo")],
        board=[_row("Challah bread"), _row("Honey turkey slices"),
               _row("Jalapenos")])
    assert "Holding" not in out, out
    assert out == SAY


def test_the_dove_bar_still_gets_named():
    """The failure this function exists for must survive: confirmed, not
    written, not on the board — say so."""
    out = note_held_items(
        SAY,
        [{"food": "Dove bar"}, {"food": "Chicken"}],
        [_call("Chicken")],
        board=[_row("Chicken")])
    assert "Holding the Dove bar" in out, out


def test_this_turns_write_still_counts():
    """A food written THIS turn is not on the board yet — the board snapshot is
    taken before the write — so both lists have to be consulted."""
    out = note_held_items(SAY, [{"food": "Mayo"}], [_call("Mayo")], board=[])
    assert "Holding" not in out, out


def test_a_renamed_row_is_matched_through_THIS_turns_writes():
    """The ask stashed "Challah"; the executor wrote "Challah bread, sliced".

    This asserted the same loose match against the BOARD, and that was the
    weaker premise. A rename happens inside the turn that writes it, where
    `tool_calls` still carries both names — so the loose match belongs there.
    On the board, where rows come from earlier turns, a food that merely
    CONTAINS this name is a different food (Chicken / Chicken wings, Egg /
    Eggplant parm), and matching loosely silences a hold that was real.

    The asymmetry is deliberate and follows the costs: naming a food that turns
    out to be done is an apology, dropping one that was genuinely held is
    silent loss. Err toward naming.
    """
    assert "Holding" not in note_held_items(
        SAY, [{"food": "Challah"}], [_call("Challah bread, sliced")], board=[])


def test_no_board_argument_is_the_old_behaviour():
    """Defaulted so every existing caller keeps working; the food lane passes
    the board explicitly."""
    out = note_held_items(SAY, [{"food": "Dove bar"}], [])
    assert "Holding the Dove bar" in out


# ── but the board is this exchange, not the whole day ─────────────────────────

def _old_row(name, mins):
    return {"id": 9, "food": name, "qty": "1", "mins_ago": mins, "cal": 100}


def test_a_breakfast_row_does_not_silence_a_dinner_hold():
    """Folding the WHOLE day in traded one bug for another. A coffee logged at
    breakfast made "Coffee cake" eight hours later read as already done, and
    the notice — the one thing between a stashed food and silent loss —
    vanished. Every row carries `mins_ago`, so the window costs nothing."""
    out = note_held_items(SAY, [{"food": "Coffee cake"}], [],
                          board=[_old_row("Coffee", 480)])
    assert "Holding the Coffee cake" in out, out


def test_the_board_is_matched_exactly_not_by_substring():
    """On the board a different food that merely CONTAINS this name is a
    different food. Chicken/Chicken wings, Egg/Eggplant parm."""
    out = note_held_items(SAY, [{"food": "Chicken wings"}], [],
                          board=[_old_row("Chicken", 5)])
    assert "Holding the Chicken wings" in out, out


def test_this_turns_write_is_still_matched_loosely():
    """The executor may rename what it writes ("Challah" -> "Challah bread,
    sliced"), so THIS turn's calls keep substring matching in both directions.
    Only the board is exact."""
    out = note_held_items(SAY, [{"food": "Challah"}],
                          [_call("Challah bread, sliced")], board=[])
    assert "Holding" not in out, out
