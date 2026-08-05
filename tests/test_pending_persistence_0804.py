"""Durable pending operations, and a revision that cannot be overwritten.

The first irreversible step: pending state that survives a restart and a second
worker. Every write is conditional on the revision the writer READ, because
without that two turns arriving seconds apart both read revision 3, both write
revision 4, and the second silently erases the first.

SHADOW ONLY. Nothing reads these rows for a live decision; the legacy path
stays authoritative behind `PENDING_OPERATION_PERSIST_SHADOW`.
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.pool import StaticPool

from core import pending_repository as repo
from db.models import Base


@pytest_asyncio.fixture
async def sessions():
    """Two sessions on one database — two workers, one row store."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    a, b = maker(), maker()
    try:
        yield a, b
    finally:
        await a.close(); await b.close(); await engine.dispose()


async def _new(db, oid="op_1", **kw):
    row = await repo.create_operation(
        db, operation_id=oid, user_id=26, status="awaiting_clarification",
        storage_status="active", **kw)
    await db.commit()
    return row


# ── persistence ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_operation_survives_a_reload(sessions):
    """Written by one session, read by another — which is what "survives a
    restart" means when the process is gone."""
    a, b = sessions
    await _new(a, mode="strict", source_turn_id="turn_7",
               payload=repo.encode_payload(
                   items=[{"id": "item:1", "food": "Chicken"}],
                   unresolved_fields=[{"id": "item:1.portion"}],
                   assumptions=[{"field": "rice.quantity"}]))

    row = await repo.load_operation(b, "op_1")
    assert row is not None
    assert row.status == "awaiting_clarification"
    assert row.storage_status == "active"
    assert row.revision == 0
    assert row.mode == "strict" and row.source_turn_id == "turn_7"

    payload = repo.decode_payload(row.canonical_payload)
    assert payload["items"][0]["id"] == "item:1", "stable item ids must survive"
    assert payload["unresolved_fields"][0]["id"] == "item:1.portion"
    assert payload["assumptions"][0]["field"] == "rice.quantity"


@pytest.mark.asyncio
async def test_a_terminal_reason_survives(sessions):
    a, b = sessions
    await _new(a, oid="op_t")
    assert (await repo.mark_cancelled(
        a, operation_id="op_t", expected_revision=0,
        reason="user_cancelled")).ok
    await a.commit()

    row = await repo.load_operation(b, "op_t")
    assert row.status == "cancelled" and row.terminal_reason == "user_cancelled"
    assert row.storage_status == "cancelled"


@pytest.mark.asyncio
async def test_status_is_not_reconstructed_from_storage_status(sessions):
    """Five operation states project onto "active". The projection is for
    QUERIES; the status is read from its own column, and this pins that they
    are stored separately rather than derived."""
    a, b = sessions
    await _new(a, oid="op_s")
    assert (await repo.mark_committing(
        a, operation_id="op_s", expected_revision=0, commit_key="k")).ok
    await a.commit()

    row = await repo.load_operation(b, "op_s")
    assert row.storage_status == "active"     # still open, by the projection
    assert row.status == "committing"          # but the real state is richer


# ── optimistic concurrency ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_workers_on_one_revision_and_exactly_one_wins(sessions):
    a, b = sessions
    await _new(a, oid="op_c")

    first = await repo.save_revision(a, operation_id="op_c",
                                     expected_revision=0, mode="quick")
    await a.commit()
    second = await repo.save_revision(b, operation_id="op_c",
                                      expected_revision=0, mode="strict")

    assert first.ok and first.revision == 1
    assert second.ok is False and second.conflict is True
    assert second.revision == 1, "the conflict reports the CURRENT revision"


@pytest.mark.asyncio
async def test_a_stale_write_does_not_overwrite_a_newer_one(sessions):
    """Revision 2 may not overwrite revision 3 — the silent-erase this exists
    to prevent."""
    a, b = sessions
    await _new(a, oid="op_r", mode="original")
    await repo.save_revision(a, operation_id="op_r", expected_revision=0,
                             mode="second")
    await a.commit()
    await repo.save_revision(a, operation_id="op_r", expected_revision=1,
                             mode="third")
    await a.commit()

    stale = await repo.save_revision(b, operation_id="op_r",
                                     expected_revision=1, mode="clobber")
    assert stale.conflict is True
    row = await repo.load_operation(b, "op_r")
    assert row.mode == "third" and row.revision == 2


