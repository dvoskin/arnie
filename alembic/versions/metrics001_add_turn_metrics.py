"""turn_metrics — latency that outlives the logs

`RequestTrace` emits a good line per request: total, per-stage breakdown,
outcome, build. A line is not a dataset. Render retains logs for days; "did p95
regress after that deploy" is asked in weeks; and the +54% p50 regression
flagged on 2026-07-30 was never explained because by the time anyone looked the
evidence had rotated away.

One SUMMARY row per request, with the stage breakdown as JSON. Enough to
compute percentiles by route, channel and stage; cheap enough to write on every
turn; small enough that retention is a delete rather than a project. A span
store would be the right answer to a question nobody has asked yet.

Pure ADD of a new table: no backfill, no constraint on existing rows, nothing
to fail on. An old instance during a rolling deploy simply never writes to it.

Parents delivery001. Deploy runs `alembic upgrade heads`.

Revision ID: metrics001
Revises: delivery001
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "metrics001"
down_revision: Union[str, None] = "delivery001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ONLINE ONLY — offline (--sql) hands back a MockConnection with no
    # inspection system, and CI compiles the head migration offline.
    if not context.is_offline_mode():
        if "turn_metrics" in sa.inspect(op.get_bind()).get_table_names():
            return

    op.create_table(
        "turn_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("command", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("stages_json", sa.Text(), nullable=True),
        sa.Column("build_sha", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_turn_metrics_time", "turn_metrics", ["created_at"])
    op.create_index("ix_turn_metrics_route_time", "turn_metrics",
                    ["command", "created_at"])
    op.create_index("ix_turn_metrics_turn", "turn_metrics", ["turn_id"])


def downgrade() -> None:
    op.drop_index("ix_turn_metrics_turn", table_name="turn_metrics")
    op.drop_index("ix_turn_metrics_route_time", table_name="turn_metrics")
    op.drop_index("ix_turn_metrics_time", table_name="turn_metrics")
    op.drop_table("turn_metrics")
