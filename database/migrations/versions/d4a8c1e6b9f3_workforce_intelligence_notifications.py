"""workforce_intelligence_notifications

Revision ID: d4a8c1e6b9f3
Revises: c4d8e1f6a3b7
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4a8c1e6b9f3'
down_revision: Union[str, None] = 'c4d8e1f6a3b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 'deviationseverity' already exists (created by
    # a7d2e9c1f4b8_workforce_intelligence_detection's own create_table) —
    # create_type=False so this create_table doesn't try to CREATE TYPE a
    # second time against the same connection (same situation
    # c4d8e1f6a3b7 hit for reviewstatus, just create_table instead of
    # add_column here).
    #
    # MUST be postgresql.ENUM here, not plain sa.Enum — the generic
    # sa.Enum has no create_type parameter at all (silently swallows an
    # unrecognized kwarg into SchemaType's **kw instead of raising), so it
    # tried to CREATE TYPE anyway and crashed the real Postgres deploy with
    # DuplicateObject; SQLite's test suite never caught this because SQLite
    # has no native enum type (Enum renders as VARCHAR+CHECK there, no
    # CREATE TYPE emitted regardless of this flag).
    severity_enum = postgresql.ENUM(
        'MODERATE', 'HIGH', name='deviationseverity', create_type=False
    )

    op.create_table(
        'notifications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('recipient_user_id', sa.Uuid(), nullable=False),
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('deviation_flag_id', sa.Uuid(), nullable=True),
        sa.Column('dedupe_key', sa.String(length=64), nullable=False),
        sa.Column('metric', sa.String(length=50), nullable=False),
        sa.Column('severity', severity_enum, nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('recommended_action', sa.JSON(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('email_status', sa.String(length=20), nullable=False),
        sa.Column('email_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['deviation_flag_id'], ['employee_deviation_flags.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'recipient_user_id', 'dedupe_key', name='uq_notifications_recipient_dedupe'
        ),
    )
    op.create_index(
        'ix_notifications_recipient_read', 'notifications', ['recipient_user_id', 'is_read']
    )
    op.create_index('ix_notifications_email_status', 'notifications', ['email_status'])


def downgrade() -> None:
    op.drop_index('ix_notifications_email_status', table_name='notifications')
    op.drop_index('ix_notifications_recipient_read', table_name='notifications')
    op.drop_table('notifications')
