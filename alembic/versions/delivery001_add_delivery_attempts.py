"""delivery_attempts — a proactive row that means what it says

A proactive `conversation_logs` row meant "we reached the send function".
`_send` returned None on every path it has — kill switch, allowlist, APNs not
configured, no registered device, provider rejection, swallowed exception, and
genuine delivery — and `_send_logged` wrote history regardless.

Three things were built on that row and all three inherited the ambiguity: the
rolling 24h cadence budget, the silence streak, and engagement analysis. The
worst of them is the budget — a user whose pushes all fail was rate-limited as
though they were being reached, so the failure suppressed its own retry.

One row per ATTEMPT, not per message, so a fan-out to three devices that half
fails stays legible instead of collapsing to a boolean.

`accepted` and `delivered` are deliberately separate. APNs accepting a push is
a promise to try, not proof a phone displayed it; keeping them apart leaves
room for a receipt callback later without redefining what `accepted` already
means. Nothing sets `delivered` yet, and that is honest rather than incomplete.

`destination_reference` is a reference, never the token or address — this table
will be read by analytics and a credential does not belong in it.

Pure ADD of a new table: no backfill, no constraint on existing rows, nothing
to fail on. An old instance during a rolling deploy simply never writes to it.

Parents outbox001. Deploy runs `alembic upgrade heads`.

Revision ID: delivery001
Revises: outbox001
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "delivery001"
down_revision: Union[str, None] = "outbox001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ONLINE ONLY — offline (--sql) hands back a MockConnection with no
    # inspection system, and CI compiles the head migration offline against
    # Postgres precisely to catch that.
    if not context.is_offline_mode():
        if "delivery_attempts" in sa.inspect(op.get_bind()).get_table_names():
            return

    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.Column("slot_key", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("destination_reference", sa.String(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default="1"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("token_invalidated", sa.Boolean(), server_default="0"),
        sa.Column("attempted_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("build_sha", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_attempts_user_time", "delivery_attempts",
                    ["user_id", "attempted_at"])
    op.create_index("ix_delivery_attempts_status", "delivery_attempts",
                    ["status"])
    op.create_index("ix_delivery_attempts_turn", "delivery_attempts",
                    ["turn_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_attempts_turn", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_status", table_name="delivery_attempts")
    op.drop_index("ix_delivery_attempts_user_time",
                  table_name="delivery_attempts")
    op.drop_table("delivery_attempts")
