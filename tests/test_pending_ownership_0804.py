"""Who owns pending state — measured, including the owner nobody calls.

Step 4's first job was to find the owners, and the finding inverted the work:
`skills/nutrition/pending_store.py` is 355 lines, fully tested, and has ZERO
production importers. It is not a competing owner; it is the ANSWER, unwired.

It implements the lifecycle the directive asks for — versioning, expiry,
status — and `claim()` is a real database-level atomic guard:

    UPDATE pending_questions SET answered_at = now()
    WHERE id = :id AND answered_at IS NULL

Exactly one caller sees rowcount 1. That is precisely the idempotency the
acceptance gate is failing for, since what food actually uses is
`turn_idempotency_key(user_id, message, tool_calls)` over an in-process dict —
message-keyed and process-local, surviving neither a restart nor a second
worker.

So step 4 is an ADOPTION, not a build. These tests pin the measurement that
justifies that, so the claim decays loudly if it stops being true.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PROD_ROOTS = ("core", "handlers", "skills", "api", "db")


def _prod_refs(symbol: str, exclude_self: str = "") -> list:
    rx = re.compile(rf"\b{re.escape(symbol)}\b")
    out = []
    for root in PROD_ROOTS:
        for p in (REPO / root).rglob("*.py"):
            rel = str(p.relative_to(REPO))
            if exclude_self and rel == exclude_self:
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if rx.search(line) and not line.strip().startswith("#"):
                    out.append(f"{rel}:{i}")
    return out


def test_pending_store_is_still_unwired():
    """If this fails, something adopted it — update the migration doc rather
    than the assertion, because that is the outcome step 4 wants."""
    refs = [r for r in _prod_refs("pending_store",
                                  "skills/nutrition/pending_store.py")
            if not r.startswith("core/semantics.py")]
    assert not refs, f"pending_store is now imported by: {refs}"


def test_it_really_does_implement_the_lifecycle():
    """The reason not to build a fifth. Asserted on the module rather than
    quoted from a commit message."""
    from skills.nutrition import pending_store as PS

    assert hasattr(PS, "PendingClarification")
    assert callable(PS.claim) and callable(PS.load_open) and callable(PS.save)
    fields = PS.PendingClarification.__dataclass_fields__
    for name in ("version", "status", "attempt_count", "turn_id",
                 "held_item_ids", "question_ids"):
        assert name in fields, f"missing {name}"


def test_the_claim_is_a_conditional_update_not_a_read_then_write():
    """The property that makes it atomic: the DATABASE arbitrates, because two
    callers holding equally-valid snapshots cannot arbitrate in process."""
    import inspect

    from skills.nutrition import pending_store as PS

    src = inspect.getsource(PS.claim)
    assert "answered_at.is_(None)" in src, "the guard is gone"
    assert "rowcount" in src, "the winner is no longer decided by the write"


#: WHO MUTATES pending state, by action. A reader is not an owner.
_MUTATIONS = {
    "create": r"record_pending_question\(",
    "update": r"\.payload_json\s*=",
    "consume": r"\.answered_at\s*=",
    "cancel": r"_clear_deferred\(|_drop_deferred",
    "expire": r"pending_expired\(|_settle_expired_deferred\(",
    "commit_held": r"execute_tool_calls\(",
}


def _mutation_sites():
    out = {}
    for action, pattern in _MUTATIONS.items():
        rx = re.compile(pattern)
        hits = []
        for root in PROD_ROOTS:
            for p in (REPO / root).rglob("*.py"):
                rel = str(p.relative_to(REPO))
                if rel == "skills/nutrition/pending_store.py":
                    continue
                for i, line in enumerate(p.read_text().splitlines(), 1):
                    if not line.strip().startswith("#") and rx.search(line):
                        hits.append(rel)
        out[action] = hits
    return out


def test_pending_mutation_authority_does_not_spread():
    """A RATCHET ON AUTHORITY, not on references.

    Counting symbol references measured the wrong thing — a count can fall
    while ownership stays fragmented, or rise from harmless readers and tests.
    The criterion is that one module may CHANGE pending lifecycle state, so
    this inventories the actions that change it.

    Measured 2026-08-04: 30 sites across 7 modules. `expire` alone is spread
    over three. Both numbers must go DOWN as the adoption proceeds.
    """
    sites = _mutation_sites()
    modules = {m for hits in sites.values() for m in hits}
    total = sum(len(h) for h in sites.values())
    assert total <= 30, (
        f"pending mutation spread further: {total} sites, "
        f"{ {k: len(v) for k, v in sites.items()} }")
    assert len(modules) <= 7, f"now mutated from {len(modules)} modules: {modules}"


def test_every_mutation_action_is_still_accounted_for():
    """If an action stops matching, it was renamed or removed — and the ratchet
    above would silently pass while measuring less."""
    sites = _mutation_sites()
    for action, hits in sites.items():
        assert hits, f"no sites found for {action!r}; the pattern has rotted"


def test_the_two_pending_status_enums_are_reconciled_in_code():
    """Two enums with overlapping member names and different SCOPES is how a
    single source of truth quietly becomes two. The mapping is code so the
    relationship cannot drift into folklore."""
    from core.semantics import PendingStatus, storage_projection
    from skills.nutrition.pending_store import PendingStatus as StoreStatus

    store_values = {s.value for s in StoreStatus}
    for status in PendingStatus:
        assert storage_projection(status) in store_values, (
            f"{status} maps to a storage state that does not exist")

    # And the mapping is not the identity: the scopes genuinely differ.
    assert storage_projection(PendingStatus.COMMITTED) == "consumed"
    assert storage_projection(PendingStatus.AWAITING_CLARIFICATION) == "active"


# ── the two failure states, and the two idempotency guarantees ───────────────

def test_failed_is_not_both_terminal_and_claimable():
    """THE CONTRADICTION THIS FIXES. `FAILED` was terminal AND projected onto a
    claimable row — the operation is over and may continue. A failed operation
    would have been reloaded as open on the next turn and reprocessed with no
    explicit retry transition.

    Split rather than picked, because both models are real: a transient write
    error should retry, a rejected commit should not.
    """
    from core.semantics import PendingStatus, storage_projection

    assert PendingStatus.FAILED.is_terminal
    assert storage_projection(PendingStatus.FAILED) != "active", (
        "a terminal failure must not leave a claimable row")

    assert not PendingStatus.RETRYABLE_FAILURE.is_terminal
    assert storage_projection(PendingStatus.RETRYABLE_FAILURE) == "active"


def test_retry_is_bounded():
    """The exhausted case is no longer expressible, which is stronger than
    asserting `may_retry` is False for it — that state cannot be constructed at
    all, so `record_failure` is the only way to reach the boundary and it lands
    on FAILED."""
    import dataclasses

    from core.semantics import PendingOperation, PendingStatus

    op = PendingOperation(id="p", user_id="u", domain="food",
                          status=PendingStatus.RETRYABLE_FAILURE,
                          attempt_count=2, max_attempts=3)
    assert op.may_retry
    # A terminal state cannot be built without a reason, so the FAILED case is
    # reached the only way it can be — through the transition that supplies one.
    terminal = op.record_failure("boom")
    assert terminal.status is PendingStatus.FAILED and not terminal.may_retry
    assert terminal.terminal_reason == "attempts_exhausted"


def test_the_projection_is_lossy_and_has_no_inverse():
    """`_STORAGE_PROJECTION` is a projection, not the persisted state.

    Five operation states share "active", so a restart reading only the row
    learns that something is open and CANNOT learn whether it was waiting on
    the user, ready to commit, already committing, or a retryable failure —
    which need different next actions. Both must be persisted; the operation
    status may never be reconstructed from the row status.
    """
    from collections import Counter

    from core.semantics import PendingStatus, storage_projection

    counts = Counter(storage_projection(s) for s in PendingStatus)
    assert counts["active"] >= 5, (
        "if this drops to 1 the projection became invertible and this test "
        "should be replaced, not deleted")

    import core.semantics as S
    assert not hasattr(S, "operation_status_from_storage"), (
        "an inverse cannot exist: five states share one row status")


def test_answer_claim_and_commit_idempotency_are_separate_fields():
    """TWO GUARANTEES, NOT ONE. `claim()` proves exactly one caller consumed
    the ANSWER; it says nothing about the ledger write that follows. A worker
    can claim, commit food, crash before marking the operation consumed, and a
    retry can commit again.
    """
    from core.semantics import PendingOperation

    fields = PendingOperation.__dataclass_fields__
    assert "answer_claim_key" in fields and "commit_key" in fields
    assert "attempt_count" in fields and "last_error" in fields


# ── the state that must not exist ────────────────────────────────────────────

def test_an_exhausted_retryable_failure_is_unconstructable():
    """The same "over and yet continuing" ambiguity that `FAILED` had, one
    level down: exhausted RETRYABLE_FAILURE is open, stored active, and
    forbidden to retry.

    Rejected at CONSTRUCTION rather than described in a comment, so no code
    path can produce it — including a future one nobody has written.
    """
    from core.semantics import PendingOperation, PendingStatus

    with pytest.raises(ValueError, match="not retryable"):
        PendingOperation(id="p", user_id="u", domain="food",
                         status=PendingStatus.RETRYABLE_FAILURE,
                         attempt_count=3, max_attempts=3)


def test_record_failure_transitions_atomically():
    """The transition happens WHEN THE ATTEMPT IS RECORDED, not in a later
    sweep. A cleanup job would leave a window in which the operation is open,
    stored active and unable to retry — the ambiguity removed above,
    reintroduced as a race."""
    from core.semantics import PendingOperation, PendingStatus

    op = PendingOperation(id="p", user_id="u", domain="food", max_attempts=3)
    op = op.record_failure("first")
    assert op.status is PendingStatus.RETRYABLE_FAILURE and op.may_retry
    op = op.record_failure("second")
    assert op.may_retry and op.attempt_count == 2
    op = op.record_failure("third")
    assert op.status is PendingStatus.FAILED
    assert op.is_terminal_state if hasattr(op, "is_terminal_state") \
        else op.status.is_terminal
    assert not op.may_retry and not op.is_open
    assert op.last_error == "third"


def test_a_terminal_operation_says_why_it_ended():
    """Cancellation, permanent validation failure and exhausted retries all
    project onto the same storage row. Without a persisted reason, support and
    recovery tooling read an infrastructure failure as somebody changing their
    mind."""
    from core.semantics import PendingOperation, PendingStatus

    op = PendingOperation(id="p", user_id="u", domain="food", max_attempts=1)
    assert op.record_failure("db down").terminal_reason == "attempts_exhausted"
    assert op.cancel().terminal_reason == "user_cancelled"
    assert op.cancel("validation_rejected").terminal_reason == \
        "validation_rejected"
    # And the two are distinguishable even though the row is not.
    from core.semantics import storage_projection
    assert storage_projection(PendingStatus.FAILED) == \
        storage_projection(PendingStatus.CANCELLED)


# ── fields are not guarantees ────────────────────────────────────────────────

def test_the_enforcement_gap_is_measured_not_asserted():
    """`answer_claim_key` and `commit_key` are FIELDS. Adding them delivers no
    idempotency, and the gap between declaring and enforcing is exactly where a
    meal commits twice.

    This pins the honest state: the answer claim IS enforced (a conditional
    UPDATE exists, unwired); the ledger boundary is NOT (no constraint exists).
    When the adoption adds it, this test changes to assert the opposite.
    """
    from core.semantics import adoption_requirements

    req = adoption_requirements()
    assert req["answer_consumption"]["enforced"] is True
    assert req["ledger_mutation"]["enforced"] is False, (
        "if this is now enforced, the adoption landed — update the test")
    assert req["duplicate_commit"]["enforced"] is False
    assert "UNIQUE" in req["ledger_mutation"]["mechanism"], (
        "an application-level check cannot arbitrate concurrent workers")


# ── one transition authority ─────────────────────────────────────────────────

def _committed():
    from core.semantics import PendingOperation, PendingStatus
    return (PendingOperation(id="p", user_id="u", domain="food")
            .transition_to(PendingStatus.READY_TO_COMMIT)
            .transition_to(PendingStatus.COMMITTING)
            .transition_to(PendingStatus.COMMITTED, commit_key="mc_1"))


@pytest.mark.parametrize("action", [
    lambda op: op.record_failure("timeout"),
    lambda op: op.cancel(),
])
def test_a_committed_meal_cannot_be_reopened(action):
    """PREVENTING INVALID SHAPES IS NOT PREVENTING INVALID TRANSITIONS, and the
    model did the first while permitting the second. `committed.record_failure()`
    returned a retryable operation — a committed meal, reopened."""
    from core.semantics import InvalidPendingTransition

    with pytest.raises(InvalidPendingTransition):
        action(_committed())


def test_a_cancelled_operation_cannot_be_retried():
    from core.semantics import (InvalidPendingTransition, PendingOperation)

    cancelled = PendingOperation(id="p", user_id="u", domain="food").cancel()
    with pytest.raises(InvalidPendingTransition):
        cancelled.record_failure("db down")


def test_every_terminal_state_is_a_dead_end():
    """The property that makes the table worth having: terminal means terminal,
    for all four, with no exceptions to remember."""
    from core.semantics import _ALLOWED_TRANSITIONS, PendingStatus

    for status in PendingStatus:
        if status.is_terminal:
            assert _ALLOWED_TRANSITIONS[status] == set(), (
                f"{status.value} can still move")


def test_the_table_covers_every_state():
    """A state missing from the table would refuse ALL transitions and look
    terminal — a silent freeze rather than an error."""
    from core.semantics import _ALLOWED_TRANSITIONS, PendingStatus

    assert set(_ALLOWED_TRANSITIONS) == set(PendingStatus)


def test_the_helpers_route_through_the_authority():
    """`record_failure` and `cancel` used to replace the status independently,
    which is why the invalid transitions existed. One boundary means one place
    to be right."""
    import inspect

    from core.semantics import PendingOperation

    for fn in (PendingOperation.record_failure, PendingOperation.cancel):
        src = inspect.getsource(fn)
        assert "transition_to(" in src, f"{fn.__name__} bypasses the authority"
        assert "replace(" not in src, f"{fn.__name__} still replaces directly"


# ── terminal invariants hold however the object was built ────────────────────

@pytest.mark.parametrize("status", ["failed", "cancelled", "expired"])
def test_a_terminal_operation_cannot_be_built_without_a_reason(status):
    """The property held only for callers using the helpers, so direct
    construction could still produce a terminal row with no reason — which
    recovery tooling reads as a user cancellation."""
    from core.semantics import PendingOperation, PendingStatus

    with pytest.raises(ValueError, match="terminal_reason"):
        PendingOperation(id="p", user_id="u", domain="food",
                         status=PendingStatus(status))


def test_a_committed_operation_requires_a_commit_reference():
    """COMMITTED needs a RESULT, not a failure reason: "it ended" is not the
    interesting fact about a commit, "which write" is."""
    from core.semantics import PendingOperation, PendingStatus

    with pytest.raises(ValueError, match="commit_key"):
        PendingOperation(id="p", user_id="u", domain="food",
                         status=PendingStatus.COMMITTED)
    assert _committed().commit_key == "mc_1"


def test_the_happy_path_still_works():
    """Guards against a table so strict nothing can proceed."""
    from core.semantics import PendingOperation, PendingStatus

    op = PendingOperation(id="p", user_id="u", domain="food")
    op = op.transition_to(PendingStatus.AWAITING_CLARIFICATION)
    op = op.transition_to(PendingStatus.READY_TO_COMMIT)
    op = op.transition_to(PendingStatus.COMMITTING)
    op = op.transition_to(PendingStatus.COMMITTED, commit_key="mc_2")
    assert op.status.is_terminal and not op.is_open

    # And a retry genuinely recovers.
    retry = (PendingOperation(id="p2", user_id="u", domain="food",
                              max_attempts=3)
             .record_failure("transient"))
    assert retry.may_retry
    assert retry.transition_to(PendingStatus.RESOLVING).is_open
