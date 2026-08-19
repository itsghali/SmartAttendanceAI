"""employee_deviation_flag_review_state

Revision ID: c4d8e1f6a3b7
Revises: b3e6f0a2c9d4
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d8e1f6a3b7'
down_revision: Union[str, None] = 'b3e6f0a2c9d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Unlike e4a1c8f2b3d6/a7d2e9c1f4b8's enums (created implicitly by
    # op.create_table's own DDL event), this enum lands on an ALTER TABLE
    # ADD COLUMN against an EXISTING table — op.add_column does not create
    # the type for us, so it must be created explicitly first.
    review_status_enum = sa.Enum('NEW', 'REVIEWED', 'DISMISSED', name='reviewstatus')
    review_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'employee_deviation_flags',
        sa.Column(
            'review_status', review_status_enum, nullable=False, server_default='NEW'
        ),
    )
    op.add_column(
        'employee_deviation_flags',
        sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    )
    op.add_column(
        'employee_deviation_flags',
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_employee_deviation_flags_reviewed_by',
        'employee_deviation_flags',
        'users',
        ['reviewed_by'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_employee_deviation_flags_reviewed_by',
        'employee_deviation_flags',
        type_='foreignkey',
    )
    op.drop_column('employee_deviation_flags', 'reviewed_at')
    op.drop_column('employee_deviation_flags', 'reviewed_by')
    op.drop_column('employee_deviation_flags', 'review_status')

    sa.Enum(name='reviewstatus').drop(op.get_bind(), checkfirst=True)
