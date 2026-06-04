"""add user_attributes table and user_bio columns

Revision ID: a1b2c3d4e5f6
Revises: fad6e9870bc0
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fad6e9870bc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_attributes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('attribute_key', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=True),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('value_type', sa.String(), nullable=True),
        sa.Column('unit', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('relevance_tier', sa.String(), nullable=True),
        sa.Column('attribute_status', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('confidence', sa.String(), nullable=True),
        sa.Column('last_value', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'attribute_key', name='uq_user_attribute_key'),
    )
    with op.batch_alter_table('user_attributes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_attributes_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_attributes_attribute_key'), ['attribute_key'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_bio', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('user_bio_updated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('user_bio_updated_at')
        batch_op.drop_column('user_bio')

    with op.batch_alter_table('user_attributes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_attributes_attribute_key'))
        batch_op.drop_index(batch_op.f('ix_user_attributes_user_id'))

    op.drop_table('user_attributes')
