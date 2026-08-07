"""Why a clarification re-asked, typed.

`unrelated_report_while_awaiting` is deliberately NOT a value here. The answer
turn runs before the interpreter and sees only the raw message, so it cannot
distinguish "I had some salmon too" from "it was pretty good" — recording that
distinction would be recording knowledge the turn does not have.

`universe_unavailable` is separate from `estimate_unsupported` because one is
an outage and the other is a fact about a person's history. Pooled, a storage
failure would read as a population of users whose logs we lack.

Revision ID: b1obs004
Revises: b1uni002
"""
import sqlalchemy as sa
from alembic import op

revision = "b1obs004"
down_revision = "b1uni002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("b1_answer_observations",
                  sa.Column("repair_reason", sa.String(), nullable=False,
                            server_default=""))
    op.create_index("ix_b1_answer_repair_reason", "b1_answer_observations",
                    ["repair_reason"])


def downgrade():
    op.drop_index("ix_b1_answer_repair_reason",
                  table_name="b1_answer_observations")
    op.drop_column("b1_answer_observations", "repair_reason")
