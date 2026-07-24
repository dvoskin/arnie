"""add health_import_tombstones — deleted auto-imports must stay deleted

Apple Health replace-on-sync and WHOOP ref-upserts both resurrect entries the
user explicitly deleted. Tombstone the (user_id, source_ref) on delete; both
ingests skip tombstoned refs.

Revision ID: hlthtomb0001
Revises: f7e8d9c0b1a2
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "hlthtomb0001"
down_revision: Union[str, Sequence[str], None] = "f7e8d9c0b1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_import_tombstones",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False, index=True),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "source_ref", name="uq_tombstone_user_ref"),
    )


def downgrade() -> None:
    op.drop_table("health_import_tombstones")
