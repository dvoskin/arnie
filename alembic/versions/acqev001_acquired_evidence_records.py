"""acquired evidence — the artifact rung stops being a hand-built catalog

⛔⛔⛔ THIS TABLE IS THE 9%. The artifact rung reads a COMMITTED JSON FILE:
`evidence_for()` says "Generation happens outside the turn, by the script, or
not at all this turn", and `_artifact()` is "a file read; never a fetch". A
running process that learns a new food has nowhere to put it — and on Render
the filesystem is ephemeral and per-instance, so even writing it would not
survive. The catalog therefore held 27 foods, seeded from a list whose own
generator admits "seems likely someone will log this" is NOT a criterion, and
every food outside it fell to legacy forever no matter how often it was logged.

    catalog   foods Arnie was BUILT to know
    cache     evidence Arnie has ALREADY ESTABLISHED   <- this table

⭐ SAME RUNG, NOT A NEW ONE. Rows are read into the SAME `ArtifactEvidence`
shape under the SAME `pricing_artifact.key`, and ranked by the SAME
`select_priced_rung`. Acquisition sources must not become extra rungs inside
`look()`; they establish evidence, and canonical consumes it under the
authority rules it already has.

⛔⛔ AND IT OBEYS THE SEEDED EVIDENCE'S STALENESS CONTRACT — `resolver_version`
and `retrieval_fingerprint` are matched ON READ, `acquired_at` ages against the
same MAX_ARTIFACT_AGE_DAYS. Without that the cache is simply the way to EVADE
the freshness rule the file artifact obeys.

Revision ID: acqev001
Revises: memtrust001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "acqev001"
down_revision: Union[str, None] = "memtrust001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "acquired_evidence_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_identity", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_identifier", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("authority_grade", sa.String(), nullable=False),
        sa.Column("nutrition_basis", sa.String(), nullable=False,
                  server_default="per_100g"),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("identity_evidence", sa.JSON(), nullable=False),
        sa.Column("serving_basis", sa.JSON(), nullable=False),
        sa.Column("quantity_compatibility", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("resolver_version", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("retrieval_fingerprint", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # ⭐ IDEMPOTENCE ON THE FACT, NOT ON THE FETCH. Two turns racing to
        # acquire the same food under the same instrument must produce ONE row.
        sa.UniqueConstraint("canonical_identity", "resolver_version",
                            "retrieval_fingerprint", "source_fingerprint",
                            name="uq_acquired_evidence_fact"),
    )
    # A stale-resolver row must never be SERVED but must remain STORED, so the
    # instrument columns are part of the read key rather than a delete filter.
    op.create_index("ix_acquired_evidence_identity",
                    "acquired_evidence_records",
                    ["canonical_identity", "resolver_version",
                     "retrieval_fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_acquired_evidence_identity",
                  table_name="acquired_evidence_records")
    op.drop_table("acquired_evidence_records")
