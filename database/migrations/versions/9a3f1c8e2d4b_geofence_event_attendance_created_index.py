"""geofence_event attendance+created index

Revision ID: 9a3f1c8e2d4b
Revises: 7e2a4f6c9b1d
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "9a3f1c8e2d4b"
down_revision = "7e2a4f6c9b1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_geofence_events_attendance_created",
        "geofence_events",
        ["attendance_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_geofence_events_attendance_created", table_name="geofence_events")
