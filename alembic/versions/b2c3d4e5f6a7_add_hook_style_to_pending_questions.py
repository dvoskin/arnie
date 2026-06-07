"""add hook_style to pending_questions

Revision ID: b2c3d4e5f6a7
Revises: 5ed44c60f075
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '5ed44c60f075'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add hook_style column — distinguishes question hooks from engagement hooks
    so the follow-up re-ask uses the correct framing template."""
    with op.batch_alter_table('pending_questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'hook_style',
            sa.String(),
            nullable=True,
            server_default='question',
        ))


def downgrade() -> None:
    with op.batch_alter_table('pending_questions', schema=None) as batch_op:
        batch_op.drop_column('hook_style')
