"""The durable candidate universe: generation, selection, presentation.

Five tables that make every quantity decision explainable from stored rows
alone — and DOMAIN-NEUTRAL, so exercise identity, set/rep, distance, duration
and dose ambiguity reuse them without a schema redesign. Nothing here names a
food.

APPEND-ONLY BY INTENT. These rows are evidence: a new revision or policy
writes a new set and a new decision, and the previous one stays exactly as it
was. `ondelete="RESTRICT"` on every foreign key is part of that — a candidate
that an option references must not be removable while the option exists.

The unique constraints are the load-bearing part:

  uq_candidate_set_identity     the IDEMPOTENCY KEY. A retried ask finds the
                                first universe instead of minting a second.
  uq_candidate_within_set       one id, one candidate — an option cannot
                                resolve to two justifications.
  uq_exclusion_within_decision  a candidate is excluded once, for one reason.
  uq_presented_option_position  no two options occupied the same place.

Revision ID: b1uni001
Revises: b1obs003
"""
import sqlalchemy as sa
from alembic import op

revision = "b1uni001"
down_revision = "b1obs003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_set_id", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False,
                  server_default="food"),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("interaction_revision", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("field_id", sa.String(), nullable=False),
        sa.Column("subject_entity_id", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("subject_variant_id", sa.String(), nullable=True),
        sa.Column("generator_version", sa.String(), nullable=False),
        sa.Column("generation_input_fingerprint", sa.String(), nullable=False),
        sa.Column("rejections", sa.JSON(), nullable=False,
                  server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("candidate_set_id", name="uq_candidate_set_id"),
        sa.UniqueConstraint("operation_id", "interaction_revision", "field_id",
                            "generator_version",
                            name="uq_candidate_set_identity"),
    )
    op.create_index("ix_candidate_sets_user", "candidate_sets", ["user_id"])
    op.create_index("ix_candidate_sets_operation", "candidate_sets",
                    ["operation_id"])

    op.create_table(
        "candidate_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_set_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("candidate_kind", sa.String(), nullable=False,
                  server_default="quantity"),
        sa.Column("position", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("semantic_hash", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_set_id"],
                                ["candidate_sets.candidate_set_id"],
                                ondelete="RESTRICT"),
        sa.UniqueConstraint("candidate_set_id", "candidate_id",
                            name="uq_candidate_within_set"),
    )
    op.create_index("ix_candidate_records_set", "candidate_records",
                    ["candidate_set_id"])

    op.create_table(
        "candidate_evidence_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_set_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("evidence_index", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_dataset_id", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("source_dataset_version", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("source_record_key", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("source_record_version", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("subject_scope", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("subject_user_id", sa.Integer(), nullable=True),
        sa.Column("subject_variant_id", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        # COMPOSITE, so evidence cannot orphan itself onto a candidate that
        # belongs to another set.
        sa.ForeignKeyConstraint(
            ["candidate_set_id", "candidate_id"],
            ["candidate_records.candidate_set_id",
             "candidate_records.candidate_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("candidate_set_id", "candidate_id",
                            "evidence_index",
                            name="uq_evidence_within_candidate"),
    )
    op.create_index("ix_candidate_evidence_source",
                    "candidate_evidence_records", ["source_type"])

    op.create_table(
        "candidate_selection_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("candidate_set_id", sa.String(), nullable=False),
        sa.Column("selection_policy_version", sa.String(), nullable=False),
        sa.Column("surface", sa.String(), nullable=False,
                  server_default="label_text"),
        sa.Column("locale", sa.String(), nullable=False, server_default="en"),
        sa.Column("maximum_options", sa.Integer(), nullable=False,
                  server_default="3"),
        sa.Column("renderer_contract_version", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("selected_candidate_ids", sa.JSON(), nullable=False,
                  server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["candidate_set_id"],
                                ["candidate_sets.candidate_set_id"],
                                ondelete="RESTRICT"),
        sa.UniqueConstraint("decision_id", name="uq_selection_decision_id"),
        sa.UniqueConstraint("candidate_set_id", "selection_policy_version",
                            "surface", "locale", "renderer_contract_version",
                            name="uq_selection_decision_conditions"),
    )
    op.create_index("ix_selection_decisions_set",
                    "candidate_selection_decisions", ["candidate_set_id"])

    op.create_table(
        "candidate_exclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["candidate_selection_decisions.decision_id"],
            ondelete="RESTRICT"),
        sa.UniqueConstraint("decision_id", "candidate_id",
                            name="uq_exclusion_within_decision"),
    )
    op.create_index("ix_candidate_exclusions_reason", "candidate_exclusions",
                    ["reason"])

    op.create_table(
        "presented_candidate_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("candidate_set_id", sa.String(), nullable=False),
        sa.Column("option_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("interaction_revision", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("selected_position", sa.Integer(), nullable=False),
        sa.Column("rendered_label", sa.String(), nullable=False),
        sa.Column("renderer_contract_version", sa.String(), nullable=False,
                  server_default=""),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["candidate_selection_decisions.decision_id"],
            ondelete="RESTRICT"),
        sa.UniqueConstraint("decision_id", "option_id",
                            name="uq_presented_option_id"),
        sa.UniqueConstraint("decision_id", "selected_position",
                            name="uq_presented_option_position"),
    )
    op.create_index("ix_presented_options_candidate",
                    "presented_candidate_options", ["candidate_id"])


def downgrade():
    op.drop_table("presented_candidate_options")
    op.drop_table("candidate_exclusions")
    op.drop_table("candidate_selection_decisions")
    op.drop_table("candidate_evidence_records")
    op.drop_table("candidate_records")
    op.drop_table("candidate_sets")
