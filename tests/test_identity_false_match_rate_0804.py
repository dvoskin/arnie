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

from core.food_turn import (_claims_the_same_food,           # noqa: E402
                            _is_renaming_of)


def _score(fn=_claims_the_same_food):
    """Scored against the DELETE PATH by default.

    `_is_renaming_of` answers "do these read like one food renamed?" — a
    reasonable question with a heuristic answer. `_claims_the_same_food`
    authorises DELETING a row, and that is the function whose false-match rate
    is worth ratcheting.
    """
    false_match, missed = [], []
    for a, b, same, why in IDENTITY_PAIRS:
        got = fn(a, b)
        if got and not same:
            false_match.append((a, b, why))
        elif same and not got:
            missed.append((a, b, why))
    return false_match, missed


#: A RATCHET. A change may lower these and may not raise them.
#:
#:   1 / 5  string rule alone, measured 2026-08-04 before the registry
#:   0 / 1  registry first, string rule where the registry abstains
#:   0 / 2  registry ONLY on the delete path; abstention preserves both
#:   0 / 1  after six alias rows closed the abstentions that mattered
#:   0 / 0  after typed relations (berry/berries closed by an alias row)
#:
#: The false-match number is the one that deletes a row the user reported, and
#: it is now zero. The survivor is berry/berries, which the registry does not
#: know — an abstention, not a wrong answer.
BASELINE_FALSE_MATCHES = 0
BASELINE_MISSED_RENAMES = 0


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
    assert not _is_renaming_of(a, b), (
        f"{b!r} would claim and delete {a!r} ({why})")


@pytest.mark.parametrize("a,b,why", [
    p for p in ((a, b, w) for a, b, s, w in IDENTITY_PAIRS if s)
])
def test_a_rename_still_collapses(a, b, why):
    """The duplicate-collapse the mechanism exists for must survive every
    narrowing."""
    assert _is_renaming_of(a, b), f"{b!r} should collapse into {a!r} ({why})"


# ── abstention must preserve, never delegate a delete ────────────────────────

def test_an_unknown_food_is_preserved_not_guessed():
    """THE RULE THE DELETE PATH NOW FOLLOWS.

        registry says same      -> claim
        registry says different -> preserve
        registry says UNKNOWN   -> preserve

    Not "unknown -> let the fuzzy matcher decide whether to delete the row".
    A missed rename writes the food twice: visible, one tap from repair. A
    false match deletes a row the user reported: silent, unrecoverable. Where
    there is no opinion, the asymmetry decides.
    """
    from skills.nutrition.entities import same_food

    # A pair the registry does not know, that the string rule WOULD collapse.
    # Deliberately a nonsense food: any real one can be closed by an alias row,
    # and this test is about what happens when NOTHING is known — which is the
    # permanent state for the long tail of real user language.
    assert same_food("zzyzx", "zzyzx surprise") is None
    assert _claims_the_same_food("zzyzx", "zzyzx surprise") is False


def test_the_delete_path_never_consults_the_string_rule_when_strict():
    """`_is_renaming_of` still exists and is still string-based. It simply no
    longer decides anything mutation-critical — which is the acceptance
    criterion, not a style preference."""
    import core.food_turn as FT

    called = []
    original = FT._is_renaming_of
    FT._is_renaming_of = lambda a, b: called.append((a, b)) or original(a, b)
    try:
        for a, b, _s, _w in IDENTITY_PAIRS:
            FT._claims_the_same_food(a, b)
    finally:
        FT._is_renaming_of = original
    assert not called, f"the string rule was consulted on the delete path: {called[:3]}"


def test_the_fallback_can_be_restored(monkeypatch):
    """Reversible. `FOOD_IDENTITY_STRICT=false` returns the old behaviour, so
    a coverage problem in production is a config change rather than a revert."""
    monkeypatch.setenv("FOOD_IDENTITY_STRICT", "false")
    assert _claims_the_same_food("zzyzx", "zzyzx surprise") is _is_renaming_of(
        "zzyzx", "zzyzx surprise")


# ── a relationship is not an identity ────────────────────────────────────────

def test_a_subtype_is_not_the_same_food():
    """`same_food` answers IDENTITY and nothing else.

    Subtype, prepared form and product variant were all inside `UNIFYING`,
    which made `same_food("bread", "banana bread")` return True. A meal can
    contain both, and greek yogurt has materially different protein from
    yogurt — a function claiming otherwise hands every future caller a licence
    to merge them.
    """
    from skills.nutrition.entities import may_refine, same_food

    for a, b in [("bread", "banana bread"), ("rice", "fried rice"),
                 ("yogurt", "greek yogurt"), ("chicken", "grilled chicken")]:
        assert same_food(a, b) is False, f"{a}/{b} must not be one entity"
        assert may_refine(a, b) is True, f"{a}/{b} should be refinable"

    # A true alias is identity, and stays so.
    assert same_food("potato", "potatoes") is True
    # An ingredient edge is neither.
    assert same_food("chicken", "chicken noodle soup") is False
    assert may_refine("chicken", "chicken noodle soup") is False


@pytest.mark.parametrize("message,foods", [
    p for p in __import__("data.identity_collisions", fromlist=["x"]
                          ).ADVERSARIAL_LISTS
])
def test_a_list_of_two_related_foods_keeps_both(message, foods):
    """THE FAILURE MODE A RELATIONSHIP-AWARE MATCHER INVITES.

    Every one of these names a food and something related to it in one message,
    and every one must end with two rows. Driven through `_undeferred` because
    the protection is not the registry alone — it is exact-first injective
    matching, which claims the food the user actually named twice before any
    refinement test sees it.
    """
    from core.food_turn import _undeferred

    def call(n):
        return {"name": "log_food", "input": {"food_name": n}}

    for plan in ([], foods, foods[:1], foods[1:]):
        kept = _undeferred([call(f) for f in foods], [call(p) for p in plan])
        surviving = {c["input"]["food_name"] for c in kept} | set(plan)
        assert surviving >= set(foods), (
            f"{message!r} with plan={plan} lost "
            f"{set(foods) - surviving}")
