"""add non_training_activity to users

Revision ID: f7e8d9c0b1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-09 00:00:00.000000

Adds a `non_training_activity` column to capture occupational / daily-life
activity separately from `training_experience`. The two were previously
conflated in compute_macro_targets() (years lifting was driving the activity
multiplier), which over-projected TDEE for desk-job lifters. This field
introduces the correct signal; the math is NOT wired to read from it yet —
that switch happens in a follow-up change once users have populated values.

Values: sedentary / lightly_active / moderately_active / very_active. Maps
to the ACSM 1.2 / 1.375 / 1.55 / 1.725 tiers.

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f7e8d9c0b1a2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('non_training_activity', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('non_training_activity')
