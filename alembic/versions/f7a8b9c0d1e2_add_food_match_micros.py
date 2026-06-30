"""add micros_100_json to user_food_matches (cache the micronutrient panel)

Revision ID: f7a8b9c0d1e2
Revises: e1f2a3b4c5d6
Create Date: 2026-06-30 00:00:00.000000

The per-user food memory (user_food_matches) cached only the macro per-100g
columns, so a repeat-logged staple hit memory and came back with NO micros —
micronutrients_json stayed empty on every entry after the first. This column
caches the full per-100g micro panel (JSON) alongside the macros so memory hits
keep their micros. Paired with the UserFoodMatch.micros_100_json model column
(db/database.py _migrate is SQLite-only; Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_food_matches', sa.Column('micros_100_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_food_matches', 'micros_100_json')
