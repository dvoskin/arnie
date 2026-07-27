"""single head: rejoin the health-tombstone and fitness-session branches

NO SCHEMA CHANGE. This exists so `alembic upgrade head` works again.

The tree carried two heads — the health-import-tombstone branch and the
branch the fitness session id landed on. With more than one head alembic
cannot resolve "head", so `upgrade head` fails outright with "Multiple head
revisions are present" and does nothing. That is a silent no-op in a deploy
script: the migration appears to run and no schema moves. It is what stopped
`workout_group_id` from applying the first time it was attempted.

Both parents were already applied; this only rejoins them so there is one
head to point at.

Revision ID: onehead001
Revises: hlthtomb0001, wkoutgrp001
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'onehead001'
down_revision: Union[str, Sequence[str], None] = ('hlthtomb0001', 'wkoutgrp001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Nothing to do — a merge only rejoins lineage."""


def downgrade() -> None:
    """Splitting the head back apart would recreate the ambiguity this
    removes, so the downgrade is intentionally a no-op."""
