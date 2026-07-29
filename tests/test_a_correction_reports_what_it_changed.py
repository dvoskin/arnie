"""A correction's receipt describes the row, not the shape of the command.

`_correction_step` decided what to say from which keys the interpreter had
sent: a `quantity` key meant "Corrected the serving · Macros rescaled to the
new amount", a macro key meant "Corrected the macros · Used the numbers you
gave". Neither is a fact about the turn — `_update_call` fills both from the
MODEL's proposal, so both lines could be printed about things that had not
happened.

Three production turns, 2026-07-29, all on the same shrimp entry and one on a
second user:

  * "Yea they were deep fried" — the name became "Shrimp, deep fried, 7 small"
    and the row stayed at 35 cal / 9g protein. The receipt reported a serving
    correction with macros rescaled. Nothing had been rescaled, and the user
    had to ask "How does it change the total then?" — a question which then
    performed the write the correction should have.
  * "Switch those back to regular small shrimp" — receipt: "Used the numbers
    you gave". The message contains no digits, and the figures being credited
    to the user were the deep-fried ones the correction was reverting.
  * "No no not dollar slices ... they're the sopresseta" — same claim, same
    absence of numbers, 855 cal unchanged.

The executor knows all of this: it holds the row before and after. So the
receipt is read from the outcome, and a provenance claim is made only when the
figures the row now holds appear in the user's own message — the rule the say
contract already applies to digits.
"""
from types import SimpleNamespace

from core.reasoning import build_reasoning


def _receipt(inp, correction, result="Updated."):
    """Render the receipt the way the executor feeds it: outcome on the typed
    call, surfaced onto a derived view of the input.

    `build_reasoning` keys the typed view by `id(raw_input)`, so the call must
    carry the very object the batch does."""
    call = SimpleNamespace(raw_input=inp, result_text=result,
                           sourcing=None, correction=correction)
    return build_reasoning([{"name": "update_food_entry", "input": inp}], {},
                           None, None,
                           execution=SimpleNamespace(calls=(call,)))


def _labels(rec):
    return [s.get("label", "") for s in rec["steps"]]


def _details(rec):
    return [s.get("detail", "") for s in rec["steps"]]


# ── the two claims this stops making ─────────────────────────────────────────

def test_a_preparation_change_that_moved_no_number_does_not_report_a_rescale():
    """"Yea they were deep fried": the name moved, the row did not."""
    rec = _receipt(
        {"entry_id": 1, "quantity": "7 shrimp", "food_name": "Shrimp, deep fried"},
        {"changed": ["food_name"], "moved_numbers": False, "renamed": True,
         "stated_by_user": [], "unpriced": False, "moved_day": False})
    assert not any("rescaled" in d.lower() for d in _details(rec))
    assert any("did not change" in d.lower() for d in _details(rec))


def test_a_correction_with_no_numbers_in_the_message_claims_none_from_the_user():
    """"Switch those back to regular small shrimp" — no digits were typed."""
    rec = _receipt(
        {"entry_id": 1, "calories": 35, "food_name": "Shrimp, regular"},
        {"changed": ["food_name", "calories"], "moved_numbers": True,
         "renamed": True, "stated_by_user": [], "unpriced": False,
         "moved_day": False})
    assert not any("numbers you gave" in d.lower() for d in _details(rec))


def test_a_figure_the_user_actually_typed_is_credited_to_them():
    rec = _receipt(
        {"entry_id": 1, "calories": 80},
        {"changed": ["calories"], "moved_numbers": True, "renamed": False,
         "stated_by_user": ["calories"], "unpriced": False, "moved_day": False})
    assert any("numbers you gave" in d.lower() for d in _details(rec))


# ── the outcomes that had no line at all ─────────────────────────────────────

def test_an_identity_that_could_not_be_priced_says_so():
    """Silence here is what made a user notice for us: "the calories haven't
    updated tho"."""
    rec = _receipt(
        {"entry_id": 1, "_reresolved": "Double cheeseburger"},
        {"changed": ["food_name"], "moved_numbers": False, "renamed": True,
         "stated_by_user": [], "unpriced": True, "moved_day": False})
    joined = " ".join(_labels(rec) + _details(rec)).lower()
    assert "couldn't price" in joined or "could not price" in joined
    assert "previous figures stand" in joined


def test_a_serving_change_that_did_move_the_macros_still_says_rescaled():
    rec = _receipt(
        {"entry_id": 1, "quantity": "1 cucumber"},
        {"changed": ["quantity", "calories"], "moved_numbers": True,
         "renamed": False, "stated_by_user": [], "unpriced": False,
         "moved_day": False})
    assert any("rescaled" in d.lower() for d in _details(rec))


def test_a_serving_change_that_moved_nothing_does_not_claim_a_rescale():
    rec = _receipt(
        {"entry_id": 1, "quantity": "7 shrimp"},
        {"changed": ["quantity"], "moved_numbers": False, "renamed": False,
         "stated_by_user": [], "unpriced": False, "moved_day": False})
    assert not any("rescaled" in d.lower() for d in _details(rec))


def test_a_re_dating_is_reported_as_a_move_not_an_edit():
    """The user said it was yesterday. The row was re-parented, not rewritten."""
    rec = _receipt(
        {"entry_id": 1, "date": "yesterday"},
        {"changed": [], "moved_numbers": False, "renamed": False,
         "stated_by_user": [], "unpriced": False, "moved_day": True})
    assert any("another day" in l.lower() for l in _labels(rec))


# ── the fallback still works where there is no outcome to read ───────────────

def test_a_batch_the_real_executor_did_not_run_still_gets_a_receipt():
    """Mocked executors and direct callers carry no outcome; the older
    key-shape reading stays for them rather than leaving the turn silent."""
    rec = build_reasoning(
        [{"name": "update_food_entry", "input": {"entry_id": 1, "quantity": "2 cups"}}],
        {"update_food_entry": "Updated."})
    assert rec["steps"], "a receipt is still produced without execution state"
