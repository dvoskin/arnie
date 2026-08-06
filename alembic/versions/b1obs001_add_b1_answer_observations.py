"""b1 answer observations — durable telemetry for the D4.1 window

The trace ring is `deque(maxlen=2000)` in process memory and empties on every
restart; measured zero lines minutes after a deploy. An observation window read
from it would silently be a window over "since the last deploy". This is where
the funnel lives instead.

Revision ID: b1obs001
Revises: b1corr001
"""
import sqlalchemy as sa
from alembic import op

revision = "b1obs001"
down_revision = "b1corr001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "b1_answer_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_turn_id", sa.String(), nullable=False),
        sa.Column("attribute", sa.String(), nullable=False,
                  server_default="quantity"),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("modality", sa.String(), nullable=False, server_default=""),
        sa.Column("selected_source", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("offered", sa.String(), nullable=False, server_default=""),
        sa.Column("round_index", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("interaction_revision", sa.Integer(), nullable=True),
        sa.Column("question_version", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("entry_id", sa.Integer(), nullable=True),
        sa.Column("cohort", sa.String(), nullable=False, server_default=""),
        sa.Column("observed_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("operation_id", "source_turn_id",
                            name="uq_b1_answer_operation_turn"),
    )
    op.create_index("ix_b1_answer_observed", "b1_answer_observations",
                    ["observed_at"])
    op.create_index("ix_b1_answer_source", "b1_answer_observations",
                    ["selected_source"])


def downgrade():
    op.drop_index("ix_b1_answer_source", table_name="b1_answer_observations")
    op.drop_index("ix_b1_answer_observed", table_name="b1_answer_observations")
    op.drop_table("b1_answer_observations")
