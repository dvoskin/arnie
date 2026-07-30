"""Add conversation_logs.turn_id — the turn⋈operation join.

The master audit (2026-07-30 §9) could not verify "a narrated success has a
matching successful operation" — invariant I16 — because the canonical turn id
lived only on the ledger side, in three inconsistent formats, and
conversation_logs had no turn id at all. This column stores the same value the
ledger contextvar stamps on every operation the turn performs, so the join is
one indexed equality.

The backfill is deliberately narrow. Historic iOS ledger rows carry a
double-prefixed id ("ios:" + the already-prefixed idempotency key — the bug
fixed in code alongside this migration), so reconstructing exactly that
double-prefixed value is what makes HISTORIC joins work. Do not "fix" the
backfill to a single prefix: it would match nothing. Hash-fallback turns
({ch}:h:…) are unreconstructible from stored data and stay NULL by design.

Parents onehead001. Deploy runs `alembic upgrade heads`.
Rollback: `alembic downgrade` — drops the index and column; no data outside
them is touched.

Revision ID: turnjoin001
Revises: onehead001
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "turnjoin001"
down_revision: Union[str, None] = "onehead001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_logs") as batch:
        batch.add_column(sa.Column("turn_id", sa.String(), nullable=True))
    op.create_index("ix_conversation_logs_turn_id", "conversation_logs",
                    ["turn_id"])
    # Deterministic historic backfill, iOS only: ledger rows were stamped
    # "ios:" || idempotency_key, so this reconstructs the exact (double-
    # prefixed) historic value. || works on both Postgres and SQLite.
    op.execute(
        "UPDATE conversation_logs SET turn_id = 'ios:' || idempotency_key "
        "WHERE platform = 'ios' AND idempotency_key LIKE 'ios:%' "
        "AND turn_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_logs_turn_id",
                  table_name="conversation_logs")
    with op.batch_alter_table("conversation_logs") as batch:
        batch.drop_column("turn_id")
