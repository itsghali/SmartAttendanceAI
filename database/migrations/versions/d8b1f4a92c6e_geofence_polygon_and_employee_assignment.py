"""geofence_polygon_and_employee_assignment

Revision ID: d8b1f4a92c6e
Revises: 9a3f1c8e2d4b
Create Date: 2026-08-06 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8b1f4a92c6e'
down_revision: Union[str, None] = '9a3f1c8e2d4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    boundary_type_enum = sa.Enum('CIRCLE', 'POLYGON', name='geofenceboundarytype')
    boundary_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'geofences',
        sa.Column(
            'boundary_type',
            boundary_type_enum,
            nullable=False,
            server_default='CIRCLE',
        ),
    )
    op.add_column('geofences', sa.Column('polygon_points', sa.JSON(), nullable=True))
    op.alter_column('geofences', 'center_latitude', existing_type=sa.Float(), nullable=True)
    op.alter_column('geofences', 'center_longitude', existing_type=sa.Float(), nullable=True)
    op.alter_column('geofences', 'radius_meters', existing_type=sa.Float(), nullable=True)

    op.create_table(
        'employee_geofences',
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('geofence_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['geofence_id'], ['geofences.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'geofence_id', name='uq_employee_geofence'),
    )
    op.create_index(
        'ix_employee_geofences_geofence_id', 'employee_geofences', ['geofence_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_employee_geofences_geofence_id', table_name='employee_geofences')
    op.drop_table('employee_geofences')

    op.alter_column('geofences', 'radius_meters', existing_type=sa.Float(), nullable=False)
    op.alter_column('geofences', 'center_longitude', existing_type=sa.Float(), nullable=False)
    op.alter_column('geofences', 'center_latitude', existing_type=sa.Float(), nullable=False)
    op.drop_column('geofences', 'polygon_points')
    op.drop_column('geofences', 'boundary_type')

    geofenceboundarytype = sa.Enum('CIRCLE', 'POLYGON', name='geofenceboundarytype')
    geofenceboundarytype.drop(op.get_bind(), checkfirst=True)
