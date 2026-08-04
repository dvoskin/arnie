"""Unit conversion has one definition, and the audit that proves it cannot lie.

Measured 2026-08-04: `2.20462` appeared at 69 sites across 16 modules with no
units module anywhere — the largest duplication in the codebase, and the one
thing the cross-domain audit found genuinely shared (seven of eight non-food
domains had no language-layer anti-patterns at all, but every one converts
units).

The interesting failure here was not the duplication. It was that the FIRST
audit under-reported it: the pattern `0\\.45359\\b` cannot match `0.453592`,
because `\\b` needs a word boundary and "9" to "2" is not one. Four user
WEIGHT-WRITE paths in api/app.py were therefore invisible to the scan, AND the
shorter spelling looked like the one in use — so the registry adopted 0.45359
and migrating would have shifted those writes by 4.4e-6 without anything
saying so.

An audit that reports a number lower than the truth is worse than no audit: it
says the work is done. So these tests pin the CONSTANTS and the SEARCH, not
just the outcome.
"""
import pathlib
import re

import pytest

from core import units


REPO = pathlib.Path(__file__).resolve().parent.parent
ROOTS = ("core", "handlers", "skills", "api", "db")


@pytest.mark.parametrize("name,expected", [
    ("LB_PER_KG", 2.20462),
    ("KG_PER_LB", 0.453592),
    ("G_PER_OZ", 28.3495),
    ("CM_PER_IN", 2.54),
    ("ML_PER_FLOZ", 29.5735),
])
def test_the_constants_are_what_the_call_sites_used(name, expected):
    """A migration whose purpose is to change no numbers must change no
    numbers. Each of these is the literal the call sites wrote, so any later
    test failure is a real bug rather than sixth-decimal drift. Promoting them
    to their defined values (`units._EXACT`) is a separate, deliberate change.
    """
    assert getattr(units, name) == expected


def test_every_constant_is_close_to_its_defined_value():
    """The values in use are roundings, not mistakes. If one ever drifts far
    from the real conversion this catches it without pinning the exact digit,
    which is what `_EXACT` is for."""
    for name, exact in units._EXACT.items():
        got = getattr(units, name)
        assert abs(got - exact) / exact < 1e-4, (
            f"{name}={got} is not a rounding of {exact}")


def test_lb_and_kg_round_trip():
    for kg in (0.5, 60.0, 80.0, 113.4, 200.0):
        assert abs(units.lb_to_kg(units.kg_to_lb(kg)) - kg) / kg < 1e-5


#: Every spelling of every conversion, written so a longer literal cannot hide
#: behind its own prefix and a trailing digit cannot defeat a word boundary.
_LITERALS = re.compile(
    r"(?<![\d.])(?:2\.2046\d*|0\.4535\d*|2\.54|0\.3937\d*"
    r"|28\.34\d*|28\.35|29\.57\d*)(?![\d])")


def test_no_module_but_units_spells_a_conversion_out():
    """THE GATE. A new `weight * 2.20462` anywhere is a new source of truth,
    and the whole point of the registry is that there is one.

    Deliberately a source scan rather than a behavioural test: the defect being
    prevented is a DUPLICATE DEFINITION, which by construction behaves
    identically to the original until the two drift. Nothing observable
    distinguishes them, so nothing observable can catch them.
    """
    offenders = []
    for root in ROOTS:
        for path in (REPO / root).rglob("*.py"):
            if path.name == "units.py":
                continue
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if _LITERALS.search(line):
                    offenders.append(
                        f"{path.relative_to(REPO)}:{i}  {line.strip()[:70]}")
    assert not offenders, (
        "conversion literals outside core/units.py:\n  "
        + "\n  ".join(offenders))


def test_the_scan_catches_the_spelling_that_defeated_the_first_audit():
    """A regression test for the AUDIT, not the code. `0.453592` was invisible
    to `0\\.45359\\b`; if the pattern above ever regains a `\\b`, this goes
    red before four weight-write paths go quiet again."""
    for spelling in ("0.453592", "0.45359", "2.20462", "2.2046",
                     "28.3495", "28.35", "29.5735", "29.574", "2.54"):
        assert _LITERALS.search(f"x = weight * {spelling}"), spelling


def test_the_scan_does_not_fire_on_ordinary_numbers():
    """The ontology is full of 28.0 g bread slices and 2.5 confidences. A gate
    that cries wolf gets disabled, which is how it stops gating."""
    for benign in ("28.0", "2.5", "0.45", "29.0", "2.2", "254", "22.0462"):
        assert not _LITERALS.search(f"x = {benign}"), benign
