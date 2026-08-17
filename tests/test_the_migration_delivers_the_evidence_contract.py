"""⛔⛔ THE EVIDENCE-DURABILITY CONTRACT, PROVEN ON THE MIGRATED SCHEMA.

P17f's build caught the model declaring an FK while the migration added a bare
Integer — schema drift no ORM test can see, because every suite builds from the
MODELS with `create_all` while production is built by ALEMBIC. The sibling gate
(`test_the_migrations_build_what_the_models_declare`) compares columns and
server defaults; it fetches nullability and never checks it, and knows nothing
of constraints — which is precisely where this drift lived.

So this file asserts the contract on the database THE MIGRATIONS build:

    product_evidence.provider_revision    NOT NULL, DEFAULT ''
    UNIQUE (provider, canonical_code, provider_revision, source_fingerprint)
    food_entries.product_evidence_id      FK -> product_evidence.id, RESTRICT

If the model and the production migration ever disagree on evidence
durability, CI fails — the lesson paid for once, made permanent.

Postgres only, like the sibling, and for the same reason: the drift that
matters is the drift in the database production actually runs.
"""
import os
import pathlib

import pytest

PG = os.getenv("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not PG,
    reason="needs a real Postgres (TEST_POSTGRES_URL) — the contract under "
           "test is about the schema production runs, and SQLite is not it")


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


@pytest.fixture(scope="module")
def migrated():
    """The schema alembic builds, in an isolated search path.

    Driven as a SUBPROCESS with DATABASE_URL set, the way production drives it
    — `alembic/env.py` resolves the URL from the environment, and a comparison
    that ran migrations through a path production never uses would be
    describing something else.
    """
    import subprocess
    import sys

    from sqlalchemy import create_engine, text

    from db.database import pin_session_utc

    url = _sync_url(PG)
    # One Clock: every Postgres engine is pinned UTC or refuses to run.
    engine = pin_session_utc(create_engine(url))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS evc CASCADE"))
        conn.execute(text("CREATE SCHEMA evc"))

    env = dict(os.environ, DATABASE_URL=f"{url}?options=-csearch_path%3Devc")
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "heads"],
        capture_output=True, text=True, env=env,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent))
    assert proc.returncode == 0, (
        f"alembic upgrade heads failed:\n{proc.stdout}\n{proc.stderr}")

    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS evc CASCADE"))
    engine.dispose()


def test_provider_revision_is_not_null_with_an_empty_default(migrated):
    """⛔ Postgres and SQLite both admit unlimited duplicates through a UNIQUE
    constraint when a component is NULL. NOT NULL DEFAULT '' is what makes
    revision-less providers participate in snapshot identity — as a property
    of the PRODUCTION schema, not a habit of the store code."""
    from sqlalchemy import text

    with migrated.connect() as conn:
        row = conn.execute(text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema='evc' AND table_name='product_evidence' "
            "AND column_name='provider_revision'")).one()
    assert row.is_nullable == "NO", (
        "provider_revision is nullable in the migrated schema — a NULL slips "
        "every such row past the uniqueness constraint")
    assert row.column_default is not None and "''" in row.column_default


def test_snapshot_identity_is_the_four_part_key(migrated):
    """provider + canonical_code + provider_revision + source_fingerprint —
    each EXPLICIT. Two providers describing one barcode are two snapshots;
    two provider revisions of identical facts are two snapshots."""
    from sqlalchemy import text

    with migrated.connect() as conn:
        cols = [r.column_name for r in conn.execute(text(
            "SELECT ccu.column_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name "
            " AND tc.table_schema = ccu.table_schema "
            "WHERE tc.table_schema='evc' "
            "  AND tc.constraint_name='uq_product_evidence_snapshot' "
            "ORDER BY ccu.ordinal_position")).fetchall()]
    assert cols == ["provider", "canonical_code", "provider_revision",
                    "source_fingerprint"], (
        f"the snapshot identity is {cols!r} in production — evidence identity "
        f"has drifted from the four-part contract")


def test_referenced_evidence_is_delete_restricted(migrated):
    """⛔⛔ THE DRIFT THIS FILE EXISTS FOR. The model declared this FK and the
    first migration draft added a bare Integer — only production would have
    allowed deleting evidence a committed meal cites. Asserted on the migrated
    schema, where it was missing."""
    from sqlalchemy import text

    with migrated.connect() as conn:
        row = conn.execute(text(
            "SELECT rc.delete_rule, kcu.column_name, ccu.table_name AS ref "
            "FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            " AND rc.constraint_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON rc.unique_constraint_name = ccu.constraint_name "
            " AND rc.unique_constraint_schema = ccu.table_schema "
            "WHERE rc.constraint_schema='evc' "
            "  AND rc.constraint_name='fk_food_entry_product_evidence'"
        )).one_or_none()
    assert row is not None, (
        "fk_food_entry_product_evidence does not exist in the migrated schema "
        "— the bare-Integer drift is back and production can delete evidence "
        "a committed meal cites")
    assert row.delete_rule == "RESTRICT"
    assert row.column_name == "product_evidence_id"
    assert row.ref == "product_evidence"


def test_every_fk_the_models_declare_exists_in_the_migrated_schema(migrated):
    """⭐ THE GENERAL FORM OF THE LESSON, so the NEXT bare-Integer drift — on
    any table — fails CI too. The sibling gate compares columns and defaults;
    foreign keys were invisible to it, which is exactly where this class of
    defect lives."""
    from sqlalchemy import text

    from db.database import Base
    from db import models  # noqa: F401 — registers tables

    declared = set()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            declared.add((table.name, fk.parent.name,
                          fk.column.table.name, fk.column.name))

    with migrated.connect() as conn:
        built = {(r.tbl, r.col, r.ref_tbl, r.ref_col) for r in conn.execute(text(
            "SELECT kcu.table_name AS tbl, kcu.column_name AS col, "
            "       ccu.table_name AS ref_tbl, ccu.column_name AS ref_col "
            "FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON rc.constraint_name = kcu.constraint_name "
            " AND rc.constraint_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON rc.unique_constraint_name = ccu.constraint_name "
            " AND rc.unique_constraint_schema = ccu.table_schema "
            "WHERE rc.constraint_schema='evc'")).fetchall()}

    missing = sorted(declared - built)
    assert not missing, (
        "declared as ForeignKey on the model and absent from the migrated "
        "schema — tests will enforce these and production will not:\n  " +
        "\n  ".join(f"{t}.{c} -> {rt}.{rc}" for t, c, rt, rc in missing))
