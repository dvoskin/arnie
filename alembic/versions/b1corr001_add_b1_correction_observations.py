"""B-1 correction observations, deduplicated by (operation, entry).

The sweep that spots "this committed row was corrected minutes later" runs on
a timer, so without a persisted record it re-emits the same observation on
every tick — and a metric that counts one event N times is not a metric, it is
a function of how often cron runs.

Keyed by (operation_id, entry_id) with a UNIQUE constraint, so the dedup is
enforced by the database rather than by the sweep remembering. The sweep is
the thing most likely to be restarted mid-run.

Revision ID: b1corr001
Revises: mealcommit001
"""
import sqlalchemy as sa
from alembic import op

revision = "b1corr001"
down_revision = "mealcommit001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "b1_correction_observations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("operation_id", sa.String, nullable=False),
        sa.Column("entry_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        # WHICH correction, kept rather than collapsed: an edit and a deletion
        # are both evidence the number was wrong, and they are not the same
        # evidence. Collapsing them would make the rate unactionable.
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("minutes_after_commit", sa.Float, nullable=False),
        sa.Column("observed_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("operation_id", "entry_id",
                            name="uq_b1_correction_operation_entry"),
    )
    op.create_index("ix_b1_correction_observed",
                    "b1_correction_observations", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_b1_correction_observed",
                  table_name="b1_correction_observations")
    op.drop_table("b1_correction_observations")
