"""add coach_layout to user_preferences (cross-device Coach dashboard sync)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-07-01 00:00:00.000000

The iOS Coach home lets a user reorder + show/hide its metric sections. That
layout is stored as a small JSON blob ({"order":[...],"hidden":[...]}) on the
user's preferences row so it follows them across devices. Nullable — null means
the client falls back to its default order with everything shown. Paired with
the UserPreferences.coach_layout model column (db/database.py _migrate is
SQLite-only; Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_preferences', sa.Column('coach_layout', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_preferences', 'coach_layout')
