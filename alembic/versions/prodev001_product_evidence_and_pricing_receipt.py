"""product_evidence snapshots + the pricing receipt on food_entries

⭐ P17f, migration-first. Two halves of one storage contract *(Danny,
2026-08-17)*: EVIDENCE ROWS ARE IMMUTABLE SNAPSHOTS. CANONICAL MEAL ROWS
REFERENCE THEM. ACQUISITION MAY ADD EVIDENCE; SETTLEMENT MAY ONLY READ
EVIDENCE.

`product_evidence` is APPEND-ONLY and snapshot-addressed — identity is
canonical_code + provider revision + fingerprint, never code alone, because OFF
is mutable and tomorrow's edit must INSERT a new snapshot rather than rewrite
the evidence out from under meals already committed. "Latest" is a query over
created_at, not an overwrite.

The receipt columns on `food_entries` record which facts THIS meal used and
how — rung, evidence ids, basis, conversion ids, amounts, factor — as
first-class columns rather than payload JSON, because B-1.8 joins on them:
load the referenced evidence, change the factor, reprice deterministically,
no provider fetch.

Pure ADDs: one new table, nine nullable columns. No backfill, nothing to fail
on existing rows; legacy and estimate rows simply never write the receipt.

Parents entres001. Deploy runs `alembic upgrade heads`.

Revision ID: prodev001
Revises: entres001
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "prodev001"
down_revision: Union[str, None] = "entres001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RECEIPT = [
    ("pricing_rung", sa.String()),
    ("nutrition_evidence_id", sa.String()),
    ("source_basis", sa.String()),
    ("basis_evidence_id", sa.String()),
    ("conversion_evidence_ids_json", sa.Text()),
    ("source_amount", sa.Float()),
    ("source_unit", sa.String()),
    ("scaling_factor", sa.Float()),
    ("product_evidence_id", sa.Integer()),
]


def upgrade() -> None:
    # ONLINE ONLY. Offline (--sql) hands back a MockConnection with no
    # inspection system, and CI compiles the head migration offline against
    # Postgres precisely to catch that (idem001 learned this the hard way).
    online = not context.is_offline_mode()
    if not (online and sa.inspect(op.get_bind())
            .has_table("product_evidence")):
        op.create_table(
            "product_evidence",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(), nullable=False,
                      server_default="off"),
            sa.Column("canonical_code", sa.String(), nullable=False),
            # NOT NULL: a NULL component exempts a row from the UNIQUE
            # constraint in both Postgres and SQLite. Revision-less providers
            # write '' and participate in identity like everyone else.
            sa.Column("provider_revision", sa.String(), nullable=False,
                      server_default=""),
            sa.Column("provider_modified_at", sa.Integer(), nullable=True),
            sa.Column("source_fingerprint", sa.String(), nullable=False),
            sa.Column("product_name", sa.String(), nullable=True),
            sa.Column("brands", sa.String(), nullable=True),
            sa.Column("per_serving_json", sa.Text(), nullable=True),
            sa.Column("per100g_json", sa.Text(), nullable=True),
            sa.Column("per100ml_json", sa.Text(), nullable=True),
            sa.Column("serving_amount", sa.Float(), nullable=True),
            sa.Column("serving_unit", sa.String(), nullable=True),
            sa.Column("serving_mass_g", sa.Float(), nullable=True),
            sa.Column("serving_ml", sa.Float(), nullable=True),
            sa.Column("package_unit", sa.String(), nullable=True),
            sa.Column("servings_per_package", sa.Float(), nullable=True),
            sa.Column("source_reference_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now()),
            sa.UniqueConstraint("provider", "canonical_code",
                                "provider_revision", "source_fingerprint",
                                name="uq_product_evidence_snapshot"),
        )
        op.create_index("ix_product_evidence_code", "product_evidence",
                        ["canonical_code", "created_at"])

    existing = set()
    if online:
        existing = {c["name"] for c in
                    sa.inspect(op.get_bind()).get_columns("food_entries")}
    for name, kind in _RECEIPT:
        if name not in existing:
            op.add_column("food_entries",
                          sa.Column(name, kind, nullable=True))
    # ⛔ THE FK THE MODEL DECLARES, WITH RESTRICT — a bare Integer here would be
    # schema drift no suite can see: tests build from the models, production
    # from the migrations, and only production would allow deleting evidence a
    # committed meal still cites.
    if online and not any(
            fk.get("name") == "fk_food_entry_product_evidence"
            for fk in sa.inspect(op.get_bind())
            .get_foreign_keys("food_entries")):
        op.create_foreign_key(
            "fk_food_entry_product_evidence", "food_entries",
            "product_evidence", ["product_evidence_id"], ["id"],
            ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint("fk_food_entry_product_evidence", "food_entries",
                       type_="foreignkey")
    for name, _ in reversed(_RECEIPT):
        op.drop_column("food_entries", name)
    op.drop_index("ix_product_evidence_code", table_name="product_evidence")
    op.drop_table("product_evidence")
