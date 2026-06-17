"""add weights column to exercise_entries (per-set variable load)

Revision ID: e4f5a6b7c8d9
Revises: b1c2d3e4f5a6
Create Date: 2026-06-17 00:00:00.000000

Adds the per-set weights CSV column to exercise_entries. The column was
originally introduced via the `_migrate` additions list in db/database.py
(2026-06-16), which only runs on SQLite (dev) — on Postgres (prod), the
additions list is skipped, so this migration is what gets the column there.

PROD HISTORICAL NOTE: this column was manually ALTERed onto prod Postgres on
2026-06-17 during an incident response (the deploy of the merge commit
3a6bfe9 brought the new model field but no migration, so SELECTs crashed).
This migration is intentionally idempotent (inspect-then-add) so that the
existing prod column is recognized and the upgrade no-ops, and future fresh
environments still get the column normally.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c['name'] for c in insp.get_columns('exercise_entries')}
    if 'weights' in existing:
        return  # already present (prod manual ALTER 2026-06-17 path)
    with op.batch_alter_table('exercise_entries') as batch_op:
        batch_op.add_column(sa.Column('weights', sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c['name'] for c in insp.get_columns('exercise_entries')}
    if 'weights' not in existing:
        return
    with op.batch_alter_table('exercise_entries') as batch_op:
        batch_op.drop_column('weights')
