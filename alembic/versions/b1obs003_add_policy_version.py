"""b1 answer observations: which policy decided the answer

A policy version recorded only in a log line cannot survive the ring, and the
reason a version exists at all is so observations collected under one rule stay
separable from those collected under the next. `estimate_evidence_v1` was
emitted and not stored.

NEW MIGRATION, not an amendment. b1obs002 is applied in production, and this
repo has already lost a column to amending a shipped revision — main
auto-deploys, so "I checked and it was unapplied" is stale by the time the
amendment lands.

Revision ID: b1obs003
Revises: b1obs002
"""
import sqlalchemy as sa
from alembic import op

revision = "b1obs003"
down_revision = "b1obs002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("b1_answer_observations",
                  sa.Column("policy_version", sa.String(), nullable=False,
                            server_default=""))


def downgrade():
    op.drop_column("b1_answer_observations", "policy_version")
