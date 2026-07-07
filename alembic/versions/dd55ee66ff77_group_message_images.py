"""group_messages.image_b64 — photo messages in groups (2026-07-06)

Revision ID: dd55ee66ff77
Revises: cc44dd55ee66
Create Date: 2026-07-06 00:00:00.000000

Downscaled JPEG stored as base64, served lazily per message (visibility-
checked). Paired with db/models.py.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'dd55ee66ff77'
down_revision: Union[str, Sequence[str], None] = 'cc44dd55ee66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('group_messages', sa.Column('image_b64', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('group_messages', 'image_b64')
