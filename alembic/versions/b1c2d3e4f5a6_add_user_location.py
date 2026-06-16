"""add lat/lng/location_updated_at to users (+ merge the two open heads)

Revision ID: b1c2d3e4f5a6
Revises: c9d0e1f2a3b4, f7e8d9c0b1a2
Create Date: 2026-06-16 00:00:00.000000

Two things in one step:

1. MERGE — the migration tree had two open heads (c9d0e1f2a3b4 add_carb_fat_targets
   and f7e8d9c0b1a2 add_non_training_activity), so `alembic upgrade head` was
   ambiguous. This revision lists both as down_revision, collapsing them to a
   single head again.

2. SCHEMA — adds the columns backing the Telegram location feature:
     lat, lng                 — last shared coordinates (Float, nullable)
     location_updated_at      — when they were last refreshed (DateTime, nullable)
   All nullable, no backfill: existing users simply have no location until they
   share one. Gated end-to-end by LOCATION_ENABLED, so this is inert data until
   the feature is switched on.

batch_alter_table is used so the change also applies cleanly on SQLite (dev),
matching every other migration in this project.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = ('c9d0e1f2a3b4', 'f7e8d9c0b1a2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('lng', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('location_updated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('location_updated_at')
        batch_op.drop_column('lng')
        batch_op.drop_column('lat')
