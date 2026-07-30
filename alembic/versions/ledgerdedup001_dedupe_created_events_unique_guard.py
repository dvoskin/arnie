"""Dedupe ledger `created` events and make the duplicate structurally impossible.

Master audit 2026-07-30, invariant I3: every exercise creation was recorded
twice, 0 seconds apart — `add_exercise_entry`'s internal event under
domain="fitness" plus the caller's under domain="exercise". The code fix
(5d6e90b) made `add_exercise_entry` the sole writer; this migration repairs the
history that fix left behind and adds the database-level guard so no future
writer — new endpoint, regression, race — can reintroduce the double.

Order inside upgrade() is load-bearing: data repairs BEFORE the unique index,
or index creation fails mid-deploy on the very rows it exists to prevent.

Three data repairs, then the guard:
1. Orphan "fitness" created events (no "exercise" twin) are RE-DOMAINED, not
   deleted — they are the only record of those logs, and `ledger_undo._invert`
   handles only "exercise", so re-domaining also makes them undoable.
2. "fitness" twins WITH an "exercise" twin are deleted — bookkeeping
   duplicates, not user history.
3. A defensive same-domain dedupe (keep MIN(id)) so any other historic double
   cannot fail the index build.
4. UNIQUE partial index on (domain, entry_id) WHERE event_type='created' AND
   entry_id IS NOT NULL. `domain` is mandatory: entry ids come from four
   independent per-domain sequences (food, exercise, water, weight), so a
   domain-less index would collide across domains deterministically.

Parents turnjoin001 (keeps the single head onehead001 exists to preserve).
Deploy runs `alembic upgrade heads`.
Rollback: `alembic downgrade` drops the index only. The data repairs are
one-way by design (matching the 9c814ca1d70d precedent): deleted rows were
bookkeeping duplicates, and re-domained rows are strictly more correct where
they are (they become undoable). Affected-row counts are printed during
upgrade for the deploy log.

Revision ID: ledgerdedup001
Revises: turnjoin001
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ledgerdedup001"
down_revision: Union[str, None] = "turnjoin001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Re-domain orphan "fitness" created events → "exercise".
    r1 = conn.execute(sa.text("""
        UPDATE ledger_events SET domain = 'exercise'
        WHERE domain = 'fitness' AND event_type = 'created'
          AND entry_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM ledger_events e2
                          WHERE e2.domain = 'exercise'
                            AND e2.event_type = 'created'
                            AND e2.entry_id = ledger_events.entry_id
                            AND e2.user_id = ledger_events.user_id)"""))

    # 2. Delete the bookkeeping twin where an "exercise" created event exists.
    r2 = conn.execute(sa.text("""
        DELETE FROM ledger_events
        WHERE domain = 'fitness' AND event_type = 'created'
          AND entry_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM ledger_events e2
                      WHERE e2.domain = 'exercise'
                        AND e2.event_type = 'created'
                        AND e2.entry_id = ledger_events.entry_id
                        AND e2.user_id = ledger_events.user_id)"""))

    # 3. Defensive same-domain dedupe: keep the earliest event per
    #    (domain, entry_id) so step 4 cannot fail on any other historic double.
    r3 = conn.execute(sa.text("""
        DELETE FROM ledger_events
        WHERE event_type = 'created' AND entry_id IS NOT NULL
          AND id NOT IN (SELECT MIN(id) FROM ledger_events
                         WHERE event_type = 'created'
                           AND entry_id IS NOT NULL
                         GROUP BY domain, entry_id)"""))

    # Row counts for the deploy log. In offline (--sql) mode execute() returns
    # None — the counts only exist when the statements actually ran.
    if r1 is not None:
        print(f"ledgerdedup001: re-domained {r1.rowcount} orphan fitness "
              f"events, deleted {r2.rowcount} twins, deduped {r3.rowcount} "
              f"same-domain doubles")

    # 4. The guard.
    op.create_index(
        "uq_ledger_events_created_entry", "ledger_events",
        ["domain", "entry_id"], unique=True,
        postgresql_where=sa.text(
            "event_type = 'created' AND entry_id IS NOT NULL"),
        sqlite_where=sa.text(
            "event_type = 'created' AND entry_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_ledger_events_created_entry",
                  table_name="ledger_events")
