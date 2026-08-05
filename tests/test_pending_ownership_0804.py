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
        # EITHER DOOR, because both enforce the table and the field allowlist.
        # `_transition_unchecked` is the authority; `transition_to` is the
        # public guard on top of it that additionally refuses failure targets.
        # What must never appear is a bare `replace`, which is how the invalid
        # transitions existed in the first place.
        assert "_transition_unchecked(" in src or "self.transition_to(" in src, (
            f"{fn.__name__} bypasses the authority")
        assert "replace(" not in src or "_transition_unchecked" in src, (
            f"{fn.__name__} still replaces directly")


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


# ── failure is entered by recording one ──────────────────────────────────────

def _fresh():
    from core.semantics import PendingOperation
    return PendingOperation(id="p", user_id="u", domain="food", max_attempts=3)


@pytest.mark.parametrize("target", ["retryable_failure", "failed"])
def test_a_failure_state_cannot_be_entered_directly(target):
    """THE BOUND LIVED IN `record_failure`, SO THE PUBLIC DOOR BYPASSED IT.
    Verified before fixing: `transition_to(RETRYABLE_FAILURE)` produced a
    failure state with attempt_count=0 and no error, then self-transitioned
    five more times without `max_attempts` ever engaging. "Bounded by
    max_attempts" was not true of the door callers actually use.
    """
    from core.semantics import InvalidPendingTransition, PendingStatus

    with pytest.raises(InvalidPendingTransition, match="record_failure"):
        _fresh().transition_to(PendingStatus(target))


def test_the_retryable_self_transition_is_closed_too():
    """The loop that made the bound unreachable."""
    from core.semantics import InvalidPendingTransition, PendingStatus

    once = _fresh().record_failure("first")
    with pytest.raises(InvalidPendingTransition):
        once.transition_to(PendingStatus.RETRYABLE_FAILURE)


def test_every_recorded_failure_increments_exactly_once():
    first = _fresh().record_failure("first")
    second = first.record_failure("second")
    assert (first.attempt_count, second.attempt_count) == (1, 2)
    assert second.last_error == "second"


def test_the_bound_now_actually_engages():
    """What the earlier claim asserted and the code did not do."""
    from core.semantics import PendingStatus

    op = _fresh()
    for i in range(3):
        op = op.record_failure(f"attempt {i + 1}")
    assert op.status is PendingStatus.FAILED and op.attempt_count == 3


# ── a transition may not rewrite semantic payload ────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("user_id", "someone-else"),
    ("domain", "workout"),
    ("id", "another-operation"),
    ("mode", "quick"),
])
def test_a_transition_cannot_change_who_or_what_it_is(field, value):
    """`**changes` reached `replace()` unfiltered, so a lifecycle move could
    rewrite `user_id` AND `domain` — verified, not hypothesised. A transition
    changes lifecycle state; semantic payload belongs to methods that revise
    the operation."""
    from core.semantics import InvalidPendingTransition, PendingStatus

    with pytest.raises(InvalidPendingTransition, match="semantic payload"):
        _fresh().transition_to(PendingStatus.AWAITING_CLARIFICATION,
                               **{field: value})


def test_lifecycle_fields_are_still_settable():
    """A guard that blocks everything is not a guard, it is a wall."""
    from core.semantics import PendingStatus

    op = (_fresh().transition_to(PendingStatus.READY_TO_COMMIT)
          .transition_to(PendingStatus.COMMITTING)
          .transition_to(PendingStatus.COMMITTED, commit_key="mc_9",
                         version=2))
    assert op.commit_key == "mc_9" and op.version == 2


def test_record_failure_uses_the_primitive_not_the_public_door():
    """If it called `transition_to`, it would refuse itself — the check that
    closes the bypass would close the only legitimate path into failure."""
    import inspect

    from core.semantics import PendingOperation

    src = inspect.getsource(PendingOperation.record_failure)
    assert "_transition_unchecked(" in src
    assert "self.transition_to(" not in src


# ── the primitive is safe when misused ───────────────────────────────────────

@pytest.mark.parametrize("changes,why", [
    ({}, "no accounting at all"),
    ({"attempt_count": 1}, "counted but no error"),
    ({"last_error": "x"}, "error but no count"),
    ({"attempt_count": 7, "last_error": "x"}, "count is not +1"),
    ({"attempt_count": 0, "last_error": "x"}, "count did not move"),
])
def test_the_primitive_refuses_failure_without_accounting(changes, why):
    """"UNCHECKED" NAMES ONE THING ONLY: it does not refuse failure TARGETS,
    because it is how `record_failure` reaches them.

    A private door that is safe only when called correctly is the same bypass
    one underscore further in, and this one had it — verified before fixing:
    `_transition_unchecked(RETRYABLE_FAILURE)` produced attempts=0 and retried
    forever, exactly as the public door had.
    """
    from core.semantics import InvalidPendingTransition, PendingStatus

    with pytest.raises(InvalidPendingTransition):
        _fresh()._transition_unchecked(PendingStatus.RETRYABLE_FAILURE,
                                       **changes)


