"""⛔⛔ ONLY ONE BOARD MAY SEQUENCE THE WORK *(Danny, 2026-08-17, on review)*.

The directive is ~8,000 lines and most of it is correctly-marked history. That is
not the hazard. The hazard is that enough old `NEXT` / `IMMEDIATE NEXT` /
`next session` language survived INSIDE that history for an agent to pick up a
superseded instruction in good faith — several sections still describe general
settlement as the future substantive build, when it is frozen and
production-proven.

So the rule: **§NEXT is the only section that may tell anyone what to do next.**
Everything after it is evidence. A later section may record what was next *when
it was written*, and must mark itself as history when it does.

⭐ WHY A TEXT GATE, WHEN THIS REPO HAS BEEN BURNED BY GREP GATES TWICE. Because
the subject IS text — there is no AST for a markdown instruction. What made the
earlier grep traps traps was asserting a SPELLING and reading it as a STRUCTURE
(`ClarificationAttribute` in a comment; the A2 gate failing on its own
docstring). This gate is narrow in the way that avoids that:

  * it only looks BELOW §NEXT, so the authority itself is never its own subject;
  * it matches EXECUTABLE MARKERS (`<- NEXT`, `⬅ NEXT`, `IMMEDIATE NEXT`,
    `NEXT SESSION`), not the ordinary English word "next";
  * a line is exonerated by naming itself history — which is the actual
    remedy, so the gate points at the fix rather than at a rewording.

⚠ AND IT MUST NOT BE ABLE TO PASS BY FINDING NOTHING. The anti-vacuity test
below proves the matcher still fires on a known-bad line, because a matcher that
cannot fail disables its own detector.
"""
from __future__ import annotations

import pathlib
import re

DIRECTIVE = (pathlib.Path(__file__).resolve().parent.parent
             / "docs" / "CANONICAL_MIGRATION_DIRECTIVE.md")

#: The heading that owns sequencing. Everything after it is evidence.
BOARD_HEADING = "## ⏭ §NEXT — THE ONLY EXECUTABLE SEQUENCING IN THIS DOCUMENT"

#: Markers that read as an INSTRUCTION rather than as prose. Deliberately not
#: the bare word "next": "the next reader", "what to do next" and "the next
#: largest measured gap" are all legitimate English in a history section.
#:
#: ⭐ THE ARROW MAY CARRY A LABEL BEFORE THE WORD, AND THE ANTI-VACUITY TEST IS
#: WHAT FOUND THAT. The first version required `NEXT` to follow the arrow
#: immediately, so it did not match `<- P0, next` — which is the exact form that
#: was live at line 294 of the directive. A gate whose own fixture catches it
#: before the document does is the only kind worth writing.
EXECUTABLE = re.compile(
    r"(?:<-|⬅|⬅️|→)[^\n]{0,24}?\bNEXT\b"
    r"|IMMEDIATE\s+NEXT\b"
    r"|NEXT\s+SESSION\b"
    r"|^\s*NEXT\s*$",
    re.IGNORECASE | re.MULTILINE)

#: A line that names itself history is exonerated — that IS the remedy.
EXONERATED = re.compile(
    r"HISTORY|SUPERSEDED|was\s+NEXT|was\s+\"?immediate next|was\s+P0-next"
    r"|no longer|CLOSED|PARKED|see\s+§NEXT",
    re.IGNORECASE)


def _below_the_board() -> list[tuple[int, str]]:
    text = DIRECTIVE.read_text(encoding="utf-8")
    assert BOARD_HEADING in text, (
        "the directive has no §NEXT section — the one board that may sequence "
        "the work is gone, and every instruction below is now unowned")
    start = text.index(BOARD_HEADING)
    # Line numbers are 1-based over the WHOLE file so a failure is navigable.
    offset = text[:start].count("\n")
    body = text[start:].split("\n")
    # Skip the §NEXT section itself: it ends at the next top-level heading.
    end = next((i for i, l in enumerate(body[1:], 1) if l.startswith("## ")),
               len(body))
    return [(offset + end + i + 1, line)
            for i, line in enumerate(body[end:])]


def test_no_section_below_the_board_carries_an_executable_next():
    offenders = [(n, l) for n, l in _below_the_board()
                 if EXECUTABLE.search(l) and not EXONERATED.search(l)]
    assert not offenders, (
        "these lines sit BELOW §NEXT and still read as instructions — an agent "
        "can pick one up as current work. Either delete the marker or mark the "
        "line as history:\n" +
        "\n".join(f"  line {n}: {l.strip()[:100]}" for n, l in offenders))


