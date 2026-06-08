"""add item_referenced to pending_questions for food_clarification kind

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-08 01:00:00.000000

T2.2 of the unified rewrite. PendingQuestion gets one nullable column —
item_referenced — that captures WHAT a clarifying question is about
(e.g. "chicken sandwich" for a "grilled or fried?" question). The
existing profile_stats / conversation_hook kinds leave it NULL; the
new food_clarification kind populates it so the executor can auto-
resolve the right row when log_food fires for that item.

Backward compatible: nullable, default NULL, no data migration needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('pending_questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'item_referenced',
            sa.String(),
            nullable=True,
        ))


def downgrade() -> None:
    with op.batch_alter_table('pending_questions', schema=None) as batch_op:
        batch_op.drop_column('item_referenced')
