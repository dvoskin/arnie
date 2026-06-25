"""exercise_entries: avg_hr (wearable session heart rate)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-25 00:30:00.000000

Additive, nullable: average heart rate (bpm) for a session, populated from a
wearable workout (WHOOP / Apple Health). Null for manual logs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("exercise_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("avg_hr", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("exercise_entries", schema=None) as batch_op:
        batch_op.drop_column("avg_hr")
