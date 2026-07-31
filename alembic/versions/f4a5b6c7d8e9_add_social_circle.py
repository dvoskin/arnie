"""add social circle — friendships table + users.friend_code

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-25 00:00:00.000000

Backs the "circle" leaderboard side-quest: a friend graph where members see each
other's calories, workouts, and streaks.

  • users.friend_code — a stable, shareable, UNIQUE code. Nullable: it's minted
    lazily the first time a user opens their circle / runs /invite, and minting
    it is the opt-in (no code → unaddable → invisible). A partial unique index
    lets the many NULLs coexist while forbidding two users sharing a code.

  • friendships — bidirectional accepted edges (A↔B is two rows). Unique
    (user_id, friend_id) makes a double-add a no-op. Both ids are canonical
    user ids.

Idempotent (inspect-then-create/add) per [[feedback_arnie_migrate_postgres_gap]]
— safe to re-run, safe if added out-of-band during an incident.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # ── users.friend_code ────────────────────────────────────────────────────
    existing_cols = {c['name'] for c in insp.get_columns('users')}
    if 'friend_code' not in existing_cols:
        with op.batch_alter_table('users') as batch_op:
            batch_op.add_column(sa.Column('friend_code', sa.String(), nullable=True))

    existing_indexes = {i['name'] for i in insp.get_indexes('users')}
    if 'ix_users_friend_code' not in existing_indexes:
        # Unique: Postgres treats multiple NULLs as distinct, so a global unique
        # index enforces "no two users share a non-null friend_code" without
        # forcing every user to own one.
        op.create_index('ix_users_friend_code', 'users', ['friend_code'], unique=True)

    # ── friendships table ────────────────────────────────────────────────────
    if 'friendships' not in insp.get_table_names():
        op.create_table(
            'friendships',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('friend_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint('user_id', 'friend_id', name='uq_friendship_pair'),
        )

    has_friendships = 'friendships' in insp.get_table_names()
    fr_indexes = {i['name'] for i in insp.get_indexes('friendships')} if has_friendships else set()
    if 'ix_friendships_user_id' not in fr_indexes:
        op.create_index('ix_friendships_user_id', 'friendships', ['user_id'])
    if 'ix_friendships_friend_id' not in fr_indexes:
        op.create_index('ix_friendships_friend_id', 'friendships', ['friend_id'])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'friendships' in insp.get_table_names():
        fr_indexes = {i['name'] for i in insp.get_indexes('friendships')}
        if 'ix_friendships_friend_id' in fr_indexes:
            op.drop_index('ix_friendships_friend_id', table_name='friendships')
        if 'ix_friendships_user_id' in fr_indexes:
            op.drop_index('ix_friendships_user_id', table_name='friendships')
        op.drop_table('friendships')

    existing_indexes = {i['name'] for i in insp.get_indexes('users')}
    if 'ix_users_friend_code' in existing_indexes:
        op.drop_index('ix_users_friend_code', table_name='users')

    existing_cols = {c['name'] for c in insp.get_columns('users')}
    if 'friend_code' in existing_cols:
        with op.batch_alter_table('users') as batch_op:
            batch_op.drop_column('friend_code')
