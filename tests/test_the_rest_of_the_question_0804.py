"""Answering ONE of two questions must not end the structured turn.

The whole 2026-08-04 transcript is this branch. Arnie asked two things in one
breath — how the chicken was cooked, and how much of it. The user tapped "60g",
which answers the second. The interpreter came back with an ask for the first,
still unanswered and still correct.

`food_turn.py`'s never-loop guard then threw it away. It allows a re-ask only
when the user invited one ("don't you wanna know what kind?") or the model
flagged a NEW ambiguity — and the remaining half of the original question is
neither. So `_run_untraced` returned None, `run()`'s `_settle_deferred` took the
`out is None` arm, wrote the held rice as a `_writes_only` side effect, and the
turn fell to legacy.

Everything the user saw follows from that one None:

  * legacy re-asked in prose — "60g gives you 99 cal, but I still need cook
    method for the chicken, grilled, baked, or fried?" — which proves the
    question survived and only its STRUCTURE was lost;
  * so that re-ask carried no chips, on the one turn the user had already
    answered once and least deserved to type;
  * the rice committed with no card (see the sibling fix in
    `_settle_expired_deferred`), moving the day total against nothing visible;
  * and the fallback logged `reason=interpreter_none`, which reads as a model
    failure, so the only trace of the real cause said something untrue.

The guard is not removed. It is replaced with a stronger test than a counter:
a re-ask is allowed when it asks about STRICTLY FEWER things than the ask
before it, all of them already asked. A strictly shrinking finite set reaches
empty, so the exchange provably terminates — and it terminates by running out
of questions rather than by running out of patience. A counter cannot make that
distinction at all, because it cannot tell a second question from the second
half of the first one.
"""
import pytest

from core.food_turn import _asks_strictly_less


def _q(item, text):
    return {"item": item, "text": text}


def _p(label, *qs):
    return {"label": label, "qs": list(qs)}


ASKED_BOTH = {"questions": [_q("Chicken", "Grilled, baked, or fried?"),
                            _q("Chicken", "And rough amount?")]}
ASKED_ONE = {"questions": [_q("Chicken", "Grilled, baked, or fried?")]}


def test_the_live_case_one_of_two_answered():
    """"Having some chicken and rice" -> two questions -> user taps "60g".
    The cook method is still open and must stay in the structured lane."""
    assert _asks_strictly_less([_p("Chicken", "grilled or fried?")],
                               ASKED_BOTH) is True


def test_it_terminates():
    """THE PROPERTY THAT REPLACES THE COUNTER. One question was asked, one
    comes back — nothing shrank, so the answer is no. There is no sequence of
    turns where this keeps saying yes, because the set is finite and must get
    strictly smaller every time it does."""
    assert _asks_strictly_less([_p("Chicken", "grilled or fried?")],
                               ASKED_ONE) is False


def test_a_new_food_is_still_a_new_question():
    """The behaviour the guard exists for. The model chaining a question about
    something it never asked about is exactly the loop being prevented, and it
    is refused whether or not it asks about fewer things."""
    assert _asks_strictly_less([_p("Rice", "how much rice?")],
                               ASKED_BOTH) is False


def test_a_new_food_smuggled_in_beside_an_old_one():
    """Refused on BOTH halves — it does not shrink, and one of its points was
    never asked. Either alone would be enough."""
    assert _asks_strictly_less(
        [_p("Chicken", "cooked how?"), _p("Rice", "how much?")],
        ASKED_BOTH) is False


@pytest.mark.parametrize("points,prior", [
    (None, None),
    ([], ASKED_BOTH),
    ([_p("Chicken", "x")], {}),
    ([_p("Chicken", "x")], {"questions": []}),
    ([_p("", "x")], ASKED_BOTH),                    # unlabelled matches nothing
    ([{"not": "a point"}], ASKED_BOTH),
    (["a bare string"], ASKED_BOTH),
    ([_p("Chicken", "x")], {"questions": [{"item": ""}, {"item": None}]}),
])
def test_it_fails_closed(points, prior):
    """Every malformed shape resolves to "this is a new question", which is the
    safe direction: the worst case is the behaviour that shipped before this
    existed, never an unbounded exchange."""
    assert _asks_strictly_less(points, prior) is False


def test_the_match_is_on_the_food_not_the_wording():
    """The model rephrases freely between turns — "how was it cooked" one turn,
    "grilled or fried" the next. The food is the part that has to be stable,
    because it is what the answer binds to."""
    assert _asks_strictly_less(
        [_p("chicken", "was it grilled at all?")],
        {"questions": [_q("Chicken", "How was the chicken cooked?"),
                       _q("Chicken", "About how much?")]}) is True
