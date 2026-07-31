"""background_jobs becomes a real outbox — identity, provenance, safe claiming

`background_jobs` was already an outbox in all but name: durable, retried,
backed off, deduped, swept by the scheduler. Adding a second `outbox_events`
table beside it would have been a rename with extra steps, and the directive's
own rule is to extend an adequate abstraction rather than replace it for
aesthetic reasons.

Three things it genuinely could not do:

  turn_id     WHICH request queued this work. The same canonical id the ledger
              event and the request trace carry, so post-commit work joins the
              turn that caused it instead of floating free. A job that fails
              two days later was previously unattributable.

  build_sha   WHICH deploy queued it. A job written by a build that has since
              been rolled back is a different fact from one written by the
              current build, and nothing recorded the difference.

  claimed_at  WHICH worker holds it right now. Claiming was a plain SELECT, so
              two sweepers would both pick up the same row. That was tolerable
              while the only two job kinds were idempotent (profile synthesis
              throttles, reflection dedups) and stops being tolerable the
              moment delivery joins the queue: sending a push twice is not a
              no-op. Paired with a `processing` status and SKIP LOCKED.

Pure ADD of three nullable columns. No backfill, no constraint, nothing to fail
on existing rows; an old instance during a rolling deploy simply never writes
them, and rows already queued keep working exactly as they do.

Parents serving001. Deploy runs `alembic upgrade heads`.

Revision ID: outbox001
Revises: serving001
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "outbox001"
down_revision: Union[str, None] = "serving001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("turn_id", sa.String()),
    ("build_sha", sa.String()),
    ("claimed_at", sa.DateTime()),
)


def upgrade() -> None:
    # ONLINE ONLY — offline (--sql) hands back a MockConnection with no
    # inspection system, and CI compiles the head migration offline against
    # Postgres precisely to catch that (idem001 learned this the hard way).
    existing: set = set()
    if not context.is_offline_mode():
        existing = {c["name"] for c in
                    sa.inspect(op.get_bind()).get_columns("background_jobs")}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column("background_jobs", sa.Column(name, type_,
                                                       nullable=True))
    if "turn_id" not in existing:
        op.create_index("ix_background_jobs_turn", "background_jobs",
                        ["turn_id"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_turn", table_name="background_jobs")
    for name, _ in _COLUMNS:
        op.drop_column("background_jobs", name)
