"""keep the label's own serving — a counted portion needs it to be answerable

`user_food_matches` stored a per-100g panel and nothing else. Open Food Facts
publishes the serving the product is actually sold in — "3 pieces (30 g)",
"about 30 chips (28 g)" — `off.search` already returns it as `serving_text`,
and `normalize.serving_unit_mass` already turns it into grams-per-unit for THAT
record. The field just had nowhere to live, so it was dropped at cache time and
every repeat log of a branded food arrived with per-100g alone.

A counted portion is then unanswerable. "5 twizzlers" has no mass, nothing can
divide a serving that was never kept, and the model's calorie guess becomes the
anchor with no check behind it. Measured 2026-07-31: five Twizzlers logged at
323 cal — the per-100g density — where the label gives 162. Three users hit the
same shape inside 30 days and it errs BOTH ways; two 16 oz lattes logged as
200 cal understated by half, which for a coaching app is the worse direction.

Absence keeps its meaning. A panel with a mass but no count ("50 g"), or with
neither (""), still parses to None and the portion stays unscalable — which the
ask ladder can act on and a guess cannot. This migration does not make anything
ask; it gives the existing ladder the fact it was missing.

Pure ADD of one nullable column: no backfill, no constraint, nothing to fail on
existing rows. Old instances during a rolling deploy simply never write it, and
rows cached before this stay NULL and behave exactly as they do today — they
fall to the ask rather than to a guess.

Parents idem001. Deploy runs `alembic upgrade heads`.

Revision ID: serving001
Revises: idem001
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "serving001"
down_revision: Union[str, None] = "idem001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ONLINE ONLY. Offline (--sql) hands back a MockConnection with no
    # inspection system, and CI compiles the head migration offline against
    # Postgres precisely to catch that (idem001 learned this the hard way).
    if not context.is_offline_mode():
        cols = {c["name"] for c in
                sa.inspect(op.get_bind()).get_columns("user_food_matches")}
        if "serving_text" in cols:
            return
    op.add_column("user_food_matches",
                  sa.Column("serving_text", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_food_matches", "serving_text")
