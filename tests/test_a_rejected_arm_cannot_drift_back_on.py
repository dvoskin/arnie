"""⛔⛔⛔ A REJECTED EXPERIMENTAL ARM MUST STAY REJECTED — AND STAY RUNNABLE.

Shape C (`FOOD_EXTRAS_REPORT_ONLY`, the report-only `extras` permission class)
was FALSIFIED by arms E1/E2/E3 at `83342c6`:

    C off  22/50 and 23/50      C ON  30/50
    null envelope 1             effect +7.5   OUTSIDE it, in the HARM direction

It does not reduce asking; it increases it by 15 points across 8 of 25 cases.
Its earlier apparent benefit was not partly an artifact — the artifact WAS the
benefit and was masking an effect of the opposite sign.

⭐ WHY THE FLAG SURVIVES ITS OWN REJECTION. "Extras should just be report-only"
is an attractive idea and someone will have it again. Left as a comment, they
repeat 150 turns to learn what is known. Left as a runnable arm, they meet the
falsification and can reproduce it in one command.

⛔ BUT A DISABLED FLAG AND A FALSIFIED ONE READ IDENTICALLY IN A CONFIG FILE,
and that is how a rejected idea becomes zombie functionality: one `true` away
from re-enabling a measured-harmful path, with nothing to catch it. So this
file pins FIVE conditions, and deliberately pins them in BOTH directions —
because a guard that only proves the flag is off would be satisfied by deleting
the feature, and a guard that only proves it works would be satisfied by
shipping it on.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLAG = "FOOD_EXTRAS_REPORT_ONLY"
#: The arms that killed it. Named here so the rejection cannot be softened into
#: "we tried it once" — a reader can go and read the run.
REJECTING_ARMS = ("E1", "E2", "E3")


def test_1_the_code_default_is_OFF():
    """Absent configuration must not enable a falsified path."""
    from core.food_turn import extras_report_only
    saved = os.environ.pop(FLAG, None)
    try:
        assert extras_report_only() is False, (
            f"{FLAG} defaults ON — a falsified arm is enabled wherever nobody "
            "set it, which is most places")
    finally:
        if saved is not None:
            os.environ[FLAG] = saved


def test_2_production_config_asserts_OFF():
    txt = (ROOT / "render.yaml").read_text(encoding="utf-8")
    m = re.search(rf'- key:\s*{FLAG}\s*\n\s*value:\s*"?([^"\n]*)"?', txt)
    assert m, f"{FLAG} is not declared in render.yaml at all — an undeclared " \
              "flag is invisible to `pin_config`, so a run could vary it " \
              "without recording that it did"
    assert m.group(1).strip() == "false", (
        f"render.yaml sets {FLAG}={m.group(1)!r}. This arm was MEASURED "
        "HARMFUL (+7.5 asks against a null of 1). Turning it on in production "
        "is not a config tweak, it is reversing a result.")


def test_3_the_config_names_the_experiment_THAT_REJECTED_IT():
    """⭐ A NUMBER, NOT A VERDICT. "We decided against it" ages into "nobody
    remembers why" and then into "let's try it". The arms and the effect size
    sit next to the flag so rediscovery costs one screen, not 150 turns."""
    txt = (ROOT / "render.yaml").read_text(encoding="utf-8")
    block = txt[max(0, txt.index(f"- key: {FLAG}") - 2200):txt.index(f"- key: {FLAG}")]
    assert "REJECTED" in block, (
        "the render.yaml comment does not say REJECTED — 'off' and 'falsified' "
        "look identical in a config file, and only one of them is a result")
    for arm in REJECTING_ARMS:
        assert arm in block, f"the comment does not name arm {arm}"
    assert "+7.5" in block and "null envelope 1" in block, (
        "the comment records no effect size — a verdict without its number is "
        "an opinion, and opinions get overturned by the next opinion")


def test_4_the_registry_holds_it_REFUTED_with_its_evidence():
    import json
    reg = json.loads((ROOT / "data" / "criteria_registry.json").read_text())
    c = next((x for x in reg["criteria"]
              if x["name"] == "shape_c_unstated_extras_report_only_field"), None)
    assert c, "Shape C is not in the criteria registry"
    assert c["status"] == "refuted", (
        f"Shape C is registered {c['status']!r}, not 'refuted' — the registry "
        "is where a future session looks first")
    assert all(a in c["note"] for a in REJECTING_ARMS), \
        "the registry entry does not name the arms that refuted it"


def test_5_the_arm_STILL_WORKS_when_deliberately_switched_on():
    """⛔ THE OTHER DIRECTION, and the one a naive guard would miss.

    Every check above is satisfied by DELETING the feature. If the branch were
    quietly removed, "retained as a runnable historical causal arm" becomes a
    false claim in four documents at once, and the next person to reach for the
    idea gets a config key that does nothing rather than a reproducible result.

    So: the prompt cut must still be REAL, and it must still be the ONLY thing
    the flag changes.
    """
    import core.food_turn as FT
    saved = os.environ.get(FLAG)
    try:
        os.environ[FLAG] = "false"
        off = FT._interpreter_system(narrate=False)
        os.environ[FLAG] = "true"
        on = FT._interpreter_system(narrate=False)
    finally:
        os.environ.pop(FLAG, None)
        if saved is not None:
            os.environ[FLAG] = saved

    assert "REPORT-ONLY" not in off, "the arm leaks into the OFF prompt"
    assert "REPORT-ONLY" in on, (
        "switching the arm ON changes nothing — the branch has been deleted or "
        "neutered, so it is no longer a runnable historical arm and the "
        "documents that call it one are now wrong")
    assert "[[" not in on and "]]" not in on and "XTRA" not in off, \
        "the prompt-splice sentinel leaks into a rendered prompt"
    assert len(on) > len(off), "the ON prompt is not the OFF prompt plus the cut"


def test_6_the_board_marks_it_REJECTED_not_merely_disabled():
    """The sequencing authority is what a parallel session reads. `off` there
    would read as 'not yet tried'."""
    txt = (ROOT / "docs" / "CANONICAL_MIGRATION_DIRECTIVE.md").read_text(
        encoding="utf-8")
    head = txt[:12000]
    assert re.search(r"C\s*/\s*`?unstated_extras`?.*REJECTED", head, re.I | re.S) \
        or "unstated_extras: REJECTED" in head, (
        "the directive's top banner does not mark C as REJECTED — a board that "
        "says 'FAIL adoption' without saying the re-run settled it invites "
        "someone to re-run it")
