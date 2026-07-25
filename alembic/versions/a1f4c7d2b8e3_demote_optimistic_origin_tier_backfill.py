"""demote the optimistic origin_tier backfill (a USDA exact match is not a label)

Revision ID: a1f4c7d2b8e3
Revises: 9c814ca1d70d
Create Date: 2026-07-25 00:00:00.000000

9c814ca1d70d added the column and backfilled it from `confidence`, the only
origin signal legacy rows carry. That backfill maps `confidence = 'exact'` to
`branded_exact`, and it is wrong in one direction that matters: **USDA text
matches are also graded 'exact'.** A cached generic USDA row for a branded name
therefore came back as a product answer.

The consequence is precisely the behaviour the column was added to fix, still
running:

  * `branded_exact` seats at `saved_product` on the manufactured ladder, which
    is not a fallback rung, so `needs_branded_lookup()` returns False and the
    branded lookup never fires; and
  * the staleness gate treats a tier above GENERIC_EXACT as a real answer, so
    the row gets the 90-day horizon rather than the short branded re-check.

So the fixed rows keep suppressing branded enrichment, and the fix reads as
though it shipped.

Legacy rows cannot prove they were branded — the column that would say so is
the one being backfilled. So the value is the pessimistic one: only a row the
user actually confirmed keeps its authority, and `exact` drops to
`generic_exact` alongside every other unrecognised grade. A row that really was
a label re-earns `branded_exact` on its next lookup and re-caches itself, which
costs one lookup per stale product and is self-correcting. The other direction
is not: it is permanent and silent.

Rows written after this point are unaffected — they take their origin from the
rung the resolver actually used (skills/nutrition/authority.candidate_map), not
from a confidence string that never distinguished the two cases.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'a1f4c7d2b8e3'
down_revision: Union[str, Sequence[str], None] = '9c814ca1d70d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only the rows the earlier backfill promoted, and only where the user did
    # not confirm them. Anything written since (origin taken from the resolver's
    # rung) is left alone — this is a repair of one backfill, not a policy.
    op.execute("""
        UPDATE user_food_matches
           SET origin_tier = 'generic_exact'
         WHERE origin_tier = 'branded_exact'
           AND confidence = 'exact'
           AND (user_confirmed IS NULL OR user_confirmed IS NOT TRUE)
    """)


def downgrade() -> None:
    # Restores 9c814ca1d70d's mapping, including its optimism.
    op.execute("""
        UPDATE user_food_matches
           SET origin_tier = 'branded_exact'
         WHERE origin_tier = 'generic_exact'
           AND confidence = 'exact'
           AND (user_confirmed IS NULL OR user_confirmed IS NOT TRUE)
    """)
