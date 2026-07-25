"""add ledger_events + processed_turns (FOOD_LEDGER_V2 Phase 2)

The ledger's durable memory, for ALL logging domains (food now, exercise
wired alongside, weight/water as they migrate onto the contract): an
append-only event history (created/updated/deleted with payloads — undo,
debugging, correction analytics) and a claimed-turn table making structured
commits exactly-once across restarts and devices.

Parents the askfirst01_pending_payload head (the food-clarification lineage).
The deploy command is `alembic upgrade heads` (plural), so the other heads are
unaffected. Distinctive revision id by repo convention (usrthreads001 pattern)
so it can't collide with the hex-style ids.

Revision ID: foodledger002
Revises: askfirst01_pending_payload
Create Date: 2026-07-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'foodledger002'
down_revision: Union[str, Sequence[str], None] = 'askfirst01_pending_payload'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ledger_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(), server_default='food', nullable=False),
        sa.Column('entry_id', sa.Integer(), nullable=True),
        sa.Column('daily_log_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'),
                  nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ledger_events_user_id', 'ledger_events', ['user_id'])
    op.create_index('ix_ledger_events_user_time', 'ledger_events',
                    ['user_id', 'created_at'])
    op.create_index('ix_ledger_events_domain_entry', 'ledger_events',
                    ['domain', 'entry_id'])

    op.create_table(
        'processed_turns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('idem_key', sa.String(), nullable=False),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'),
                  nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'idem_key', name='uq_processed_turn_key'),
    )
    op.create_index('ix_processed_turns_user_time', 'processed_turns',
                    ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_processed_turns_user_time', table_name='processed_turns')
    op.drop_table('processed_turns')
    op.drop_index('ix_ledger_events_domain_entry', table_name='ledger_events')
    op.drop_index('ix_ledger_events_user_time', table_name='ledger_events')
    op.drop_index('ix_ledger_events_user_id', table_name='ledger_events')
    op.drop_table('ledger_events')