@pytest.mark.asyncio
async def test_a_conflict_is_typed_not_a_bare_false(sessions):
    """"it did not save" and "somebody else got there first" need different
    handling and used to look identical."""
    a, _ = sessions
    await _new(a, oid="op_x")
    out = await repo.save_revision(a, operation_id="op_x",
                                   expected_revision=99, mode="x")
    assert out.ok is False and out.conflict is True
    assert isinstance(out, repo.SaveOutcome)


# ── failure accounting, mirrored from the model ──────────────────────────────

@pytest.mark.asyncio
async def test_recorded_failures_exhaust_into_a_terminal_state(sessions):
    a, _ = sessions
    await _new(a, oid="op_f")
    rev = 0
    for i in range(3):
        out = await repo.record_failure(
            a, operation_id="op_f", expected_revision=rev,
            error=f"attempt {i + 1}", attempt_count=i, max_attempts=3)
        assert out.ok
        rev = out.revision
        await a.commit()

    row = await repo.load_operation(a, "op_f")
    assert row.status == "failed" and row.attempt_count == 3
    assert row.terminal_reason == "attempts_exhausted"
    assert row.storage_status == "cancelled"


@pytest.mark.asyncio
async def test_a_failure_must_carry_its_error(sessions):
    a, _ = sessions
    await _new(a, oid="op_e")
    with pytest.raises(ValueError):
        await repo.record_failure(a, operation_id="op_e",
                                  expected_revision=0, error="",
                                  attempt_count=0)


@pytest.mark.asyncio
async def test_a_committed_operation_requires_a_commit_key(sessions):
    a, _ = sessions
    await _new(a, oid="op_k")
    with pytest.raises(ValueError):
        await repo.mark_committed(a, operation_id="op_k",
                                  expected_revision=0, commit_key="")


# ── serialization ────────────────────────────────────────────────────────────

def test_the_payload_is_versioned_canonical_json():
    raw = repo.encode_payload(items=[{"id": "item:1"}])
    data = json.loads(raw)
    assert data["schema_version"] == repo.SCHEMA_VERSION
    assert set(data) >= {"items", "unresolved_fields", "assumptions"}


def test_an_unknown_future_field_survives_a_read():
    """A row written by a newer build must round-trip through an older one
    without losing what it does not understand."""
    raw = json.dumps({"schema_version": 1, "items": [],
                      "unresolved_fields": [], "assumptions": [],
                      "something_new": {"a": 1}})
    assert repo.decode_payload(raw)["something_new"] == {"a": 1}


@pytest.mark.parametrize("raw", [
    "{not json",
    "[]",
    json.dumps({"items": []}),                      # no schema_version
    json.dumps({"schema_version": 999, "items": []}),
])
def test_a_malformed_payload_fails_closed(raw):
    """An empty operation looks like "nothing was pending", which is how a held
    meal disappears. Raising is the safe direction."""
    with pytest.raises(repo.UnreadablePayload):
        repo.decode_payload(raw)


def test_an_absent_payload_is_empty_not_an_error():
    out = repo.decode_payload(None)
    assert out["items"] == [] and out["schema_version"] == repo.SCHEMA_VERSION


# ── rollout flags ────────────────────────────────────────────────────────────

def test_every_phase_has_its_own_flag(monkeypatch):
    """One flag for every phase means a problem in any of them costs all
    three."""
    for name, fn in (("PENDING_OPERATION_PERSIST_SHADOW",
                      repo.persist_shadow_enabled),
                     ("PENDING_OPERATION_READ_SHADOW", repo.read_shadow_enabled),
                     ("COMMIT_COORDINATOR_SHADOW", repo.commit_shadow_enabled),
                     ("COMMIT_COORDINATOR_ENFORCE",
                      repo.commit_enforce_enabled)):
        monkeypatch.delenv(name, raising=False)
        assert fn() is False, f"{name} must default OFF"
        monkeypatch.setenv(name, "true")
        assert fn() is True
        monkeypatch.setenv(name, "false")
        assert fn() is False
