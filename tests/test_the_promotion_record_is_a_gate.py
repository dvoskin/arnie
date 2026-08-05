"""A promotion is complete when its record says so, checkably.

`docs/QUICK_LOG_PROMOTION_RECORD.md` is the evidence that quick_log is
canonical in PRODUCTION — a different claim from "the tests pass", and the one
that gates migration 2/4. A document asserting completion in prose is exactly
the kind of unchecked claim this whole rearchitecture exists to replace, so the
document's own status is parsed and cross-checked against the code it
describes.

This does NOT re-verify production (nothing in CI can reach it). It verifies
that the record is internally honest: every step resolved, no step silently
dropped, and the promoted state it claims matches the code that shipped.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECORD = ROOT / "docs" / "QUICK_LOG_PROMOTION_RECORD.md"


def _rows():
    """The step table, as (number, step, outcome)."""
    out = []
    for line in RECORD.read_text().splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|([^|]+)\|[^|]+\|([^|]+)\|", line)
        if m:
            out.append((int(m.group(1)), m.group(2).strip(),
                        m.group(3).strip()))
    return out


def test_the_record_exists_and_declares_a_status():
    text = RECORD.read_text()
    assert "**Status:" in text
    status = re.search(r"\*\*Status:\s*(\w+)", text).group(1)
    assert status in ("COMPLETE", "INCOMPLETE"), status


def test_every_step_is_resolved_when_the_record_claims_completion():
    """COMPLETE means every step carries evidence. A ☐ under a COMPLETE
    heading is the record contradicting itself."""
    text = RECORD.read_text()
    rows = _rows()
    assert len(rows) >= 9, f"the step table lost rows: {len(rows)}"

    if "**Status: COMPLETE" not in text:
        pytest.skip("record is INCOMPLETE — steps may still be pending")

    unresolved = [(n, s) for n, s, outcome in rows if "☐" in outcome
                  or not outcome or outcome.lower().startswith("pending")]
    assert not unresolved, (
        f"the record claims COMPLETE but these steps are unresolved: "
        f"{unresolved}")


def test_a_complete_record_names_the_verified_build():
    """An outcome with no sha is not evidence — it cannot be re-checked, and
    a later deploy would silently invalidate it without changing the text."""
    text = RECORD.read_text()
    if "**Status: COMPLETE" not in text:
        pytest.skip("record is INCOMPLETE")
    assert re.search(r"\b[0-9a-f]{12}\b", text), (
        "no build sha in the record — 'verified' against what?")


def test_the_record_matches_the_code_that_shipped():
    """The record claims quick_log's food writer is canonical. If the code
    ever reverts, this fails BEFORE anyone trusts the record again."""
    text = RECORD.read_text()
    if "**Status: COMPLETE" not in text:
        pytest.skip("record is INCOMPLETE")

    import ast

    src = (ROOT / "api" / "quick_log.py").read_text()
    assert 'FOOD_WRITER = "canonical"' in src, (
        "the record says the canonical writer is promoted; the code no longer "
        "declares it")
    assert "write_canonical_meal" in src

    # AST, not substring: the module's docstring EXPLAINS which legacy call the
    # promotion deleted, and a prose mention of a deleted function is
    # documentation, not usage. Banning the word would punish the comment that
    # records the history — the same error as an invariant claiming more than
    # it proves. C7 checks it the same way.
    used = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            used |= {a.name for a in node.names}
        elif isinstance(node, ast.Call):
            name = (getattr(node.func, "id", None)
                    or getattr(node.func, "attr", None))
            if name:
                used.add(name)
    assert "add_food_entry" not in used, (
        "the legacy writer is CALLED again on a path the record says was "
        "deleted")


def test_migration_two_is_gated_on_this_record():
    """The gate is stated IN the record, so the next migration's author reads
    it where they are already looking."""
    assert "Migration 2/4 does not begin until this record is complete" in \
        RECORD.read_text()
