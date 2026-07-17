"""activation gates: log/coach unlocked_at + grandfather

Adds users.log_unlocked_at / users.coach_unlocked_at — the timestamps a user
earned the Log and Coach tabs (null = still locked; new-user gating).

GRANDFATHER: every user that exists at migration time is seeded as unlocked.
The gates are an activation mechanic for NEW users only — an existing beta
user waking up to a locked tab they've been using for weeks would read as a
regression/paywall, not a game. Only rows created after this deploy ever see
a lock.

Revision ID: e7750abe4362
Revises: usrthreads001
Create Date: 2026-07-17 12:02:34.052298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7750abe4362'
down_revision: Union[str, Sequence[str], None] = 'usrthreads001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("log_unlocked_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("coach_unlocked_at", sa.DateTime(), nullable=True))
    # Grandfather everyone who already exists (see docstring).
    op.execute(
        "UPDATE users SET log_unlocked_at = CURRENT_TIMESTAMP, "
        "coach_unlocked_at = CURRENT_TIMESTAMP"
    )


def downgrade() -> None:
    op.drop_column("users", "coach_unlocked_at")
    op.drop_column("users", "log_unlocked_at")
