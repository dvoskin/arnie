"""Complete the candidate universe's durable identity and integrity.

FORWARD ONLY. `b1uni001` is already pushed, and `main` auto-deploys, so
amending it is the mistake this programme has already paid for once: the check
that says "it has not been applied yet" is true when you make it and stale by
the time the amendment ships.

Three corrections:

1. `maximum_options` joins the decision's durable identity. The selection
   context claims the outcome is determined by surface, locale, maximum
   options and renderer version — but the unique constraint omitted the third,
   so a three-option text row and a five-option structured row collided under
   one identity. The second could never be written, and the first was replayed
   in its place.

2. `candidate_exclusions.candidate_set_id`, so set membership is enforceable
   in SQL rather than only by the aggregate. The dataclass catches a foreign
   candidate on the primary write path; a migration, a script or a future
   writer does not go through the dataclass, and an exclusion naming another
   set's candidate makes the partition arithmetic wrong wherever it is read.

3. Composite foreign keys from exclusions and presented options to
   `candidate_records`, so the chain `option -> candidate -> set` cannot have
   a dangling middle link.

EXISTING ROWS REMAIN READABLE. The backfill fills `candidate_set_id` from the
decision each exclusion already points at, so rows written by `b1uni001` keep
their meaning and satisfy the new constraint.

Revision ID: b1uni002
Revises: b1uni001
"""
import sqlalchemy as sa
from alembic import op

revision = "b1uni002"
down_revision = "b1uni001"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. the exclusion learns which set it belongs to ─────────────────────
    op.add_column("candidate_exclusions",
                  sa.Column("candidate_set_id", sa.String(), nullable=False,
                            server_default=""))
    # BACKFILL BEFORE CONSTRAINING. Every existing exclusion already points at
    # a decision, and the decision names the set — so the value is derivable
    # and no row has to be guessed at or dropped.
    op.execute(sa.text(
        "UPDATE candidate_exclusions SET candidate_set_id = ("
        "  SELECT d.candidate_set_id FROM candidate_selection_decisions d"
        "  WHERE d.decision_id = candidate_exclusions.decision_id) "
        "WHERE candidate_set_id = '' OR candidate_set_id IS NULL"))

    # ── 2. maximum_options joins the decision's identity ────────────────────
    with op.batch_alter_table("candidate_selection_decisions") as batch:
        batch.drop_constraint("uq_selection_decision_conditions",
                              type_="unique")
        batch.create_unique_constraint(
            "uq_selection_decision_conditions_v2",
            ["candidate_set_id", "selection_policy_version", "surface",
             "locale", "maximum_options", "renderer_contract_version"])

    # ── 3. membership, enforced by the database ─────────────────────────────
    #
    # SQLite cannot add a foreign key in place; `batch_alter_table` rebuilds
    # the table, which is the supported path and is why these run inside one.
    with op.batch_alter_table("candidate_exclusions") as batch:
        batch.create_foreign_key(
            "fk_exclusion_candidate_membership", "candidate_records",
            ["candidate_set_id", "candidate_id"],
            ["candidate_set_id", "candidate_id"], ondelete="RESTRICT")
    with op.batch_alter_table("presented_candidate_options") as batch:
        batch.create_foreign_key(
            "fk_presented_candidate_membership", "candidate_records",
            ["candidate_set_id", "candidate_id"],
            ["candidate_set_id", "candidate_id"], ondelete="RESTRICT")



def downgrade():
    with op.batch_alter_table("presented_candidate_options") as batch:
        batch.drop_constraint("fk_presented_candidate_membership",
                              type_="foreignkey")
    with op.batch_alter_table("candidate_exclusions") as batch:
        batch.drop_constraint("fk_exclusion_candidate_membership",
                              type_="foreignkey")
    with op.batch_alter_table("candidate_selection_decisions") as batch:
        batch.drop_constraint("uq_selection_decision_conditions_v2",
                              type_="unique")
        batch.create_unique_constraint(
            "uq_selection_decision_conditions",
            ["candidate_set_id", "selection_policy_version", "surface",
             "locale", "renderer_contract_version"])
    op.drop_column("candidate_exclusions", "candidate_set_id")
