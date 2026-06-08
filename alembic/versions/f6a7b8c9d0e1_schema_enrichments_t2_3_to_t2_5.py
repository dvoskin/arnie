"""schema enrichments — meal_type/meal_time/alcohol/from_photo, BodyMetric.context, WaterEntry table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-08 02:00:00.000000

T2.3-T2.5 of the unified rewrite. Three independent additions, one migration:

T2.3 (FoodEntry): adds meal_type, meal_time, alcohol_units, micronutrients_json,
  from_photo. Enables meal-timing coaching and dashboard meal grouping
  downstream — pure data capture now, render changes follow in a later phase.

T2.4 (WaterEntry): new timestamped table. DailyLog.total_water_ml stays as a
  cached aggregate (computed on water log) for backward compatibility; the
  per-entry table is the canonical source for hydration timing coaching.

T2.5 (BodyMetric): adds context field (morning_fasted, post_meal, evening,
  post_workout, unknown). Improves weight trend interpretation.

All additions are nullable + default-NULL — backward compatible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── T2.3: FoodEntry enrichments ─────────────────────────────────────────
    with op.batch_alter_table('food_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('meal_type', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('meal_time', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('alcohol_units', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('micronutrients_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('from_photo', sa.Boolean(),
                                       nullable=True, server_default=sa.false()))

    # ── T2.5: BodyMetric.context ────────────────────────────────────────────
    with op.batch_alter_table('body_metrics', schema=None) as batch_op:
        batch_op.add_column(sa.Column('context', sa.String(), nullable=True))

    # ── T2.4: WaterEntry table ──────────────────────────────────────────────
    op.create_table(
        'water_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('daily_log_id', sa.Integer(),
                  sa.ForeignKey('daily_logs.id'), nullable=True),
        sa.Column('amount_ml', sa.Float(), nullable=False),
        sa.Column('context', sa.String(), nullable=True),  # morning|with_meal|post_workout|...
        sa.Column('source_type', sa.String(), nullable=True, server_default='text'),
        sa.Column('timestamp', sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('water_entries')
    with op.batch_alter_table('body_metrics', schema=None) as batch_op:
        batch_op.drop_column('context')
    with op.batch_alter_table('food_entries', schema=None) as batch_op:
        batch_op.drop_column('from_photo')
        batch_op.drop_column('micronutrients_json')
        batch_op.drop_column('alcohol_units')
        batch_op.drop_column('meal_time')
        batch_op.drop_column('meal_type')
