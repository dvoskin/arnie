"""add conversation_logs.idempotency_key — deterministic retry dedup

Revision ID: a8b9c0d1e2f3
Revises: e3f4a5b6c7d8
Create Date: 2026-06-26 00:00:00.000000

A stable per-send id for the inbound request a turn answered (iOS client UUID,
Telegram update_id, iMessage GUID — channel-prefixed). The turn entry path looks
the key up before running; a client retry / webhook redelivery reuses the same
key, so the duplicate is recognized deterministically and replayed/skipped
instead of re-running the coaching turn and double-writing food/exercise logs.

This is the structural fix for the resend-driven duplicate-log class (e.g. shrugs
3×14,14,15 written twice on 2026-06-25) that the text+time heuristic could only
approximate.

Idempotent (inspect-then-add) per [[feedback_arnie_migrate_postgres_gap]] — the
`_migrate` ALTER net is SQLite-only, so Postgres relies entirely on this.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a8b9c0d1e2f3'
# Chains off the avg_hr migration (the last revision on main), NOT the social-circle
# migration f4a5b6c7d8e9 — that one is uncommitted/undeployed, so depending on it
# would dangle the chain on deploy. When social-circle does land it also revises
# e3f4a5b6c7d8, giving two heads; `alembic upgrade heads` (render preDeploy) applies
# both, and a later merge migration can unify them.
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_cols = {c['name'] for c in insp.get_columns('conversation_logs')}
    if 'idempotency_key' not in existing_cols:
        with op.batch_alter_table('conversation_logs') as batch_op:
            batch_op.add_column(sa.Column('idempotency_key', sa.String(), nullable=True))

    existing_indexes = {i['name'] for i in insp.get_indexes('conversation_logs')}
    if 'ix_conversation_logs_idempotency_key' not in existing_indexes:
        op.create_index('ix_conversation_logs_idempotency_key',
                        'conversation_logs', ['idempotency_key'])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_indexes = {i['name'] for i in insp.get_indexes('conversation_logs')}
    if 'ix_conversation_logs_idempotency_key' in existing_indexes:
        op.drop_index('ix_conversation_logs_idempotency_key',
                      table_name='conversation_logs')

    existing_cols = {c['name'] for c in insp.get_columns('conversation_logs')}
    if 'idempotency_key' in existing_cols:
        with op.batch_alter_table('conversation_logs') as batch_op:
            batch_op.drop_column('idempotency_key')