def test_the_primitive_refuses_a_terminal_failure_with_no_reason():
    """Refused on the CAUSE now, which fires before the reason check — a
    stronger refusal than the one this test originally asserted. The reason
    requirement still holds and is covered where a cause IS supplied."""
    from core.semantics import (InvalidPendingTransition, PendingStatus,
                                TransitionCause)

    with pytest.raises(InvalidPendingTransition):
        _fresh()._transition_unchecked(PendingStatus.FAILED)

    # With a legitimate cause, the missing reason is what stops it.
    op = _fresh().record_failure("first").record_failure("second")
    with pytest.raises(InvalidPendingTransition, match="say why"):
        op._transition_unchecked(PendingStatus.FAILED,
                                 _cause=TransitionCause.ATTEMPTS_EXHAUSTED,
                                 last_error="third",
                                 attempt_count=op.attempt_count + 1)


def test_the_only_legitimate_caller_still_works():
    """A primitive strict enough to refuse its own caller is not a fix."""
    from core.semantics import PendingStatus

    op = _fresh()
    for i in range(3):
        op = op.record_failure(f"attempt {i + 1}")
    assert op.status is PendingStatus.FAILED
    assert op.attempt_count == 3 and op.last_error == "attempt 3"


def test_no_path_reaches_a_failure_state_without_accounting():
    """The property, stated once over BOTH doors: every route into a retryable
    failure increments exactly one attempt and carries an error."""
    from core.semantics import InvalidPendingTransition, PendingStatus

    op = _fresh()
    for door in (op.transition_to, op._transition_unchecked):
        with pytest.raises(InvalidPendingTransition):
            door(PendingStatus.RETRYABLE_FAILURE)
    recorded = op.record_failure("the only way in")
    assert recorded.attempt_count == 1 and recorded.last_error


# ── two entries into failure, and nothing else ───────────────────────────────

def test_the_primitive_refuses_terminal_failure_without_a_cause():
    """THE CLAIM WAS FALSE FOR `FAILED`. Verified before fixing:

        op._transition_unchecked(FAILED, terminal_reason="permanent_failure")
        -> attempts=0, last_error='', record_failure never called

    "record_failure is the only way in" was a convention, and a convention is
    not a check. `TransitionCause` makes it one: a raw caller has no cause, and
    the primitive refuses a failure target without one.
    """
    from core.semantics import InvalidPendingTransition, PendingStatus

    with pytest.raises(InvalidPendingTransition, match="fail_permanently"):
        _fresh()._transition_unchecked(PendingStatus.FAILED,
                                       terminal_reason="permanent_failure")


def test_a_cause_still_cannot_forge_the_wrong_shape():
    """The cause is not a bypass token. Each one admits exactly one shape."""
    from core.semantics import (InvalidPendingTransition, PendingStatus,
                                TransitionCause)

    op = _fresh()
    # A recorded failure is retryable until attempts run out — it may not jump.
    with pytest.raises(InvalidPendingTransition, match="retryable until"):
        op._transition_unchecked(PendingStatus.FAILED,
                                 _cause=TransitionCause.FAILURE_RECORDED,
                                 last_error="x", terminal_reason="y")
    # Exhaustion is reached by recording the FINAL attempt, not asserted.
    with pytest.raises(InvalidPendingTransition, match="final attempt"):
        op._transition_unchecked(PendingStatus.FAILED,
                                 _cause=TransitionCause.ATTEMPTS_EXHAUSTED,
                                 last_error="x", terminal_reason="y")
    # A permanent failure does not produce a RETRYABLE one.
    with pytest.raises(InvalidPendingTransition, match="does not produce"):
        op._transition_unchecked(PendingStatus.RETRYABLE_FAILURE,
                                 _cause=TransitionCause.PERMANENT_FAILURE,
                                 last_error="x", attempt_count=1)


def test_permanent_failure_skips_the_retry_budget():
    """A validation rejection is not worth three attempts. Burning the budget
    on it would delay the terminal state without changing it."""
    from core.semantics import PendingStatus

    op = _fresh().fail_permanently("validation_rejected", "payload rejected")
    assert op.status is PendingStatus.FAILED
    assert op.attempt_count == 0 and not op.may_retry
    assert op.terminal_reason == "validation_rejected"
    assert op.last_error == "payload rejected"


def test_exhaustion_and_permanent_failure_are_distinguishable():
    """Both are FAILED; recovery tooling needs to tell an outage from a
    rejection."""
    op = _fresh()
    exhausted = op
    for i in range(3):
        exhausted = exhausted.record_failure(f"attempt {i + 1}")
    permanent = op.fail_permanently("validation_rejected", "bad payload")

    assert exhausted.terminal_reason == "attempts_exhausted"
    assert permanent.terminal_reason == "validation_rejected"
    assert exhausted.attempt_count == 3 and permanent.attempt_count == 0


def test_a_permanent_failure_needs_both_a_reason_and_an_error():
    with pytest.raises(ValueError):
        _fresh().fail_permanently("", "error")
    with pytest.raises(ValueError):
        _fresh().fail_permanently("reason", "")


def test_no_route_into_any_failure_state_lacks_accounting():
    """The property over EVERY door, stated once. This is the assertion whose
    earlier version was true of RETRYABLE_FAILURE and false of FAILED."""
    from core.semantics import InvalidPendingTransition, PendingStatus

    op = _fresh()
    for target in (PendingStatus.RETRYABLE_FAILURE, PendingStatus.FAILED):
        for door in (op.transition_to, op._transition_unchecked):
            with pytest.raises(InvalidPendingTransition):
                door(target)
    assert op.record_failure("x").last_error
    assert op.fail_permanently("r", "e").last_error
