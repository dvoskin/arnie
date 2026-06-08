"""add food_logging_mode to user_preferences

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = '4c74f120d1df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add food_logging_mode — controls how aggressively Arnie confirms
    food amounts/prep before logging (quick / moderate / strict).
    Default 'moderate' preserves current behavior for all existing users."""
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'food_logging_mode',
            sa.String(),
            nullable=True,
            server_default='moderate',
        ))


def downgrade() -> None:
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.drop_column('food_logging_mode')
