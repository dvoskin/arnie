"""Question-generation stamps, and the created_at default production never had

TWO FIXES, ONE MIGRATION, AND THE SECOND IS THE SERIOUS ONE.

1. `b1obs001` was amended in place after it had already been applied. It was
   verified unapplied at a moment in time, and `main` auto-deploys — so the
   original shipped, alembic stamped it, and the amendment was skipped
   silently. The rule is not "check whether it has been applied", it is NEVER
   AMEND A MIGRATION THAT HAS BEEN PUSHED.

2. `pending_operations.created_at` has no DEFAULT in production. The model
   declares `server_default=func.now()` and nothing sets it in Python, so
   SQLAlchemy omits the column and Postgres writes NULL — measured: 7 of 7
   rows. `OwnedOperation.asked_at` reads it, so every answer latency and every
   abandonment age has been None since the table existed, and D4's latency
   metric was structurally unrecordable.

   Existing NULLs are left NULL on purpose. `updated_at` is settlement time,
   not ask time; backfilling from it would turn "unknown" into a fabricated
   near-zero latency, and a made-up number is worse than a missing one in a
   window whose whole purpose is deciding what to build next.

3. `meal_commits.created_at` has the same defect, found by
   `tests/test_the_migrations_build_what_the_models_declare.py` — written
   alongside this migration because no test in the suite could see this class
   of drift: every suite builds its schema from the MODELS via `create_all`,
   production builds it from the MIGRATIONS, and the two descriptions were
   never compared to each other in either direction.

Revision ID: b1obs002
Revises: b1obs001
"""
import sqlalchemy as sa
from alembic import op

revision = "b1obs002"
down_revision = "b1obs001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("b1_answer_observations",
                  sa.Column("interaction_revision", sa.Integer(),
                            nullable=True))
    op.add_column("b1_answer_observations",
                  sa.Column("question_version", sa.String(), nullable=False,
                            server_default=""))
    op.alter_column("pending_operations", "created_at",
                    server_default=sa.text("now()"))
    # THE SECOND INSTANCE, found by the drift test written alongside this
    # migration rather than by anyone noticing a NULL. Same defect, same
    # cause: the model promises a default the migration never created.
    op.alter_column("meal_commits", "created_at",
                    server_default=sa.text("now()"))


def downgrade():
    op.alter_column("meal_commits", "created_at", server_default=None)
    op.alter_column("pending_operations", "created_at", server_default=None)
    op.drop_column("b1_answer_observations", "question_version")
    op.drop_column("b1_answer_observations", "interaction_revision")
