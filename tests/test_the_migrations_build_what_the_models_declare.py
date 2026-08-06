"""THE SCHEMA THE MIGRATIONS BUILD MUST BE THE SCHEMA THE MODELS DECLARE.

COST: `pending_operations.created_at` had no DEFAULT in production. The model
says `server_default=func.now()`; the migration that created the table did not.
SQLAlchemy relies on the server for a `server_default` and omits the column on
INSERT, so Postgres wrote NULL — measured 2026-08-06, 7 of 7 rows.

`OwnedOperation.asked_at` reads that column. So every answer latency and every
abandonment age was None for as long as the table has existed, and D4's latency
metric was structurally unrecordable before the window ever opened.

WHY 7882 PASSING TESTS COULD NOT SEE IT. Every suite — SQLite and Postgres
alike — builds its schema with `Base.metadata.create_all`, which reads the
MODELS. Production is built by ALEMBIC, which reads the migrations. The two
descriptions of the same database were never compared to each other, so any
drift between them was invisible by construction, in both directions, forever.

That is the same shape as the trace ring and `/health`: an instrument that
cannot report the thing it appears to be about. This file is the comparison.

Postgres only, and that is the point — SQLite would have to be excluded from
the defaults comparison anyway, and the drift that matters is the drift in the
database production actually runs.
"""
import os
import pathlib

import pytest

PG = os.getenv("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not PG,
    reason="needs a real Postgres (TEST_POSTGRES_URL) — this compares two "
           "schema builders and SQLite is neither of them")


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


@pytest.fixture(scope="module")
def built():
    """Two schemas of the same database: one from alembic, one from the models.

    Alembic runs as a SUBPROCESS with DATABASE_URL set, because `alembic/env.py`
    resolves the URL from the environment and ignores a Config passed in
    process. Driving it the way production drives it is also the point — a
    comparison that ran migrations through a path production never uses would
    be describing something else.
    """
    import subprocess
    import sys

    from sqlalchemy import create_engine, text

    from db.database import Base, pin_session_utc
    from db import models  # noqa: F401 — registers tables

    url = _sync_url(PG)
    engine = pin_session_utc(create_engine(url))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS mig CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS mdl CASCADE"))
        conn.execute(text("CREATE SCHEMA mig"))
        conn.execute(text("CREATE SCHEMA mdl"))

    env = dict(os.environ, DATABASE_URL=f"{url}?options=-csearch_path%3Dmig")
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True, env=env,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent))
    assert proc.returncode == 0, (
        f"alembic upgrade head failed — the migrations cannot build the "
        f"schema at all:\n{proc.stdout}\n{proc.stderr}")

    mdl_engine = pin_session_utc(create_engine(
        url, connect_args={"options": "-csearch_path=mdl"}))
    Base.metadata.create_all(mdl_engine)

    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS mig CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS mdl CASCADE"))
    engine.dispose()
    mdl_engine.dispose()


#: Alembic's own bookkeeping. It exists only in the migrated schema by
#: definition, and modelling it would be modelling the migration tool.
_NOT_A_MODEL = {"alembic_version"}


def _columns(conn, schema):
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT table_name, column_name, column_default, is_nullable, data_type "
        "FROM information_schema.columns WHERE table_schema = :s"
    ), {"s": schema}).fetchall()
    return {(t, c): (d, n, ty) for t, c, d, n, ty in rows
            if t not in _NOT_A_MODEL}


def test_no_column_exists_in_one_and_not_the_other(built):
    mig, mdl = _columns(built.connect(), "mig"), _columns(built.connect(), "mdl")
    only_model = sorted(set(mdl) - set(mig))
    only_migration = sorted(set(mig) - set(mdl))
    assert not only_model, (
        f"declared on the model and never created by a migration — production "
        f"will not have these columns: {only_model}")
    assert not only_migration, (
        f"created by a migration and absent from the model — nothing reads "
        f"them and no test describes them: {only_migration}")


def test_every_server_default_survives_the_migration(built):
    """The exact defect: a default the model promises and the migration omits.

    SQLAlchemy does not send a value for a `server_default` column — it lets
    the database fill it. So a column whose default exists only in the model is
    a column that is NULL in production and correct in every test.
    """
    mig, mdl = _columns(built.connect(), "mig"), _columns(built.connect(), "mdl")
    missing = []
    for key, (default, _nullable, _ty) in mdl.items():
        if key not in mig or default is None:
            continue
        mig_default = mig[key][0]
        if mig_default is None:
            missing.append((key, default))
    assert not missing, (
        "the model promises a server default that the migrations do not "
        "create, so production writes NULL while every test passes:\n  " +
        "\n  ".join(f"{t}.{c} should default to {d}" for (t, c), d in missing))
