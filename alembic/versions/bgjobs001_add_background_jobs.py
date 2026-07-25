"""add background_jobs (P0.7 — durable post-turn work)

Profile synthesis and memory reflection ran as detached asyncio tasks: a
deploy, crash or shutdown dropped them with no retry, so whether a durable
fact got remembered depended on process luck. A row here survives all three;
the in-process task stays the fast path and the scheduler sweeps the rest.

Parents turnid001. Deploy runs `alembic upgrade heads`.

Revision ID: bgjobs001
Revises: turnid001
Create Date: 2026-07-25 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'bgjobs001'
down_revision: Union[str, Sequence[str], None] = 'turnid001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'background_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), server_default='pending', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=True),
        sa.Column('dedup_key', sa.String(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'),
                  nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_background_jobs_due', 'background_jobs',
                    ['status', 'next_attempt_at'])
    op.create_index('ix_background_jobs_user', 'background_jobs', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_background_jobs_user', table_name='background_jobs')
    op.drop_index('ix_background_jobs_due', table_name='background_jobs')
    op.drop_table('background_jobs')
