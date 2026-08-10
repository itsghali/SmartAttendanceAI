"""break_period_one_open_per_attendance

Revision ID: 7e2a4f6c9b1d
Revises: 4cb7cdbeb134
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e2a4f6c9b1d'
down_revision: Union[str, None] = '4cb7cdbeb134'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Two near-simultaneous start_break() requests both pass the
    # get_open_for_attendance() check before either commits — the same race
    # attendance_records already closed with uq_attendance_one_open_session.
    # break_periods never got the equivalent guard. This mirrors it exactly.
    op.create_index(
        'uq_break_period_one_open_per_attendance',
        'break_periods',
        ['attendance_id'],
        unique=True,
        postgresql_where=sa.text('break_end_at IS NULL'),
        sqlite_where=sa.text('break_end_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_break_period_one_open_per_attendance',
        table_name='break_periods',
        postgresql_where=sa.text('break_end_at IS NULL'),
        sqlite_where=sa.text('break_end_at IS NULL'),
    )
