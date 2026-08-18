"""product_unit_evidence — what a consumer unit means for one exact snapshot

⭐ P17-UA *(Danny, 2026-08-18)*. The snapshot knows `1 serving = 55 g`; it
must not invent `1 bar = 1 serving`. This table holds that second equality
ONLY when evidence establishes it — manufacturer label, package facts, a
catalog's structured serving text, or the user's confirmation FOR ONE
CONSUMPTION — keyed to the immutable snapshot it is about. Pricing "2 bars"
is then mechanical (2 x 1 serving/bar x 55 g/serving), every edge sourced.

Append-only, snapshot-addressed like `product_evidence`; FK RESTRICT so
evidence a meal priced through cannot be deleted from under it. Pure ADD:
one new table, no backfill.

Parents corrrec001. Deploy runs `alembic upgrade heads`.

Revision ID: produnit001
Revises: corrrec001
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "produnit001"
down_revision: Union[str, None] = "corrrec001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    online = not context.is_offline_mode()
    if online and sa.inspect(op.get_bind()).has_table("product_unit_evidence"):
        return
    op.create_table(
        "product_unit_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_evidence_id", sa.Integer(),
                  sa.ForeignKey("product_evidence.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("consumer_unit", sa.String(), nullable=False),
        sa.Column("consumer_units_per_serving", sa.Float(), nullable=False),
        sa.Column("provenance", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False,
                  server_default="snapshot"),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("entry_id", sa.Integer(), nullable=True),
        sa.Column("source_reference_json", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("product_evidence_id", "consumer_unit", "scope",
                            "source_fingerprint",
                            name="uq_product_unit_evidence_fact"),
    )
    op.create_index("ix_product_unit_evidence_snapshot", "product_unit_evidence",
                    ["product_evidence_id", "consumer_unit"])


def downgrade() -> None:
    op.drop_index("ix_product_unit_evidence_snapshot",
                  table_name="product_unit_evidence")
    op.drop_table("product_unit_evidence")
