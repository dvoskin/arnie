"""food_entries.resolved_grams — the mass a row is priced at, for repair

⭐ B-1.8b. The repair primitive's count->grams bridge ("2 eggs -> actually
100 g") divides by the mass the original count was PRICED AT. Settlement has
recorded that value in the receipt payload since P17f (prodev001) and the
writer already forwards it — but the COLUMN was never created, so the value
was silently dropped at write time. Found by the first B-1.8b test that needed
it, before any correction ran in production.

Pure ADD of one nullable column. Rows without a sourced conversion stay NULL,
and the primitive refuses the bridge by name rather than guessing.

Parents prodev001. Deploy runs `alembic upgrade heads`.

Revision ID: corrrec001
Revises: prodev001
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "corrrec001"
down_revision: Union[str, None] = "prodev001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not context.is_offline_mode():
        cols = {c["name"] for c in
                sa.inspect(op.get_bind()).get_columns("food_entries")}
        if "resolved_grams" in cols:
            return
    op.add_column("food_entries",
                  sa.Column("resolved_grams", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("food_entries", "resolved_grams")
