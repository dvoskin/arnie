"""extend_health_snapshot_whoop_fields

Revision ID: fad6e9870bc0
Revises: 25156fc5f0a3
Create Date: 2026-06-03 23:06:24.393832

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'fad6e9870bc0'
down_revision: Union[str, Sequence[str], None] = '25156fc5f0a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('health_snapshots') as batch_op:
        batch_op.add_column(sa.Column('respiratory_rate',     sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('sleep_performance_pct', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('sleep_need_hours',     sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('sleep_efficiency_pct', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('whoop_workouts',       sa.Text(),  nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('health_snapshots') as batch_op:
        batch_op.drop_column('whoop_workouts')
        batch_op.drop_column('sleep_efficiency_pct')
        batch_op.drop_column('sleep_need_hours')
        batch_op.drop_column('sleep_performance_pct')
        batch_op.drop_column('respiratory_rate')
