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


def test_the_three_live_owners_are_still_three():
    """A ratchet on the fragmentation itself. This number must go DOWN as the
    migration proceeds; it may not go up."""
    live = {name: len(_prod_refs(name)) for name in
            ("payload_json", "deferred_calls", "staged_items")}
    assert all(v > 0 for v in live.values()), live
    assert sum(live.values()) <= 60, (
        f"pending state spread further rather than consolidating: {live}")


def test_the_two_pending_status_enums_are_reconciled_in_code():
    """Two enums with overlapping member names and different SCOPES is how a
    single source of truth quietly becomes two. The mapping is code so the
    relationship cannot drift into folklore."""
    from core.semantics import PendingStatus, storage_status
    from skills.nutrition.pending_store import PendingStatus as StoreStatus

    store_values = {s.value for s in StoreStatus}
    for status in PendingStatus:
        assert storage_status(status) in store_values, (
            f"{status} maps to a storage state that does not exist")

    # And the mapping is not the identity: the scopes genuinely differ.
    assert storage_status(PendingStatus.COMMITTED) == "consumed"
    assert storage_status(PendingStatus.AWAITING_CLARIFICATION) == "active"
