"""add_workout_programs_table

Revision ID: 25156fc5f0a3
Revises: 5ed44c60f075
Create Date: 2026-06-02 18:43:25.946723

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '25156fc5f0a3'
down_revision: Union[str, Sequence[str], None] = '5ed44c60f075'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'workout_programs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('program_json', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # Single unique index on user_id (one program per user)
    op.create_index('ix_workout_programs_user_id', 'workout_programs', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_workout_programs_user_id', table_name='workout_programs')
    op.drop_table('workout_programs')
