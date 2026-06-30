"""add micros_estimated to food_entries (LLM-estimated micros vs measured)

Revision ID: a9b0c1d2e3f4
Revises: f7a8b9c0d1e2
Create Date: 2026-06-30 00:00:00.000000

When a food has no database (USDA) match, its micro panel is estimated by the
model (core/micro_estimator). This flag marks those rows so the client renders
them softer than measured values and never claims a confident "good source".
Paired with the FoodEntry.micros_estimated model column (db/database.py _migrate
is SQLite-only; Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('food_entries',
                  sa.Column('micros_estimated', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade() -> None:
    op.drop_column('food_entries', 'micros_estimated')
