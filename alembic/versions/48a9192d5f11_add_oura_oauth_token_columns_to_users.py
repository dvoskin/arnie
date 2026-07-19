"""add oura oauth token columns to users

Revision ID: 48a9192d5f11
Revises: 1404c258d0b0
Create Date: 2026-07-19 00:31:32.662759

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48a9192d5f11'
down_revision: Union[str, Sequence[str], None] = '1404c258d0b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add per-user Oura OAuth token columns (mirrors the whoop_* trio)."""
    op.add_column('users', sa.Column('oura_access_token', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('oura_refresh_token', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('oura_token_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'oura_token_expires_at')
    op.drop_column('users', 'oura_refresh_token')
    op.drop_column('users', 'oura_access_token')
