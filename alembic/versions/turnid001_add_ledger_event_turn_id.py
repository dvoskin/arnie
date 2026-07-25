"""add ledger_events.turn_id (P0.1 — canonical transaction identity)

Every write born from a turn traces back to its canonical turn_id
(core/turn_identity): the seed of the end-to-end turn trace and the anchor
for exactly-once across transports. Nullable — historical events and
non-turn writes (health imports, background jobs) simply have none.

Parents foodledger002. Deploy runs `alembic upgrade heads`.

Revision ID: turnid001
Revises: foodledger002
Create Date: 2026-07-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'turnid001'
down_revision: Union[str, Sequence[str], None] = 'foodledger002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ledger_events',
                  sa.Column('turn_id', sa.String(), nullable=True))
    op.create_index('ix_ledger_events_turn', 'ledger_events', ['turn_id'])


def downgrade() -> None:
    op.drop_index('ix_ledger_events_turn', table_name='ledger_events')
    op.drop_column('ledger_events', 'turn_id')
