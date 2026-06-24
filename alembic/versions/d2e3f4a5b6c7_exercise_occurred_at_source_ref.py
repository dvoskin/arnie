"""exercise_entries: occurred_at (time-of-day) + source_ref (wearable dedup)

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-24 17:30:00.000000

Two additive, nullable columns on exercise_entries:
- occurred_at: when the workout actually happened (user-specified time-of-day, or
  a wearable workout's start time). `timestamp` stays "when logged"; display/sort
  falls back to it when occurred_at is null.
- source_ref: external dedup key for entries auto-created from a wearable
  (e.g. "whoop:<workout_id>"), so repeated syncs upsert instead of duplicating.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("exercise_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("occurred_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("source_ref", sa.String(), nullable=True))
        batch_op.create_index(
            "ix_exercise_entries_source_ref", ["source_ref"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("exercise_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_exercise_entries_source_ref")
        batch_op.drop_column("source_ref")
        batch_op.drop_column("occurred_at")
