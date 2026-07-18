"""add achievements table

One row per earned badge per user (quiet trophies, loud moments — the badge
registry lives in core/achievements.py, so adding new badges never needs
another migration). Unique(user_id, badge_id) makes awarding idempotent.

Revision ID: 1404c258d0b0
Revises: e7750abe4362
Create Date: 2026-07-18 13:52:43.420318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1404c258d0b0'
down_revision: Union[str, Sequence[str], None] = 'e7750abe4362'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "achievements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("badge_id", sa.String(), nullable=False),
        sa.Column("earned_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "badge_id", name="uq_achievement_user_badge"),
    )
    op.create_index("ix_achievements_user_id", "achievements", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_achievements_user_id", table_name="achievements")
    op.drop_table("achievements")
