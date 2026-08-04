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


def test_a_board_row_named_more_precisely_still_matches():
    """The ask stashed "Challah bread"; the row landed as "Challah bread,
    sliced". Substring matching in either direction is what this function has
    always used, and the board must get the same treatment as the writes."""
    out = note_held_items(
        SAY, [{"food": "Challah"}], [], board=[_row("Challah bread, sliced")])
    assert "Holding" not in out, out


def test_no_board_argument_is_the_old_behaviour():
    """Defaulted so every existing caller keeps working; the food lane passes
    the board explicitly."""
    out = note_held_items(SAY, [{"food": "Dove bar"}], [])
    assert "Holding the Dove bar" in out
