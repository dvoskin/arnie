"""The false-match rate, as a number that has to go down.

The directive asks for "replay demonstrates lower false-match rates without
unacceptable unresolved growth". That is unanswerable without ground truth, so
this is the ground truth: the collision families the directive itself lists,
labelled, run against the identity functions that own reconciliation today.

It is 36 pairs, not the 1,000+ messages the directive asks for, and it is
authored rather than sampled from production. Both are recorded rather than
glossed. What it buys is the thing the identity migration cannot start without
— a red line under the exact pairs that, confused, delete a row.

TWO KINDS OF WRONG, and they are not equally bad:

  * a FALSE MATCH collapses two foods into one. A row the user reported
    silently disappears, with `outcome=covered` logged over the loss.
  * a MISSED RENAME leaves two readings of one food as two rows. The user sees
    their food twice, which is visible and one tap from repair.

So the false-match count is the number that must reach zero first.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from data.identity_collisions import IDENTITY_PAIRS          # noqa: E402

from core.food_turn import _is_renaming_of                   # noqa: E402


def _score():
    false_match, missed = [], []
    for a, b, same, why in IDENTITY_PAIRS:
        got = _is_renaming_of(a, b)
        if got and not same:
            false_match.append((a, b, why))
        elif same and not got:
            missed.append((a, b, why))
    return false_match, missed


#: BASELINE, measured 2026-08-04 before any identity migration. These numbers
#: are a ratchet: a change may lower them and may not raise them.
BASELINE_FALSE_MATCHES = 1
BASELINE_MISSED_RENAMES = 5


def test_the_false_match_rate_does_not_regress():
    """The number that deletes rows. Must never go up."""
    false_match, _ = _score()
    assert len(false_match) <= BASELINE_FALSE_MATCHES, (
        "identity got MORE likely to delete a row:\n  "
        + "\n  ".join(f"{a!r} vs {b!r} ({why})" for a, b, why in false_match))


def test_the_missed_rename_rate_does_not_regress():
    """The number that duplicates rows. Visible and repairable, so second
    priority — but still a ratchet."""
    _, missed = _score()
    assert len(missed) <= BASELINE_MISSED_RENAMES, (
        "identity got MORE likely to duplicate a row:\n  "
        + "\n  ".join(f"{a!r} vs {b!r} ({why})" for a, b, why in missed))


@pytest.mark.parametrize("a,b,why", [
    p for p in ((a, b, w) for a, b, s, w in IDENTITY_PAIRS if not s)
])
def test_no_distinct_food_is_claimed_by_another(a, b, why):
    """Every DIFFERENT pair, individually, so a failure names the food it would
    have deleted rather than moving a count by one.

    `butter` / `peanut butter` is the known survivor and is xfailed with its
    reason: the head-noun rule is CONSISTENT here — "butter" really is the head
    of "peanut butter" — and being consistent is exactly why a string rule
    cannot fix it. Peanut butter is a distinct food that happens to be a
    butter, which is what `protected_compound` on the entity registry is for.
    """
    if (a, b) == ("butter", "peanut butter"):
        pytest.xfail("protected compound; needs the entity registry, not a "
                     "negative regex")
    assert not _is_renaming_of(a, b), (
        f"{b!r} would claim and delete {a!r} ({why})")


@pytest.mark.parametrize("a,b,why", [
    p for p in ((a, b, w) for a, b, s, w in IDENTITY_PAIRS if s)
])
def test_a_rename_still_collapses(a, b, why):
    """The duplicate-collapse the mechanism exists for must survive every
    narrowing."""
    if (a, b) == ("chicken", "chicken breast"):
        pytest.xfail("a cut is a trailing head noun; correct by the rule, "
                     "wrong for reconciliation — needs entity parentage")
    if a + "s" in b or b.endswith(("es", "ies")):
        pytest.xfail(
            "PLURAL BLINDNESS. `_is_renaming_of` does not singularise, so a "
            "re-read of the same food is treated as a different one and the "
            "row is written TWICE. Live today. Fixed in step 2 (canonical "
            "food identity); the stemmer it needs already exists in "
            "normalize._stems and is not reachable from here.")
    assert _is_renaming_of(a, b), f"{b!r} should collapse into {a!r} ({why})"
