"""Why a structured answer was refused, typed and durable.

`b1obs004` added `repair_reason` and the commit message claimed it added
`refusal_reason` too. It did not: the type existed in memory and stopped at the
answer function, so the reason a CLIENT has to branch on never reached storage
or the wire. Forward-only, because b1obs004 is on main and main auto-deploys.

Separate from `repair_reason` on purpose. A repair is the user being asked
again; a refusal is a stale screen or our own defect. One column holding both
could be counted as neither.

Revision ID: b1obs005
Revises: b1obs004
"""
import sqlalchemy as sa
from alembic import op

revision = "b1obs005"
down_revision = "b1obs004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("b1_answer_observations",
                  sa.Column("refusal_reason", sa.String(), nullable=False,
                            server_default=""))
    op.create_index("ix_b1_answer_refusal_reason", "b1_answer_observations",
                    ["refusal_reason"])


def downgrade():
    op.drop_index("ix_b1_answer_refusal_reason",
                  table_name="b1_answer_observations")
    op.drop_column("b1_answer_observations", "refusal_reason")
