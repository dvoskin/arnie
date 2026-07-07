"""Groups v1 — community spaces + the private Feedback line (2026-07-06)

Revision ID: aa22bb33cc44
Revises: 0a1b2c3d4e5f
Create Date: 2026-07-06 00:00:00.000000

groups / group_members / group_messages. Two launch groups seeded lazily by
the API (idempotent), not here — SQLite test DBs build from models and never
run migrations, so a data seed here would diverge the two paths. Paired with
the model classes in db/models.py.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'aa22bb33cc44'
down_revision: Union[str, Sequence[str], None] = '0a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.Column('description', sa.String()),
        sa.Column('emoji', sa.String()),
        sa.Column('kind', sa.String(), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        'group_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('joined_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('group_id', 'user_id', name='uq_group_member'),
    )
    op.create_index('ix_group_members_user', 'group_members', ['user_id'])
    op.create_table(
        'group_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_group_messages_group', 'group_messages', ['group_id', 'id'])
    op.create_index('ix_group_messages_user', 'group_messages', ['user_id'])


def downgrade() -> None:
    op.drop_table('group_messages')
    op.drop_table('group_members')
    op.drop_table('groups')
