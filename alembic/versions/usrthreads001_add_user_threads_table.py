"""add_user_threads_table

The memory-graph spine (Stage 1): the time-bound "open loop" node type that
complements user_attributes (the durable trait node). See docs/MEMORY_GRAPH.md.

Parents the current single head (ee66ff770011). Uses a deliberately distinctive
revision id ('usrthreads001') so it can't collide with the hex-style ids already
in the tree.

Revision ID: usrthreads001
Revises: ee66ff770011
Create Date: 2026-07-08 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'usrthreads001'
down_revision: Union[str, Sequence[str], None] = 'ee66ff770011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_threads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), server_default='open', nullable=False),
        sa.Column('salience', sa.Integer(), server_default='3', nullable=True),
        sa.Column('source', sa.String(), server_default='stated', nullable=True),
        sa.Column('origin_platform', sa.String(), nullable=True),
        sa.Column('provenance_log_id', sa.Integer(), nullable=True),
        sa.Column('start_at', sa.DateTime(), nullable=True),
        sa.Column('due_at', sa.DateTime(), nullable=True),
        sa.Column('next_touch_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_referenced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_threads_user_id', 'user_threads', ['user_id'])
    op.create_index('ix_user_threads_user_status', 'user_threads', ['user_id', 'status'])
    op.create_index('ix_user_threads_touch', 'user_threads', ['status', 'next_touch_at'])


def downgrade() -> None:
    op.drop_index('ix_user_threads_touch', table_name='user_threads')
    op.drop_index('ix_user_threads_user_status', table_name='user_threads')
    op.drop_index('ix_user_threads_user_id', table_name='user_threads')
    op.drop_table('user_threads')
