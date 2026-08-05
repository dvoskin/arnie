"""meal_commits: one ledger mutation per (operation, revision)

Revision ID: mealcommit001
Revises: metrics001
Create Date: 2026-08-04 00:00:00.000000

THE GUARANTEE THAT DID NOT EXIST. `pending_store.claim()` proves exactly one
caller consumed the clarification ANSWER — a conditional UPDATE where one
caller sees rowcount 1. It says nothing about the ledger write that follows,
and the gap between them is a real sequence:

    worker A claims the answer
    worker A commits food
    worker A crashes before marking the operation consumed
    a retry reconstructs the operation and commits again

An application-level `if not already_committed(key)` cannot close that: two
workers both read "not committed", and both write. Only the database can
arbitrate, so the uniqueness lives in a constraint rather than in a check.

`(operation_id, revision)` rather than a single key because a corrected meal is
a NEW mutation of the SAME operation — revision is what lets a legitimate
re-commit through while a duplicate of the same revision is refused.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mealcommit001"
#: THE ACTUAL HEAD, not the newest-looking filename. Basing this on
#: `b2c3d4e5f6a7` (the pending_questions migration, chosen because the name
#: matched the subject) FORKED THE CHAIN — alembic then reported two heads, and
#: `test_the_build_knows_which_head_it_expects` exists because a divergent
#: chain deploys unpredictably. Resolved with `ScriptDirectory.get_heads()`
#: rather than by reading filenames.
down_revision: Union[str, Sequence[str], None] = "metrics001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── the durable operation record ─────────────────────────────────────────
    # ADDITIVE ONLY. Nothing existing is renamed, dropped or backfilled, so
    # this deploys while the current pending path keeps running unchanged.
    op.create_table(
        "pending_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False,
                  server_default="food"),
        # THE FULL LIFECYCLE. `storage_status` is a projection kept for
        # queries; five operation states share "active", so reconstructing
        # `status` from it is guessing and is forbidden.
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("storage_status", sa.String(), nullable=False,
                  server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("source_turn_id", sa.String(), nullable=True),
        # Versioned JSON, so an unknown future field does not break a read.
        sa.Column("canonical_payload", sa.Text(), nullable=True),
        sa.Column("unresolved_fields", sa.Text(), nullable=True),
        sa.Column("assumptions", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(), nullable=True),
        # TWO KEYS, TWO GUARANTEES. One consumer of the answer; one write of
        # the meal. A single key cannot express both.
        sa.Column("answer_claim_key", sa.String(), nullable=True),
        sa.Column("commit_key", sa.String(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False,
                  server_default="3"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("terminal_reason", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_pending_operations_open", "pending_operations",
                    ["user_id", "domain", "storage_status"])

    # ── the authoritative commit result ──────────────────────────────────────
    op.create_table(
        "meal_commits",
        sa.Column("commit_id", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("operation_revision", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("commit_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False,
                  server_default="claimed"),
        # WHAT A DUPLICATE MUST RECEIVE. Enough to reproduce the committed and
        # updated items, the totals, the assumptions and the render actions —
        # a duplicate that gets nothing cannot tell "already done" from
        # "nothing happened".
        sa.Column("result_payload", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        # THE WHOLE POINT OF THE TABLE. The database arbitrates, because two
        # workers both read "not committed" and both write.
        sa.UniqueConstraint("operation_id", "operation_revision",
                            name="uq_meal_commits_operation_revision"),
    )
    op.create_index("ix_meal_commits_user", "meal_commits",
                    ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_meal_commits_user", table_name="meal_commits")
    op.drop_table("meal_commits")
    op.drop_index("ix_pending_operations_open",
                  table_name="pending_operations")
    op.drop_table("pending_operations")
