"""dedup + unique (user_id, date) on daily_logs and health_snapshots

Revision ID: c1d2e3f4a5b6
Revises: b8c9d0e1f2a3
Create Date: 2026-06-20 07:30:00.000000

get_or_create_today_log / upsert_health_snapshot do a non-atomic
check-then-insert keyed by (user_id, date), and neither table had a unique
constraint. The iOS app fires several endpoints concurrently on launch (chat +
native_data + quick_log + water), so the first write of a new day could race two
daily_logs rows for the same date. get_today_log's scalar_one_or_none() then
raised MultipleResultsFound and every coaching turn for that user 500'd
(incident 2026-06-20: user 26 had two empty daily_logs for 2026-06-20, created
2ms apart).

This migration:
  1. De-dupes existing (user_id, date) groups — keep the lowest id, reparent
     food/exercise/water children onto it, delete the extras, recompute totals.
  2. Adds the unique constraints (uq_daily_log_user_date, uq_health_snapshot_user_date)
     so the race now fails the loser's INSERT with IntegrityError, which the query
     layer catches and turns into a read-back of the winner's row.

Idempotent per [[feedback_arnie_migrate_postgres_gap]]: the SQLite path adds the
same dedup + unique index via db.database._migrate; Postgres (prod) skips
_migrate, so this revision is the only thing that constrains it there. The
constraint-add is guarded on existing-constraint inspection so a re-run is safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dedupe_daily_logs(bind) -> None:
    """Collapse duplicate (user_id, date) daily_logs onto the lowest id."""
    groups = bind.execute(sa.text(
        "SELECT user_id, date, MIN(id) AS survivor "
        "FROM daily_logs GROUP BY user_id, date HAVING COUNT(*) > 1"
    )).fetchall()
    for g in groups:
        dup_ids = bind.execute(sa.text(
            "SELECT id FROM daily_logs WHERE user_id = :u AND date = :d AND id <> :s"
        ), {"u": g.user_id, "d": g.date, "s": g.survivor}).scalars().all()
        for dup in dup_ids:
            for table in ("food_entries", "exercise_entries", "water_entries"):
                bind.execute(sa.text(
                    f"UPDATE {table} SET daily_log_id = :s WHERE daily_log_id = :d"
                ), {"s": g.survivor, "d": dup})
            bind.execute(sa.text("DELETE FROM daily_logs WHERE id = :d"), {"d": dup})
        bind.execute(sa.text(
            "UPDATE daily_logs SET "
            "  total_calories = COALESCE((SELECT SUM(calories) FROM food_entries WHERE daily_log_id = :s), 0), "
            "  total_protein  = COALESCE((SELECT SUM(protein)  FROM food_entries WHERE daily_log_id = :s), 0), "
            "  total_carbs    = COALESCE((SELECT SUM(carbs)    FROM food_entries WHERE daily_log_id = :s), 0), "
            "  total_fats     = COALESCE((SELECT SUM(fats)     FROM food_entries WHERE daily_log_id = :s), 0) "
            "WHERE id = :s"
        ), {"s": g.survivor})


def _dedupe_health_snapshots(bind) -> None:
    """Collapse duplicate (user_id, date) health_snapshots onto the lowest id.
    No child rows — just delete the extras (the survivor keeps the oldest values;
    the webhook re-upserts fresh metrics on the next sync)."""
    bind.execute(sa.text(
        "DELETE FROM health_snapshots WHERE id NOT IN "
        "(SELECT MIN(id) FROM health_snapshots GROUP BY user_id, date)"
    ))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    _dedupe_daily_logs(bind)
    _dedupe_health_snapshots(bind)

    dl_uniques = {c['name'] for c in insp.get_unique_constraints('daily_logs')}
    if 'uq_daily_log_user_date' not in dl_uniques:
        op.create_unique_constraint(
            'uq_daily_log_user_date', 'daily_logs', ['user_id', 'date']
        )

    hs_uniques = {c['name'] for c in insp.get_unique_constraints('health_snapshots')}
    if 'uq_health_snapshot_user_date' not in hs_uniques:
        op.create_unique_constraint(
            'uq_health_snapshot_user_date', 'health_snapshots', ['user_id', 'date']
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'uq_health_snapshot_user_date' in {c['name'] for c in insp.get_unique_constraints('health_snapshots')}:
        op.drop_constraint('uq_health_snapshot_user_date', 'health_snapshots', type_='unique')
    if 'uq_daily_log_user_date' in {c['name'] for c in insp.get_unique_constraints('daily_logs')}:
        op.drop_constraint('uq_daily_log_user_date', 'daily_logs', type_='unique')
