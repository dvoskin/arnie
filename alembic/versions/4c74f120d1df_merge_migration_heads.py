"""merge_migration_heads

Revision ID: 4c74f120d1df
Revises: a1b2c3d4e5f6, b2c3d4e5f6a7
Create Date: 2026-06-07 14:56:37.298262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c74f120d1df'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f6', 'b2c3d4e5f6a7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
