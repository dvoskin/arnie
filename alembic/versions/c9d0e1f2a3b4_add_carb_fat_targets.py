"""add carb_target and fat_target to user_preferences

Revision ID: c9d0e1f2a3b4
Revises: a3b4c5d6e7f8
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user_preferences') as batch_op:
        batch_op.add_column(sa.Column('carb_target', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('fat_target', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('user_preferences') as batch_op:
        batch_op.drop_column('fat_target')
        batch_op.drop_column('carb_target')
