"""synthetic_data_run_idempotency_key

Revision ID: f1c4a9d7e8b2
Revises: e4a1c8f2b3d6
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c4a9d7e8b2'
down_revision: Union[str, None] = 'e4a1c8f2b3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'synthetic_data_runs',
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        'uq_synthetic_data_runs_idempotency_key',
        'synthetic_data_runs',
        ['idempotency_key'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_synthetic_data_runs_idempotency_key', 'synthetic_data_runs', type_='unique'
    )
    op.drop_column('synthetic_data_runs', 'idempotency_key')
