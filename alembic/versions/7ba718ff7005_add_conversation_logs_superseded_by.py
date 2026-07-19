"""add conversation_logs superseded_by

Revision ID: 7ba718ff7005
Revises: 6d1fca8432ee
Create Date: 2026-07-19 16:02:23.435579

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ba718ff7005'
down_revision: Union[str, Sequence[str], None] = '6d1fca8432ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The supersede pointer a [REGENERATE] turn sets on the reply it
    replaced (history hides superseded rows). IDEMPOTENT: prod already
    got this column via a manual ALTER during the 07-19 outage fix, so
    guard on existence instead of blindly adding."""
    conn = op.get_bind()
    cols = [c["name"] for c in sa.inspect(conn).get_columns("conversation_logs")]
    if "superseded_by" not in cols:
        op.add_column("conversation_logs",
                      sa.Column("superseded_by", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_logs", "superseded_by")
