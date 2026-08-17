"""break_period_source

Revision ID: b3f7a1c9d2e6
Revises: fec40df529fb
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7a1c9d2e6'
down_revision: Union[str, None] = 'fec40df529fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

break_source_enum = sa.Enum('MANUAL', 'GEOFENCE_EXIT', name='breaksource')


def upgrade() -> None:
    break_source_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'break_periods',
        sa.Column(
            'source',
            break_source_enum,
            nullable=False,
            server_default='MANUAL',
        ),
    )


def downgrade() -> None:
    op.drop_column('break_periods', 'source')
    break_source_enum.drop(op.get_bind(), checkfirst=True)
