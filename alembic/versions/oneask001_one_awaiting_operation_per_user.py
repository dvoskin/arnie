"""pending_operations — at most one awaiting operation per (user, domain)

⛔⛔ CF5c-B3 *(Danny, 2026-08-19)*. `product_bound_ask._open` checked for a
prior awaiting ask and then inserted its own; the check sat in a bare except
that CONTINUED, a same-turn retry found its own ask as the "prior", cancelled
it and collided on the same operation id, and two workers could each pass the
check and both insert — nothing at the database said "one awaiting ask per
user". This is that constraint: a PARTIAL unique index over (user_id, domain)
for rows that are `awaiting_answer` AND `active`. Settled, cancelled and
expired rows are outside the predicate and repeat freely, so nothing existing
is disturbed and no backfill is needed.

Pure ADD: one index. If a violating pair already exists the CREATE fails
loudly, which is the correct outcome — that pair IS the bug.

Parents produnit001. Deploy runs `alembic upgrade heads`.

Revision ID: oneask001
Revises: produnit001
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "oneask001"
down_revision: Union[str, None] = "produnit001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME = "uq_pending_operations_one_awaiting"
_WHERE = "status = 'awaiting_answer' AND storage_status = 'active'"


def upgrade() -> None:
    online = not context.is_offline_mode()
    if online:
        existing = {i["name"] for i in
                    sa.inspect(op.get_bind()).get_indexes("pending_operations")}
        if _NAME in existing:
            return
    op.create_index(_NAME, "pending_operations", ["user_id", "domain"],
                    unique=True,
                    postgresql_where=sa.text(_WHERE),
                    sqlite_where=sa.text(_WHERE))


def downgrade() -> None:
    op.drop_index(_NAME, table_name="pending_operations")
