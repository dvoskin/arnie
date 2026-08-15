"""The interpretation boundary, durable: what a surface food name means.

Measured 2026-08-14 over 691 real production entries: the largest unreachable
food population is food named in a non-Latin script — 30.4%, three times the
next bucket — because canonical identity is built from the SURFACE STRING.
`Помидор` cannot reach `tomato|` however many identities the pricing artifact
holds. This table is where the interpreted meaning becomes durable, so
settlement can read a canonical entity id instead of guessing from bytes.

GLOBAL, NOT PER-USER. "Помидор denotes a tomato" is a fact about language;
`user_food_matches` is per-user because it holds that user's nutrition profile,
which is a different kind of fact.

⚠ FORWARD-ONLY IN PRACTICE — main auto-deploys, so this migration is applied by
the deploy that carries it and must never be amended afterwards. `downgrade`
exists for a local rollback, not as an operational plan.

⚠⚠ EVERY COLUMN HERE IS PAIRED WITH ITS MODEL FIELD IN `db/models.py`. No test
can see schema drift — every suite builds from the MODELS and production builds
from the MIGRATIONS — so the only protection is that both sides are written in
the same commit and reviewed together.

Revision ID: entres001
Revises: b1obs005
"""
import sqlalchemy as sa
from alembic import op

revision = "entres001"
down_revision = "b1obs005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "food_entity_resolutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("surface_form", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("surface_key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("canonical_entity_id", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("interpreted_meaning", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("source_language", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("resolver_version", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("model_id", sa.String(), nullable=False, server_default=""),
        sa.Column("contract_fingerprint", sa.String(), nullable=False,
                  server_default=""),
        # ⚠ ADVISORY. Nullable because "nobody scored this" and "scored zero"
        # are different facts, and a NOT NULL default would erase the first.
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    # ONE ROW PER SURFACE FORM, in the schema rather than in the writer: two
    # resolutions of one string are two answers to one question, and the reader
    # raises on them — which would surface at settle time as a 500 rather than
    # as the data problem it is.
    op.create_unique_constraint("uq_food_entity_surface_key",
                                "food_entity_resolutions", ["surface_key"])
    op.create_index("ix_food_entity_resolutions_surface_key",
                    "food_entity_resolutions", ["surface_key"])
    op.create_index("ix_food_entity_resolution_entity",
                    "food_entity_resolutions", ["canonical_entity_id"])
    op.create_index("ix_food_entity_resolution_state",
                    "food_entity_resolutions", ["state"])


def downgrade():
    op.drop_index("ix_food_entity_resolution_state",
                  table_name="food_entity_resolutions")
    op.drop_index("ix_food_entity_resolution_entity",
                  table_name="food_entity_resolutions")
    op.drop_index("ix_food_entity_resolutions_surface_key",
                  table_name="food_entity_resolutions")
    op.drop_constraint("uq_food_entity_surface_key", "food_entity_resolutions")
    op.drop_table("food_entity_resolutions")
