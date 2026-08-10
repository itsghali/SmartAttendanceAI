"""check_in_is_jailbroken flag

Revision ID: a49a07557a55
Revises: 75b40a0c4e5e
Create Date: 2026-08-10 17:09:12.027556

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a49a07557a55'
down_revision: Union[str, None] = '75b40a0c4e5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate also proposed dropping ix_employee_geofences_geofence_id —
    # a pre-existing, already-tracked discrepancy (TODOS.md #32, model vs.
    # live-DB mismatch predating this migration), deliberately left out here,
    # same as every prior migration that has hit this same autogenerate noise.
    op.add_column(
        'attendance_records',
        sa.Column('check_in_is_jailbroken', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('attendance_records', 'check_in_is_jailbroken')
