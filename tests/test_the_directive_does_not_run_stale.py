"""THE SEQUENCING AUTHORITY MUST NOT RUN STALE.

The status board came to read "B-1 NEXT" while B-1 was production-proven, and
six companion documents sat two days behind a period in which the lane gate,
the Semantic Extension Contract, B-1.5's lifecycle and B-1.5E all landed. A
document that is the authority and is stale is worse than no document — a
parallel session reads it and executes superseded instructions, which nearly
happened with the pre-"one promotion event" milestone order.

Staleness is a fact about dates, and dates are checkable. This is the check.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRECTIVE = ROOT / "docs" / "CANONICAL_MIGRATION_DIRECTIVE.md"

#: How far the reconciliation stamp may lag the newest code change. Two days:
#: one working session plus a buffer, matching how the drift actually happened
#: (docs stamped 08-05, code moved through 08-07).
MAX_LAG_DAYS = 2

#: Directories whose commits mean "the system changed and the authority should
#: know". Docs and tests are deliberately excluded — updating the directive
#: must not itself demand another update.
_CODE = ("core", "skills", "api", "handlers", "db")


def _last_code_commit_date() -> dt.date:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", *_CODE],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    # FAIL LOUD, NOT SKIP. A freshness gate that silently passes where git is
    # missing is an instrument lying by silence — the exact defect class this
    # repo keeps cataloguing.
    assert out.returncode == 0 and out.stdout.strip(), (
        f"git unavailable or no history ({out.stderr.strip()!r}) — this gate "
        f"cannot run, and 'cannot run' must not look like 'passed'")
    return dt.date.fromisoformat(out.stdout.strip())


def _reconciled_date() -> dt.date:
    text = DIRECTIVE.read_text(encoding="utf-8")
    match = re.search(r"Last reconciled (\d{4}-\d{2}-\d{2})", text)
    assert match, (
        "the directive has no 'Last reconciled YYYY-MM-DD' stamp — the board "
        "section must carry one, or freshness cannot be checked at all")
    return dt.date.fromisoformat(match.group(1))


def test_the_directive_is_reconciled_against_current_code():
    """The stamp may lag the newest code commit by at most MAX_LAG_DAYS.

    When this fails, the fix is NOT to edit the date. Re-read the status
    board and the affected sections against what actually changed, update
    them, and stamp the reconciliation you actually did — the stamp is a
    CLAIM, and this gate only keeps the claim honest, not true.
    """
    code = _last_code_commit_date()
    stamp = _reconciled_date()
    lag = (code - stamp).days
    assert lag <= MAX_LAG_DAYS, (
        f"code last changed {code} but the directive was last reconciled "
        f"{stamp} ({lag} days behind) — the sequencing authority is stale. "
        f"Reconcile the board and affected sections, then update the stamp.")


def test_the_companion_documents_carry_currency_banners():
    """Each companion document opens with a 'Current as of' banner, so a
    reader knows at a glance whether they are reading history."""
    for name in ("ARCHITECTURE_CONTRACT.md", "CLARIFICATION_MIGRATION.md",
                 "CHIP_GENERATION_MIGRATION.md", "DELETION_INVENTORY.md",
                 "WORKOUT_CONTRACTS.md", "QUICK_LOG_PROMOTION_RECORD.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert re.search(r"Current as of \d{4}-\d{2}-\d{2}", text[:2000]), (
            f"docs/{name} has no 'Current as of' banner near the top")


def test_the_board_does_not_claim_a_closed_state_for_open_work():
    """The specific lie the board told once: 'B-1 NEXT' while B-1 was
    production-proven. Generalized: the board must still contain the markers
    of the actually-open work, so a stale copy-paste cannot quietly close it.

    UPDATE THIS TEST when the state genuinely advances — that is the point:
    closing a phase now requires touching the gate that says it is open.
    """
    text = DIRECTIVE.read_text(encoding="utf-8")
    board = text[text.index("## Status board"):]

    # B-1.5 CLOSED 2026-08-10. The turn this gate demanded was observed: typed
    # two-field answering proven live on /chat after the `live_field` root
    # cause, and both natural-language pricing canaries landed on
    # pre-registered predictions. So the assertion it held is retired HERE, in
    # the commit that closes the board — which is the whole mechanism.
    #
    # ⚠ AND THIS GATE ALSO CAUGHT A REAL PROCESS FAILURE, which is why the
    # note stays. `aecbb97` closed B-1.5 on the board and its message reported
    # "8700 tests 0 failures" — from a run that STARTED BEFORE the board edit
    # and finished after it. The suite never saw the tree that was committed,
    # main went red, and the number in the commit message was true of a
    # different tree. A suite result is evidence only for the tree it read;
    # a run that races an edit is not a measurement of either version.
    #
    # What replaces it is B-1.6's open state, so a stale copy-paste cannot
    # close THAT quietly either.
    # B-1.6 CLOSED 2026-08-10 — the conditional lifecycle is proven end to
    # end and its gate is retired HERE, in the commit that closes it. What
    # replaces it is B-1.7's open state AND the reason B-1.6 could close with
    # pricing unbuilt: the blocker is missing SEMANTIC STATE, not a missing
    # lifecycle, and a board that forgot that distinction would re-open B-1.6
    # to chase a pricing problem.
    # PHASE 0 CLOSED 2026-08-14 (`a4b6d23`, re-frozen `bcb7b45`), so the
    # "authority migration is next" assertion it held is retired HERE, in the
    # commit that re-sequences the roadmap — which is the mechanism.
    #
    # ⭐⭐⭐ WHAT REPLACES IT IS A STRONGER CLAIM THAN A PHASE NAME. Danny froze
    # a MEASURED-ADOPTION order on 2026-08-14, and the thing a stale copy-paste
    # would quietly revert is not the roadmap's position — it is the REASON the
    # oils moved. Measured on 691 real production entries, the artifact is the
    # deciding rung on 13 of them (1.9%), while the non-English/modifier miss
    # bucket is 30.4%. A reader who lands on B-1.7a and starts building would
    # be widening what the spine can theoretically do while ordinary turns
    # still cannot reach it — the exact conflation Phase 0's closure taught.
    #
    # So the gate asserts the ORDER and the MEASUREMENT together: either can be
    # edited, but not silently, and not without the other.
    text_head = text[:text.index("## End goal")]
    assert "THE FROZEN ROADMAP — MEASURED-ADOPTION ORDER" in text_head, (
        "the frozen roadmap is no longer the first section of the directive — "
        "it must precede everything, because the sequencing was re-derived "
        "from measurement and the detail sections below it still carry the "
        "old specification order")
    assert "INTERPRETATION BOUNDARY" in text_head, (
        "the roadmap no longer names the interpretation boundary as the "
        "immediate next work. Canonical identity is still built from the "
        "SURFACE STRING, so 30.4% of real food cannot reach the spine at all — "
        "starting anywhere else widens a spine real turns do not arrive at")
    assert "1.9%" in text_head, (
        "the roadmap no longer carries the measurement that re-sequenced it. "
        "Without 'the artifact decides 1.9% of real food' the oils read as an "
        "arbitrary deferral instead of a measured one, and the next reader "
        "restores the specification order in good faith")

    assert "B-1.7" in board, (
        "the board no longer tracks B-1.7 — added-fat identity, materiality "
        "policy and component pricing are the open slice")
    assert "ADDED_FAT_IDENTITY" in board, (
        "the board no longer records that added-fat pricing is blocked on an "
        "identity CONTRACT rather than on implementation — without that line, "
        "the next reader defaults to 'oil' to reach pricing, which is the "
        "legacy phrase table under a typed interface")
    assert "CLOSED BY CONSTRUCTION, NOT BY OBSERVATION" in board, (
        "the board no longer distinguishes canary F being closed by "
        "construction from being observed. A duplicate delivery has never "
        "occurred in production, so COMMIT_DUPLICATE_BEHAVIOUR is proven only "
        "in the harness — if a deliberate staging exercise has since proven "
        "it live, record that and update this assertion in the same commit")
    # CI WENT GREEN 2026-08-09 (2fa8f7c, repaired by #72), so the red-CI
    # assertion that stood here is retired — in the same commit that removed
    # the banner, which is what this gate exists to force.
    #
    # What replaces it is NOT symmetric. "CI is green" needs no gate; it is
    # observable from GitHub any time. What needs one is the thing a green
    # board quietly buries: B-1b.1's 22 tests did not run for three days while
    # two workstreams landed, and passing today says nothing about the commits
    # that landed unwatched. That gap cannot be closed retroactively, so the
    # board must keep saying so until someone decides to re-run the matrix
    # against that history or to accept it.
    assert "RUNNABLE AGAIN, NOT DISCHARGED" in board, (
        "the board no longer distinguishes B-1b.1 being runnable from being "
        "discharged — if the matrix has since been re-run against the commits "
        "that landed while CI was red, or that gap was consciously accepted, "
        "record which and update this assertion in the same commit")
    # Promotion has not happened.
    assert "PROMOTION" in board and "after B-2" in board, (
        "the promotion line left the board — promotion is a single event "
        "after B-2 and the board must say so until it happens")
