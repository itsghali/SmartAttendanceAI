"""workforce_intelligence_schema

Revision ID: e4a1c8f2b3d6
Revises: b3f7a1c9d2e6
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4a1c8f2b3d6'
down_revision: Union[str, None] = 'b3f7a1c9d2e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No explicit .create() here (unlike the is_synthetic ALTER TABLE columns
    # below) — op.create_table's own DDL event already creates an Enum
    # column's type as part of table creation; pre-creating it too causes a
    # duplicate CREATE TYPE against the same connection/transaction.
    run_status_enum = sa.Enum('REQUESTED', 'RUNNING', 'COMPLETED', 'FAILED', name='syntheticdatarunstatus')

    op.create_table(
        'synthetic_data_runs',
        sa.Column('requested_by', sa.Uuid(), nullable=True),
        sa.Column('employee_scope', sa.JSON(), nullable=False),
        sa.Column('date_range_start', sa.Date(), nullable=False),
        sa.Column('date_range_end', sa.Date(), nullable=False),
        sa.Column('anomaly_config', sa.JSON(), nullable=False),
        sa.Column('status', run_status_enum, nullable=False, server_default='REQUESTED'),
        sa.Column('error_message', sa.String(length=1000), nullable=True),
        sa.Column('row_counts', sa.JSON(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'employee_baselines',
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('window_start', sa.Date(), nullable=False),
        sa.Column('window_end', sa.Date(), nullable=False),
        sa.Column('metric_stats', sa.JSON(), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', name='uq_employee_baselines_employee_id'),
    )

    for table in ('attendance_records', 'break_periods', 'geofence_events'):
        op.add_column(
            table,
            sa.Column('is_synthetic', sa.Boolean(), nullable=False, server_default='false'),
        )
        op.add_column(table, sa.Column('synthetic_run_id', sa.Uuid(), nullable=True))
        op.add_column(
            table, sa.Column('synthetic_anomaly_type', sa.String(length=50), nullable=True)
        )
        op.create_foreign_key(
            f'fk_{table}_synthetic_run_id',
            table,
            'synthetic_data_runs',
            ['synthetic_run_id'],
            ['id'],
            ondelete='SET NULL',
        )
        op.create_index(
            f'ix_{table}_synthetic_run', table, ['synthetic_run_id'], unique=False
        )

    op.create_index(
        'ix_attendance_employee_synthetic',
        'attendance_records',
        ['employee_id', 'is_synthetic'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_attendance_employee_synthetic', table_name='attendance_records')

    for table in ('geofence_events', 'break_periods', 'attendance_records'):
        op.drop_index(f'ix_{table}_synthetic_run', table_name=table)
        op.drop_constraint(f'fk_{table}_synthetic_run_id', table, type_='foreignkey')
        op.drop_column(table, 'synthetic_anomaly_type')
        op.drop_column(table, 'synthetic_run_id')
        op.drop_column(table, 'is_synthetic')

    op.drop_table('employee_baselines')
    op.drop_table('synthetic_data_runs')

    run_status_enum = sa.Enum('REQUESTED', 'RUNNING', 'COMPLETED', 'FAILED', name='syntheticdatarunstatus')
    run_status_enum.drop(op.get_bind(), checkfirst=True)
