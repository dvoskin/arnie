"""add brain_dump to users (free-form onboarding dump)

Revision ID: c0d1e2f3a4b5
Revises: a9b0c1d2e3f4
Create Date: 2026-06-30 00:00:00.000000

The native onboarding flow ends with a free-form "brain dump" — everything the
user wants Arnie to know in their own words (nutrition, lifestyle, history,
motivation). Stored verbatim on the user row; feeds the personalized opening
intro and Arnie's ongoing context. Paired with the User.brain_dump model column
(db/database.py _migrate is SQLite-only; Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('brain_dump', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'brain_dump')
