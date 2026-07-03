"""add processing_level to food_entries (NOVA class from the model at log time)

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-03 00:00:00.000000

The Health Score's processing lane used a food-name keyword proxy only. The
model now classifies each food at log time (whole | processed |
ultra_processed) via log_food.processing_level; the score prefers that and
damps keyword-classified calories. Nullable — older rows keep the keyword
fallback. Paired with the FoodEntry.processing_level model column
(db/database.py _migrate is SQLite-only; Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('food_entries',
                  sa.Column('processing_level', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('food_entries', 'processing_level')
