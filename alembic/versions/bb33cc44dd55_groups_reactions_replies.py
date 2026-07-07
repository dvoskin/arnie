"""Groups v1.1 — reactions + direct replies (2026-07-06)

Revision ID: bb33cc44dd55
Revises: aa22bb33cc44
Create Date: 2026-07-06 00:00:00.000000

group_message_reactions (toggle per message/user/emoji) + reply_to_id on
group_messages for inline quoted replies. Paired with db/models.py.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'bb33cc44dd55'
down_revision: Union[str, Sequence[str], None] = 'aa22bb33cc44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('group_messages',
                  sa.Column('reply_to_id', sa.Integer(),
                            sa.ForeignKey('group_messages.id'), nullable=True))
    op.create_table(
        'group_message_reactions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('group_messages.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('emoji', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('message_id', 'user_id', 'emoji', name='uq_group_reaction'),
    )
    op.create_index('ix_group_reactions_message', 'group_message_reactions', ['message_id'])


def downgrade() -> None:
    op.drop_table('group_message_reactions')
    op.drop_column('group_messages', 'reply_to_id')
