"""One open pending question per (user, kind) — enforced by the database.

Invariant I2. `record_pending_question`'s own contract is already
"one open question per kind — update in place rather than stacking"
(db/queries.py), and since the 07-29 deploy production holds it behaviourally
(master audit §12: duplicates fell from 4–19/day to 0). What does NOT exist is
structural enforcement: the helper is get-then-insert, so two concurrent turns
can still stack, and a future writer that skips the helper can regress G
silently. This index makes that impossible.

Data repair first: any historic stacked open rows are closed (all but the
newest per user+kind get answered_at stamped) so index creation cannot fail.
Closing rather than deleting — they are history, and `answered_at` is the
column the schema already uses to mean "no longer open".

Parents ledgerdedup001. Deploy runs `alembic upgrade heads`.
Rollback: `alembic downgrade` drops the index; the closed duplicates stay
closed (they were stale stacked rows, and re-opening them would recreate the
defect).

Revision ID: pendinguniq001
Revises: ledgerdedup001
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "pendinguniq001"
down_revision: Union[str, None] = "ledgerdedup001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Close stacked open rows, keeping the newest per (user, kind, purpose).
    # `item_referenced` is the purpose discriminator: the clarification kinds
    # legitimately hold one open row PER ITEM ("grilled or fried?" about the
    # sandwich and "what dressing?" about the salad coexist), so it is part of
    # the identity — the directive's own phrasing is "one active pending
    # question per user, turn, and purpose". COALESCE folds NULL and '' into
    # one bucket so the ref-less kinds (conversation_hook, profile_stats…)
    # stay strictly one-per-kind.
    r = conn.execute(sa.text("""
        UPDATE pending_questions SET answered_at = CURRENT_TIMESTAMP
        WHERE answered_at IS NULL
          AND id NOT IN (SELECT MAX(id) FROM pending_questions
                         WHERE answered_at IS NULL
                         GROUP BY user_id, kind,
                                  COALESCE(item_referenced, ''))"""))
    if r is not None:   # offline (--sql) mode returns None from execute()
        print(f"pendinguniq001: closed {r.rowcount} stacked open pendings")

    op.create_index(
        "uq_pending_open_per_user_kind", "pending_questions",
        ["user_id", "kind", sa.text("COALESCE(item_referenced, '')")],
        unique=True,
        postgresql_where=sa.text("answered_at IS NULL"),
        sqlite_where=sa.text("answered_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_pending_open_per_user_kind",
                  table_name="pending_questions")
