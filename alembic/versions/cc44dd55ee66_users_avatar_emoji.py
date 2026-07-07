"""users.avatar_emoji — user-chosen profile icon (2026-07-06)

Revision ID: cc44dd55ee66
Revises: bb33cc44dd55
Create Date: 2026-07-06 00:00:00.000000

Single emoji from the iOS curated picker; null falls back to the
name-initial disc. Paired with db/models.py.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'cc44dd55ee66'
down_revision: Union[str, Sequence[str], None] = 'bb33cc44dd55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('avatar_emoji', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'avatar_emoji')
