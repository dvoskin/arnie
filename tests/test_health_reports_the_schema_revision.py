"""`/health` says which migration the live database is on.

Deployed 433cdf39f2d0 reported its commit and its feature flags and nothing at
all about the schema. `render.yaml` documents `alembic upgrade heads` as the
pre-deploy command, but the service is configured by hand in the Render
dashboard and Render never reads that file — so a deploy whose pre-deploy step
is missing looks completely healthy until the first write to a column that was
never added.

These tests pin the three properties that make the answer trustworthy:
  * it reports what the DATABASE is on, not what the code hopes
  * `in_sync` compares that against what the BUILD expects
  * it never raises — an observability gap must not become an outage
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.diagnostics import _expected_head, schema_summary


def test_the_build_knows_which_head_it_expects():
    """Read from the alembic script directory, so it cannot drift from the
    migrations that actually shipped in the image."""
    head = _expected_head()
    assert head, "the build could not name its own expected migration head"
    assert "," not in head, (
        f"multiple alembic heads ({head}) — the one-head CI check exists "
        "because a divergent chain deploys unpredictably"
    )


@pytest.mark.asyncio
async def test_it_reports_the_revision_the_database_is_actually_on(
    monkeypatch, engine,
):
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    async with factory() as db:
        await db.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await db.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('idem001')"))
        await db.commit()

    monkeypatch.setattr("db.database.AsyncSessionLocal", factory)
    out = await schema_summary()

    assert out["applied"] == "idem001"
    assert out["expected"] == _expected_head()
    assert out["in_sync"] is (out["applied"] == out["expected"])


@pytest.mark.asyncio
async def test_a_stale_database_is_reported_out_of_sync(monkeypatch, engine):
    """The deploy this endpoint exists to stop: code ahead of schema."""
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    async with factory() as db:
        await db.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await db.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('pendinguniq001')"))
        await db.commit()

    monkeypatch.setattr("db.database.AsyncSessionLocal", factory)
    out = await schema_summary()

    assert out["applied"] == "pendinguniq001"
    assert out["in_sync"] is False, (
        "a database one migration behind the build reported as in sync"
    )


@pytest.mark.asyncio
async def test_an_unreadable_schema_does_not_raise(monkeypatch, engine):
    """No `alembic_version` table at all — an unmigrated database. That is an
    answer, not a crash."""
    factory = async_sessionmaker(engine, class_=AsyncSession,
                                 expire_on_commit=False)
    monkeypatch.setattr("db.database.AsyncSessionLocal", factory)

    out = await schema_summary()

    assert out["applied"] is None
    assert "error" in out
    assert "in_sync" not in out, (
        "in_sync must be absent when applied is unknown — a missing answer is "
        "not a passing one"
    )
