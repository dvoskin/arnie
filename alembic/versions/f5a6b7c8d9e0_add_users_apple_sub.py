"""add apple_sub column to users (Apple Sign-in binding)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-06-18 00:00:00.000000

First step of cross-channel identity unification: gives the users table a place
to record an Apple Sign-in subject (`sub` claim from a verified identity token).
Nullable — most users won't sign in with Apple. A partial unique index ensures
no two users share the same Apple sub, while allowing many NULLs.

This unblocks the bind-apple-sub-to-existing-device-user flow in
api/auth_routes.create_session — when an iOS user already authenticated via the
device-identity path taps "Sign in with Apple," the backend binds the verified
sub onto their existing user row instead of creating a fresh empty account.

Idempotent (inspect-then-add) — safe to run against environments where the
column was added out-of-band, e.g. via a manual ALTER during incident response.
Matches the [[feedback_arnie_migrate_postgres_gap]] template.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_cols = {c['name'] for c in insp.get_columns('users')}
    if 'apple_sub' not in existing_cols:
        with op.batch_alter_table('users') as batch_op:
            batch_op.add_column(sa.Column('apple_sub', sa.String(), nullable=True))

    existing_indexes = {i['name'] for i in insp.get_indexes('users')}
    if 'ix_users_apple_sub' not in existing_indexes:
        # Unique index. Postgres treats multiple NULLs as distinct under a unique
        # constraint, so this enforces "no two users share a non-null apple_sub"
        # without forcing every user to have one.
        op.create_index('ix_users_apple_sub', 'users', ['apple_sub'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_indexes = {i['name'] for i in insp.get_indexes('users')}
    if 'ix_users_apple_sub' in existing_indexes:
        op.drop_index('ix_users_apple_sub', table_name='users')

    existing_cols = {c['name'] for c in insp.get_columns('users')}
    if 'apple_sub' in existing_cols:
        with op.batch_alter_table('users') as batch_op:
            batch_op.drop_column('apple_sub')
