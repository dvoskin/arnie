"""memory trust linkage — a cache row may name the canonical settlement that made it

⛔⛔⛔ CF24 — `origin_tier` CANNOT ESTABLISH TRUST. It is free text any caller
can set, and every lookup path writes through the same public door. A guard
keyed on a string is a magic word.

These columns are the alternative: a row is trusted when it can point at a REAL
canonical operation, and the predicate RESOLVES that pointer rather than
believing a label. A non-settlement writer has no operation id to write.

Revision ID: memtrust001
Revises: oneask001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "memtrust001"
down_revision: Union[str, None] = "oneask001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All nullable: every one of the 838 existing rows stays exactly as it is,
    # untrusted and untouched. No backfill, no deletion — the repair is a
    # forward path, not a rewrite of history.
    op.add_column("user_food_matches",
                  sa.Column("settled_by_operation_id", sa.String(), nullable=True))
    op.add_column("user_food_matches",
                  sa.Column("settled_basis", sa.String(), nullable=True))
    op.add_column("user_food_matches",
                  sa.Column("settled_evidence_id", sa.String(), nullable=True))
    op.add_column("user_food_matches",
                  sa.Column("settled_at", sa.DateTime(), nullable=True))
    op.create_index("ix_ufm_settled_operation", "user_food_matches",
                    ["settled_by_operation_id"])


def downgrade() -> None:
    op.drop_index("ix_ufm_settled_operation", table_name="user_food_matches")
    for col in ("settled_at", "settled_evidence_id", "settled_basis",
                "settled_by_operation_id"):
        op.drop_column("user_food_matches", col)
