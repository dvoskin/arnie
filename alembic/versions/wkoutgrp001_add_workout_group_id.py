"""add workout_group_id to exercise_entries

A WORKOUT IS A THING; until now only its sets were.

`exercise_entries` stores one row per logged set, and nothing bound those rows
into an exercise or a session. Five rows of `sets=1` for the same movement,
minutes apart, are one exercise inside one workout — but every consumer had to
re-infer that from names and timestamps, which is why cross-source dedup ended
up guessing at "starts within 30 min, durations within 40%".

This is the fitness analogue of `meal_group_id`: an opaque id shared by every
set of one training session, assigned at write time. It gives live surfaces
(rest timers, form cues, an in-progress workout view) a session to attach to,
and it lets the ledger describe a workout rather than a scatter of rows.

Nullable and unbackfilled on purpose. Historic rows have no session we can
honestly reconstruct — inventing one from timestamps would bake the very
guesswork this exists to remove — so they stay NULL and readers treat a NULL
group as "one row, its own session".

Revision ID: wkoutgrp001
Revises: a1f4c7d2b8e3
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "wkoutgrp001"
down_revision: Union[str, Sequence[str], None] = "a1f4c7d2b8e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("exercise_entries") as batch:
        batch.add_column(sa.Column("workout_group_id", sa.String(),
                                   nullable=True))
    # Read path is always "the sets of this session", so the index is on the
    # group alone — the same shape food_entries uses for its meal grouping.
    op.create_index("ix_exercise_entries_workout_group",
                    "exercise_entries", ["workout_group_id"])


def downgrade() -> None:
    op.drop_index("ix_exercise_entries_workout_group",
                  table_name="exercise_entries")
    with op.batch_alter_table("exercise_entries") as batch:
        batch.drop_column("workout_group_id")
