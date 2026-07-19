"""add conversation_logs feedback

Revision ID: 6d1fca8432ee
Revises: 48a9192d5f11
Create Date: 2026-07-19 14:57:30.924788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d1fca8432ee'
down_revision: Union[str, Sequence[str], None] = '48a9192d5f11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Per-turn thumbs verdict ("up" / "down" / NULL), the persisted reasoning
    receipt (steps + duration_ms JSON) for history restores, and the
    supersede pointer set when a [REGENERATE] turn replaces a reply."""
    op.add_column("conversation_logs", sa.Column("feedback", sa.String(), nullable=True))
    op.add_column("conversation_logs", sa.Column("reasoning_json", sa.Text(), nullable=True))
    op.add_column("conversation_logs", sa.Column("superseded_by", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_logs", "superseded_by")
    op.drop_column("conversation_logs", "reasoning_json")
    op.drop_column("conversation_logs", "feedback")
