"""⛔⛔⛔ THE CENTRAL TRANCHE Q INVARIANT, PROVEN AT EVERY RUNG SEPARATELY.

    A quantity whose unit contradicts this item's measured unit is NOT the
    user's statement of this item's amount — through ANY path.

Written because the same defect was fixed three times in three days, arriving
each time through whichever path was newest:

    round 1 review   the raw-substring fallback   "1 scoop"      as 1 tbsp
    round 3          a shared noun set            "1 scoop"      as 1 tbsp
    round 5          the half and range rungs     "half a scoop" as 0.5 tbsp

⭐ THE PATTERN, NOT THE INSTANCE: each new path re-answered "is this the user's
number?" without re-answering "in whose unit?". Per-rung tests could not catch
that, because each was written for the rung that had just broken. This file is
per-INVARIANT, so a rung added tomorrow is covered the day it is added — or
`test_every_rung_is_covered_by_this_corpus` fails and names the gap.

⛔⛔ AND THE FIRST VERSION OF THIS FILE WAS A CLAIM, NOT A PROOF. It ran each
pair through the whole function and labelled it with the rung it was "about".
Measured: **8 of 16 compatible twins were answered by the NORMALIZER rung**,
which sits first and parses these sentences perfectly well — including every
row labelled `digit` and most labelled `half`. Those pairs proved the
normalizer declines a contradicted unit, three times over, and said nothing
about the rungs they claimed to test.

So each pair now runs with every rung ABOVE the one under test disabled, and
the answer is attributable to that rung alone:

    normalizer  nothing disabled — it is first
    digit       normalizer off
    half        normalizer off, digit off
    range       normalizer off, digit off, half off
    refine      normalizer off (the primary clause carries no number, so the
                refining clause is what answers)

Each rung gets BOTH halves of the pair, and both are load-bearing:

    compatible twin -> True   the rung was REACHED and accepts this shape
    conflicting twin -> False  that rung's OWN unit check declined it

Without the first, a False proves only that the message was unreachable — the
failure mode where a corpus of unparseable sentences "passes" by declining
everything.

⭐ ONE HONEST LIMIT. The `normalizer` rows disable nothing, because the
normalizer is first — so a True there IS attributable to it, but a False is
not: the rungs below it also ran and also declined. Measured: breaking the
DIGIT rung's unit check reddens the `normalizer` rows too. They are therefore
full-function rows wearing the first rung's name, and the rungs below have
their own isolated rows for exactly that reason.
"""
from __future__ import annotations

import contextlib

import pytest

import core.food_turn as FT
import skills.nutrition.normalize as NZ
from core.food_turn import _item_is_stated

PB, GC, WM, OIL = "Peanut butter", "Grilled chicken", "Whole milk", "Olive oil"

#: The rungs of `_item_is_stated` that can answer "the user stated this",
#: in the order the function consults them.
RUNGS = ("normalizer", "digit", "half", "range", "refine")


def _dead_normalizer(*_a, **_k):
    """The normalizer rung is wrapped in `try/except`, so raising is how it is
    switched off without touching the code under test."""
    raise RuntimeError("normalizer disabled to isolate a lower rung")


def _never(*_a, **_k):
    return False


@contextlib.contextmanager
def _isolated(rung, monkeypatch):
    """Disable every rung ABOVE `rung`, so whatever answers is `rung`."""
    assert rung in RUNGS, rung
    if rung != "normalizer":
        monkeypatch.setattr(NZ, "normalize_quantity", _dead_normalizer)
    if rung in ("half", "range"):
        monkeypatch.setattr(FT, "_literal_amount_with_unit", _never)
    if rung == "range":
        monkeypatch.setattr(FT, "_half_binds_to_food", _never)
    try:
        yield
    finally:
        monkeypatch.undo()


#: (rung, message, food, amount, item_unit, expected)
#:
#: Read in pairs: within a pair the ITEM is identical and only the unit word in
#: the message changes, so the two rows differ by exactly the thing under test.
CORPUS = [
    # ── scoop vs tbsp — the shipped 190-calorie defect ────────────────────
    ("normalizer", "I had 1 scoop of peanut butter",  PB, 1,   "tbsp", False),
    ("normalizer", "I had 1 tbsp of peanut butter",   PB, 1,   "tbsp", True),
    ("digit",      "I had 1 scoop of peanut butter",  PB, 1,   "tbsp", False),
    ("digit",      "I had 1 tbsp of peanut butter",   PB, 1,   "tbsp", True),
    ("half",       "half a scoop of peanut butter",   PB, 0.5, "tbsp", False),
    ("half",       "half a tbsp of peanut butter",    PB, 0.5, "tbsp", True),
    ("range",      "1-2 scoops of peanut butter",     PB, 1.5, "tbsp", False),
    ("range",      "1-2 tbsp of peanut butter",       PB, 1.5, "tbsp", True),

    # ── oz vs g — a 28x mass error, not a rounding one ────────────────────
    ("digit",      "I had 6 oz of grilled chicken",   GC, 6,   "g",    False),
    ("digit",      "I had 6 g of grilled chicken",    GC, 6,   "g",    True),
    ("half",       "half a gram of grilled chicken",  GC, 0.5, "oz",   False),
    ("half",       "half an oz of grilled chicken",   GC, 0.5, "oz",   True),
    ("range",      "5-6 oz grilled chicken",          GC, 5.5, "g",    False),
    ("range",      "5-6 oz grilled chicken",          GC, 5.5, "oz",   True),

    # ── glass vs cup — a vessel the user named, and one we did ────────────
    ("digit",      "I had 2 glasses of milk",         WM, 2,   "cup",  False),
    ("digit",      "I had 2 cups of milk",            WM, 2,   "cup",  True),
    ("half",       "half a glass of milk",            WM, 0.5, "cup",  False),
    ("half",       "half a cup of milk",              WM, 0.5, "cup",  True),
    ("range",      "1-2 glasses of milk",             WM, 1.5, "cup",  False),
    ("range",      "1-2 cups of milk",                WM, 1.5, "cup",  True),

    # ── the REFINING clause: a second clause naming the same head noun ────
    #
    # It earns no weaker a test than the primary one. Reached only when the
    # later clause repeats the food's head noun ("...of OIL") — the anti-bleed
    # rule that stops "half a banana" refining peanut butter.
    ("refine", "some olive oil, about 2 scoops of oil", OIL, 2, "tbsp", False),
    ("refine", "some olive oil, about 2 tbsp of oil",   OIL, 2, "tbsp", True),
    ("refine", "some olive oil, about 2 tbsp of oil",   OIL, 2, "cup",  False),
]

