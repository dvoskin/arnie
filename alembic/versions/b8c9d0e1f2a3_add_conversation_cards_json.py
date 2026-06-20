"""add conversation_logs.cards_json (persist typed inline cards)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-20 00:00:00.000000

Native clients (iOS) render macro/recap/log/suggestion cards inline beneath
Arnie's reply, built from the live `cards` wire array. Those cards were never
persisted, so when the app restored history (cold launch / view re-creation)
the transcript reloaded text-only and every card vanished. This adds a JSON
column on conversation_logs to store the turn's cards so history can rehydrate
them. Also flips voice turns back into voice-style bubbles client-side (no
schema needed for that — source_type='voice' already records it).

Idempotent (inspect-then-add) per [[feedback_arnie_migrate_postgres_gap]] —
the SQLite path adds this via db.database._migrate; Postgres (prod) skips
_migrate entirely, so this Alembic revision is the only thing that adds the
column there. Safe to re-run, safe if the column was added out-of-band.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = {c['name'] for c in insp.get_columns('conversation_logs')}
    if 'cards_json' not in cols:
        op.add_column('conversation_logs', sa.Column('cards_json', sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = {c['name'] for c in insp.get_columns('conversation_logs')}
    if 'cards_json' in cols:
        op.drop_column('conversation_logs', 'cards_json')
