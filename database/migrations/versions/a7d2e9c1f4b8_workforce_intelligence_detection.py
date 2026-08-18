"""workforce_intelligence_detection

Revision ID: a7d2e9c1f4b8
Revises: f1c4a9d7e8b2
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d2e9c1f4b8'
down_revision: Union[str, None] = 'f1c4a9d7e8b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'impossible_travel_rejections',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('prior_attendance_id', sa.Uuid(), nullable=True),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('distance_km', sa.Float(), nullable=False),
        sa.Column('elapsed_hours', sa.Float(), nullable=False),
        sa.Column('implied_speed_kmh', sa.Float(), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['prior_attendance_id'], ['attendance_records.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_impossible_travel_rejections_employee_created',
        'impossible_travel_rejections',
        ['employee_id', 'created_at'],
    )

    # No explicit .create() here (mirrors e4a1c8f2b3d6's own precedent for
    # syntheticdatarunstatus) — op.create_table's own DDL event already
    # creates an Enum column's type as part of table creation; pre-creating
    # it too causes a duplicate CREATE TYPE against the same
    # connection/transaction.
    deviation_severity = sa.Enum('MODERATE', 'HIGH', name='deviationseverity')

    op.create_table(
        'employee_deviation_flags',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('attendance_id', sa.Uuid(), nullable=False),
        sa.Column('metric', sa.String(length=50), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('observed_value', sa.Float(), nullable=False),
        sa.Column('self_mean', sa.Float(), nullable=False),
        sa.Column('self_std', sa.Float(), nullable=False),
        sa.Column('self_z', sa.Float(), nullable=True),
        sa.Column('peer_mean', sa.Float(), nullable=False),
        sa.Column('peer_std', sa.Float(), nullable=False),
        sa.Column('peer_z', sa.Float(), nullable=True),
        sa.Column('severity', deviation_severity, nullable=False),
        sa.Column('window_start', sa.Date(), nullable=False),
        sa.Column('window_end', sa.Date(), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_synthetic', sa.Boolean(), nullable=False),
        sa.Column('synthetic_run_id', sa.Uuid(), nullable=True),
        sa.Column('synthetic_anomaly_type', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['attendance_id'], ['attendance_records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['synthetic_run_id'], ['synthetic_data_runs.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_employee_deviation_flags_employee_window',
        'employee_deviation_flags',
        ['employee_id', 'window_start', 'window_end'],
    )
    op.create_index(
        'ix_employee_deviation_flags_synthetic_run',
        'employee_deviation_flags',
        ['synthetic_run_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_employee_deviation_flags_synthetic_run', table_name='employee_deviation_flags'
    )
    op.drop_index(
        'ix_employee_deviation_flags_employee_window', table_name='employee_deviation_flags'
    )
    op.drop_table('employee_deviation_flags')
    sa.Enum(name='deviationseverity').drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        'ix_impossible_travel_rejections_employee_created',
        table_name='impossible_travel_rejections',
    )
    op.drop_table('impossible_travel_rejections')