#: A count noun carries no contradiction — "15" versus "piece" is not a
#: disagreement — so these keep binding on nearness alone. They are the other
#: half of the rule, and the reason it is not simply "always demand a unit".
COUNT_TWINS = [
    ("2 fried eggs",              "Fried eggs",      2,   "egg"),
    ("6 chicken nuggets",         "Chicken nuggets", 6,   "piece"),
    ("half a banana",             "Banana",          0.5, "banana"),
    ("ate half the banana",       "Banana",          0.5, "banana"),
    ("like 5-6 fries",            "French fries",    5.5, "piece"),
    ("I had like 15 peanut m&m",  "Peanut M&Ms",     15,  "pieces"),
]


def _item(food, amount, unit):
    return {"food": food, "amount": amount, "unit": unit, "basis": "estimate"}


@pytest.mark.parametrize("rung,message,food,amount,unit,stated", CORPUS)
def test_a_contradicted_unit_is_never_stated_at_any_rung(
        rung, message, food, amount, unit, stated, monkeypatch):
    """One row, run with every rung above `rung` switched off.

    `basis="estimate"` throughout: all of these sit ABOVE the basis veto,
    which is precisely why an unbound match here launders our inference into
    the user's own words instead of being refused."""
    with _isolated(rung, monkeypatch):
        got = _item_is_stated(_item(food, amount, unit), message)
    assert got is stated, (
        f"rung={rung}: {message!r} against {amount} {unit} — "
        + ("this rung accepted a contradicted unit" if stated is False else
           "this rung was never reached, so its conflicting twin proves nothing"))


@pytest.mark.parametrize("message,food,amount,unit", COUNT_TWINS)
def test_a_count_unit_has_nothing_to_contradict(message, food, amount, unit):
    """The rule is measured-unit AGREEMENT, not "always demand a unit".
    Tightening it into the latter would refuse plainly stated counts — the
    defect this tranche exists to prevent, running backwards. Driven through
    the whole function, because that is where a user meets it."""
    assert _item_is_stated(_item(food, amount, unit), message) is True, (
        f"a stated count was refused: {message!r}")


@pytest.mark.parametrize("message,food,amount,unit,stated", [
    ("I had 1 scoop of peanut butter",  PB, 1,   "tbsp", False),
    ("half a scoop of peanut butter",   PB, 0.5, "tbsp", False),
    ("1-2 scoops of peanut butter",     PB, 1.5, "tbsp", False),
    ("I had 6 oz of grilled chicken",   GC, 6,   "g",    False),
    ("5-6 oz grilled chicken",          GC, 5.5, "g",    False),
    ("I had 2 glasses of milk",         WM, 2,   "cup",  False),
    ("half a glass of milk",            WM, 0.5, "cup",  False),
    ("I had 1 tbsp of peanut butter",   PB, 1,   "tbsp", True),
    ("half a cup of milk",              WM, 0.5, "cup",  True),
    ("1-2 cups of milk",                WM, 1.5, "cup",  True),
    ("5-6 oz grilled chicken",          GC, 5.5, "oz",   True),
])
def test_the_whole_function_agrees_with_its_rungs(message, food, amount, unit,
                                                  stated):
    """The isolated rungs are the proof; this is the behaviour. A rung can be
    right in isolation and unreachable in practice, or shadowed by one above
    it that is wrong — so the assembled function is checked too."""
    assert _item_is_stated(_item(food, amount, unit), message) is stated


def test_every_rung_is_covered_by_this_corpus():
    """⛔⛤ THE GUARD ON THE FILE ITSELF. A rung with no row is a rung this
    invariant does not protect, and the whole point of writing the corpus
    per-invariant rather than per-defect is that the NEXT path added is
    covered on the day it is added.

    If a rung is added to `_item_is_stated`, add it to `RUNGS` and to
    `_isolated`, and this fails until it has a conflicting/compatible pair."""
    covered = {rung for rung, *_ in CORPUS}
    missing = set(RUNGS) - covered
    assert not missing, (
        f"no conflicting-unit pair exercises {sorted(missing)} — that rung is "
        "unprotected by this invariant")
    for rung in RUNGS:
        rows = [r for r in CORPUS if r[0] == rung]
        assert any(r[5] for r in rows), (
            f"{rung} has no COMPATIBLE twin, so its refusals prove only that "
            "the message never reached it")
        assert any(not r[5] for r in rows), (
            f"{rung} has no CONFLICTING twin, so nothing tests its unit check")
