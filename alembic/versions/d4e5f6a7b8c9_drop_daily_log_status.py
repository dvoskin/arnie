"""drop daily_logs.status column

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-08 00:00:00.000000

T1.1 of the unified rewrite. The open/closed day-status concept is vestigial:
users can log and modify any day (today or past) via the date= field on log
tools. The close_day / reopen_day tools and silent auto-reopen logic are being
deleted in the same commit; this migration removes the underlying column so
nothing in the schema implies a state transition that no longer exists.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('daily_logs', schema=None) as batch_op:
        batch_op.drop_column('status')


def downgrade() -> None:
    with op.batch_alter_table('daily_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'status',
            sa.String(),
            nullable=True,
            server_default='open',
        ))
