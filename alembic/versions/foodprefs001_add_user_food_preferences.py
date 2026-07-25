"""add user_food_preferences + food_corrections (directive 14, 15)

Two tables, two different jobs.

user_food_preferences learns what "my Fairlife" means for THIS user, so a
question that has been answered the same way three times stops being asked.
Deliberately not a cache of nutrition: it stores the IDENTITY and portion
defaults, and the resolver still prices them. A cached number goes stale when a
product is reformulated; a cached identity does not.

food_corrections is the signal, kept separately and kept raw. When a user says
"no, it was the Elite bottle" we currently fix the entry and throw the
information away — which means the same mis-pick happens next week. The row
records what was said, what we chose, what they meant, and the full candidate
ranking at the time, so alias maps and scoring can be improved from evidence
rather than from memory of complaints.

Parents bgjobs001. Deploy runs `alembic upgrade heads`.

Revision ID: foodprefs001
Revises: bgjobs001
Create Date: 2026-07-25 04:40:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'foodprefs001'
down_revision: Union[str, Sequence[str], None] = 'bgjobs001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_food_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        # The phrase the user actually says, normalized. "my fairlife".
        sa.Column('trigger_term', sa.String(), nullable=False),
        # Identity defaults — what the phrase RESOLVES to.
        sa.Column('canonical_name', sa.String(), nullable=True),
        sa.Column('brand', sa.String(), nullable=True),
        sa.Column('product_line', sa.String(), nullable=True),
        sa.Column('variant', sa.String(), nullable=True),
        sa.Column('package_amount', sa.Float(), nullable=True),
        sa.Column('package_unit', sa.String(), nullable=True),
        # Portion defaults.
        sa.Column('default_consumed_fraction', sa.Float(), nullable=True),
        sa.Column('default_unit_mass_g', sa.Float(), nullable=True),
        # Promotion state. A preference is NOT created from one occurrence.
        sa.Column('confirmations', sa.Integer(), server_default='0',
                  nullable=False),
        sa.Column('contradictions', sa.Integer(), server_default='0',
                  nullable=False),
        sa.Column('confidence', sa.Float(), server_default='0', nullable=False),
        sa.Column('promoted_at', sa.DateTime(), nullable=True),
        sa.Column('last_confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('last_contradicted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'),
                  nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        # One row per (user, phrase): a second row for the same phrase would
        # make "which default applies" undecidable.
        sa.UniqueConstraint('user_id', 'trigger_term',
                            name='uq_user_food_pref_term'),
    )
    op.create_index('ix_user_food_prefs_user', 'user_food_preferences',
                    ['user_id'])

    op.create_table(
        'food_corrections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('turn_id', sa.String(), nullable=True),
        sa.Column('staged_item_id', sa.String(), nullable=True),
        sa.Column('entry_id', sa.Integer(), nullable=True),
        sa.Column('original_text', sa.String(), nullable=True),
        sa.Column('ambiguity_type', sa.String(), nullable=True),
        sa.Column('field_name', sa.String(), nullable=True),
        sa.Column('chosen_value', sa.String(), nullable=True),
        sa.Column('corrected_value', sa.String(), nullable=True),
        sa.Column('chosen_candidate_id', sa.String(), nullable=True),
        sa.Column('corrected_candidate_id', sa.String(), nullable=True),
        # The full ranking at decision time. Without it, "why did it pick
        # that?" is unanswerable after the fact.
        sa.Column('candidate_ranking_json', sa.Text(), nullable=True),
        sa.Column('mode', sa.String(), nullable=True),
        sa.Column('via_alias', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'),
                  nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_food_corrections_user_time', 'food_corrections',
                    ['user_id', 'created_at'])
    op.create_index('ix_food_corrections_field', 'food_corrections',
                    ['field_name'])


def downgrade() -> None:
    op.drop_index('ix_food_corrections_field', table_name='food_corrections')
    op.drop_index('ix_food_corrections_user_time',
                  table_name='food_corrections')
    op.drop_table('food_corrections')
    op.drop_index('ix_user_food_prefs_user',
                  table_name='user_food_preferences')
    op.drop_table('user_food_preferences')
