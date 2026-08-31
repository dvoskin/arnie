"""⛔⛔⛔ EVERY PREREGISTRATION MUST NAME BENEFIT, NULL **AND** HARM.

The C re-run preregistered two outcomes — *inside the envelope* and *survives in
the predicted direction*. What happened was the third: the effect survived with
its SIGN REVERSED, 15 points of extra asking on a null envelope of 1.

⭐ THE FAILURE WAS STRUCTURAL, NOT CARELESS. Only the outcomes someone can
imagine WANTING get written down, and a document built that way cannot classify
the result that matters most. The reversal had to be named after the fact by the
person who had just read it — which is the exact ordering preregistration exists
to forbid.

⛔ AND THE HARM BRANCH IS THE ONE THAT EARNS THE VOCABULARY. Under a two-way
prediction a reversal reads as a near-miss, and a near-miss invites "maybe the
threshold just needs tuning". A sign reversal means the mechanism is not what it
was believed to be; tuning a misunderstood mechanism produces a number, not
knowledge. So HARM must carry its action in writing: STOP, characterise the
reversal, do not design another candidate first.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TEMPLATE = DOCS / "PREREG_TEMPLATE.md"


def _preregistrations():
    return sorted(p for p in DOCS.glob("PREREG_*.md") if p != TEMPLATE)


def test_the_template_exists_and_defines_all_three():
    assert TEMPLATE.exists(), "docs/PREREG_TEMPLATE.md is missing"
    txt = TEMPLATE.read_text(encoding="utf-8")
    for word in ("BENEFIT", "NULL", "HARM"):
        assert word in txt, f"the template does not define {word}"
    assert re.search(r"STOP OPTIMIZATION", txt), (
        "the template does not bind the HARM branch to an action — a named "
        "outcome with no consequence is a label, not a rule")


@pytest.mark.parametrize("path", _preregistrations(),
                         ids=lambda p: p.name)
def test_every_preregistration_names_all_three_outcomes(path):
    """⚠ RETROACTIVE ON PURPOSE. The document whose gap produced this rule is
    held to it too — by amendment, never by editing its prediction."""
    txt = path.read_text(encoding="utf-8")
    missing = [w for w in ("BENEFIT", "NULL", "HARM") if w not in txt.upper()]
    assert not missing, (
        f"{path.name} does not name {missing}. All three outcomes, always: a "
        "prediction that cannot name the result it gets cannot be evidence "
        "about it. If this document predates the rule, add a dated AMENDMENT "
        "classifying its outcome in the three-way vocabulary — do not edit the "
        "prediction.")


@pytest.mark.parametrize("path", _preregistrations(),
                         ids=lambda p: p.name)
def test_every_preregistration_declares_refusal_conditions(path):
    """A run with no way to be VOID is a run that can only be interpreted."""
    txt = path.read_text(encoding="utf-8")
    assert re.search(r"refusal condition|VOID", txt, re.I), (
        f"{path.name} declares no refusal conditions — nothing that would make "
        "the run void rather than merely noisy")


def test_there_is_at_least_one_preregistration_to_check():
    """⭐ THE ANTI-VACUITY GATE. Both parametrised tests above generate ZERO
    cases if `docs/PREREG_*.md` ever matches nothing, and zero cases is a green
    run that checked nothing at all."""
    assert _preregistrations(), (
        "no preregistrations found — the parametrised gates above are "
        "vacuously green")
