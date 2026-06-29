"""add supplement_intakes table (daily supplement adherence log)

Revision ID: e1f2a3b4c5d6
Revises: c4d5e6f7a8b9
Create Date: 2026-06-29 00:00:00.000000

Backs the Coach "Stack" card: the supplement REGIMEN lives in the brain as
health_supplement_* UserAttributes (Arnie learns them from chat); this table is
the per-day "taken it" adherence log layered on top. One row per
(user, supplement_key, local date). The UNIQUE constraint makes the toggle
idempotent.

batch_alter_table-free create_table works on both SQLite (dev) and Postgres
(prod). Paired with the SupplementIntake model — required because db/database.py
_migrate is SQLite-only (Postgres relies on alembic).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'supplement_intakes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('supplement_key', sa.String(), nullable=False),
        sa.Column('supplement_name', sa.String(), nullable=True),
        sa.Column('intake_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'supplement_key', 'intake_date',
                            name='uq_supplement_intake_user_key_date'),
    )
    op.create_index('ix_supplement_intakes_user_id', 'supplement_intakes', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_supplement_intakes_user_id', table_name='supplement_intakes')
    op.drop_table('supplement_intakes')
