"""deviation_flag_sample_sizes

Revision ID: e7b2f4a1c8d5
Revises: d4a8c1e6b9f3
Create Date: 2026-08-20 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b2f4a1c8d5'
down_revision: Union[str, None] = 'd4a8c1e6b9f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no backfill: existing rows predate this column and detection
    # reruns replace their own (employee, window) flags within a day anyway
    # (see WorkforceIntelligenceService.run_detection) — a NULL "historical
    # observations" count on a pre-migration row that's about to be deleted
    # isn't worth a backfill pass.
    op.add_column(
        'employee_deviation_flags', sa.Column('self_n', sa.Integer(), nullable=True)
    )
    op.add_column(
        'employee_deviation_flags', sa.Column('peer_n', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('employee_deviation_flags', 'peer_n')
    op.drop_column('employee_deviation_flags', 'self_n')