def _the_sequencing_list() -> str:
    """The fenced block inside §NEXT that carries the NEXT list, and nothing else.

    ⭐ SCOPED TO THE FENCE, AND A MUTATION IS WHY. The first version sliced from
    the §NEXT heading to the next `##`, which swallowed §NEXT's own
    `### P16 — MISS ATTRIBUTION` subsection — so removing `P16` from the
    sequencing LIST still found it in the PROSE below, and the assertion passed
    on a board that had lost its phase pointer. A positive gate whose haystack
    is bigger than its subject is a positive gate that cannot fail.
    """
    text = DIRECTIVE.read_text(encoding="utf-8")
    section = text[text.index(BOARD_HEADING):]
    if "\n## " in section[10:]:
        section = section[:section.index("\n## ", 10)]
    for block in re.findall(r"```text\n(.*?)```", section, re.DOTALL):
        if re.search(r"^NEXT$", block, re.MULTILINE):
            return block
    raise AssertionError(
        "§NEXT has no fenced block containing a NEXT list — the one board that "
        "may sequence the work no longer sequences anything")


def test_the_board_itself_still_sequences():
    """⭐ THE POSITIVE HALF. A gate that only forbids instructions would pass
    perfectly on a document that had stopped telling anyone anything."""
    listing = _the_sequencing_list()
    for required in ("P16", "DO NOT", "36.9%"):
        assert required in listing, (
            f"the §NEXT sequencing list lost {required!r} — it must carry the "
            f"open phase, the prohibitions and the ownership number it is "
            f"sequenced on")


def test_the_matcher_can_still_fail():
    """⚠ ANTI-VACUITY. If `EXECUTABLE` stopped matching, the gate above would
    pass by finding nothing — the shape of every instrument this repo has caught
    lying by silence."""
    for bad in ("### 0  PRICING AUTHORITY MIGRATION  <- IMMEDIATE NEXT SESSION",
                "1  INTERPRETATION BOUNDARY          <- P0, NEXT",
                "**THE NEXT SESSION STARTS AT THE REBUILD.**",
                "NEXT"):
        assert EXECUTABLE.search(bad), f"the matcher stopped seeing {bad!r}"
    for fine in ("the next reader restores the specification order",
                 "what to do next",
                 "the next largest measured gap"):
        assert not EXECUTABLE.search(fine), f"the matcher over-reaches on {fine!r}"


def test_every_code_fence_opens_and_closes_in_order():
    """⛔ A PROSE BLOCK THAT RENDERS AS CODE IS HOW AN INSTRUCTION GETS MISREAD.

    Found 2026-08-17: the `P0–P10` board fence opened and was NEVER CLOSED, so
    forty lines of prose — including the paragraph explaining that commit
    numbering disagrees with the board — rendered inside a code block. The
    review had already flagged the neighbouring P11/P12 paragraph as corrupted;
    the corruption was wider than the paragraph it named.

    ⭐⭐ AND A MOD-2 COUNT SAID "BALANCED" THROUGHOUT. Counting markers and
    checking parity is the weak instrument: it passes on a document where a
    stray close later re-pairs the sequence. Depth has to be WALKED, which is
    the difference between counting a thing and checking it.
    """
    lines = DIRECTIVE.read_text(encoding="utf-8").split("\n")
    depth, defects = 0, []
    for number, line in enumerate(lines, 1):
        if not line.startswith("```"):
            continue
        if len(line.strip()) > 3:                  # ```text / ```bash opens
            if depth == 1:
                defects.append(f"line {number}: opens a fence inside an open one")
            depth = 1
        else:                                      # bare ``` closes
            if depth == 0:
                defects.append(f"line {number}: closes a fence that is not open")
            depth = 0
    if depth:
        defects.append("end of file: a fence is still open")
    assert not defects, "the directive's code fences are corrupt:\n  " + \
        "\n  ".join(defects)


def test_the_rollout_threshold_is_written_down():
    """⛔ "COVERAGE DECISION" MUST NOT BE RE-ARGUABLE EVERY TIME THE NUMBER
    MOVES. The threshold table has to exist and has to name the band we are in,
    so expansion is a lookup rather than an opinion."""
    text = DIRECTIVE.read_text(encoding="utf-8")
    assert "OWNERSHIP        COHORT PERMITTED" in text, \
        "the rollout threshold table is gone — expansion is subjective again"
    assert "user 26 only" in text and "WE ARE HERE" in text, \
        "the threshold table no longer marks which band the product is in"
