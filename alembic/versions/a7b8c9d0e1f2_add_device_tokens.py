"""add device_tokens table (APNs push registration)

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0
Create Date: 2026-06-18 00:00:00.000000

First step of the APNs delivery slice (#3 in the iOS↔TG parity roadmap):
gives the backend a place to record each iOS device's push token so the
proactive scheduler (slice 2c) can fan nudges out to a user's devices via
APNs HTTP/2.

This migration lands the *plumbing* only — no sender, no scheduler hook.
The new POST /api/v1/devices/apns-token endpoint will write here; the rows
sit harmlessly until later slices consume them.

Idempotent (inspect-then-create) per [[feedback_arnie_migrate_postgres_gap]] —
safe to re-run, safe if the table was added out-of-band.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'device_tokens' not in insp.get_table_names():
        op.create_table(
            'device_tokens',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('token', sa.String(), nullable=False),
            sa.Column('platform', sa.String(), nullable=False, server_default='apns'),
            sa.Column('environment', sa.String(), nullable=False, server_default='production'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('last_seen_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
        )

    existing_indexes = {i['name'] for i in insp.get_indexes('device_tokens')} if 'device_tokens' in insp.get_table_names() else set()
    if 'ix_device_tokens_user_id' not in existing_indexes:
        op.create_index('ix_device_tokens_user_id', 'device_tokens', ['user_id'])
    if 'ix_device_tokens_token' not in existing_indexes:
        # Unique index on token. Same physical device → same token; if a token
        # already exists under a different user_id, upsert_device_token's flow
        # is to UPDATE that row's user_id rather than insert a duplicate, so
        # this constraint never trips from legitimate use.
        op.create_index('ix_device_tokens_token', 'device_tokens', ['token'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'device_tokens' in insp.get_table_names():
        existing_indexes = {i['name'] for i in insp.get_indexes('device_tokens')}
        if 'ix_device_tokens_token' in existing_indexes:
            op.drop_index('ix_device_tokens_token', table_name='device_tokens')
        if 'ix_device_tokens_user_id' in existing_indexes:
            op.drop_index('ix_device_tokens_user_id', table_name='device_tokens')
        op.drop_table('device_tokens')
