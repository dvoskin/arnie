"""add generated_workout_programs + generated_workout_sessions

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-29 02:30:00.000000

Backs the science-based program builder (skills/fitness/program_builder).

Two NEW tables — keeps the legacy `workout_programs` table (raw-text parse +
auto-fill flows, one per user) untouched, so the iOS web "AI Profile → Workout
program" path continues working unchanged. The two systems share intent (a
user's training plan) but live separate lifecycles:

  • workout_programs            — AI-parsed free text. One row per user.
  • generated_workout_programs  — Builder output. Multiple rows per user
                                  (history preserved), one `active=True` at
                                  a time.
  • generated_workout_sessions  — Per-day exercise prescription hanging off
                                  the parent program (cascade delete).

Per [[feedback_arnie_migrate_postgres_gap]]: every new table needs an Alembic
migration AND a paired SQLite path in db/database.py — Postgres doesn't run the
inline _migrate(). The SQLite path is `Base.metadata.create_all` (covers new
tables automatically); only column additions on existing tables need the
explicit list. So this migration is the ONLY thing that creates these tables
on Postgres. Idempotent: guarded on existing-table inspection so a re-run is
safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "generated_workout_programs"):
        op.create_table(
            "generated_workout_programs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("goal", sa.String(), nullable=False),
            sa.Column("days_per_week", sa.Integer(), nullable=False),
            sa.Column("split", sa.String(), nullable=False),
            sa.Column("equipment_csv", sa.String(), server_default=""),
            sa.Column("experience_level", sa.String(), server_default="intermediate"),
            sa.Column("weak_points_csv", sa.String(), server_default=""),
            sa.Column("rationale", sa.Text(), server_default=""),
            sa.Column("weekly_volume_json", sa.Text(), server_default="{}"),
            sa.Column("notes", sa.Text(), server_default=""),
            sa.Column("active", sa.Boolean(), server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "ix_generated_workout_programs_user_id",
            "generated_workout_programs", ["user_id"],
        )
        op.create_index(
            "ix_generated_workout_programs_active",
            "generated_workout_programs", ["active"],
        )
        op.create_index(
            "ix_generated_workout_programs_created_at",
            "generated_workout_programs", ["created_at"],
        )

    if not _has_table(bind, "generated_workout_sessions"):
        op.create_table(
            "generated_workout_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("program_id", sa.Integer(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("focus_csv", sa.String(), server_default=""),
            sa.Column("exercises_json", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(
                ["program_id"], ["generated_workout_programs.id"], ondelete="CASCADE",
            ),
        )
        op.create_index(
            "ix_generated_workout_sessions_program_id",
            "generated_workout_sessions", ["program_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_generated_workout_sessions_program_id",
                  table_name="generated_workout_sessions")
    op.drop_table("generated_workout_sessions")
    op.drop_index("ix_generated_workout_programs_created_at",
                  table_name="generated_workout_programs")
    op.drop_index("ix_generated_workout_programs_active",
                  table_name="generated_workout_programs")
    op.drop_index("ix_generated_workout_programs_user_id",
                  table_name="generated_workout_programs")
    op.drop_table("generated_workout_programs")
