"""hot-path composite indexes (2026-07-06 perf sweep)

Revision ID: b3c4d5e6f7a8
Revises: e2f3a4b5c6d7
Create Date: 2026-07-06 00:00:00.000000

The per-turn hot path and the 30-min scheduler both filter these tables on
(user_id, time) or join on daily_log_id, none of which were indexed beyond
single-column FKs (and Postgres does not auto-index FK columns at all):

  conversation_logs(user_id, timestamp) — every turn's history window, the
    scheduler's recency/silence gates, and proactive send-target routing.
  body_metrics(user_id, timestamp)      — weight-trend read in every context build.
  food_entries(daily_log_id)            — day-view + totals joins.
  exercise_entries(daily_log_id)        — same join pattern.
  pending_questions(user_id, answered_at) — open-question scan per scheduler tick.

Paired with the matching Index() declarations in db/models.py (db/database.py
_migrate is SQLite-only; Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    ("ix_conversation_logs_user_ts", "conversation_logs", ["user_id", "timestamp"]),
    ("ix_body_metrics_user_ts", "body_metrics", ["user_id", "timestamp"]),
    ("ix_food_entries_daily_log", "food_entries", ["daily_log_id"]),
    ("ix_exercise_entries_daily_log", "exercise_entries", ["daily_log_id"]),
    ("ix_pending_questions_user_open", "pending_questions", ["user_id", "answered_at"]),
)


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols, if_not_exists=True)


def downgrade() -> None:
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
