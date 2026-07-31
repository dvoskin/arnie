"""One request, one write — the idempotency record (invariant I18).

The tap-log REST endpoints (`api/quick_log.py`) had no identity for a REQUEST,
only for the rows it produced, so a retried delivery wrote the food twice.
Measured on deployed 433cdf39f2d0: two identical taps produced two food rows,
two `created` events, and `turn_id = NULL` on both.

This table is the claim. The unique index on `key` is the enforcement — the
helper in `core/idempotency.py` inserts first and lets the database reject the
loser, so two racing workers resolve against Postgres instead of against a
select-then-insert window.

Pure ADD: a new table, no backfill, no constraint applied to existing data, so
it cannot fail on production rows and an old instance running alongside it
during a rolling deploy simply never writes to it. Rollback drops the table;
the domain rows it protected are untouched.

Parents pendinguniq001 (the single head). Deploy runs `alembic upgrade heads`.

Revision ID: idem001
Revises: pendinguniq001
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "idem001"
down_revision: Union[str, None] = "pendinguniq001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent (inspect-then-create) per [[feedback_arnie_migrate_postgres_gap]]:
    # the SQLite test DB builds this table from db/models.py metadata before
    # migrations run, so a bare create_table would fail there.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "idempotency_records" in inspector.get_table_names():
        return

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("command", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False,
                  server_default="in_progress"),
        sa.Column("result_entry_id", sa.Integer(), nullable=True),
        sa.Column("result_daily_log_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # THE guarantee. Everything else in this feature is bookkeeping around it.
    op.create_index("uq_idempotency_key", "idempotency_records", ["key"],
                    unique=True)
    op.create_index("ix_idempotency_user_created", "idempotency_records",
                    ["user_id", "created_at"])
    op.create_index("ix_idempotency_records_turn_id", "idempotency_records",
                    ["turn_id"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_turn_id",
                  table_name="idempotency_records")
    op.drop_index("ix_idempotency_user_created",
                  table_name="idempotency_records")
    op.drop_index("uq_idempotency_key", table_name="idempotency_records")
    op.drop_table("idempotency_records")
