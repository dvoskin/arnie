"""add body_metrics.source — source-aware weight dedup (manual vs apple_health)

Revision ID: b3c4d5e6f7a8
Revises: a8b9c0d1e2f3
Create Date: 2026-06-27 00:00:00.000000

Tags weight readings by origin so the per-(user, calendar-day, source) UPSERT in
add_body_metric keeps a user's DELIBERATE weigh-in ("manual") separate from a
passive wearable sync ("apple_health"). The old <0.06 kg / 30-min fold let a
manual 84.73 and a HealthKit 85.28 nine minutes apart STACK (four rows oscillating
one morning), and the dashboard headlined the latest (passive) value over the
user's own number (Danny 2026-06-27). With a source column, manual and
apple_health are parallel rows; each source folds to one row per day; manual is
the headline.

server_default='manual' backfills every existing row to manual — they predate
HealthKit weight ingestion, so they ARE the user's manual readings.

Chains off a8b9c0d1e2f3 (the deployed head — per-send idempotency key), NOT the
uncommitted/undeployed social-circle migration f4a5b6c7d8e9; depending on that
would dangle this chain on deploy.

Idempotent (inspect-then-add) per [[feedback_arnie_migrate_postgres_gap]] — the
_migrate ALTER net is SQLite-only, so Postgres relies entirely on this migration.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_cols = {c['name'] for c in insp.get_columns('body_metrics')}
    if 'source' not in existing_cols:
        with op.batch_alter_table('body_metrics') as batch_op:
            batch_op.add_column(
                sa.Column('source', sa.String(),
                          nullable=False, server_default='manual')
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_cols = {c['name'] for c in insp.get_columns('body_metrics')}
    if 'source' in existing_cols:
        with op.batch_alter_table('body_metrics') as batch_op:
            batch_op.drop_column('source')
