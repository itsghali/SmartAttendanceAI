"""workforce_intelligence_notice_ack

Revision ID: b3e6f0a2c9d4
Revises: a7d2e9c1f4b8
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e6f0a2c9d4'
down_revision: Union[str, None] = 'a7d2e9c1f4b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('workforce_intelligence_notice_acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'workforce_intelligence_notice_acknowledged_at')
