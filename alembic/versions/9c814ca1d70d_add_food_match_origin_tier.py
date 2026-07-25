"""add origin_tier to user_food_matches (stop a cached generic laundering itself)

Revision ID: 9c814ca1d70d
Revises: foodprefs001
Create Date: 2026-07-25 00:00:00.000000

user_food_matches is written automatically after every successful lookup, so
almost every row is a cache of the resolver's own answer rather than anything
the user vouched for. Both USER_REGULAR candidate builders read only per100g,
so those rows re-entered resolution at authority tier 2 with MatchGrade.EXACT —
above BRANDED_EXACT, and labelled "user-confirmed" to the user.

That makes a generic estimate permanent: it outranks the real product label
once one exists, and it suppresses the generic-fallback disclosure because the
winning tier is no longer GENERIC_EXACT.

This column records which tier first produced the numbers, so the cache can
re-enter at the authority it actually has. Existing rows are backfilled from
the coarse `confidence` string, which is the only origin signal those rows
carry. Paired with UserFoodMatch.origin_tier (db/database.py _migrate is
SQLite-only; Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '9c814ca1d70d'
down_revision: Union[str, Sequence[str], None] = 'foodprefs001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_food_matches',
                  sa.Column('origin_tier', sa.String(), nullable=True))
    # Backfill from `confidence`, the only origin signal legacy rows have.
    # Deliberately pessimistic: "exact" is the one value that implies a branded
    # or exact label match, and anything unrecognised becomes generic rather
    # than inheriting user authority by default.
    op.execute("""
        UPDATE user_food_matches SET origin_tier = CASE
            WHEN user_confirmed IS TRUE OR confidence = 'user-confirmed'
                THEN 'user_regular'
            WHEN confidence = 'exact'     THEN 'branded_exact'
            WHEN confidence = 'estimated' THEN 'estimated'
            ELSE 'generic_exact'
        END
    """)


def downgrade() -> None:
    op.drop_column('user_food_matches', 'origin_tier')
