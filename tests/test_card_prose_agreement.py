"""A card may not contradict its own numbers.

From the live session:

    Card:   Chicken thigh, grilled teriyaki marinated  (2 thighs)
            370 cal · 62g protein
            822 cal left · 38g protein to go
            ● Strong protein hit — the day closes clean from here.

    Prose:  Protein is running light, though, about 38g to go.

The prose was right. The card's own remaining figure was right. The sentence
between them was wrong, and it came from the model: `_logged_entry_card` lets
`coach_read` overwrite the deterministic verdict because "varied and contextual
beats canned", guarded only by "short" and "carries no digits".

Both guards passed. Neither looked at the snapshot the rest of the payload was
built from — which is sitting in the same dict.
"""
from core.receipt import coach_read_contradicts as contradicts


# ── the shipped failure ───────────────────────────────────────────────────────
def test_the_shipped_card_sentence_is_rejected():
    assert contradicts("Strong protein hit — the day closes clean from here.",
                       {"remaining_protein": 38})


def test_the_prose_that_was_right_is_not_rejected():
    assert not contradicts("Protein is running light", {"remaining_protein": 38})


# ── the four claims that are checkable ────────────────────────────────────────
def test_claiming_protein_is_done_while_short():
    for line in ("Protein's handled for the day.", "Protein landed.",
                 "You hit your protein.", "Protein's covered."):
        assert contradicts(line, {"remaining_protein": 12}), line


def test_claiming_protein_is_short_while_hit():
    assert contradicts("One more protein-forward meal gets you to your target.",
                       {"remaining_protein": -5})


def test_claiming_room_while_over():
    assert contradicts("You still have room for a full meal.",
                       {"remaining_cal": -200})


def test_claiming_over_while_under():
    assert contradicts("You're over target for the day.",
                       {"remaining_cal": 400})


# ── what must NOT be second-guessed ───────────────────────────────────────────
def test_the_deterministic_verdicts_pass_their_own_check():
    """Every line receipt.py can produce must survive the guard on the state
    that produces it — otherwise the guard is rejecting the truth."""
    assert not contradicts(
        "Protein's handled for the day — calories are the thing to watch now.",
        {"remaining_protein": 0})
    assert not contradicts("One more protein-forward meal gets you to your target.",
                           {"remaining_protein": 40})
    assert not contradicts("You're over target for the day, so keep the rest of it clean.",
                           {"remaining_cal": -300})


def test_a_line_making_no_checkable_claim_is_left_alone():
    """The point is to stop a sentence and a figure disagreeing, not to police
    the writing."""
    for line in ("That's a solid anchor to build the rest of the day on.",
                 "Good protein after training.",
                 "Nice clean base."):
        assert not contradicts(line, {"remaining_protein": 38,
                                      "remaining_cal": 400}), line


def test_no_receipt_means_nothing_to_contradict():
    assert not contradicts("Protein's handled for the day.", None)
    assert not contradicts("Protein's handled for the day.", {})


def test_an_empty_coach_line_is_not_a_contradiction():
    assert not contradicts("", {"remaining_protein": 38})
