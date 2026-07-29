"""The text no model wrote is held to the persona's rules anyway.

Of the eleven things in this system that produce user-visible text, two derive
from the canonical voice. The rest are deterministic floors —
`_deterministic_line`, `clarify_text_from_points`, `enforce_say_contract`'s
tokenized line, the `fallback()` family — and they run when the composer has
already failed twice, an outage is in progress, or the flag is off. Which is
to say: the paths where sounding like a different product does the most damage
are the paths with no derivation at all.

They cannot be sent through a model without ceasing to be the floor. So they
get the rules mechanically instead, from the same source the briefs are
compiled from — `voice.check()` — and this file runs every one of them
through it.

It found a real violation on the first pass. The canonical voice ends:

    never one bubble alone after logging food.

and `_deterministic_line` was one bubble. So the rule the composer is held to
was broken by the thing that speaks when the composer fails. Two ideas were
already there — what happened, then where the day stands — joined with a
space; they are joined with a ||| now.

`banned_phrases()` is lifted from the persona's own declarations rather than
retyped, so adding a phrase there bans it here. The extraction is scoped by
STRUCTURE (a comma-separated run) rather than proximity, because scoping it by
paragraph swallowed the line right after the list — the persona demonstrating
the correct deflection — and banning the example of good behaviour is the
failure mode of extracting by nearness.
"""
import pytest

from core.food_ledger import (TransactionSnapshot, _deterministic_line,
                              render_committed)
from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, fallback)
from core.food_turn import clarify_text_from_points, enforce_say_contract
from core.prompts import voice as V

SNAP = TransactionSnapshot(batch_cal=350, batch_protein=25, day_cal=1450,
                           day_protein=95, cal_target=2200, protein_target=160,
                           logged=("Rice cake", "Greek yogurt"))
UNDO = TransactionSnapshot(day_cal=1100, day_protein=70, cal_target=2200,
                           protein_target=160, deleted=("Fries",))
EDIT = TransactionSnapshot(batch_cal=95, day_cal=1545, day_protein=95,
                           cal_target=2200, protein_target=160,
                           updated=("Cheeseburger",))
CALLS = [{"input": {"food_name": "Rice cake", "quantity": "1 cake"}}]


def _plan(intent) -> FoodResponsePlan:
    return FoodResponsePlan(
        intent=intent,
        committed_items=(FoodItemSummary(name="Rice cake"),),
        committed_snapshot=SNAP)


#: (name, text, did-this-turn-log-food). Every deterministic producer the user
#: can actually read.
FLOORS = [
    ("_deterministic_line/log", _deterministic_line(SNAP), True),
    ("_deterministic_line/undo", _deterministic_line(UNDO), False),
    ("_deterministic_line/edit", _deterministic_line(EDIT), False),
    ("render_committed", render_committed("", "", "", SNAP), True),
    ("render_committed/regular",
     render_committed("", "", "save_as_regular", SNAP), True),
    ("enforce_say_contract", enforce_say_contract("", CALLS), True),
    ("clarify_text_from_points",
     clarify_text_from_points([{"label": "Chicken",
                                "qs": ["grilled, baked, or fried?"]}],
                              ["Bagel"]), False),
    ("fallback/commit", fallback(_plan(FoodResponseIntent.COMMIT)), True),
    ("fallback/failure", fallback(_plan(FoodResponseIntent.FAILURE)), False),
    ("fallback/clarify", fallback(_plan(FoodResponseIntent.CLARIFY)), False),
    ("fallback/undo", fallback(_plan(FoodResponseIntent.UNDO)), False),
    ("fallback/correct", fallback(_plan(FoodResponseIntent.CORRECT)), False),
]


@pytest.mark.parametrize("name,text,logged", FLOORS,
                         ids=[f[0] for f in FLOORS])
def test_every_deterministic_floor_passes_the_voice_check(name, text, logged):
    violations = V.check(text, after_food_log=logged)
    assert not violations, (
        f"{name} → {text!r}\n  " +
        "\n  ".join(f"{v.rule}: {v.detail}" for v in violations))


@pytest.mark.parametrize("name,text,_l", FLOORS, ids=[f[0] for f in FLOORS])
def test_no_floor_is_silent(name, text, _l):
    """A floor that says nothing is not a floor. The composer returning "" is
    a legal outcome; the thing that catches it returning "" is not."""
    assert text and text.strip()


def test_the_commit_floor_is_two_bubbles():
    """The violation this file found. One bubble after a food log is forbidden
    by the last line of the canonical voice."""
    assert _deterministic_line(SNAP).count("|||") == 1


def test_the_tokenized_say_floor_is_two_bubbles():
    assert enforce_say_contract("", CALLS).count("|||") == 1


def test_a_turn_that_wrote_nothing_needs_no_second_bubble():
    """The rule is about logging food. A snapshot with no action is just a
    day position, and padding it would be the template talking."""
    bare = TransactionSnapshot(day_cal=1100, cal_target=2200,
                               protein_target=160)
    assert "|||" not in _deterministic_line(bare)


def test_the_follow_up_bubble_still_rides_on_top():
    text = render_committed("", "", "save_as_regular", SNAP)
    assert text.count("|||") == 2, "action ||| day ||| offer"
    assert "regulars" in text.split("|||")[-1]


# ── the checker itself is bound to the persona ───────────────────────────────
def test_the_ban_list_comes_from_the_persona():
    banned = V.banned_phrases()
    assert "as an AI" in banned and "Great job!" in banned


def test_a_new_ban_in_the_persona_propagates(monkeypatch):
    """The propagation proof, for the mechanical side."""
    from core.prompts import arnie as canon
    monkeypatch.setattr(canon, "IDENTITY", canon.IDENTITY.replace(
        '"as a language model".', '"as a language model", "beep boop".'))
    assert "beep boop" in V.banned_phrases()
    assert any(v.rule == "banned_phrase"
               for v in V.check("Logged. beep boop."))


def test_the_persona_s_own_good_example_is_not_banned():
    """Scoping the extraction by paragraph swallowed the deflection line right
    after the list. Banning the example of good behaviour is what extracting
    by proximity gets you."""
    assert not any("all that matters" in p for p in V.banned_phrases())


@pytest.mark.parametrize("bad,rule", [
    ("Successfully logged 1 x rice cake.", "receipt"),
    ("The resolver could not find that.", "machinery"),
    ("As an AI I can't be sure.", "banned_phrase"),
    ("Great job! Logged.", "banned_phrase"),
    ("Logged ~350 cal.", "tilde"),
    ("Logged — nice one.", "em_dash"),
    ("LOGGED that for you.", "shouting"),
    ("Validation failed on that entry.", "machinery"),
])
def test_the_checker_catches_what_a_person_would_never_type(bad, rule):
    assert rule in {v.rule for v in V.check(bad)}


def test_a_clean_line_is_clean():
    assert not V.check("Rice cake logged, 350 cal.|||You're at 1450.",
                       after_food_log=True)
