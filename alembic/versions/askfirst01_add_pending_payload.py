"""add pending_questions.payload_json for the ask-first hold

Revision ID: askfirst01_pending_payload
Revises: 7ba718ff7005
Create Date: 2026-07-22

Descriptive revision id (not hex) so it can't collide with the auto-generated
ids already in the tree — the same collision lesson as usrthreads001.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'askfirst01_pending_payload'
down_revision: Union[str, Sequence[str], None] = '7ba718ff7005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Stash column for the ASK-FIRST hold: the held log_food inputs, replayed
    deterministically on the answer if the model loops. IDEMPOTENT (guard on
    existence) so a manual ALTER or a re-run never errors."""
    conn = op.get_bind()
    cols = [c["name"] for c in sa.inspect(conn).get_columns("pending_questions")]
    if "payload_json" not in cols:
        op.add_column("pending_questions",
                      sa.Column("payload_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pending_questions", "payload_json")
