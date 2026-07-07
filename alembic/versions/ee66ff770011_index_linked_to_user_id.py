"""index users.linked_to_user_id — hottest unindexed filter (2026-07-07 audit)

Revision ID: ee66ff770011
Revises: dd55ee66ff77
Create Date: 2026-07-07 00:00:00.000000

Filtered as a WHERE predicate on the coaching hot path (context build runs it
2× per turn for every canonical user), in the unified-thread history query, and
every scheduler tick — but the column was never indexed. Seq-scan over users is
cheap at beta, a full scan twice per turn at scale. Paired with the model
`index=True` on User.linked_to_user_id.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'ee66ff770011'
down_revision: Union[str, Sequence[str], None] = 'dd55ee66ff77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_users_linked_to_user_id', 'users',
                    ['linked_to_user_id'], if_not_exists=True)


def downgrade() -> None:
    op.drop_index('ix_users_linked_to_user_id', table_name='users', if_exists=True)
